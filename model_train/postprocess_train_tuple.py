"""
Second script, run preprocess_train_tuple first. Combines the per process .root files into one big Pandas dataframe.
"""

import uproot
import pandas as pd
import numpy as np
import os
import argparse
from glob import glob
import sys

sys.path.append(os.environ["ANALYSIS_PATH"])

import common.utilities as utilities

def col_to_str(df):
    for col in ['dataset', 'process', 'era']:
        x = df[col]
        df[col] = x.to_numpy().reshape([x.shape[0],]).astype(str)
    return df


def concat_all_dfs(include_data=False):
    pattern = os.path.join("Run3_*", "*.root")
    filelist = glob(pattern)
    if not include_data:
        filelist = [x for x in filelist if 'Data' not in x]
    all_dfs = []
    for fname in filelist:
        print("Reading in", fname)
        with uproot.open(fname + ":Events") as f:
            df = f.arrays(library='pd')
            all_dfs.append(df)
    print("Converting needed cols to str frmt...")
    all_dfs = [col_to_str(x) for x in all_dfs]
    print("Concat'ing...")
    return pd.concat(all_dfs, ignore_index=True)


def prepro(df, data_cols, filter_inf=True, filter_sigma=True):

    # Rename processes to cannonical names
    df['og_process'] = df.process.values.copy()
    df['process'] = df.process.apply(lambda x: 'DY' if 'DY' in x else x)
    df['process'] = df.process.apply(lambda x: 'VBFHto2Mu' if 'VBFHto2Mu' in x else x)
    df['process'] = df.process.apply(lambda x: 'GluGluHto2Mu' if 'GluGlu' in x else x)
    df['process'] = df.process.apply(lambda x: 'EWK' if 'EWK' in x else x)

    if filter_inf:
        print("Filtering inf...")
        for col in data_cols:
            print("\tOn col:", col)
            df = df[df[col] != np.inf]
            print("\tDF length:", len(df))
        df.reset_index(inplace=True, drop=True)

    # # Keep only 6 sigma events
    if filter_sigma:
        mask = np.ones(len(df))
        print("Renorming...")
        print("Initial size:", np.sum(mask))
        for col in data_cols:
            x = df[col].values
            m = np.mean(x)
            s = np.std(x)
            y = np.abs((x - m)/s)
            mask = np.logical_and(mask, y < 6)
            print(f"\tAfter column {col}:", np.sum(mask))
        df = df[mask]
        df.reset_index(inplace=True, drop=True)
            

    # Apply era code for era aware
    print("Applying era code...")
    lookup = {
        "Run3_2022"     : 0,
        "Run3_2022EE"   : 1,
        "Run3_2023"     : 2,
        "Run3_2023BPix" : 3,
        "Run3_2024"     : 4,
        "Run3_2025"     : 5
    }
    df['era_code'] = df.era.apply(lambda x: lookup[x])

    print("Return...")
    return df

def get_arguments():
    """
    Builds an argument parser to get CLI arguments for the config file and dataset directory.
    """
    parser = argparse.ArgumentParser(
        prog="NN train sample postprocess",
        description="Filter and clean a pandas DF for training",
    )
    parser.add_argument(
        "-d",
        "--directory",
        required=True,
        help="the directory containing the parsed skims .root files to use",
    )
    parser.add_argument(
        "-c",
        "--config",
        required=True
    )
    parser.add_argument(
        "-l",
        "--label",
        required=False,
        help="some name for the output dataframe",
    )
    args = parser.parse_args()
    return args

if __name__ == "__main__":

    args = get_arguments()
    parser_cfg = utilities.get_config(args.config)
    data_cols = parser_cfg["columns_config"]["data_columns"]
    os.chdir(args.directory)

    df = concat_all_dfs(include_data=False)
    df = prepro(df, data_cols, filter_inf=False, filter_sigma=False)
    filename = args.label + ".pkl"
    df.to_pickle(filename)