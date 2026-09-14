import json
import math
import os
from pathlib import Path

import yaml

CORRECTION_NAMES = {
    "dy_ptll_njets_reweight": "dy_ptll_reweight",
    "dy_njets_reweight": "dy_njets_reweight",
    "dy_jet_component_reweight": "dy_012j_reweight",
}

DY_AMCATNLO_NORMALIZATION = 0.9393839712918659
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

# Keys of the ``reweight_jsons`` block of a process entry in process_names.yaml.
DY_REWEIGHT_KEYS = ("ptll_njets", "njets", "jet_component")
# Process entry used when the dataset does not declare its own payloads.
DY_REWEIGHT_FALLBACK_PROCESS = "DY"


def _process_entry_for_dataset(process_cfg, dataset_name):
    """Return (process, entry) of the process_names.yaml entry owning a dataset."""
    if not dataset_name:
        return None, None
    for process, entry in process_cfg.items():
        if not isinstance(entry, dict):
            continue
        datasets = list(entry.get("datasets") or [])
        datasets.extend(entry.get("sub_processes") or [])
        if dataset_name in datasets:
            return process, entry
    return None, None


def configured_reweight_jsons(era, dataset_name=None):
    """Read the DY reweight payloads declared in config/<era>/process_names.yaml.

    Returns ``(reweight_jsons, process, config_path)``.  The entry owning
    ``dataset_name`` wins; otherwise the inclusive ``DY`` entry is used, which is
    the one every era aliases its other DY processes to.
    """
    config_path = REPOSITORY_ROOT / "config" / str(era) / "process_names.yaml"
    if not config_path.is_file():
        raise FileNotFoundError(
            f"Cannot resolve the DY reweight JSONs for era {era}: "
            f"missing {config_path}"
        )
    process_cfg = yaml.safe_load(config_path.read_text()) or {}
    process, entry = _process_entry_for_dataset(process_cfg, dataset_name)
    if not isinstance(entry, dict) or "reweight_jsons" not in entry:
        process = DY_REWEIGHT_FALLBACK_PROCESS
        entry = process_cfg.get(process) or {}
    return dict(entry.get("reweight_jsons") or {}), process, config_path


def reweight_json_paths(era, configured_paths=None, required=None, dataset_name=None):
    """Return the histogram reweight payloads configured for one physical era.

    ``configured_paths`` is the ``reweight_jsons`` block of a process entry in
    ``config/<era>/process_names.yaml``.  When it is None the block is read back
    from that file: there is no hard-coded payload location, so a caller that
    forgets to forward the process configuration gets the configured payloads
    rather than a silently different set.  Payload locations therefore only ever
    change by editing the era configuration.
    """
    era_name = str(era)
    if configured_paths is None:
        configured_paths, process, config_path = configured_reweight_jsons(
            era_name, dataset_name
        )
        source = f"{config_path}, process {process}"
        print(
            f"[INFO] DY reweight JSONs for era {era_name} resolved from {source}"
        )
    else:
        source = f"the caller (config/{era_name}/process_names.yaml)"

    paths = {}
    for name, configured_path in (configured_paths or {}).items():
        if name not in DY_REWEIGHT_KEYS:
            raise KeyError(f"Unknown DY reweight JSON key: {name}")
        path = Path(configured_path)
        paths[name] = path if path.is_absolute() else REPOSITORY_ROOT / path

    required = set(DY_REWEIGHT_KEYS) if required is None else set(required)
    unknown = sorted(required - set(DY_REWEIGHT_KEYS))
    if unknown:
        raise KeyError(f"Unknown DY reweight JSON key: {', '.join(unknown)}")
    unconfigured = sorted(required - set(paths))
    if unconfigured:
        raise KeyError(
            f"No DY reweight JSON configured for era {era_name}: "
            + ", ".join(unconfigured)
            + f" (expected under reweight_jsons in {source})"
        )
    missing = [str(paths[name]) for name in sorted(required) if not paths[name].is_file()]
    if missing:
        raise FileNotFoundError(
            f"Missing histogram reweight JSON for era {era_name} "
            f"(configured in {source}): " + ", ".join(missing)
        )
    return paths


def _column_names(df):
    return {str(col) for col in df.GetColumnNames()}


def is_dy_dataset(dataset_name):
    if not dataset_name:
        return False

    name = dataset_name.lower()
    return name.startswith("dy") or "dyto" in name


def is_dy_amcatnlo_dataset(dataset_name):
    if not dataset_name:
        return False
    name = dataset_name.lower()
    return is_dy_dataset(name) and "amcatnlo" in name


