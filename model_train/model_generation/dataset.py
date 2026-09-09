"""
Deprecated, but keeping around. This defined a new Dataset object that would zero pad jet variables on the fly.
It's (obviously) faster to do this on the Root side and then pass in a normal dataset object to Torch.
"""

import awkward as ak
import numpy as np
from torch.utils.data import Dataset


class JetDataset(Dataset):
    def __init__(
        self,
        dataframe,
        weight_col,
        max_jets,
        pad_value=0,
        for_inference=False,
        **kwargs
    ):
        self.df = dataframe
        self.max_jets = max_jets
        self.pad_value = pad_value
        self.for_inference = for_inference

        self.mumu_pt = self.df["pt_mumu"].values
        self.pt = self.df["FilteredJet_pt"].values
        self.eta = self.df["FilteredJet_eta"].values
        self.phi = self.df["FilteredJet_phi"].values
        self.btag = self.df["FilteredJet_btagPNetQvG"].values
        self.puid = self.df["FilteredJet_puIdDisc"].values

        self.label = self.df["Label"].values
        self.indices = self.df.index.values

        if weight_col is not None:
            self.weight = self.df[weight_col].values
        else:
            self.weight = np.ones(len(self.df))

    def __len__(self):
        return len(self.df)

    def pad(self, arr):
        """
        Pads the array with zeros if fewer than max_jets jets are available.
        """
        arr = arr[: self.max_jets]
        padlen = self.max_jets - len(arr)
        if padlen > 0:
            arr = np.pad(arr, (0, padlen), constant_values=self.pad_value)
        return arr

    def __getitem__(self, idx):
        """
        Defines the next vector to return.
        """
        mumu = self.mumu_pt[idx]
        pt_pad = self.pad(self.pt[idx])
        eta_pad = self.pad(self.eta[idx])
        phi_pad = self.pad(self.phi[idx])
        btag_pad = self.pad(self.btag[idx])
        puid_pad = self.pad(self.puid[idx])
        jets = np.stack([pt_pad, eta_pad, phi_pad, btag_pad, puid_pad], axis=1)
        data = ak.flatten(jets)
        data = np.concatenate((mumu, data))
        target = self.label[idx].reshape(
            [
                1,
            ]
        )
        weight = self.weight[idx]
        if self.for_inference:
            index = self.indices[idx]
            return data, index
        return data, target, weight
