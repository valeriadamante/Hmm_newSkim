"""Shared skim-ntuple preparation for histograms, training, and snapshots.

prepare_rdf returns the same observables, selections, and weights for every
consumer. It accepts an existing skim RDF or ROOT input files and books no
histograms or snapshots. Callers choose output columns and terminal actions.
prepare_region_dataframes optionally creates region/category views.
"""

import ROOT

from common.utilities import get_segmentation_dict, list_root_files, get_valid_root_files
from common.trigger_weights import AddTriggerWeightsAndErrors
from common.jer_split import define_split_jer_collections
from common.add_vars import (
    GetAllMuonsObservablesNew, SelectedJetObservablesDef,
    SoftJetCollectionCleaningInVBF, VBFJetMuonsObservablesDef, VBFJetObservablesDef,
    DefineSelections, GetSelectionSuffixForSystematic,
)
from common.apply_custom_weights import apply_custom_weights
from common.jet_component_splitting import (
    add_jet_component_categories, expanded_jet_component_categories, define_jet_gen_matching,
)
from common.dnn_histogram_production import (
    apply_sideband_mass_shifted_dnn, needs_sideband_mass_shift,
)

# PyROOT does not own the input TChains; retain them through lazy event loops.
_RDF_INPUT_CHAINS = []


# Input dataframes and base weights
# ---------------------------------

def _inverse_sum_expression(seg_dict):
    if len(seg_dict) == 1 and "return true;" in seg_dict:
        total_val = seg_dict["return true;"]
        return f"{1.0 / total_val}f" if total_val != 0.0 else "0.f"

    expression = "0.f"
    for selection, total_val in seg_dict.items():
        if total_val == 0.0:
            continue
        if selection.strip().lower() == "return true;":
            expression = f"{1.0 / total_val}f"
        else:
            expression = (
                f"({selection}) ? ({1.0 / total_val}f) : ({expression})"
            )
    return expression


def build_rdf(
    rdf,
    is_data,
    seg_dict,
    weight_dict,
    store_shifted_weights,
    dnn_payloads=None,
    btag_algo="PNet",
    era=None,
    dnn_model_set="updated",
    qcd_scale_config=None,
    qcd_scale_seg_dicts=None,
    pdf_config=None,
):
    if not is_data:
        rdf = AddTriggerWeightsAndErrors(
            rdf,
            WantErrors=store_shifted_weights,
        )
        if seg_dict:
            rdf = rdf.Define("inv_N_orig", _inverse_sum_expression(seg_dict))

        if store_shifted_weights and pdf_config is not None:
            from corrections.pdf import define_pdf_weights

            rdf = define_pdf_weights(rdf, pdf_config)

    for weight_name_template, weight_info in weight_dict.items():
        if weight_info.get("derived_envelope", False):
            continue
        if weight_name_template == "Central":
            variations = [("Central", weight_info["expression"])]
        elif store_shifted_weights:
            weight_expression = weight_info.get("expression")
            if weight_expression is None:
                if "relative_expression" not in weight_info:
                    raise RuntimeError(
                        f"Weight '{weight_name_template}' has neither an "
                        "'expression' nor a 'relative_expression'"
                    )
                weight_expression = "1.f"
            if "{scale}" in weight_name_template:
                variations = [
                    (
                        weight_name_template.replace("{scale}", scale),
                        weight_expression.replace("{scale}", scale),
                    )
                    for scale in ("up", "down")
                ]
            else:
                variations = [(weight_name_template, weight_expression)]
        else:
            variations = []

        for weight_name, weight_expression in variations:
            relative_expression = weight_info.get("relative_expression")
            if relative_expression:
                scale = next(
                    (
                        candidate
                        for candidate in ("up", "down")
                        if weight_name
                        == weight_name_template.replace("{scale}", candidate)
                    ),
                    None,
                )
                if scale is None and "{scale}" in relative_expression:
                    raise RuntimeError(
                        f"Cannot resolve scale for relative weight '{weight_name}'"
                    )
                if scale is not None:
                    relative_expression = relative_expression.replace(
                        "{scale}", scale
                    )
                central_expression = weight_dict["Central"]["expression"]
                weight_expression = (
                    f"({central_expression}) * ({relative_expression})"
                )
            expr = "1.f" if is_data else f"({weight_expression}) * inv_N_orig"
            rdf = rdf.Define(f"weight__{weight_name}", expr)

    if (
        store_shifted_weights
        and qcd_scale_config is not None
        and qcd_scale_config.get("enabled", True)
    ):
        from corrections.qcd_scale import get_qcd_scale_points

        if is_data:
            for point in get_qcd_scale_points(qcd_scale_config):
                rdf = rdf.Define(
                    f"weight__QCDScale__{point['name']}",
                    "1.f",
                )
            qcd_scale_config = None

    if (
        not is_data
        and store_shifted_weights
        and qcd_scale_config is not None
        and qcd_scale_config.get("enabled", True)
    ):
        from corrections.qcd_scale import get_qcd_scale_points

        branch = qcd_scale_config.get("branch", "LHEScaleWeight")
        available_columns = {str(column) for column in rdf.GetColumnNames()}
        if branch not in available_columns:
            raise RuntimeError(
                f"QCD scale branch '{branch}' is missing from the skim"
            )
        central_expression = weight_dict["Central"]["expression"]
        for point in get_qcd_scale_points(qcd_scale_config):
            name = point["name"]
            index = int(point["index"])
            point_seg_dict = (qcd_scale_seg_dicts or {}).get(name, {})
            if not point_seg_dict:
                raise RuntimeError(
                    f"Missing qcd_scale__{name} sums in skim reports. "
                    "Reproduce the skim with --want-variations."
                )
            inv_column = f"inv_N_qcd_scale__{name}"
            rdf = rdf.Define(
                inv_column,
                _inverse_sum_expression(point_seg_dict),
            )
            rdf = rdf.Define(
                f"weight__QCDScale__{name}",
                f"({central_expression}) * "
                f"qcd_scale::weightAt({branch}, {index}u) * {inv_column}",
            )
    rdf = SelectedJetObservablesDef(rdf)
    rdf = VBFJetObservablesDef(rdf)
    rdf = GetAllMuonsObservablesNew(rdf)
    rdf = VBFJetMuonsObservablesDef(rdf)
    rdf = SoftJetCollectionCleaningInVBF(rdf)
    if dnn_payloads:
        from common.dnn_application import ApplyDNN

        rdf = ApplyDNN(
            rdf,
            dnn_payloads,
            btag_algo=btag_algo,
            era=era,
            model_set=dnn_model_set,
        )
    return rdf


