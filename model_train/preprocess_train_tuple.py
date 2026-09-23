"""
First (of two) scripts. Script to run over skims, apply a selection, and write 1 new root file per process (per era)
with the combined samples postselection. Basically the same pipeline Valeria uses to produce HistTuples.
"""


import ROOT
import sys
import os
import argparse
from pprint import pprint
from glob import glob

ROOT.gROOT.SetBatch(True)
ROOT.EnableThreadSafety()

sys.path.append(os.environ["ANALYSIS_PATH"])

import common.utilities as utilities
from common.rdf_utilities import GetRdfForDataset
from common.add_vars_to_skim_tuples import DefineHistogramSelections, SelectedJetObservablesDef
from common.dy_ptll_reweight import ApplyDYNJetsReweight, ApplyDYPtLLReweight, ApplyDYAmcatnloNormalization
from common.gen_vbf_filter import ApplyGenVBFFilter

HEADERS = ["analysis/AnalysisTools.h"]
for header in HEADERS:
    utilities.DeclareHeader(f"{os.environ['ANALYSIS_PATH']}/{header}")


def get_arguments():
    """
    Builds an argument parser to get CLI arguments for the config file and dataset directory.
    """
    parser = argparse.ArgumentParser(
        prog="TrainTupleGenerator",
        description="For a given directory and era(s) therewithin, read and filter skim tuples",
    )
    parser.add_argument("-c", "--config", required=True, help="the .toml config file")
    parser.add_argument(
        "-e",
        "--era",
        required=True,
        help="the era to run, or 'all'",
    )
    args = parser.parse_args()
    return args


def do_one_dataset(input_dir, dataset, is_data, era, syst_cfg, parser_cfg, sel_cfg, dy_ptll_njets_reweight_json=None, dy_njets_reweight_json=None):
    """
    Primary workhorse function. Takes a skip tuple dataset directory and returns an RDF.
    Corrections for DY are calculated and input features not included at skim level calculated.
    """
    ### Load the dataframe and add some additional features

    if is_data:
        weight_dict = {}
    else:
        weight_dict = syst_cfg["weights"]


    rdf = GetRdfForDataset(
        input_dir,
        is_data,
        weight_dict,
        store_shifted_weights=False,
        treeName="Events",
    )

    if rdf is None:
        return None

    if is_data:
        rdf = DefineHistogramSelections(
            rdf,
            sel_cfg,
            syst_cfg=None,
            want_variations=False
        )
    else:
        rdf = DefineHistogramSelections(
            rdf,
            sel_cfg,
            syst_cfg=syst_cfg,
            want_variations=False
        )

    ### Filter
    rdf = rdf.Filter(parser_cfg["meta"]["selection"])

    ### DY Reweighting stuff
    systs_to_run = {
        "Central": syst_cfg["systematics"]["Central"]
    }
    weight_columns = sorted(
        {
            syst_info["weight"]
            for syst_info in systs_to_run.values()
            if "weight" in syst_info
        }
    )

    if 'DY' in dataset:
        rdf = ApplyDYAmcatnloNormalization(rdf, dataset, weight_columns)

    if dy_ptll_njets_reweight_json:
        print("\t\tApplying PTll reweight...")
        rdf = ApplyDYPtLLReweight(
            rdf,
            dataset,
            dy_ptll_njets_reweight_json,
            weight_columns,
        )
    if dy_njets_reweight_json:
        print("\t\tApplying NJet reweight...")
        rdf = ApplyDYNJetsReweight(
            rdf,
            dataset,
            dy_njets_reweight_json,
            weight_columns,
        )

    if "GenVBFFilter" in rdf.GetColumnNames():
        if dataset == "DYto2Mu_MLL_105to160_amcatnloFXFX":
            print("\t\tApplying GenVBFFilter on inclusive...")
            rdf = rdf.Filter("GenVBFFilter==0")
        elif dataset == "DYto2Mu_MLL_105to160_amcatnloFXFX_Fil_VBF":
            print("\t\tApplying GenVBFFilter on VBFFil...")
            rdf = rdf.Filter("GenVBFFilter==1")


    ### Add some booking keeping metadata columns
    rdf = rdf.Define(
        "dataset",
        f'vector<string> v; v.push_back("{dataset}"); return v;',
    )
    rdf = rdf.Define(
        "era", f'vector<string> v; v.push_back("{era}"); return v;'
    )
    rdf = rdf.Define(
        "process",
        f'vector<string> v; v.push_back("{process_name}"); return v;',
    )

    return rdf