def load_reweight_json(json_path, expected_type=None):
    with open(json_path) as handle:
        payload = json.load(handle)

    if payload.get("schema_version") == 2 and "corrections" in payload:
        return _payload_from_correctionlib(payload, expected_type, json_path)

    if expected_type is not None and payload.get("type") != expected_type:
        raise ValueError(
            f"Unsupported DY reweight JSON type in {json_path}: "
            f"{payload.get('type')}"
        )

    return payload


def _find_correction(correction_set, expected_type, json_path):
    corrections = correction_set.get("corrections", [])
    expected_name = CORRECTION_NAMES.get(expected_type, expected_type)

    for correction in corrections:
        if correction.get("name") == expected_name:
            return correction

    if expected_type is None and len(corrections) == 1:
        return corrections[0]

    names = [correction.get("name") for correction in corrections]
    raise ValueError(
        f"Correction '{expected_name}' not found in {json_path}. "
        f"Available corrections: {names}"
    )


def _category_content(category_node, key):
    for item in category_node.get("content", []):
        if item.get("key") == key:
            return item.get("value")
    return category_node.get("default", 1.0)


def _formula_parameters(node):
    if not isinstance(node, dict) or node.get("nodetype") != "formula":
        return None
    return node.get("parameters", [])


def _ptll_payload_from_correction(correction):
    data = correction["data"]
    ggF_node = _category_content(data, 0)
    vbf_node = _category_content(data, 1)

    categories = {}
    if isinstance(ggF_node, dict):
        ggF_content = ggF_node.get("content", [])
        for name, node in zip(["ggF_0J", "ggF_1J", "ggF_ge2J"], ggF_content):
            params = _formula_parameters(node)
            if params is not None:
                categories[name] = {"fit": {"parameters": params}}

    if isinstance(vbf_node, dict):
        for node in vbf_node.get("content", []):
            params = _formula_parameters(node)
            if params is not None:
                categories["VBF_ge2J"] = {"fit": {"parameters": params}}

    return {
        "type": "dy_ptll_njets_reweight",
        "x_variable": "pt_mumu",
        "min_weight": 0.0,
        "max_weight": 5.0,
        "categories": categories,
    }


def _bins_from_binning_node(node):
    if not isinstance(node, dict) or node.get("nodetype") != "binning":
        return []

    edges = node.get("edges", [])
    content = node.get("content", [])
    bins = []
    for index, weight in enumerate(content):
        if index + 1 >= len(edges):
            break
        high = edges[index + 1]
        if float(high) >= 999.0:
            high = None
        bins.append(
            {
                "low": float(edges[index]),
                "high": high,
                "weight": float(weight),
            }
        )
    return bins


def _njets_payload_from_correction(correction):
    data = correction["data"]
    return {
        "type": "dy_njets_reweight",
        "min_weight": 0.0,
        "max_weight": 5.0,
        "categories": {
            "ggF": {"bins": _bins_from_binning_node(_category_content(data, 0))},
            "VBF": {"bins": _bins_from_binning_node(_category_content(data, 1))},
        },
    }


def _payload_from_correctionlib(correction_set, expected_type, json_path):
    correction = _find_correction(correction_set, expected_type, json_path)
    correction_name = correction.get("name")

    if correction_name == "dy_ptll_reweight":
        payload = _ptll_payload_from_correction(correction)
    elif correction_name == "dy_njets_reweight":
        payload = _njets_payload_from_correction(correction)
    else:
        raise ValueError(
            f"Unsupported DY correctionlib correction in {json_path}: "
            f"{correction_name}"
        )

    if expected_type is not None and payload.get("type") != expected_type:
        raise ValueError(
            f"Unsupported DY reweight JSON type in {json_path}: "
            f"{payload.get('type')}"
        )

    return payload


def _format_float(value):
    value = float(value)
    if not math.isfinite(value):
        return "0.0"
    return repr(value)


def _category_expression(category, condition, params, x_variable, min_weight, max_weight):
    parameters = [_format_float(value) for value in params]
    if len(parameters) != 10:
        raise ValueError(
            f"Category {category} has {len(parameters)} fit parameters, expected 10"
        )

    p = parameters

    return f"""
    if ({condition}) {{
        const double x = std::max(static_cast<double>({x_variable}), 0.0);
        const double floor_x = std::max(x, {p[8]});
        double weight =
            {p[0]}
            + {p[1]} * std::exp(-0.5 * std::pow((x - {p[2]}) / std::max({p[3]}, 1e-6), 2.0))
            + {p[4]} * std::exp(-0.5 * std::pow((x - {p[5]}) / std::max({p[6]}, 1e-6), 2.0))
            + {p[7]} * std::pow(floor_x / std::max({p[8]}, 1e-6), -{p[9]});
        if (!std::isfinite(weight)) weight = 1.0;
        return static_cast<float>(std::min(std::max(weight, {min_weight}), {max_weight}));
    }}
    """