def GetRdfForDataset(
    input_dir,
    is_data,
    weight_dict,
    store_shifted_weights,
    treeName="Events",
    explicit_files=None,
    seg_dict=None,
    skip_validation=False,
    dnn_payloads=None,
    btag_algo="PNet",
    additional_cuts=None,
    era=None,
    dnn_model_set="updated",
    qcd_scale_config=None,
    qcd_scale_seg_dicts=None,
    pdf_config=None,
):
    """
    Se explicit_files è una lista di file ROOT, RDataFrame caricherà SOLO quei file (chunk).
    Il seg_dict può essere fornito esternamente per evitare di ricalcolarlo in ogni chunk.
    """
    # 1. Calcola il denominatore globale guardando SEMPRE tutti i file JSON della cartella,
    #    a meno che non venga fornito già pre-calcolato.
    if seg_dict is None:
        # Data weights do not use generator-level normalization metadata.
        # In particular, do not send the input directory string to the JSON
        # parser (which historically resulted in one warning per character).
        seg_dict = {} if is_data else get_segmentation_dict(input_dir)

    # 2. Seleziona i file ROOT da processare (tutti o solo il chunk richiesto)
    if explicit_files is not None:
        if isinstance(explicit_files, str):
            files_to_process = [explicit_files]
        else:
            files_to_process = explicit_files
    else:
        files_to_process = list_root_files(input_dir)

    if skip_validation:
        valid_files = files_to_process
    else:
        valid_files = get_valid_root_files(files_to_process, treeName)

    if len(valid_files) == 0:
        print("[WARNING] No valid ROOT files found for this chunk.")
        return None

    # 3. Inizializza l'RDataFrame solo sul chunk di file desiderato.
    # SelectedJet_sortIdx* are derived columns and are recomputed by
    # analysis/jets.py.  Some older campaigns persisted them in only a subset
    # of the files, which makes a TChain created from the first-file schema
    # fail as soon as it reaches a file where those branches are absent.
    # Prefer a file without the optional persisted columns as the schema
    # anchor.  Extra branches appearing in later files are harmless, while a
    # branch advertised by the first file and absent later breaks TTreeReader.
    schema_anchor = None
    for candidate in reversed(valid_files):
        candidate_file = ROOT.TFile.Open(candidate, "READ")
        candidate_tree = candidate_file.Get(treeName) if candidate_file else None
        has_stored_sort = bool(
            candidate_tree and candidate_tree.GetBranch("SelectedJet_sortIdx")
        )
        if candidate_file:
            candidate_file.Close()
        if not has_stored_sort:
            schema_anchor = candidate
            break
    ordered_files = list(valid_files)
    if schema_anchor is not None and ordered_files[0] != schema_anchor:
        ordered_files.remove(schema_anchor)
        ordered_files.insert(0, schema_anchor)

    input_chain = ROOT.TChain(treeName)
    for valid_file in ordered_files:
        input_chain.Add(valid_file)
    input_chain.SetBranchStatus("SelectedJet_sortIdx*", 0)
    _RDF_INPUT_CHAINS.append(input_chain)
    rdf = ROOT.RDataFrame(input_chain)
    if additional_cuts:
        rdf = rdf.Filter(additional_cuts)
    # 4. Applica le definizioni e i pesi (usando il denominatore globale seg_dict)
    rdf_base = build_rdf(
        rdf,
        is_data,
        seg_dict,
        weight_dict,
        store_shifted_weights,
        dnn_payloads=dnn_payloads,
        btag_algo=btag_algo,
        era=era,
        dnn_model_set=dnn_model_set,
        qcd_scale_config=qcd_scale_config,
        qcd_scale_seg_dicts=qcd_scale_seg_dicts,
        pdf_config=pdf_config,
    )
    return rdf_base


