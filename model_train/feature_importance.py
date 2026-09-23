import argparse
import os
import pickle as pkl
import tomllib
from pprint import pprint

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shap
import torch
from sklearn.model_selection import train_test_split


def get_arguments():
    """
    Builds an argument parser to get CLI arguments for the config file and dataset directory.
    """
    parser = argparse.ArgumentParser(
        prog="Feature importance runner",
        description="Calculates Shapely values for the provided model and data",
    )
    parser.add_argument(
        "-r",
        "--results_dir",
        required=True,
        help="Path to the results directory containing evaluated_testing_df and model",
    )
    args = parser.parse_args()
    return args


def load_model_and_data():
    """
    Reads in a torch model and numpy renorm variables from pickle files.
    """
    datapath = "evaluated_testing_df.pkl"
    df = pd.read_pickle(datapath)
    _, df = train_test_split(df, test_size=0.05, stratify=df["process"])
    modelpath = "0_fold/model.torch"
    model = torch.load(modelpath, weights_only=False)
    corrections_path = "0_fold/renorm_vars.pkl"
    with open(corrections_path, "rb") as f:
        mean, std = pkl.load(f)
    return df, model, mean, std


def main(model, df, data_cols, process=None):
    """
    Computes the actual SHAP scores and saves violin plots of top features.
    """
    plt.clf()
    # Explainer population
    remnant, background = train_test_split(df, test_size=0.1, stratify=df["process"])
    _, sample = train_test_split(remnant, test_size=0.1, stratify=remnant["process"])
    background = background[data_cols].values
    sample = sample[data_cols].values
    # Define our objective function
    device = torch.device("cuda")
    f = lambda x: model(torch.tensor(x, device=device, dtype=torch.double))
    # Generate the explanatory model
    explainer = shap.Explainer(f, background, feature_names=data_cols)
    shap_values = explainer(sample)
    # Do the outputs!
    shap.summary_plot(shap_values=shap_values, feature_names=data_cols)
    if process is not None:
        plt.title(process)
        plt.savefig(f"{process}_feature_importance.png")
        with open(f"{process}_shapely_values.pkl", "wb") as f:
            pkl.dump(shap_values, f)
    else:
        plt.savefig("feature_importance.png")
        with open("shapely_values.pkl", "wb") as f:
            pkl.dump(shap_values, f)


if __name__ == "__main__":
    args = get_arguments()
    print("Input args:")
    pprint(args)
    os.chdir(args.results_dir)
    df, model, mean, std = load_model_and_data()
    with open("config.toml", "rb") as f:
        config = tomllib.load(f)
    data_cols = config["dataset"]["data_columns"]
    for col, m, s in zip(data_cols, mean, std):
        df[col] = (df[col] - m) / s
    main(model, df, data_cols)
