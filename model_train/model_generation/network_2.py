import torch


class Network(torch.nn.Module):
    def __init__(self, device, layer_list, batch_renorm=False, dropout=0, **kwargs):
        """
        Create a linear network with hidden layers
        """
        super().__init__()
        self.activation = torch.nn.ReLU()
        self.final_activation = torch.nn.Sigmoid()
        self.batch_renorm = batch_renorm
        self.layers = self._build_layers(layer_list)
        self.dropout = dropout
        self.to(device)
        self.double()

    def _build_layers(self, layer_list):
        layers = []
        for i in range(len(layer_list) - 1):
            in_features = layer_list[i]
            out_features = layer_list[i + 1]
            layers.append(torch.nn.Linear(in_features, out_features))
            # Add BatchNorm1d after each hidden Linear layer except the last layer
            if self.batch_renorm and i < len(layer_list) - 2:
                layers.append(torch.nn.BatchNorm1d(out_features))
        return torch.nn.ModuleList(layers)

    def forward(self, x):
        last_hidden = len(self.layers) - 1  # index of the last layer
        i = 0
        while i < last_hidden:
            x = self.layers[i](x)  # Linear
            if self.batch_renorm and isinstance(
                self.layers[i + 1], torch.nn.BatchNorm1d
            ):
                x = self.layers[i + 1](x)  # BatchNorm
                i += 1
            x = self.activation(x)
            if self.dropout > 0:
                x = torch.nn.functional.dropout(x, p=self.dropout)
            i += 1
        # Last layer (output)
        x = self.layers[-1](x)
        x = self.final_activation(x)
        return x