def _condition_for_category(category, available_columns):
    if {"ggF", "VBF", "N_SelectedJets"}.issubset(available_columns):
        if category == "ggF_0J":
            return "ggF && N_SelectedJets == 0"
        if category == "ggF_1J":
            return "ggF && N_SelectedJets == 1"
        if category == "ggF_ge2J":
            return "ggF && N_SelectedJets >= 2"
        if category == "VBF_ge2J":
            return "VBF && N_SelectedJets >= 2"

    if category in available_columns:
        return category

    return None


def build_ptll_reweight_expression(payload, available_columns):
    x_variable = payload.get("x_variable", "pt_mumu")
    if x_variable not in available_columns:
        raise RuntimeError(
            f"DY pt(ll)/NJets reweight variable '{x_variable}' not found in RDF"
        )

    min_weight = _format_float(payload.get("min_weight", 0.0))
    max_weight = _format_float(payload.get("max_weight", 5.0))

    pieces = []
    for category, category_payload in payload.get("categories", {}).items():
        condition = _condition_for_category(category, available_columns)
        if condition is None:
            continue

        params = category_payload.get("fit", {}).get("parameters", [])
        pieces.append(
            _category_expression(
                category,
                condition,
                params,
                x_variable,
                min_weight,
                max_weight,
            )
        )

    if not pieces:
        raise RuntimeError(
            "None of the DY pt(ll)/NJets reweight categories are available in RDF. "
            f"JSON categories: {sorted(payload.get('categories', {}).keys())}"
        )

    return "\n".join(pieces) + "\nreturn 1.f;"


def _njets_category_condition(category, available_columns):
    if "VBF" in available_columns:
        if category == "VBF":
            return "VBF"
        if category == "ggF":
            return "!VBF"

    if category in available_columns:
        return category

    return None


def build_njets_reweight_expression(payload, available_columns):
    if "N_SelectedJets" not in available_columns:
        raise RuntimeError("DY NJets reweight variable 'N_SelectedJets' not found in RDF")

    min_weight = _format_float(payload.get("min_weight", 0.0))
    max_weight = _format_float(payload.get("max_weight", 5.0))
    pieces = []

    for category, category_payload in payload.get("categories", {}).items():
        category_condition = _njets_category_condition(category, available_columns)
        if category_condition is None:
            continue

        for bin_payload in category_payload.get("bins", []):
            low = _format_float(bin_payload["low"])
            high = bin_payload.get("high")
            weight = _format_float(bin_payload.get("weight", 1.0))

            njets_condition = f"N_SelectedJets >= {low}"
            if high is not None:
                njets_condition += f" && N_SelectedJets < {_format_float(high)}"

            pieces.append(
                f"""
    if (({category_condition}) && ({njets_condition})) {{
        double weight = {weight};
        if (!std::isfinite(weight)) weight = 1.0;
        return static_cast<float>(std::min(std::max(weight, {min_weight}), {max_weight}));
    }}
                """
            )

    if not pieces:
        raise RuntimeError(
            "None of the DY NJets reweight categories are available in RDF. "
            f"JSON categories: {sorted(payload.get('categories', {}).keys())}"
        )

    return "\n".join(pieces) + "\nreturn 1.f;"


def build_jet_component_reweight_expression(payload, available_columns):
    required = {"VBF", "N_SelectedJets", "N_PU_FirstTwoJets", "N_PU_VBFJets"}
    missing = sorted(required - available_columns)
    if missing:
        raise RuntimeError(
            "DY jet-component reweight columns not found in RDF: "
            + ", ".join(missing)
        )

    correction = _find_correction(
        payload, "dy_jet_component_reweight", "DY jet-component payload"
    )
    data = correction.get("data", {})
    weights = {item["key"]: item["value"] for item in data.get("content", [])}
    expected = {
        "0J", "1JHard", "1JPU", "2JHard", "2JPU1", "2JPU2",
        "VBFHard", "VBFPU1", "VBFPU2",
    }
    if set(weights) != expected:
        raise ValueError(f"DY jet-component payload must contain {sorted(expected)}")
    conditions = {
        "0J": "!VBF && N_SelectedJets == 0",
        "1JHard": "!VBF && N_SelectedJets == 1 && N_PU_FirstTwoJets == 0",
        "1JPU": "!VBF && N_SelectedJets == 1 && N_PU_FirstTwoJets == 1",
        "2JHard": "!VBF && N_SelectedJets >= 2 && N_PU_FirstTwoJets == 0",
        "2JPU1": "!VBF && N_SelectedJets >= 2 && N_PU_FirstTwoJets == 1",
        "2JPU2": "!VBF && N_SelectedJets >= 2 && N_PU_FirstTwoJets == 2",
        "VBFHard": "VBF && N_PU_VBFJets == 0",
        "VBFPU1": "VBF && N_PU_VBFJets == 1",
        "VBFPU2": "VBF && N_PU_VBFJets == 2",
    }
    return "\n".join(
        f"if ({condition}) return static_cast<float>({_format_float(weights[name])});"
        for name, condition in conditions.items()
    ) + "\nreturn 1.f;"