# Systematic columns and final selections
# ---------------------------------------

def normalize_systematic_direction_columns(rdf, systs_to_run):
    """Alias systematic columns across the historical direction spellings."""
    available_columns = {str(column) for column in rdf.GetColumnNames()}
    for syst_info in systs_to_run.values():
        requested_suffixes = {
            syst_info.get(key, "") for key in ("jet_suffix", "muon_suffix")
        }
        for requested_suffix in requested_suffixes - {""}:
            alternate_suffix = None
            for ending, alternate in (
                ("Up", "up"), ("up", "Up"),
                ("Down", "down"), ("down", "Down"),
            ):
                if requested_suffix.endswith(ending):
                    alternate_suffix = (
                        f"{requested_suffix[:-len(ending)]}{alternate}"
                    )
                    break
            if not alternate_suffix:
                continue
            for source in tuple(available_columns):
                if not source.endswith(alternate_suffix):
                    continue
                target = f"{source[:-len(alternate_suffix)]}{requested_suffix}"
                if target not in available_columns:
                    rdf = rdf.Alias(target, source)
                    available_columns.add(target)
    return rdf


def define_shifted_jet_observables(rdf, systs_to_run):
    """Define derived selected-jet and VBF observables for shifted jets."""
    defined_suffixes = set()
    available_columns = {str(column) for column in rdf.GetColumnNames()}
    for syst_info in systs_to_run.values():
        jet_suffix = syst_info.get("jet_suffix", "")
        if not jet_suffix or jet_suffix in defined_suffixes:
            continue
        required = {
            f"SelectedJet_idx{jet_suffix}",
            f"SelectedJet_pt{jet_suffix}",
            f"SelectedJet_eta{jet_suffix}",
            f"SelectedJet_phi{jet_suffix}",
            f"SelectedJet_mass{jet_suffix}",
            f"SelectedJet_IsInsideHorn{jet_suffix}",
            f"HasVBF{jet_suffix}",
            f"VBFJetIdx_1{jet_suffix}",
            f"VBFJetIdx_2{jet_suffix}",
        }
        missing = sorted(required - available_columns)
        if missing:
            raise RuntimeError(
                f"Cannot build jet variation '{jet_suffix}'; missing columns: "
                + ", ".join(missing)
            )
        rdf = SelectedJetObservablesDef(rdf, suffix=jet_suffix)
        rdf = VBFJetObservablesDef(rdf, suffix=jet_suffix)
        defined_suffixes.add(jet_suffix)
        available_columns = {str(column) for column in rdf.GetColumnNames()}
    return rdf


