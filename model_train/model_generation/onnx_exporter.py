import torch


class ExportNetwork(torch.nn.Module):
    """
    Wrapper to include input renorm as an initial layer of model.
    Builds the scaling into the network.
    """

    def __init__(self, model, device, renorm_mean, renorm_std):
        super().__init__()
        self.device = device
        model.eval()
        self.model = model
        if device is not None:
            self.to(device)
            self.double()
            if renorm_mean is not None and renorm_std is not None:
                self.mean = torch.tensor(
                    renorm_mean, device=self.device, dtype=torch.double
                )
                self.std = torch.tensor(
                    renorm_std, device=self.device, dtype=torch.double
                )
            else:
                self.mean = None
                self.std = None
        else:
            if renorm_mean is not None and renorm_std is not None:
                self.mean = torch.tensor(renorm_mean, device=self.device)
                self.std = torch.tensor(renorm_std, device=self.device)
            else:
                self.mean = None
                self.std = None

    def forward(self, x):
        if self.mean is not None and self.std is not None:
            x = x.sub(self.mean).div(self.std)
        return self.model(x)


def export_to_onnx(x_data, model, outname, device, renorm_mean, renorm_std):
    """
    The main external callable function. Wraps the model and does the export.
    """
    export_model = ExportNetwork(model, device, renorm_mean, renorm_std)
    export_model.eval()
    torch.onnx.export(
        model=export_model,
        args=(x_data[0:3]),
        f=outname + ".onnx",
        input_names=["x"],
        output_names=["y"],
        dynamic_axes={"x": [0], "y": [0]},
        dynamo=False,
    )
