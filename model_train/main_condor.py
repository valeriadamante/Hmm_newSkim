import argparse
import os
import pickle as pkl
import shutil
import toml
import numpy as np

from model_generation.kfold import KFolder
from model_generation.network_2 import Network
from model_generation.onnx_exporter import export_to_onnx
from model_generation.pandas_loader import PandasLoader
from model_generation.training import Trainer

import torch
from sklearn.model_selection import train_test_split
from torch.utils.data import TensorDataset


def get_arguments():
    """
    Builds an argument parser to get CLI arguments for the config file and dataset directory.
    """
    parser = argparse.ArgumentParser(
        prog="NN_Generator",
        description="For a given dataset and config file, creates a network, trains it, and runs testing",
    )
    parser.add_argument("-c", "--config", required=True, help="the .toml config file")
    parser.add_argument(
        "-d",
        "--datafile",
        required=True,
        help="the .root file to use for testing and training events",
    )
    parser.add_argument(
        "-r",
        "--results_dir",
        required=True,
        help="The output directory",
    )
    parser.add_argument(
        "-f",
        "--fold",
        required=True,
        help="Which of the k folds are we training here",
    )
    args = parser.parse_args()
    return args


def build_layer_list(config):
    # Modify layer_list to have input and output layers
    layer_list = config["network"]["layer_list"]
    # Look at the number of data columns
    input_size = len(config["dataset"]["data_columns"])
    config["network"]["layer_list"] = [input_size] + layer_list + [1]
    return config


def make_dataset(df, for_inference, device, data_columns, **kwargs):
    """
    Converts the dataframe into a Torch dataset object
    Inferencing dataset iterates (sample, index)
    Training dataset iterates (sample, target, weight)
    """
    # Parse input features
    x = df[data_columns].values
    x = torch.tensor(x, device=device, dtype=torch.double)
    if for_inference:
        idx = df.index.values
        idx = torch.tensor(idx)
        dataset = TensorDataset(x, idx)
    else:
        # Parse targets
        y = df.Label.values
        y = y.reshape([len(y), 1])
        y = torch.tensor(y, device=device, dtype=torch.double)
        # Parse training weights
        w = df.Training_Weight.values
        w = w.reshape([len(w), 1])
        w = torch.tensor(w, device=device, dtype=torch.double)
        # Make dataset
        dataset = TensorDataset(x, y, w)
    return dataset


def get_device():
    # Set device for training (cpu or cuda)
    if torch.cuda.is_available():
        device = torch.device("cuda")
        print("Checking CUDA...")
        print(f"\tDevice count: {torch.cuda.device_count()}")
        print(f"\tCurrent device: {torch.cuda.current_device()}")
    else:
        raise ValueError("Killing! Must use CUDA (lxplus CPU training spikes memory)")
    return device

def main():
    args = get_arguments()
    device = get_device()

    # Read in config and datasets from args
    print("Reading config...")
    with open(args.config, "r") as f:
        config = toml.load(f)
    config = build_layer_list(config)

    # Load and split
    print("Reading dataframe...")
    pl = PandasLoader(args.datafile, **config["dataset"])
    df = pl.load_to_dataframe()

    # Init the output directory
    print("Init'ing output dir...")
    os.chdir(args.results_dir)
    shutil.copy(args.config, "./")

    # Begin k-fold training loop
    print("Performing k-fold split...")

    selection_column = "FullEventId"
    select = df[selection_column].values.copy()
    k = config["splitting"]["k"]
    select = np.mod(select, k)
    mask = select == int(args.fold)
    test_idx = df.index[mask]
    temp_idx = df.index[~mask]
    test_df = df.loc[test_idx]
    temp_df = df.loc[temp_idx]

    try:
        if config["splitting"]["train_types"]:
            print("Applying train_types selection...")
            print("Initial temp df:")
            print(temp_df.value_counts("process"))
            tt = config["splitting"]["train_types"]
            mask = temp_df.process.apply(lambda x: x in tt)
            temp_df = temp_df[mask]
            print("Final temp df:")
            print(temp_df.value_counts("process"))
    except KeyError:
        pass
    size = config["splitting"]["validation_size"]
    train_df, valid_df = train_test_split(
        temp_df, test_size=size, stratify=temp_df["process"]
    )

    if config["dataset"]["renorm_inputs"]:
        print("Applying input renorm to train, valid, & test DFs...")
        train_df, (mean, std) = pl.renorm_inputs(train_df, mean=None, std=None)
        valid_df, _ = pl.renorm_inputs(valid_df, mean=mean, std=std)
        test_df, _ = pl.renorm_inputs(test_df, mean=mean, std=std)
        with open("renorm_vars.pkl", "wb") as f:
            pkl.dump((mean, std), f)
    else:
        mean, std = None, None

    # Parse the pd.DFs to torch.Datasets, init trainer
    print("Converting DFs --> custom datasets...")

    train_data = make_dataset(
        train_df, for_inference=False, device=device, **config["dataset"]
    )
    valid_data = make_dataset(
        valid_df, for_inference=False, device=device, **config["dataset"]
    )
    test_data = make_dataset(
        test_df, for_inference=True, device=device, **config["dataset"]
    )

    # Init train
    print("Init'ing trainer...")
    trainer = Trainer(
        train_data,
        valid_data,
        config["optimizer"],
        **config["training"],
    )

    # Do the actual training
    print("Starting the train loop...")
    model = Network(device, **config["network"])
    model = trainer.train(model)

    # Save results
    print("Done training. Saving model...")
    loss_path = os.path.join(args.results_dir, f"{args.fold}_loss.svg")
    trainer.plot_losses(loss_path)
    torch_path = os.path.join(args.results_dir, f"{args.fold}_model.torch")
    with open(torch_path, "wb") as f:
        torch.save(model, f)
    onnx_path = os.path.join(args.results_dir, f"{args.fold}_model.onnx")
    export_to_onnx(
        train_data.tensors[0], model, onnx_path, device, mean, std
    )



if __name__ == "__main__":
    # Set correct multiprocessing (needed for DataLoader parallelism)
    # multiprocessing.set_start_method("spawn", force=True)
    # Read the CLI arguments
    main()