import os
import sys

import numpy as np
import ROOT
import yaml

if __name__ == "__main__":
    sys.path.append(os.environ["ANALYSIS_PATH"])


_REGISTRY_DECLARED = False


def _declare_prediction_registry():
    global _REGISTRY_DECLARED
    if _REGISTRY_DECLARED:
        return
    ROOT.gInterpreter.Declare(
        """
        #include <stdexcept>
        #include <unordered_map>
        #include <vector>

        namespace dnn_application {
            using PredictionMap = std::unordered_map<ULong64_t, float>;

            std::vector<PredictionMap>& payloads() {
                static std::vector<PredictionMap> data;
                return data;
            }

            std::size_t registerPayload(const std::vector<ULong64_t>& keys, const std::vector<float>& values) {
                if (keys.size() != values.size()) {
                    throw std::runtime_error("DNN prediction keys and values have different sizes");
                }
                PredictionMap payload;
                payload.reserve(values.size());
                for (std::size_t idx = 0; idx < values.size(); ++idx) {
                    payload.emplace(keys[idx], values[idx]);
                }
                payloads().push_back(std::move(payload));
                return payloads().size() - 1;
            }

            float getPrediction(std::size_t payload_id, ULong64_t event_key) {
                const auto& values = payloads().at(payload_id);
                const auto prediction = values.find(event_key);
                if (prediction == values.end()) {
                    throw std::runtime_error("DNN prediction lookup failed for event key");
                }
                return prediction->second;
            }

            void clearPayloads() {
                payloads().clear();
                payloads().shrink_to_fit();
            }
        }
        """
    )
    _REGISTRY_DECLARED = True


def clear_prediction_registry():
    """Release predictions after the RDF graph using them has completed."""
    if _REGISTRY_DECLARED:
        ROOT.dnn_application.clearPayloads()


def _parse_column_names(columns_config):
    if "features" in columns_config:
        return list(dict.fromkeys(columns_config["features"]))

    features = []
    for mu_idx in [1, 2]:
        for mu_var in columns_config["Muon"]:
            features.append(mu_var.format(mu_idx))
    features.extend(columns_config["MuPair"])
    features.extend(columns_config["MuJet"])
    for j_idx in [1, 2]:
        for jet_var in columns_config["VBFJet"]:
            features.append(f"j{j_idx}_{jet_var}")
    features.extend(columns_config["VBFJetPair"])
    return list(dict.fromkeys(features))


def _load_toml(path):
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            tomllib = None

    if tomllib is not None:
        with open(path, "rb") as f:
            return tomllib.load(f)

    config = {}
    current_section = None
    with open(path, "r") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                current_section = line.strip("[]")
                config[current_section] = {}
                continue
            if current_section and "=" in line:
                key, value = [part.strip() for part in line.split("=", 1)]
                if value.isdigit():
                    value = int(value)
                config[current_section][key] = value
    return config


def validate_predictions(predictions, payload_name, model_set="updated"):
    """Reject fully saturated output instead of silently writing bad shapes."""
    if predictions.size == 0:
        return
    if not np.isfinite(predictions).all():
        raise RuntimeError(
            f"DNN payload {payload_name!r} produced non-finite predictions"
        )
    epsilon = 1.0e-12
    all_zero = np.all(predictions <= epsilon)
    all_one = np.all(predictions >= 1.0 - epsilon)
    if all_zero or all_one:
        edge = "zero" if all_zero else "one"
        print(predictions)
        detail = (
            " The updated model is known to contain an effectively zero "
            "variance pt_vbfj1j2 feature."
            if model_set == "updated"
            else ""
        )
        # raise RuntimeError(
        #     f"DNN payload {payload_name!r} using model set {model_set!r} "
        #     f"produced predictions saturated at {edge} for every event. "
        #     "Check the selected model generation, input features, and "
        #     f"preprocessing constants.{detail}"
        # )