def apply_selection_and_weights(
    rdf,
    dataset_name,
    selections_cfg,
    systematics_cfg,
    weight_columns,
    era,
    want_variations=False,
    multiply_corrections=True,
    apply_jet_component_weight=True,
    apply_dy_ptll_weight=True,
    apply_dy_njets_weight=True,
    apply_custom_weight_corrections=True,
    reweight_jsons=None,
):
    """Apply selections and final weight corrections exactly once."""
    rdf = DefineSelections(
        rdf,
        selections_cfg,
        syst_cfg=systematics_cfg,
        want_variations=want_variations,
    )
    columns = {str(column) for column in rdf.GetColumnNames()}
    for source in ("leadingjet_eta", "subleadingjet_eta", "vbfjet1_eta"):
        target = f"abs_{source}"
        if source in columns and target not in columns:
            rdf = rdf.Define(target, f"std::abs({source})")
            columns.add(target)
    target_weights = weight_columns if multiply_corrections else []
    return apply_custom_weights(
        rdf,
        dataset_name,
        era,
        target_weights,
        apply_jet_component=apply_jet_component_weight,
        apply_dy_ptll=apply_dy_ptll_weight,
        apply_dy_njets=apply_dy_njets_weight,
        apply_custom_reweights=apply_custom_weight_corrections,
        reweight_jsons=reweight_jsons,
    )


# Production and region preparation
# ---------------------------------

def prepare_rdf(
    rdf=None, *, dataset_name, era, selections_cfg, systematics_cfg,
    is_data=False, input_dir=None, input_files=None, seg_dict=None,
    systs_to_run=None, want_variations=False, dnn_payloads=None,
    btag_algo="PNet", dnn_model_set="updated", additional_cuts=None,
    qcd_scale_seg_dicts=None, skip_validation=False,
    enable_dy012j=True, enable_dyptll=True, enable_dynjets=True,
    enable_custom_weights=True, reweight_jsons=None,
    split_jet_multiplicity=False, include_vbf_eta_regions=False,
    component_categories=("ggF", "VBF"),
):
    """Return an ordered dict of prepared RDFs (empty if no input files).

    Supply either a raw skim ``rdf`` or ``input_dir``/``input_files``.
    Inputs use this analysis's skim schema, rather than unprocessed NanoAOD.
    The returned nodes support Histo1D, Snapshot, AsNumpy, or further transforms.
    Region/category selections are defined as columns; filter the desired view
    explicitly or use prepare_region_dataframes before exporting tuples.
    ``seg_dict`` must contain the full dataset normalization, also for batches.
    Three independent switches control DY012J, DYptll and DYNJets; nominal
    normalization remains applied when custom weights are disabled.
    Splitting returns inclusive plus ggF 0J/1J/>=2J hard/PU and VBF hard/PU
    nodes; data returns inclusive only. Component nodes use central selections;
    the inclusive node also carries shifted category columns for systematics.
    The caller owns ROOT runtime initialization and DNN registry cleanup.
    """
    systs_to_run = systs_to_run or {"Central": {"weight": "weight__Central"}}
    build_options = dict(
        is_data=is_data, weight_dict=systematics_cfg["weights"],
        store_shifted_weights=want_variations, seg_dict=seg_dict,
        dnn_payloads=dnn_payloads, btag_algo=btag_algo, era=era,
        dnn_model_set=dnn_model_set,
        qcd_scale_config=systematics_cfg.get("qcd_scale"),
        qcd_scale_seg_dicts=qcd_scale_seg_dicts,
        pdf_config=systematics_cfg.get("pdf"),
    )
    if rdf is None:
        rdf = GetRdfForDataset(
            input_dir=input_dir, explicit_files=input_files,
            additional_cuts=additional_cuts, skip_validation=skip_validation,
            **build_options,
        )
    else:
        if additional_cuts:
            rdf = rdf.Filter(additional_cuts)
        rdf = build_rdf(rdf, **build_options)
    if rdf is None:
        return {}
    rdf = normalize_systematic_direction_columns(rdf, systs_to_run)
    rdf = define_split_jer_collections(rdf, systs_to_run)
    rdf = define_shifted_jet_observables(rdf, systs_to_run)
    columns = {str(column) for column in rdf.GetColumnNames()}
    split = split_jet_multiplicity and not is_data
    can_match = bool({"Jet_genJetIdx", "SelectedJet_genJetIdx"} & columns)
    if split and not can_match:
        raise RuntimeError("Jet component splitting requires reco/gen matching indices")
    if not is_data and can_match:
        rdf = define_jet_gen_matching(
            rdf, {""} | {info.get("jet_suffix", "") for info in systs_to_run.values()}
        )
    if split:
        selections_cfg = add_jet_component_categories(
            selections_cfg, include_vbf_eta_regions=include_vbf_eta_regions,
            requested_categories=component_categories,
        )
    weight_columns = sorted({info["weight"] for info in systs_to_run.values() if "weight" in info})
    rdf = apply_selection_and_weights(
        rdf, dataset_name, selections_cfg, systematics_cfg, weight_columns, era,
        want_variations=want_variations,
        apply_jet_component_weight=enable_dy012j,
        apply_dy_ptll_weight=enable_dyptll,
        apply_dy_njets_weight=enable_dynjets,
        apply_custom_weight_corrections=enable_custom_weights,
        reweight_jsons=reweight_jsons,
    )
    result = {"inclusive": rdf}
    if split:
        for category in expanded_jet_component_categories(
            include_vbf_eta_regions=include_vbf_eta_regions,
            requested_categories=component_categories,
        ):
            result[category] = rdf.Filter(category)
    return result


