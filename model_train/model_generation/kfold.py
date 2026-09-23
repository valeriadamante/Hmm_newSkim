import numpy as np
import pandas as pd


class KFolder:
    """
    K-fold training support. Returns events by modulus of the selection column.
    This column is "FullEventId" by default.
    """

    def __init__(self, k, fold_idx_only=False):
        self.k = k
        self.selection_column = "FullEventId"
        self.fold_idx_only = fold_idx_only

    def split(self, df):
        """
        Generator to yield.
        """
        select = df[self.selection_column].values.copy()
        select = np.mod(select, self.k)
        for i in range(self.k):
            mask = select == i
            idx = df.index[mask]
            if self.fold_idx_only:
                yield idx
            else:
                not_idx = df.index[~mask]
                yield idx, not_idx
