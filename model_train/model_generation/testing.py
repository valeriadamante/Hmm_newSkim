import matplotlib.pyplot as plt
import mplhep
import numpy as np
import pandas as pd
import torch
from sklearn.metrics import roc_curve
from statsmodels.stats.weightstats import DescrStatsW
from torch.utils.data import DataLoader
from tqdm import tqdm

mplhep.style.use(mplhep.styles.CMS)


class Tester:
    """
    Runs inference on the provided data using the provided model.
    Saves inference to self.testing_df, then produces plots.
    All of the nice output plots are defined here.
    """

    def __init__(
        self,
        testing_df,
        n_bins=20,
        **kwargs,
    ):
        # Set self attrs
        self.testing_df = testing_df
        self.n_bins = n_bins
        # Other on-the-fly ones
        self.hist_range = (0, 1)
        self.batch_size = 1000

    def _make_dataloader(self, data):
        return DataLoader(
            data,
            batch_size=self.batch_size,
            shuffle=False,
            # num_workers=2,
        )

    def test(self, model, testing_data):
        """
        Run the inference, save to testing_df
        """
        data = self._make_dataloader(testing_data)
        model.eval()
        with torch.no_grad():
            for x_data, indices in tqdm(data):
                outputs = model(x_data)
                outputs = outputs.cpu().numpy()
                self.testing_df.loc[indices, "NN_Output"] = outputs

    ### Calculations of metrics and other ###

    def get_roc_auc(self):
        """
        Area under curve for ROC
        """
        df = self.testing_df
        fpr, tpr, _ = roc_curve(df.Label, df.NN_Output, sample_weight=df.Class_Weight)
        score = np.trapz(x=tpr, y=fpr)
        return score

    @staticmethod
    def s2overb(signal_bins, background_bins):
        """
        Takes two np arrays. Precompute a histogram and pass the bins over here.
        """
        x = (signal_bins) / np.sqrt(background_bins)
        return np.sqrt(np.sum(x**2))

    def _calc_transformed_hist(self):
        """
        Counts the populations for the DNN' plots from AN2019_205, fig 14
        """
        df = self.testing_df
        # Calculate bin edges for percentiles
        signal = df[df.Label == 1]
        wq = DescrStatsW(data=signal.NN_Output, weights=signal.Class_Weight)
        p = np.linspace(0, 1, self.n_bins + 1)
        bin_edges = wq.quantile(p, return_pandas=False)
        # Calculate the bin populations for each process
        counts_lookup = {}
        for p in pd.unique(df.process):
            selected = df[df.process == p]
            counts, _ = np.histogram(
                selected.NN_Output, weights=selected.Class_Weight, bins=bin_edges
            )
            counts_lookup[p] = counts
        return bin_edges, counts_lookup

    ### PLOTTING ###

    def make_hist(self, weight=True, log=True, norm=False, show=False, processes=None):
        """
        Saves a histo of all signal vs all background
        """
        plt.clf()
        output_name = "model_hist"
        results = self.testing_df
        if processes:
            mask = results.process.apply(lambda x: x in processes)
            results = results[mask]
            output_name += "_trainprocessonly"
        signal = results[results.Label == 1]
        background = results[results.Label == 0]
        if norm:
            if weight:
                w = sum(background.Class_Weight) / sum(signal.Class_Weight)
            else:
                w = len(background) / len(signal)
            output_name += "_normed"
        else:
            w = 1
        if weight:
            h1 = np.histogram(
                signal.NN_Output,
                range=self.hist_range,
                bins=self.n_bins,
                weights=signal.Class_Weight * w,
            )
            h2 = np.histogram(
                background.NN_Output,
                range=self.hist_range,
                bins=self.n_bins,
                weights=background.Class_Weight,
            )
        else:
            w_temp = np.ones(len(signal))
            h1 = np.histogram(
                signal.NN_Output,
                range=self.hist_range,
                bins=self.n_bins,
                weights=w_temp * w,
            )
            h2 = np.histogram(
                background.NN_Output, range=self.hist_range, bins=self.n_bins
            )
        plt.stairs(*h2, label="Background", color="tab:orange")
        plt.stairs(*h1, label="Signal", color="tab:blue")
        # Calc sensitivity
        # sig_counts, _ = h1
        # bkg_counts, _ = h2
        # sensitivity = self.s2overb(sig_counts, bkg_counts)
        # title = r"$\frac{S}{\sqrt{B}} = $" + str(round(sensitivity, 3))
        # plt.title(title)
        # Set plot parameters based on boolean options
        if log:
            plt.yscale("log")
            output_name += "_log"
        else:
            output_name += "_lin"
        if weight:
            plt.ylabel("Weight")
            output_name += "_weighted"
        else:
            plt.ylabel("Events")
        # Set rest of plot and save/show
        plt.xlabel("Network output")
        plt.legend(bbox_to_anchor=(1.05, 1), loc="upper left")
        #mplhep.cms.label(com=13.6, lumi=62.4)
        if show:
            plt.show()
        else:
            plt.savefig(output_name + ".svg", bbox_inches="tight")

    def make_multihist(self, weight=True, log=False, show=False, processes=None):
        """
        Saves a histo with the different processes drawn independently
        """
        # Init plot
        plt.clf()
        df = self.testing_df
        output_name = "multihist"
        if processes:
            mask = df.process.apply(lambda x: x in processes)
            df = df[mask]
            output_name += "_trainprocessonly"
        # Add individual hist curves
        for p in sorted(pd.unique(df.process)):
            selected = df[df.process == p]
            if weight:
                h = np.histogram(
                    selected.NN_Output,
                    weights=selected.Class_Weight,
                    range=self.hist_range,
                    bins=self.n_bins,
                )
            else:
                h = np.histogram(
                    selected.NN_Output, range=self.hist_range, bins=self.n_bins
                )
            plt.stairs(*h, label=p)
        # Plot config from boolean parameters
        if log:
            plt.yscale("log")
        if weight:
            output_name += "_weighted"
            plt.ylabel("Weight")
        else:
            plt.ylabel("Events")
        # Finish plot config
        plt.xlabel("Network output")
        plt.legend(bbox_to_anchor=(1.05, 1), loc="upper left")
        #mplhep.cms.label(com=13.6, lumi=62.4)
        # Out (save or show)
        if show:
            plt.show()
        else:
            plt.savefig(output_name + ".svg", bbox_inches="tight")

    def make_roc_plot(self, log=True, show=False, processes=None):
        """
        Plot ROC and adds AUC calculation to plot
        """
        plt.clf()
        df = self.testing_df
        output_name = "roc"
        if processes:
            mask = df.process.apply(lambda x: x in processes)
            df = df[mask]
            output_name += "_trainprocessonly"
        df = self.testing_df
        # Calc curve from sklearn
        fpr, tpr, _ = roc_curve(df.Label, df.NN_Output, sample_weight=df.Class_Weight)
        plt.plot(tpr, fpr, label=r"$DNN$")
        # Add 45 deg
        a = np.linspace(0, 1, 1000)
        plt.plot(a, a, color="black", linestyle="dashed", label="45°")
        # Add score
        auc = self.get_roc_auc()
        x = 0.6
        if log:
            y = 3e-4
        else:
            y = 0
        text = f"1 - AUC = {round(1-auc, 3)}"
        plt.text(x, y, text)
        # Format and go!
        plt.xlabel(r"$\epsilon_{sig}$")
        plt.ylabel(r"$\epsilon_{bkg}$")
        # mplhep.cms.label()
        plt.grid()
        plt.xlim(0, 1)
        if log:
            plt.yscale("log")
            plt.ylim(1e-4, 1)
            output_name += "_log"
        plt.legend(loc="upper left")
        if show:
            plt.show()
        else:
            plt.savefig(output_name + ".svg", bbox_inches="tight")

    def make_transformed_stackplot(
        self, log=True, show=False, min_power=-3, top_power=6
    ):
        """
        Replication for the DNN' plots from AN2019_205, fig 14
        """
        plt.clf()
        df = self.testing_df
        output_name = "transformed_stack"
        bin_edges, counts_lookup = self._calc_transformed_hist()

        stack_proc = pd.unique(df.process[df.Label == 0])
        other_proc = pd.unique(df.process[df.Label == 1])
        # Sort the stacked processes (smallest on bottom)
        stack_proc = [(x, sum(counts_lookup[x])) for x in stack_proc]
        stack_proc = sorted(stack_proc, key=lambda x: x[1])
        stack_proc = [x[0] for x in stack_proc]

        # Do the stacking
        baseline = np.zeros(len(bin_edges) - 1)
        total = np.zeros(len(baseline))
        x = np.linspace(0, self.n_bins, self.n_bins + 1)
        for p in stack_proc:
            total += counts_lookup[p]
            plt.stairs(total, x, label=p, baseline=baseline, fill=True)
            baseline += counts_lookup[p]
        # and add the non-stackers
        for p in other_proc:
            plt.stairs(counts_lookup[p], x, label=p, linewidth=2)

        # Add S/sqrt(B) to plot
        sig_total = np.zeros(len(baseline))
        for p in pd.unique(df.process[df.Label == 1]):
            sig_total += counts_lookup[p]
        sensitivity = self.s2overb(sig_total, total)
        plt.text(1, 1e5, r"$\frac{S}{\sqrt{B}} = $" + str(round(sensitivity, 3)))

        # Format
        if log:
            output_name += "_log"
            plt.yscale("log")
        plt.xlabel(r"$DNN^{\prime}$")
        major_ticks = [1 * 10**x for x in range(min_power, top_power + 1)]
        minor_ticks = [
            y * 10**x for y in range(2, 10) for x in range(min_power, top_power - 1)
        ]
        plt.ylim(10**min_power, 10**top_power)
        plt.ylabel("Events")
        plt.yticks(major_ticks)
        plt.yticks(minor_ticks, minor=True)
        # plt.legend(bbox_to_anchor=(1.05, 1), loc="upper left")
        plt.legend()
        #mplhep.cms.label(com=13.6, lumi=62.4)
        if show:
            plt.show()
        else:
            output_name += ".svg"
            plt.savefig(output_name, bbox_inches="tight")


    def validation_hist(self, col):
        df = self.testing_df
        h_range = (df[col].min(), df[col].max())
        sig = df[df.Label == 1]
        bkg = df[df.Label == 0]
        h_sig = np.histogram(sig[col], weights=sig.Class_Weight, bins=self.n_bins, range=h_range)
        h_bkg = np.histogram(bkg[col], weights=bkg.Class_Weight, bins=self.n_bins, range=h_range)
        plt.clf()
        plt.stairs(*h_sig, label='sig')
        plt.stairs(*h_bkg, label='bkg')
        plt.yscale('log')
        plt.xlabel(col)
        plt.legend()
        plt.savefig(f"{col}_check.svg")

