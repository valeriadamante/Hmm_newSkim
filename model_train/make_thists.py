import pandas as pd
import ROOT
from statsmodels.stats.weightstats import DescrStatsW
import numpy as np

def create_histograms(df, data, COLUMNS_LIST, N_BINS, quantile=False):
    processes = list(df['process'].unique())
    #processes.remove('data')
    processes.append('data_obs')

    for column in COLUMNS_LIST:
        # Compute global min and max for the column
        min_edge = df[column].min()
        max_edge = df[column].max()
        print(f"Processing column: {column}, min: {min_edge}, max: {max_edge}")

        # Creat .root output file per column
        if quantile:
            output_name = f"hist_{column}_quantile.root"
        else:
            output_name = f"hist_{column}.root"
        root_file = ROOT.TFile(output_name, "RECREATE")
        # To keep references to histograms
        histograms = {}

        if quantile:
            signal = df[(df.process == 'VBFHto2Mu') | (df.process == 'GluGluHto2Mu')]
            wq = DescrStatsW(data=signal[column], weights=signal.weight__Central)
            p = np.linspace(0, 1, N_BINS + 1)
            bin_edges = wq.quantile(p, return_pandas=False)

        for proc in processes:
            # Select the values for this process/column
            if proc == 'data_obs':
                selected = data
            else:
                selected = df[df['process'] == proc]
            values = selected[column]
            weights = selected['Class_Weight']

            # ROOT does not like "/" or whitespace in object names
            safe_proc = str(proc).replace("/", "_").replace(" ", "_")
            hist_name = safe_proc

            # Create histogram
            if quantile:
                hist = ROOT.TH1F(hist_name, f"{column} ({proc})", len(bin_edges)-1, bin_edges)
            else:
                hist = ROOT.TH1F(hist_name, f"{column} ({proc})", N_BINS, min_edge, max_edge)

            # Fill histogram
            for v, w  in zip(values, weights):
                hist.Fill(v, w)

            hist.Write()  # Save histogram to file
            histograms[proc] = hist

        root_file.Close()
        print(f"Wrote file: hist_{column}.root")

def get_arguments():
    """
    Builds an argument parser to get CLI arguments for the config file and dataset directory.
    """
    parser = argparse.ArgumentParser(
        prog="Feature importance runner",
        description="Calculates Shapely values for the provided model and data",
    )
    parser.add_argument(
        "-m",
        "--mc_df",
        required=True,
        help="Path to the Pandas dataframe containing network evaluated MC samples",
    )
    parser.add_argument(
        "-d",
        "--data_df",
        required=True,
        help="Path to the Pandas dataframe containing network evaluated data",
    )
    parser.add_argument(
        "-c",
        "--column_name",
        required=False,
        default="NN_Output"
        help="Name of the dataframe column to plot",
    )
    parser.add_argument(
        "-n",
        "--nbins",
        required=False,
        default=15,
        help="Number of histogram bins",
    )
    args = parser.parse_args()
    return args

if __name__ == '__main__':
    args = get_arguments()
    print("Input args:")
    pprint(args)
    mc_df = pd.read_pickle(args.mc_df)
    data_df = pd.read_pickle(args.data_df)
    create_histograms(mc_df, data_df, args.column_name, args.n_bins, quantile=True)