def _define_and_multiply_weight(df, expression, weight_columns, output_column, available_columns):
    if output_column in available_columns:
        df = df.Redefine(output_column, expression)
    else:
        df = df.Define(output_column, expression)
        available_columns.add(output_column)

    for weight_column in sorted(set(weight_columns)):
        if weight_column not in available_columns:
            continue
        df = df.Redefine(
            weight_column,
            f"static_cast<float>({weight_column} * {output_column})",
        )

    return df


def ApplyDYAmcatnloNormalization(
    df,
    dataset_name,
    weight_columns,
    scale=DY_AMCATNLO_NORMALIZATION,
    output_column="weight_dy_amcatnlo_normalization",
):
    if not is_dy_amcatnlo_dataset(dataset_name):
        return df

    available_columns = _column_names(df)
    return _define_and_multiply_weight(
        df,
        f"static_cast<float>({float(scale):.17g})",
        weight_columns,
        output_column,
        available_columns,
    )


def ApplyDYPtLLReweight(
    df,
    dataset_name,
    json_path,
    weight_columns,
    output_column="weight_dy_ptll_njets",
):
    if not json_path:
        return df

    if not is_dy_dataset(dataset_name):
        return df

    if not os.path.exists(json_path):
        raise FileNotFoundError(
            f"DY pt(ll)/NJets reweight JSON not found: {json_path}"
        )

    payload = load_reweight_json(json_path, "dy_ptll_njets_reweight")
    available_columns = _column_names(df)
    expression = build_ptll_reweight_expression(payload, available_columns)
    return _define_and_multiply_weight(
        df,
        expression,
        weight_columns,
        output_column,
        available_columns,
    )


def ApplyDYNJetsReweight(
    df,
    dataset_name,
    json_path,
    weight_columns,
    output_column="weight_dy_njets",
):
    if not json_path:
        return df

    if not is_dy_dataset(dataset_name):
        return df

    if not os.path.exists(json_path):
        raise FileNotFoundError(
            f"DY NJets reweight JSON not found: {json_path}"
        )

    payload = load_reweight_json(json_path, "dy_njets_reweight")
    available_columns = _column_names(df)
    expression = build_njets_reweight_expression(payload, available_columns)
    return _define_and_multiply_weight(
        df,
        expression,
        weight_columns,
        output_column,
        available_columns,
    )


def ApplyDYJetComponentReweight(
    df,
    dataset_name,
    json_path,
    weight_columns,
    output_column="weight_dy_jet_component",
):
    if not is_dy_dataset(dataset_name):
        return df

    with open(json_path) as handle:
        payload = json.load(handle)
    available_columns = _column_names(df)
    expression = build_jet_component_reweight_expression(payload, available_columns)
    return _define_and_multiply_weight(
        df, expression, weight_columns, output_column, available_columns
    )


def apply_custom_weights(
    df,
    dataset_name,
    era,
    weight_columns,
    apply_jet_component=True,
    apply_dy_ptll=True,
    apply_dy_njets=True,
    apply_custom_reweights=True,
    reweight_jsons=None,
):
    """Apply every custom histogram-production weight configured for the era."""
    df = ApplyDYAmcatnloNormalization(df, dataset_name, weight_columns)
    if not apply_custom_reweights:
        return df
    if not is_dy_dataset(dataset_name):
        return df

    required = []
    if apply_dy_ptll:
        required.append("ptll_njets")
    if apply_dy_njets:
        required.append("njets")
    if apply_jet_component:
        required.append("jet_component")
    paths = reweight_json_paths(era, reweight_jsons, required, dataset_name=dataset_name)
    if apply_dy_ptll:
        df = ApplyDYPtLLReweight(
            df, dataset_name, paths["ptll_njets"], weight_columns
        )
    if apply_dy_njets:
        df = ApplyDYNJetsReweight(df, dataset_name, paths["njets"], weight_columns)
    return ApplyDYJetComponentReweight(df, dataset_name, paths["jet_component"], weight_columns) if apply_jet_component else df