if __name__ == "__main__":
    """
    Run over specified eras, then run over specified processes, then run over specified datasets.
    Three level nested loop. Save a new .root file for each dataset that is already selected and
    has needed input features for DNN. Weights should be calculated for training/testing models.
    Main dataset processing logic is in its own functions above.
    """

    ### Do some init/setup ###

    args = get_arguments()
    parser_cfg = utilities.get_config(args.config)

    if args.era.lower() == "all":
        eras = [
            "Run3_2022",
            "Run3_2022EE",
            "Run3_2023",
            "Run3_2023BPix",
            "Run3_2024",
            "Run3_2025",
            #"Run3_2026"
        ]
    else:
        eras = [args.era]

    output_columns = []
    for k, cols in parser_cfg["columns_config"].items():
        if cols is not None:
            output_columns += cols

    ### Run over each era and dataset. Save a single filtered + filled .root per dataset. ###

    for era in eras:
        print("On era:", era)

        # Read all era specific configs
        cfg_dir = os.path.join(os.environ["ANALYSIS_PATH"], "config", era)
        main_cfg = utilities.get_config(os.path.join(cfg_dir, "maincfg.yaml"))
        process_cfg = utilities.get_config(os.path.join(cfg_dir, "process_names.yaml"))
        syst_cfg = utilities.get_config(os.path.join(cfg_dir, "systematics.yaml"))
        sel_cfg = utilities.get_config(os.path.join(cfg_dir, "selections.yaml"))
       
        # Iterate over processes --> datasets
        for process_name in parser_cfg["era_processes"][era]:
            print("\tOn process:", process_name)
            try:
                all_sets = process_cfg[process_name]["datasets"]
            except KeyError:
                all_sets = []
                sub_p = process_cfg[process_name]["sub_processes"]
                for p in sub_p:
                    all_sets += process_cfg[p]["datasets"]
            for dataset in all_sets:
                print("\t\tOn dataset:", dataset)
                input_dir = os.path.join(parser_cfg["meta"]["skim_dir"], era, dataset)

                if 'DY' in dataset:
                    # if era == 'Run3_2025':
                    #     temp_era = 'Run3_2024'
                    # else:
                    #     temp_era = era
                    temp_era = era
                    reweight_dir = os.path.join(os.environ["ANALYSIS_PATH"], "reweights")
                    pattern = os.path.join(reweight_dir, "dy_ptll_reweight", temp_era, "*.json")
                    dy_ptll_njets_reweight_json = glob(pattern)[0]
                    #print("PTLL reweight:", dy_ptll_njets_reweight_json)
                    pattern = os.path.join(reweight_dir, "dy_njets_reweight", temp_era, "*.json")
                    dy_njets_reweight_json = glob(pattern)[0]
                    #print("NJets reweight:", dy_njets_reweight_json)
                else:
                    dy_ptll_njets_reweight_json = None
                    dy_njets_reweight_json = None

                if 'data' in process_name.lower():
                    is_data = True
                else:
                    is_data = False
                print("\t\tIs data?", is_data)

                # dy_ptll_njets_reweight_json = None
                # dy_njets_reweight_json = None
            
                rdf = do_one_dataset(
                    input_dir, 
                    dataset, 
                    is_data,
                    era,
                    syst_cfg, 
                    parser_cfg, 
                    sel_cfg, 
                    dy_ptll_njets_reweight_json, 
                    dy_njets_reweight_json
                )
                if rdf is not None:
                    outname = os.path.join(
                        parser_cfg["meta"]["output_dir"], era, f"{dataset}.root"
                    )
                    rdf.Snapshot("Events", outname, output_columns)
                else:
                    print("\t\t*** Dataset failed:", dataset)
