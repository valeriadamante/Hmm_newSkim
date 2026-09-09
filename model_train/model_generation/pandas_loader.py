import numpy as np
from statsmodels.stats.weightstats import DescrStatsW
import pandas as pd


class PandasLoader:
    """
    Class to input the initial .pkl file and set weights.
    Class_Weight is the column used for inferencing plotting.
    Train_Wiehgt is the column used for weighting the loss function for training.
    These may be the same, but Train_Weight usually gets some addtional rescaling/norming applied.
    """

    def __init__(
        self,
        filepath,
        signal_types,
        data_columns,
        abs_train_weight=True,
        equalize_for_training=True,
        equalize_per_process=False,
        **kwargs
    ):
        self.signal_types = signal_types
        self.abs_train_weight = abs_train_weight
        self.filepath = filepath
        self.equalize_for_training = equalize_for_training
        self.equalize_per_process = equalize_per_process
        self.data_columns = data_columns

    ### Private helper funcs ###

    def _load_file(self, filepath):
        df = pd.read_pickle(filepath)
        for col in ["era", "process", "dataset"]:
            if col in df.columns:
                df[col] = df[col].astype(str)
        return df

    def _add_labels(self, df):
        df["Label"] = df.process.apply(lambda x: 1 if x in self.signal_types else 0)
        return df

    def _set_class_weight(self, df):
        if "final_weight" in df.columns:
            df["Class_Weight"] = df.final_weight.copy()
        elif "weight_final" in df.columns:
            df["Class_Weight"] = df.weight_final.copy()
        elif "weight_Central" in df.columns:
            df["Class_Weight"] = df.weight_Central.copy()
        elif "weight__Central" in df.columns:
            df["Class_Weight"] = df.weight__Central.copy()
        return df

    def _set_training_weight(self, df):
        train_weights = df.Class_Weight.values.copy()
        if self.abs_train_weight:
            train_weights = np.abs(train_weights)
        df["Training_Weight"] = train_weights
        return df

    def _equalize_train_weights(self, df):
        """
        Scale signal to equal background weight
        """
        sig_weight = df[df.Label == 1].Training_Weight.sum()
        bkg_weight = df[df.Label == 0].Training_Weight.sum()
        mask = df.Label == 1
        scale = np.ones(len(df))
        scale[mask] = bkg_weight / sig_weight
        df["Training_Weight"] *= scale
        return df

    def _equalize_by_process(self, df):
        """
        Sets each process to an equal weight
        Should NOT use both this and equalize_train_weights
        """
        new_weights = np.zeros(len(df))
        for process in pd.unique(df.process):
            mask = df.process == process
            selected = df[mask]
            w = 1 / len(selected)
            new_weights[mask] = w
        df["Training_Weight"] = new_weights
        return df

    ### Other external ###

    def renorm_inputs(self, df, mean=None, std=None):
        """
        Applies a gaussian renorm to the variable columns
        in self.data_columns
        """
        # Calc per variable m & s if not given
        if mean is None and std is None:
            mean = np.zeros(len(self.data_columns))
            std = np.zeros(len(self.data_columns))
            for i, col in enumerate(self.data_columns):
                stats = DescrStatsW(df[col].values, weights=df.Class_Weight.values)
                mean[i] = stats.mean
                std[i] = stats.std
        # Apply (x-m)/s renorm
        for i, col in enumerate(self.data_columns):
            m = mean[i]
            s = std[i]
            df[col] = (df[col].values - m) / s
        return df, (mean, std)

    ### Main function ###

    def load_to_dataframe(self):
        df = self._load_file(self.filepath)
        df = self._add_labels(df)
        df = self._set_class_weight(df)
        df = self._set_training_weight(df)
        if self.equalize_for_training:
            df = self._equalize_train_weights(df)
        elif self.equalize_per_process:
            df = self._equalize_by_process(df)
        return df