def prepare_region_dataframes(
    rdf, *, mass_regions, categories, systs_to_run, variables=(),
    btag_algo="PNet", era=None, dnn_model_set="updated",
):
    """Build cached region/category nodes, including sideband DNN inputs.

    Keys are (mass region, category, selection suffix); values are
    (RDF, available columns). This performs no histogram booking.
    """
    base_columns = {str(column) for column in rdf.GetColumnNames()} if rdf is not None else set()
    selection_suffixes = {
        GetSelectionSuffixForSystematic(name, info)
        for name, info in systs_to_run.items()
    }
    required_selection_columns = {
        f"{selection}{suffix}"
        for suffix in selection_suffixes
        for selection in (*mass_regions, *categories)
    }
    missing_selection_columns = sorted(required_selection_columns - base_columns)
    if rdf is not None and missing_selection_columns:
        raise RuntimeError(
            "Missing histogram selection column(s): "
            + ", ".join(missing_selection_columns)
        )
    # Apply each sideband DNN once per distinct selection suffix, before any
    # histograms are booked. ApplyDNN materializes its inputs; doing this in
    # the booking loop would otherwise trigger repeated RDF event loops.
    shifted_rdfs = {}
    if rdf is not None and "DNN_NNOutput" in variables:
        for mass_region in mass_regions:
            if not needs_sideband_mass_shift(
                mass_region, "DNN_NNOutput"
            ):
                continue
            for selection_suffix in selection_suffixes:
                mass_column = f"{mass_region}{selection_suffix}"
                region_rdf = rdf.Filter(
                    mass_column,
                    f"{mass_region}_{selection_suffix or 'central'}_dnn_input",
                )
                shifted_rdf = apply_sideband_mass_shifted_dnn(
                    region_rdf,
                    mass_region,
                    btag_algo=btag_algo,
                    era=era,
                    model_set=dnn_model_set,
                )
                shifted_rdfs[(mass_region, selection_suffix)] = (
                    shifted_rdf,
                    {str(column) for column in shifted_rdf.GetColumnNames()},
                )
    # Weight-only systematics share their selection suffix. Cache each
    # region/category filter so its predicate is evaluated once per event,
    # rather than once for every weight variation.
    filtered_rdfs = {}
    if rdf is not None:
        for selection_suffix in selection_suffixes:
            for mass_region in mass_regions:
                mass_column = f"{mass_region}{selection_suffix}"
                shifted_entry = shifted_rdfs.get(
                    (mass_region, selection_suffix)
                )
                region_rdf = (
                    shifted_entry[0]
                    if shifted_entry is not None
                    else rdf.Filter(mass_column)
                )
                for category in categories:
                    category_column = f"{category}{selection_suffix}"
                    cache_key = (
                        mass_region,
                        category,
                        selection_suffix,
                    )
                    if shifted_entry is not None:
                        _, available_columns = shifted_entry
                    else:
                        available_columns = base_columns
                    filtered_rdf = region_rdf.Filter(category_column)
                    filtered_rdfs[cache_key] = (
                        filtered_rdf,
                        available_columns,
                    )
    return filtered_rdfs
