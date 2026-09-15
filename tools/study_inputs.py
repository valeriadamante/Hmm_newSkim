"""Resolve skim_v4 study samples from the era's skim and process configs."""
from pathlib import Path

import yaml


DEFAULT_BACKGROUNDS = 'DY,EWK,W_NJets,TT'
DEFAULT_SIGNALS = 'GluGluHto2Mu,VBFHto2Mu_M125_powheg'


def configured_samples(repo, era, input_root, backgrounds=DEFAULT_BACKGROUNDS,
                       signals=DEFAULT_SIGNALS):
    cfg = Path(repo) / 'config' / era
    processes = yaml.safe_load((cfg / 'process_names.yaml').read_text())
    skim = yaml.safe_load((cfg / 'skim_cfg.yaml').read_text())
    selected = set(skim.get('process_to_select', []))
    excluded = set(skim.get('datasets_exclude', []))

    def members(process):
        entry = processes[process]
        return [name for name in entry.get('datasets', []) + entry.get('sub_processes', [])
                if name not in excluded]

    if 'Data_Muon' not in selected:
        raise ValueError(f'Data_Muon is not selected in {era}/skim_cfg.yaml')
    data = members('Data_Muon')

    groups = {}
    for kind, specification in [('background', backgrounds), ('signal', signals)]:
        for requested in (x.strip() for x in specification.split(',')):
            if not requested:
                continue
            process = requested
            if requested == 'W_NJets' and 'W' in selected:
                process = 'W'
            if process in selected:
                datasets = members(process)
            else:
                datasets = [requested] if any(
                    requested in members(name) for name in selected) else []
                if datasets:
                    process = next(name for name in selected if requested in members(name))
            if not datasets:
                raise ValueError(f'{requested} is not selected in the {era} skim')
            for dataset in datasets:
                if dataset in groups:
                    continue
                directory = Path(input_root) / era / dataset
                root_files = sorted(str(p) for p in directory.glob('*.root'))
                if not root_files:
                    raise FileNotFoundError(f'Missing skim ROOT files: {directory}')
                if not list(directory.glob('report_*.json')):
                    raise FileNotFoundError(f'Missing skim reports: {directory}')
                groups[dataset] = {'process': process, 'kind': kind,
                                   'files': root_files, 'input_dir': str(directory)}
    data_files = []
    for dataset in data:
        directory = Path(input_root) / era / dataset
        root_files = sorted(str(p) for p in directory.glob('*.root'))
        if not root_files:
            raise FileNotFoundError(f'Missing data skim ROOT files: {directory}')
        data_files.extend(root_files)
    return sorted(set(data_files)), groups