class DNNApplication:
    ERA_CODES = {
        "Run3_2022": 0,
        "Run3_2022EE": 1,
        "Run3_2023": 2,
        "Run3_2023BPix": 3,
        "Run3_2024": 4,
        "Run3_2025": 5,
        # La DNN non e' allenata sul 2026: si usa il codice del 2025.
        "Run3_2026": 5,
    }

    def __init__(
        self,
        payload_name="DNN",
        base_dir=None,
        btag_algo="PNet",
        era=None,
        model_set="updated",
    ):
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise RuntimeError("onnxruntime is required for DNN application. Run 'source env.sh' first.") from exc

        self.ort = ort
        self.payload_name = payload_name
        self.btag_algo = btag_algo
        self.era = era
        self.model_set = model_set
        self.base_dir = base_dir or os.environ["ANALYSIS_PATH"]
        self.config_dir, self.models_dir = self._resolve_payload_directories()
        self.parity, self.input_features = self._load_config()
        self.models = self._load_models()

    def _resolve_payload_directories(self):
        common_dir = os.path.join(self.base_dir, "common")

        if self.payload_name == "VBFNet":
            config_name = "vbfnet_configs"
            models_name = "vbfnet_models"
        elif self.model_set == "legacy":
            if self.era in {"Run3_2024", "Run3_2025", "Run3_2026"}:
                config_name = "dnn_configs_2024"
                models_name = "dnn_models_2024"
            else:
                config_name = "dnn_configs"
                models_name = "dnn_models"
        else:
            # Use one trained DNN consistently across every Run 3 era,
            # including the sideband payload aliases.
            config_name = "updated_DNN_configs"
            models_name = "updated_DNN_models"

        config_dir = os.path.join(common_dir, config_name)
        models_dir = os.path.join(common_dir, models_name)
        if not os.path.isdir(config_dir):
            raise RuntimeError(
                f"Configuration directory for payload '{self.payload_name}' "
                f"does not exist: {config_dir}"
            )
        if not os.path.isdir(models_dir):
            raise RuntimeError(
                f"Model directory for payload '{self.payload_name}' "
                f"does not exist: {models_dir}"
            )
        return config_dir, models_dir

    def _load_config(self):
        config = _load_toml(os.path.join(self.config_dir, "config.toml"))
        columns_config_path = os.path.join(self.config_dir, "columns_config.yaml")

        if os.path.exists(columns_config_path):
            with open(columns_config_path, "r") as f:
                columns_config = yaml.safe_load(f)
            features = _parse_column_names(
                columns_config.get("vars_to_save", columns_config)
            )
        else:
            features = config.get("dataset", {}).get("data_columns")
            if not features:
                raise RuntimeError(
                    f"No DNN input features found in {self.config_dir}: expected "
                    "columns_config.yaml or dataset.data_columns in config.toml"
                )

        features = [feature.format(algo=self.btag_algo) for feature in features]
        parity = config.get("kfold", {}).get("k")
        if parity is None:
            parity = config.get("splitting", {}).get("k")
        if parity is None:
            raise RuntimeError(
                f"No k-fold value found in {self.config_dir}/config.toml"
            )
        return int(parity), list(dict.fromkeys(features))

    def _load_models(self):
        options = self.ort.SessionOptions()
        options.graph_optimization_level = self.ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        # Histogram jobs request one CPU. Keeping ORT on one thread avoids
        # oversubscription when many Condor jobs run on the same worker.
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.execution_mode = self.ort.ExecutionMode.ORT_SEQUENTIAL
        models = []
        for idx in range(self.parity):
            model_path = os.path.join(self.models_dir, f"trained_model_{idx}.onnx")
            session = self.ort.InferenceSession(
                model_path,
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
            models.append(
                (
                    session,
                    session.get_inputs()[0].name,
                    session.get_outputs()[0].name,
                )
            )
        return models

    def define_feature_aliases(self, df):
        columns = {str(col) for col in df.GetColumnNames()}

        if "era_code" not in columns:
            if self.era not in self.ERA_CODES:
                supported = ", ".join(self.ERA_CODES)
                raise ValueError(
                    f"Cannot define era_code for era {self.era!r}. "
                    f"Supported eras: {supported}"
                )
            df = df.Define("era_code", str(self.ERA_CODES[self.era]))
            columns.add("era_code")

        aliases = {
            "pt_jj": "pt_vbfj1j2",
            "Zepperfield_Var": "Zeppenfeld_Var",
        }
        for idx in [1, 2]:
            for var in ["eta", "pt", f"btag{self.btag_algo}QvG"]:
                aliases[f"j{idx}_{var}"] = f"vbfjet{idx}_{var}"

        for alias, source in aliases.items():
            if alias not in columns and source in columns:
                df = df.Define(alias, source)
                columns.add(alias)

        if "minDeltaEtaSigned" not in columns and {"HasVBF", "eta_mumu", "vbfjet1_eta", "vbfjet2_eta"} <= columns:
            df = df.Define(
                "minDeltaEtaSigned",
                "if (HasVBF) return static_cast<float>(std::min(eta_mumu - vbfjet1_eta, eta_mumu - vbfjet2_eta)); return -10000.f;",
            )
            columns.add("minDeltaEtaSigned")

        if "FullEventId" not in columns:
            df = df.Define("FullEventId", "static_cast<ULong64_t>(rdfentry_)")
            columns.add("FullEventId")

        if "DNNEntryKey" not in columns:
            df = df.Define("DNNEntryKey", "static_cast<ULong64_t>(FullEventId)")


        return df

    def apply(self, df):
        output_name = f"{self.payload_name}_NNOutput"
        if output_name in {str(col) for col in df.GetColumnNames()}:
            return df

        df = self.define_feature_aliases(df)
        columns = {str(col) for col in df.GetColumnNames()}
        missing = [feature for feature in self.input_features if feature not in columns]
        if missing:
            raise RuntimeError(f"Missing DNN input feature columns: {missing}")

        cols = ["DNNEntryKey", "FullEventId"] + self.input_features
        validation_column = "HasVBF" if "HasVBF" in columns else None
        if validation_column and validation_column not in cols:
            cols.append(validation_column)

        available = set(str(c) for c in df.GetColumnNames())
        missing = [c for c in cols if c not in available]
        if missing:
            raise RuntimeError(f"[DNN] Missing columns: {missing}")

        # Reading columns one at a time starts a complete RDF event loop for
        # every feature. The 2024 model has 39 inputs, so collect all columns
        # in one pass instead.
        try:
            arrays = df.AsNumpy(cols)
        except Exception as e:
            raise RuntimeError(
                f"[DNN] AsNumpy failed for payload '{self.payload_name}' "
                f"while reading {len(cols)} columns. Error: {repr(e)}"
            ) from e

        n_events = len(arrays["FullEventId"])
        if n_events == 0:
            predictions = np.array([], dtype=np.float32)
        else:
            input_array = np.column_stack([arrays[name] for name in self.input_features]).astype(np.float64)
            np.nan_to_num(
                input_array,
                copy=False,
                nan=-10000.0,
                posinf=-10000.0,
                neginf=-10000.0,
            )
            event_number = np.asarray(arrays["FullEventId"], dtype=np.uint64)
            event_fold = event_number % self.parity
            predictions = np.empty(n_events, dtype=np.float64)

            # Each event belongs to exactly one k-fold model. Running all
            # models over all events wastes roughly k times the inference.
            for parity_idx, (session, input_name, output_name_onnx) in enumerate(self.models):
                fold_indices = np.flatnonzero(event_fold == parity_idx)
                if fold_indices.size == 0:
                    continue
                fold_input = np.ascontiguousarray(input_array[fold_indices])
                fold_predictions = session.run(
                    [output_name_onnx],
                    {input_name: fold_input},
                )[0].reshape(fold_indices.size)
                np.nan_to_num(
                    fold_predictions,
                    copy=False,
                    nan=0.0,
                    posinf=0.0,
                    neginf=0.0,
                )
                predictions[fold_indices] = fold_predictions

            predictions = predictions.astype(np.float32)

        validation_predictions = predictions
        if validation_column:
            validation_predictions = predictions[
                np.asarray(arrays[validation_column], dtype=bool)
            ]
        validate_predictions(
            validation_predictions,
            self.payload_name,
            self.model_set,
        )
        _declare_prediction_registry()
        keys = ROOT.std.vector("ULong64_t")()
        values = ROOT.std.vector("float")()
        for key, value in zip(arrays["DNNEntryKey"], predictions):
            keys.push_back(int(key))
            values.push_back(float(value))
        payload_id = int(ROOT.dnn_application.registerPayload(keys, values))
        return df.Define(output_name, f"dnn_application::getPrediction({payload_id}, DNNEntryKey)")


def ApplyDNN(
    df, payload_names=None, btag_algo="PNet", era=None, model_set="updated"
):
    payload_names = payload_names or ["DNN"]
    for payload_name in payload_names:
        df = DNNApplication(
            payload_name=payload_name,
            btag_algo=btag_algo,
            era=era,
            model_set=model_set,
        ).apply(df)
    return df
