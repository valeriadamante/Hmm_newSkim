import argparse
import os
import toml
from glob import glob
import yaml
from pprint import pprint
import gc
import tracemalloc

import numpy as np
import pandas as pd
import onnxruntime as ort
from model_generation.kfold import KFolder
from model_generation.pandas_loader import PandasLoader

def get_arguments():
    """
    Builds an argument parser to get CLI arguments for the config file and dataset directory.
    """
    parser = argparse.ArgumentParser(
        prog="ONNX Inference Script",
        description="A script to run ONNX inference on a dataset using k-fold models",
    )
    parser.add_argument(
        "--directory",
        required=True,
        help="the results directory to infer on. should have a directories for each k fold model",
    )
    parser.add_argument(
        "--datafile",
        required=True,
        help="the input pandas df pkl file to use for inference",
    )
    parser.add_argument(
        "--column_remap",
        required=False,
        default=None,
        help="CSV to remap any feature names from datafile to what the model config expects."
    )
    parser.add_argument(
        "--output_column",
        required=True,
        help="the name of the final inference column to add"
    )
    parser.add_argument(
        "--label",
        required=True,
        help="the name of the final df"
    )
    args = parser.parse_args()
    return args

def remap_columns(csv_path, df):
    print("Remapping columns...")
    remap = pd.read_csv(csv_path)
    lookup = {}
    for i, (k, v) in remap.iterrows():
        if k != v:
            lookup[v] = k
    pprint(lookup)
    df = df.rename(columns=lookup)
    return df


if __name__ == "__main__":
    # Set correct multiprocessing (needed for DataLoader parallelism)
    # multiprocessing.set_start_method("spawn", force=True)
    # Read the CLI arguments
    tracemalloc.start()
    args = get_arguments()
    print("ARGS:")
    pprint(args)
    os.chdir(args.directory)

    # Read in config and datasets from args
    print("Reading config...")
    c = glob("config*.toml")[0]
    with open(c, "r") as f:
        config = toml.load(f)
    input_features = config['dataset']['data_columns']

    # with open("/afs/cern.ch/user/a/ayeagle/H_mumu/Studies/DNN/configs/columns_config.yaml", "r") as f:
    #     columns_config = yaml.safe_load(f)
    # input_features = parse_column_names(
    #     columns_config["vars_to_save"], column_type="data"
    # )

    # Load samples
    print("Reading in dataframe...")
    #pl = PandasLoader(args.datafile, **config["dataset"])
    df = pd.read_pickle(args.datafile)

    print("Current mem:", tracemalloc.get_traced_memory())
    if args.column_remap is not None:
        df = remap_columns(args.column_remap, df)
        print(df)
        pprint(df.columns)

    # Begin k-fold loop
    print("Performing k-fold split...")
    folds = config["splitting"]["k"]
    kfolder = KFolder(k=folds, fold_idx_only=True)
    all_predictions = np.zeros(len(df))
    for k, fold_idx in enumerate(kfolder.split(df)):
        print("* ON FOLD:", k)
   
        # prepare data
        x = df.loc[fold_idx][input_features].values

        # Load and run model
        filename = f"trained_model_{k}.onnx"
        sess = ort.InferenceSession(filename)
        input_name = sess.get_inputs()[0].name
        label_name = sess.get_outputs()[0].name
        predictions = sess.run([label_name], {input_name: x})[0]
        print(predictions.shape)
        predictions = predictions.reshape(
            predictions.shape[0],
        )
        all_predictions[fold_idx] = predictions
        print("Current mem:", tracemalloc.get_traced_memory())
        del x
        gc.collect()
        print("Current mem:", tracemalloc.get_traced_memory())


    # Save the final inference plots
    print("K-fold complete! Saving final df...")
    df[args.output_column] = all_predictions
    df.to_pickle(args.label + ".pkl")
