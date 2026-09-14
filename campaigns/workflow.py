"""Shared, guarded histogram campaign orchestration; invoked by campaigns/*.sh."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from functools import lru_cache
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from tools.histogram_completeness import datasets_for_histogram_groups
from common.jet_component_splitting import DY_COMPONENT_FILE_LABELS, jet_components_enabled_for_dataset
from histograms.hadd_hists_to_processes import dataset_file_candidates

ERAS = ['2022', '2022EE', '2023', '2023BPix', '2024', '2025']
FAMILIES = ['JEReta0pt0', 'JEReta1pt0', 'JEReta2pt0', 'JEReta2pt1', 'JEReta3pt0', 'JEReta3pt1', 'JES_Total', 'Muon', 'PDF', 'PU', 'QCDScale', 'ScaRe']
GROUPS = 'data,DY_amcatnlo,DY_amcatnlo_105_160,EWK,EWK_105_160,signals,SingleH,SingleTop,TTX,TT,W,DiTriBoson'
EOS = Path('/eos/user/v/vdamante/H_mumu')
HORN_VARIABLES = 'N_SelectedJets leadingjet_pt leadingjet_eta leadingjet_phi subleadingjet_pt subleadingjet_eta subleadingjet_phi delta_eta_jj_ls m_jj_ls m_jj delta_eta_jj vbfjet1_pt vbfjet2_pt vbfjet1_eta vbfjet2_eta vbfjet1_phi vbfjet2_phi'.split()


def era_name(era):
    return era if era.startswith('Run3_') else 'Run3_' + era


def csv(value):
    return [x for x in value.replace(',', ' ').split() if x]


@lru_cache(None)
def config(era, name):
    return yaml.safe_load((REPO / 'config' / era_name(era) / (name + '.yaml')).read_text()) or {}


@dataclass
class Campaign:
    name: str
    root: Path
    eras: list[str]
    families: list[str]
    groups: str
    hist_args: list[str]
    regions: list[str]
    categories: list[str]
    variables: list[str]
    source: str = ''
    input_root: str = '/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v3'
    manifests: str = '/eos/user/v/vdamante/H_mumu/manifests_skim_v3'
    cpus: str = '4'
    memory: str = '8GB'
    batch: str = '1'
    json_root: str = ''
    bundled_families: tuple[str, ...] = ()
    chunk_size: str = '1'

    def directory(self, family, hadded=False):
        return self.root / (family + ('_hadded' if hadded else ''))


def load_campaign(name):
    """Read existing shell configurations without duplicating physics settings."""
    source = name if name.endswith('.sh') else f'config/campaigns/{name}.sh'
    scalars = ['CAMPAIGN_ROOT', 'CAMPAIGN_LABEL', 'DATASETS', 'REQUEST_CPUS', 'REQUEST_MEMORY', 'VARIABLE_BATCH_SIZE', 'ROOT_INPUT', 'JSON_INPUT', 'MANIFEST_INPUT', 'CHUNK_SIZE']
    arrays = ['ERAS', 'SYSTEMATICS', 'HIST_ARGS']
    script = 'source "$1"\nshift\n'
    for key in scalars:
        script += f'printf "%s\\0" "${{{key}:-}}"\n'
    for key in arrays:
        script += f'printf "%s\\0" "${{{key}[@]}}"\nprintf "\\0"\n'
    result = subprocess.run(['bash', '-c', script, 'config', str(REPO/source)], check=True, stdout=subprocess.PIPE)
    tokens = result.stdout.decode().split('\0')
    values = dict(zip(scalars, tokens[:len(scalars)])); tokens = tokens[len(scalars):]
    for key in arrays:
        end = tokens.index(''); values[key] = tokens[:end]; tokens = tokens[end+1:]
    hist = values['HIST_ARGS']
    def option(key):
        if key not in hist: return []
        result = []
        for token in hist[hist.index(key)+1:]:
            if token.startswith('--'): break
            result.append(token)
        return result
    return Campaign(values['CAMPAIGN_LABEL'], Path(values['CAMPAIGN_ROOT']), values['ERAS'],
                    [x for x in values['SYSTEMATICS'] if x != 'Central'], values['DATASETS'], hist,
                    option('--mass-regions'), option('--categories'), option('--variables'), source,
                    cpus=values['REQUEST_CPUS'] or '4', memory=values['REQUEST_MEMORY'] or '8GB',
                    batch=values['VARIABLE_BATCH_SIZE'] or '8',
                    input_root=values['ROOT_INPUT'] or Campaign.__dataclass_fields__['input_root'].default,
                    json_root=values['JSON_INPUT'], chunk_size=values['CHUNK_SIZE'] or '1',
                    manifests=values['MANIFEST_INPUT'] or Campaign.__dataclass_fields__['manifests'].default)


@lru_cache(None)
def datasets(era, groups):
    samples = config(era, 'samples'); processes = config(era, 'process_names')
    selected = []
    aliases = {
        'SingleTop': {'TBbarQto2Q_t_channel_4FS': 'TBbarQ_t_channel_4FS', 'TBbarQtoLNu_t_channel_4FS': 'TBbarQ_t_channel_4FS', 'TbarBQto2Q_t_channel_4FS': 'TbarBQ_t_channel_4FS', 'TbarBQtoLNu_t_channel_4FS': 'TbarBQ_t_channel_4FS'},
        'TTX': {'TTZH_ZHto4B': 'TTZH'},
    }
    for group in csv(groups):
        if group == 'data':
            entry = processes['Data_Muon']; selected += entry.get('datasets', []) + entry.get('sub_processes', [])
        elif group == 'EWK_105_160':
            selected += [x for x in ('EWK_2Mu2J_MLL_105to160_herwig', 'EWK_2Mu2J_MLL_105to160_pythia') if x in samples]
        else:
            names = datasets_for_histogram_groups(REPO, era_name(era), [group])
            selected += names
            for original, alias in aliases.get(group, {}).items():
                if original not in samples and alias in samples: selected.append(alias)
            if group == 'DY_amcatnlo_105_160' and 'DYto2Mu_MLL_105to160_amcatnloFXFX_VBFFiltered' in samples:
                selected = [x for x in selected if x != 'DYto2Mu_MLL_105to160_amcatnloFXFX_Fil_VBF']
                selected.append('DYto2Mu_MLL_105to160_amcatnloFXFX_VBFFiltered')
    # The 2026 skim intentionally contains a reduced process set.  Restrict
    # histogram expectations to datasets actually selected by that skim.
    if era_name(era) == 'Run3_2026':
        skim = config(era, 'skim_cfg')
        available = {dataset for process in skim.get('process_to_select', [])
                     for dataset in members(processes[process])}
        available -= set(skim.get('datasets_exclude', []))
        selected = [dataset for dataset in selected if dataset in available]
    if not selected: raise RuntimeError(f'Empty dataset selection: {era} {groups}')
    return sorted(set(selected))


def members(entry):
    return entry.get('datasets', []) + entry.get('sub_processes', [])



def weight_dependencies(c, era):
    if '--no-custom-weights' in c.hist_args: return []
    from common.apply_custom_weights import reweight_json_paths
    required = [key for key, flag in [('jet_component','jet-component'),('ptll_njets','ptll'),('njets','njets')]
                if '--no-dy-'+flag+'-reweight' not in c.hist_args]
    paths = reweight_json_paths(era_name(era),config(era,'process_names')['DY'].get('reweight_jsons'),set())
    return [paths[key] for key in required]


def raw_products(c, era, family):
    c = for_era(c, era)
    processes = config(era, 'process_names')
    groups = ','.join(g for g in csv(c.groups) if family == 'Central' or g != 'data')
    result = {}
    for dataset in datasets(era, groups):
        path = c.directory(family) / era_name(era) / (dataset + '.root')
        result[path] = weight_dependencies(c, era) if dataset.lower().startswith('dy') else []
        if '--pu-hard-jet-components' not in c.hist_args: continue
        process = next((p for p, e in processes.items() if dataset in members(e)), dataset)
        if process.endswith('_nonStitched') and dataset in members(processes.get(process.removesuffix('_nonStitched'), {})):
            process = process.removesuffix('_nonStitched')
        entry = processes.get(process, {})
        split = ('--all-mc-jet-components' in c.hist_args or
                 entry.get('split_jet_components', jet_components_enabled_for_dataset(['DY', 'EWK'], dataset, process, is_signal=entry.get('is_signal', False))))
        if process.startswith('Data') or not split: continue
        labels = {label for component, label in DY_COMPONENT_FILE_LABELS.items()
                  if (component.startswith('ggF_') and 'ggF' in c.categories) or (component.startswith('VBF_') and 'VBF' in c.categories)}
        for label in labels:
            label = label if process == 'DY' else process + '_' + label.removeprefix('DY_')
            result[path.with_name(dataset + '_' + label + '.root')] = list(result[path])
    return result


def hadded_products(c, era, family):
    raw = raw_products(c, era, family)
    selected_processes = config(era, 'skim_cfg').get('process_to_select', [])
    excluded = set(config(era, 'skim_cfg').get('datasets_exclude', []))
    products = {}
    for process in selected_processes:
        entry = config(era, 'process_names')[process]
        for label in (None, *dict.fromkeys(DY_COMPONENT_FILE_LABELS.values())):
            inputs = []
            for dataset in members(entry):
                if dataset in excluded: continue
                candidates = dataset_file_candidates(str(c.directory(family) / era_name(era)), process, dataset, label)
                match = next((Path(x) for x in candidates if Path(x) in raw), None)
                if match is not None: inputs.append(match)
            if inputs:
                suffix = '_' + label.removeprefix('DY_') if label else ''
                products[c.directory(family, True)/era_name(era)/(process+suffix+'.root')] = list(dict.fromkeys(inputs))
    if not products: raise RuntimeError(f'No hadded products selected for {c.name} {era} {family}')
    return products


class Incomplete(RuntimeError):
    pass


class Workflow:
    def __init__(self, c, args):
        if args.historical:
            if args.action != 'check':
                raise ValueError('--historical is a read-only check; it cannot authorize production or merges')
            if args.mode != 'central' and (c.root/'all').is_dir():
                c = replace(c, families=['all'])
            print(f'[HISTORICAL] {c.root}: auditing existing files; correlation policy and merge receipts are not certified', flush=True)
        self.c = c; self.args = args
        self.eras = [era_name(x) for x in (csv(args.eras) if args.eras else c.eras)]
        for era in self.eras:
            if not (REPO/'config'/era).is_dir(): raise ValueError(f'Unknown physical era: {era}')
        self.families = csv(args.families) if args.families else c.families
        if set(self.families) - set(c.families): raise ValueError('Unknown systematic family for this campaign')
        if args.mode != 'central' and not self.families: raise ValueError('This campaign supports central only')
        self.selected = (['Central'] if args.mode in ('central','both') else []) + (self.families if args.mode in ('syst','both') else [])
        default = '2022_25' if self.eras == [era_name(x) for x in ERAS] else '_'.join(x.removeprefix('Run3_') for x in self.eras)
        self.merged = era_name(args.merged_era or default)
        if self.merged in self.eras and len(self.eras) > 1: raise ValueError('Merged era cannot overwrite a physical era')
        self.key_cache = {}

    def run(self, cmd):
        cmd = [str(x) for x in cmd]
        print('$ ' + shlex.join(cmd), flush=True)
        if not self.args.dry_run:
            subprocess.run(cmd, cwd=REPO, check=True)
        self.key_cache.clear()

    def keys(self, path):
        stat = path.stat(); token = (path, stat.st_mtime_ns, stat.st_size)
        if token not in self.key_cache:
            import uproot
            with uproot.open(path) as f:
                keys = {k.split(';')[0] for k, cls in f.classnames(recursive=True).items() if cls.startswith(('TH1','TH2','TH3','TProfile'))}
                if not keys: raise ValueError('no histograms')
                # Materialize arrays as well: a directory/key alone is not a valid histogram.
                for key in keys: f[key].values()
                self.key_cache[token] = keys
        return self.key_cache[token]

    def check_products(self, products, title, receipt=None):
        errors = []
        if not products: raise Incomplete(f'{title}: empty expected output set')
        print(f'[{title}] checking {len(products)} files ({self.args.check_level}) ...', flush=True)
        present = 0
        for index, (path, inputs) in enumerate(products.items(), 1):
            if index == 1 or index % 100 == 0:
                print(f'[{title}] {index}/{len(products)}: {path}', flush=True)
            if not path.is_file() or path.stat().st_size == 0:
                errors.append(f'MISSING/EMPTY {path}'); continue
            present += 1
            if Path(str(path)+'.failed_chunks.txt').exists():
                errors.append(f'FAILED_CHUNKS {path}'); continue
            missing = [x for x in inputs if not x.is_file() or x.stat().st_size == 0]
            if missing:
                errors.append(f'MISSING_INPUT {path}: {missing[0]}'); continue
            if inputs and path.stat().st_mtime_ns < max(x.stat().st_mtime_ns for x in inputs):
                errors.append(f'STALE {path}'); continue
            if self.args.check_level == 'root':
                try:
                    keys = self.keys(path)
                    if inputs:
                        required = set().union(*(self.keys(x) for x in inputs if x.suffix == '.root'))
                        if not required <= keys: raise ValueError(f'{len(required-keys)} input histogram keys absent')
                except Exception as exc: errors.append(f'INVALID_ROOT {path}: {exc}')
        if receipt is not None and not self.args.historical:
            path, expected = receipt
            try:
                actual = json.loads(path.read_text())
                matches = (actual.get('template_merge_version') == expected.get('template_merge_version') and actual.get('eras') == expected.get('eras') and actual.get('merged_era') == expected.get('merged_era')
                           and set(actual.get('families', [])) >= set(expected.get('families', [])))
                if not matches: errors.append(f'WRONG_MERGE_SELECTION {path}')
            except (OSError, ValueError): errors.append(f'MISSING_MERGE_RECEIPT {path}')
        print(f'[{title}] expected={len(products)} present={present} missing/empty={len(products)-present} problems={len(errors)} check={self.args.check_level}', flush=True)
        for error in errors: print('  ' + error, flush=True)
        if errors: raise Incomplete(f'{title}: incomplete inputs/outputs')

    def products(self, stage, families=None, merged=False):
        families = families or self.selected
        raw = stage == 'histograms'
        result = {}
        for family in families:
            per_era = [raw_products(self.c, era, family) if raw else hadded_products(self.c, era, family) for era in self.eras]
            if merged:
                for items in per_era:
                    for path in items:
                        target = path.parent.parent/self.merged/path.name
                        result.setdefault(target, []).append(path)
            else:
                for items in per_era: result.update(items)
        return result

    def syst_products(self, merged=False):
        families = ['Central', *self.families]
        hadded = self.products('hadded', families, merged)
        result = {}
        for path in hadded:
            target = self.c.root/'Hists_systMerged'/path.parent.name/path.name
            result.setdefault(target, []).append(path)
        return result

    def receipt(self, stage):
        # Selection proof prevents an old subset merge being accepted as a full-era merge.
        return self.c.root/f'.workflow_{stage}_{self.merged}.json', {'eras': self.eras, 'families': self.selected, 'merged_era': self.merged, 'template_merge_version': 2}

    def save_receipt(self, stage):
        if not self.args.dry_run:
            path, value = self.receipt(stage)
            if self.args.mode != 'central': value['families'] = ['Central',*self.families]
            path.write_text(json.dumps(value, indent=2)+'\n')

    def check(self, stage):
        print(f'[CHECK] {self.c.root} stage={stage} eras={",".join(self.eras)} families={",".join(self.selected)}', flush=True)
        if stage == 'all':
            failed = False
            for item in ['histograms','hadded'] + (['merged-eras'] if len(self.eras)>1 else []) + (['merged-syst'] + (['merged'] if len(self.eras)>1 else []) if self.args.mode != 'central' else []):
                try: self.check(item)
                except Incomplete: failed = True
            if failed: raise Incomplete('One or more campaign stages are incomplete')
        elif stage == 'histograms': self.check_products(self.products(stage), stage)
        elif self.args.historical:
            # Audit each historical stage independently, including aggregates
            # when raw files are incomplete. Dependency problems still appear.
            if stage == 'hadded': self.check_products(self.products(stage), stage)
            elif stage == 'merged-eras':
                if len(self.eras) < 2: raise ValueError('Merged-era checks require at least two physical eras')
                self.check_products(self.products('hadded', merged=True), stage)
            elif stage in ('merged-syst', 'merged'):
                if self.args.mode == 'central': raise ValueError('Systematic merge requested in central mode')
                self.check_products(self.syst_products(stage == 'merged'), stage)
            else: raise ValueError(f'Unknown stage: {stage}')
        elif stage == 'hadded': self.check_hadded(self.selected)
        elif stage == 'merged-eras':
            if len(self.eras) < 2: raise ValueError('Merged-era checks require at least two physical eras')
            self.check('hadded')
            self.check_products(self.products('hadded', merged=True), stage, self.receipt('eras'))
        elif stage in ('merged-syst','merged'):
            if self.args.mode == 'central': raise ValueError('Systematic merge requested in central mode')
            self.check_hadded(['Central',*self.families])
            if stage == 'merged':
                self.check('merged-eras')
                self.check_syst(False)
            self.check_syst(stage == 'merged')
        else: raise ValueError(f'Unknown stage: {stage}')

    def syst_receipts(self, merged):
        for era in ([self.merged] if merged else self.eras):
            yield self.c.root/f'.workflow_syst_{era}.json', {
                'eras': self.eras if merged else [era], 'families': ['Central',*self.families], 'template_merge_version': 2}

    def check_syst(self, merged):
        self.check_products(self.syst_products(merged), 'merged-syst')
        for path, expected in self.syst_receipts(merged):
            try: actual = json.loads(path.read_text())
            except (OSError,ValueError): raise Incomplete(f'Missing systematic merge receipt: {path}; run merge-syst')
            if actual != expected: raise Incomplete(f'Wrong systematic merge selection: {path}; run merge-syst')

    def check_hadded(self, families):
        self.check_products(self.products('histograms', families), 'histograms')
        self.check_products(self.products('hadded', families), 'hadded')

    def weights(self, required=None):
        from common.apply_custom_weights import reweight_json_paths
        if '--no-custom-weights' in self.c.hist_args: return
        if required is None:
            required = {key for key, flag in [('jet_component','jet-component'),('ptll_njets','ptll'),('njets','njets')]
                        if '--no-dy-'+flag+'-reweight' not in self.c.hist_args}
        for era in self.eras:
            paths = reweight_json_paths(era, config(era,'process_names')['DY'].get('reweight_jsons'), required)
            for key in required:
                payload = json.loads(paths[key].read_text())
                if not isinstance(payload, dict) or not payload: raise ValueError(f'Invalid weight payload: {paths[key]}')

    def submit(self, local=False):
        if not self.args.dry_run: self.weights()
        unavailable = []
        for era in self.eras:
            c = for_era(self.c, era)
            for family in self.selected:
                groups = ','.join(g for g in csv(c.groups) if family == 'Central' or g != 'data')
                cmd = ['bash', 'histograms/scripts/'+('hists.sh' if family == 'Central' else 'systematics.sh'),
                       '--era',era,'--datasets',groups,'--output-dir',self.c.directory(family),
                       '--manifest-input-folder',self.c.manifests,'--root-input-folder',self.c.input_root,
                       '--json-input-folder',self.c.json_root or self.c.input_root,'--systematics',(','.join(physical_family(f, era) for f in self.c.bundled_families) if family == 'all' and self.c.bundled_families else physical_family(family, era)),'--chunk-size',self.c.chunk_size,
                       '--missing-only']
                if not local:
                    cmd += ['--request-cpus',self.c.cpus,'--request-memory',self.c.memory,
                            '--condor','--condor-label',self.c.name+'_'+family]
                if self.args.force: cmd += ['--force']
                producer_args = ['--',*c.hist_args,'--rdf-threads',self.c.cpus,'--variable-batch-size',self.c.batch]
                repairs = []
                blocked = []
                if not self.args.dry_run:
                    for dataset in datasets(era, groups):
                        manifest = Path(self.c.manifests)/era/(dataset+'.json')
                        if not manifest.is_file() and not (Path(self.c.manifests)/(dataset+'.json')).is_file():
                            blocked.append(dataset)
                            unavailable.append(str(manifest))
                            print(f'[UNAVAILABLE] missing validation manifest: {manifest}', flush=True)
                    if blocked:
                        cmd += ['--exclude-dataset', ','.join(blocked)]
                    if set(datasets(era, groups)) <= set(blocked): continue
                if not self.args.dry_run and not self.args.force:
                    expected = raw_products(self.c,era,family)
                    selected_datasets = [d for d in datasets(era,groups) if d not in blocked]
                    for dataset in selected_datasets:
                        nominal = self.c.directory(family)/era/(dataset+'.root')
                        if not nominal.exists(): continue
                        outputs = {p: inputs for p,inputs in expected.items()
                                   if max((d for d in selected_datasets if p.name == d+'.root' or p.name.startswith(d+'_')), key=len, default=None) == dataset}
                        for path,inputs in outputs.items():
                            bad = not path.is_file() or path.stat().st_size == 0 or Path(str(path)+'.failed_chunks.txt').exists()
                            bad = bad or any(not x.is_file() or (path.exists() and path.stat().st_mtime_ns < x.stat().st_mtime_ns) for x in inputs)
                            if not bad and self.args.check_level == 'root':
                                try: self.keys(path)
                                except Exception: bad = True
                            if bad:
                                repairs.append(dataset); break
                if repairs:
                    # Avoid submitting the same dataset once through the group and once as a repair.
                    if set(datasets(era,groups)) - set(repairs) - set(blocked):
                        self.run(cmd + ['--exclude-dataset',','.join(repairs)] + producer_args)
                    for dataset in repairs:
                        repair = list(cmd); index = repair.index('--datasets')
                        repair[index:index+2] = ['--dataset-name',dataset]
                        self.run(repair + ['--force'] + producer_args)
                else:
                    self.run(cmd + producer_args)

        if unavailable:
            raise Incomplete(f'Submitted available inputs; {len(set(unavailable))} dataset manifests unavailable')

    def hadd(self):
        if not self.args.dry_run: self.check('histograms')
        for family in self.selected:
            for era in self.eras:
                c = for_era(self.c, era)
                groups = ','.join(g for g in csv(c.groups) if family == 'Central' or g != 'data')
                cmd = [sys.executable, 'histograms/hadd_hists_to_processes.py',
                       '--input-dir', c.directory(family)/era,
                       '--output-dir', c.directory(family, True)/era, '--era', era,
                       '--datasets', ','.join(datasets(era, groups))]
                if family == 'Central' and self.c.families: cmd += ['--add-derived-systs']
                self.run(cmd)
        if not self.args.dry_run: self.check('hadded')

    def merge_eras(self):
        if len(self.eras) < 2: raise ValueError('merge-era needs at least two physical eras')
        families = ['Central',*self.families] if self.args.mode != 'central' else ['Central']
        if not self.args.dry_run: self.check_hadded(families)
        for family in families:
            self.run([sys.executable,'tools/hmumu.py','merge-eras',self.c.directory(family,True),
                      '--eras',','.join(self.eras),'--output-era',self.merged,
                      '--nominal-dir',self.c.directory('Central',True),'--run'])
        self.save_receipt('eras')
        if not self.args.dry_run: self.check('merged-eras')
        if self.args.mode != 'central':
            self.merge_syst(merged=False)
            self.merge_syst(merged=True)

    def merge_syst(self, merged=False):
        if self.args.mode == 'central': raise ValueError('merge-syst requires --mode syst or both')
        if not self.args.dry_run:
            self.check_hadded(['Central',*self.families])
            if merged:
                # Include Central even for --mode syst; it is a mandatory merge input.
                self.check_products(self.products('hadded',['Central',*self.families],True),
                                    'merged-eras Central + syst', self.receipt('eras'))
        cmd = [sys.executable,'tools/hmumu.py','merge-systematics',self.c.directory('Central',True),
               '--era',self.merged if merged else ','.join(self.eras),'--output-dir',self.c.root/'Hists_systMerged','--run']
        for family in self.families: cmd += ['--source-dir',self.c.directory(family,True)]
        self.run(cmd)
        if not self.args.dry_run:
            self.check_products(self.syst_products(merged),'merged-syst')
            for path, value in self.syst_receipts(merged): path.write_text(json.dumps(value,indent=2)+'\n')
            self.check_syst(merged)

    def plot(self):
        if not self.args.dry_run:
            self.check(('merged' if self.args.merged else 'merged-syst') if self.args.mode != 'central' else ('merged-eras' if self.args.merged else 'hadded'))
        source = self.c.root/'Hists_systMerged' if self.args.mode != 'central' else self.c.directory('Central',True)
        for era in ([self.merged] if self.args.merged else self.eras):
            selected_configs = [for_era(self.c,e) for e in self.eras] if self.args.merged else [for_era(self.c,era)]
            regions = list(dict.fromkeys(r for c in selected_configs for r in c.regions))
            categories = list(dict.fromkeys(r for c in selected_configs for r in c.categories))
            cmd = ['bash','plotting_tools/plot_all_regions.sh','--era',era,'--input-root',source,
                   '--output',Path(self.args.plot_output or 'plots/campaigns')/self.c.name/era,
                   '--regions',','.join(regions),'--categories',','.join(categories),'--no-component-composition']
            if self.args.merged: cmd += ['--plot-option','--combined-eras','--plot-option',','.join(self.eras)]
            if self.c.variables: cmd += ['--variables',','.join(self.c.variables)]
            if self.args.mode != 'central': cmd += ['--plot-option','--systematics','--plot-option','--totalSystematics']
            self.run(cmd)

    def action(self, action):
        if action == 'check': self.check(self.args.stage)
        elif action == 'validate':
            for era in self.eras:
                self.run(['bash','analysis/scripts/validate.sh','--era',era,'--datasets',for_era(self.c, era).groups,
                          '--root-input-folder',self.c.input_root,
                          '--json-input-folder',self.c.json_root or self.c.input_root,
                          '--output-dir',self.c.manifests])
        elif action in ('submit','local'): self.submit(action == 'local')
        elif action == 'hadd': self.hadd()
        elif action in ('merge-era','merge-eras'): self.merge_eras()
        elif action == 'merge-syst': self.merge_syst(self.args.merged)
        elif action == 'plot': self.plot()
        elif action == 'finish':
            self.hadd()
            if self.args.mode != 'central': self.merge_syst()
            self.plot()
            if len(self.eras) > 1:
                self.merge_eras(); self.args.merged = True; self.plot()
        elif action == 'paths':
            print(json.dumps({'campaign':self.c.name,'root':str(self.c.root),'eras':self.eras,'families':self.selected,
                              'input_root':self.c.input_root,'json_root':self.c.json_root or self.c.input_root,
                              'manifest_root':self.c.manifests,
                              'merged_era':self.merged,'regions':self.c.regions,'categories':self.c.categories,'hist_args':self.c.hist_args},indent=2))
        else: raise ValueError(f'Unsupported action: {action}')


def set_option(arguments, option, values):
    result = list(arguments)
    if option in result:
        start = result.index(option); end = start + 1
        while end < len(result) and not result[end].startswith('--'): end += 1
        del result[start:end]
    return result + [option, *values]


def for_era(c, era):
    selections = config(era, 'selections')
    regions = [k for k,v in selections['masses_regions'].items() if v.get('store')] if c.regions == ['all'] else c.regions
    categories = [k for k,v in selections['categories'].items() if v.get('store')] if c.categories == ['all'] else c.categories
    hist = set_option(set_option(c.hist_args,'--mass-regions',regions),'--categories',categories)
    groups = csv(c.groups)
    if 'region_auto' in groups:
        groups.remove('region_auto')
        if any(r in ('Signal_Fit', 'H_sideband') for r in regions): groups.append('region_higgs')
        if any(r not in ('Signal_Fit', 'H_sideband') for r in regions): groups.append('region_inclusive')
    return replace(c, regions=regions, categories=categories, hist_args=hist, groups=','.join(groups))


JES_REGROUPED = [
    'JESRegrouped_Absolute', 'JESRegrouped_Absolute_year',
    'JESRegrouped_BBEC1', 'JESRegrouped_BBEC1_year',
    'JESRegrouped_EC2', 'JESRegrouped_EC2_year',
    'JESRegrouped_HF', 'JESRegrouped_HF_year',
    'JESRegrouped_FlavorQCD', 'JESRegrouped_RelativeBal', 'JESRelativeSample_year',
]


def physical_family(family, era):
    return family.removesuffix('_year') + '_' + era.removeprefix('Run3_') if family.endswith('_year') else family


def make_campaign(kind, args):
    if args.config:
        c = load_campaign(args.config)
    elif kind.startswith('dnn_vbf_'):
        c = load_campaign(kind + '_sep03')
    elif kind == 'all_variables':
        c = load_campaign('all_variables')
    else: raise ValueError(kind)
    if args.mode is None: args.mode = 'both' if c.families else 'central'
    if args.jes == 'regrouped':
        c.families = [part for family in c.families
                      for part in (JES_REGROUPED if family == 'JES_Total' else [family])]
    if args.systematics_layout == 'together':
        if args.families: raise ValueError('--families requires --systematics-layout split')
        c.bundled_families = tuple(c.families)
        c.families = ['all']
    if args.variables:
        c.variables = csv(args.variables)
        c.hist_args = set_option(c.hist_args, '--variables', c.variables)
    if args.datasets: c.groups = args.datasets
    if args.weights == 'none': c.hist_args += ['--no-custom-weights']
    if args.dy_weights is not None:
        requested = set(csv(args.dy_weights))
        if requested - {'jet-component', 'ptll', 'njets'}: raise ValueError('Unknown DY weight')
        for weight in ('jet-component', 'ptll', 'njets'):
            c.hist_args = [x for x in c.hist_args if x not in ('--dy-'+weight+'-reweight', '--no-dy-'+weight+'-reweight')]
            c.hist_args.append(('--dy-' if weight in requested else '--no-dy-')+weight+'-reweight')
    if args.output_root: c.root = Path(args.output_root).resolve()
    if args.regions: c.regions = csv(args.regions)
    if args.categories: c.categories = csv(args.categories)
    return input_overrides(c, args)


def input_overrides(c, args, no_horn=False):
    """Keep ROOT, bookkeeping JSON and manifest inputs consistent across producers."""
    if getattr(args, 'threads', None) is not None:
        if args.threads < 1: raise ValueError('--threads must be positive')
        c.cpus = str(args.threads)
    if getattr(args, 'memory', None): c.memory = args.memory
    suffix = '_noJetHornVeto' if no_horn else ''
    if args.input_root:
        c.input_root = args.input_root.rstrip('/') + suffix
        if not args.json_root: c.json_root = c.input_root
    if args.manifest_root: c.manifests = args.manifest_root.rstrip('/') + suffix
    if args.json_root: c.json_root = args.json_root.rstrip('/') + suffix
    if no_horn:
        if args.no_horn_input_root:
            c.input_root = args.no_horn_input_root
            if not args.no_horn_json_root and not args.json_root: c.json_root = c.input_root
        if args.no_horn_manifest_root: c.manifests = args.no_horn_manifest_root
        if args.no_horn_json_root: c.json_root = args.no_horn_json_root
    return c


def horn_campaign(variant, args):
    root = Path(args.output_root).resolve() if args.output_root else EOS/('campaigns/JetHornVetoComparison' + ('_AllWeights' if args.weights == 'analysis' else ''))
    hist = ['--custom-weights','--dy-jet-component-reweight','--dy-ptll-reweight','--dy-njets-reweight'] if args.weights == 'analysis' else ['--no-custom-weights','--no-dy-jet-component-reweight','--no-dy-ptll-reweight','--no-dy-njets-reweight']
    c = Campaign('JetHornVeto_'+variant, root/variant, ['2024','2025','2026'], [], 'data,DY_amcatnlo',
                 hist+['--variables',*HORN_VARIABLES], ['Signal_Fit','Z_sideband','H_sideband','mass_inclusive'], ['VBF','ggF','baseline'], HORN_VARIABLES)
    if variant == 'NoHornVeto':
        c.input_root += '_noJetHornVeto'; c.manifests += '_noJetHornVeto'; c.hist_args += ['--disable-jet-horn-veto']
    return input_overrides(c, args, variant == 'NoHornVeto')


def horn(args):
    if args.mode != 'central': raise ValueError('Jet horn workflow is central only')
    requested = csv(args.eras) if args.eras else ['2024','2025','2026']
    requested = [x.removeprefix('Run3_') for x in requested]
    if set(requested) - {'2024','2025','2026'}: raise ValueError('Horn comparisons support 2024, 2025, 2026')
    variants = ['WithHornVeto','NoHornVeto'] if args.variant == 'both' else [args.variant]
    workflows = []
    for variant in variants:
        years = [x for x in requested if x != '2024' or variant == 'WithHornVeto']
        if not years: continue
        opts = argparse.Namespace(**vars(args)); opts.eras = ','.join(years)
        workflows.append(Workflow(horn_campaign(variant,args),opts))
    if args.action == 'start':
        # Requested convenience: submit the 2024 reference and audit both 2025/2026 variants.
        opts = argparse.Namespace(**vars(args)); opts.eras = '2024'
        Workflow(horn_campaign('WithHornVeto',args),opts).submit()
        failed = False
        for w in workflows:
            w.eras = [e for e in w.eras if e != 'Run3_2024']
            if not w.eras: continue
            try: w.check('histograms')
            except Incomplete: failed = True
        if failed: raise Incomplete('2024 submitted; 2025/2026 still incomplete')
        return
    if args.action == 'validate':
        for w in workflows:
            for era in w.eras:
                w.run(['bash','analysis/scripts/validate.sh','--era',era,'--datasets','skim_cfg',
                       '--root-input-folder',w.c.input_root,'--json-input-folder',w.c.json_root or w.c.input_root,'--output-dir',w.c.manifests])
        return
    if not workflows: raise ValueError('No horn variants selected (2024 has only the with-veto reference)')
    if args.action not in ('plot','finish'):
        failed = False
        for w in workflows:
            if args.action in ('merge-era','merge-eras') and len(w.eras) < 2:
                print(f'[SKIP] {w.c.name}: only one physical era')
                continue
            try: w.action(args.action)
            except Incomplete: failed = True
        if failed: raise Incomplete('Horn campaign incomplete')
        return
    if args.variant != 'both': raise ValueError('Horn comparison plots require --variant both')
    for w in workflows:
        if args.action == 'finish':
            w.hadd()
            if len(w.eras) > 1: w.merge_eras()
        elif not args.dry_run: w.check('hadded')
    base = horn_campaign('WithHornVeto',args).root.parent
    comparisons = [x+'-horn' for x in requested if x != '2024']
    if {'2024','2025'} <= set(requested): comparisons.append('2024-2025')
    for comparison in comparisons:
        workflows[0].run([sys.executable,'tools/plot_jet_horn_comparison.py','--base',base,'--comparison',comparison,
                          '--output',Path(args.plot_output or 'plots/campaigns')/base.name/comparison,'--rebin'])


WEIGHT_STAGES = [('jet', 'dy012j_skim_v4','jet_component'), ('ptll','dy_ptll_skim_v4','ptll_njets'), ('njets','dy_njets_skim_v4','njets')]


def weight_workflow(stage, args):
    c = load_campaign(stage[1])
    c = input_overrides(c, args)
    if args.output_root: c.root = Path(args.output_root).resolve()/stage[0]
    opts = argparse.Namespace(**vars(args)); opts.mode = 'central'
    return Workflow(c,opts)


def fit_groups(eras):
    groups = []
    for era in eras:
        short = era.removeprefix('Run3_')
        pair = ['Run3_2022','Run3_2022EE'] if short in ('2022','2022EE') else ['Run3_2023','Run3_2023BPix'] if short in ('2023','2023BPix') else [era]
        if not set(pair) <= set(eras): raise ValueError(f'Weights for {era} use a combined fit: select {",".join(pair)}')
        if pair not in groups: groups.append(pair)
    return groups


def payload_path(era, key):
    # Resolve the same configured paths used by hist_maker; do not silently switch payload locations.
    from common.apply_custom_weights import reweight_json_paths
    return reweight_json_paths(era,config(era,'process_names')['DY'].get('reweight_jsons'),set())[key]


def check_payloads(w, key):
    for group in fit_groups(w.eras):
        path = payload_path(group[0],key)
        if any(payload_path(e,key) != path for e in group): raise ValueError('Combined eras configure different payload paths')
        inputs = [p for e in group for p in hadded_products(w.c,e,'Central')]
        if not path.is_file(): raise Incomplete(f'Missing weight payload: {path}')
        try: value = json.loads(path.read_text())
        except (OSError,ValueError) as exc: raise Incomplete(f'Invalid weight payload: {path}: {exc}')
        if not isinstance(value,dict) or not value: raise Incomplete(f'Invalid weight payload: {path}')
        if any(not p.is_file() for p in inputs) or path.stat().st_mtime_ns < max(p.stat().st_mtime_ns for p in inputs):
            raise Incomplete(f'Stale weight payload: {path}')
        print(f'[weights] OK {path}')


def fit_weights(w, stage):
    if not w.args.dry_run: w.check('hadded')
    for group in fit_groups(w.eras):
        era = group[0] if len(group) == 1 else 'Run3_'+'_'.join(e.removeprefix('Run3_') for e in group)
        path = payload_path(group[0],stage[2])
        output = path.parent
        if not w.args.dry_run: output.mkdir(parents=True,exist_ok=True)
        if stage[0] == 'jet':
            cmd = [sys.executable,'tools/derive_dy_012j_reweight.py','--era',era,'--input-dir',*[w.c.directory('Central',True)/e for e in group]]
        else:
            if len(group) > 1:
                saved_eras, saved_merged = w.eras, w.merged
                w.eras, w.merged = group, era
                w.merge_eras()
                w.eras, w.merged = saved_eras, saved_merged
            tool = 'derive_dy_ptll_njets_reweight.py' if stage[0] == 'ptll' else 'derive_dy_njets_reweight.py'
            cmd = [sys.executable,'tools/'+tool,'--era',era,'--input-dir',w.c.directory('Central',True)/era]
            if stage[0] == 'ptll': cmd += ['--smart-rebin']
        cmd += ['--output-dir',output,'--output-json',path,'--output-root',output/(path.stem+'.root')]
        w.run(cmd)
    if not w.args.dry_run: check_payloads(w,stage[2])


def weights(args):
    if args.mode != 'central': raise ValueError('Weight derivation is central only')
    stages = WEIGHT_STAGES if args.weight_stage == 'all' else [s for s in WEIGHT_STAGES if s[0] == args.weight_stage]
    if args.action == 'run' and args.weight_stage != 'all': raise ValueError('run performs the full ordered sequence; omit --weight-stage')
    failed = False
    for stage in stages:
        w = weight_workflow(stage,args)
        if args.action in ('run','fit','check-weights'):
            fit_groups(w.eras)  # Fits require both eras sharing a payload.
        if args.action == 'run':
            if args.dry_run:
                w.submit(); w.hadd(); fit_weights(w,stage); continue
            try: w.check('histograms')
            except Incomplete:
                w.submit()
                print(f'[WAIT] Submitted {stage[0]}. Re-run after Condor finishes. Incomplete existing outputs are regenerated automatically.')
                return 3
            try: w.check('hadded')
            except Incomplete: w.hadd()
            try: check_payloads(w,stage[2])
            except Incomplete: fit_weights(w,stage)
        elif args.action == 'fit': fit_weights(w,stage)
        elif args.action == 'check-weights':
            try: check_payloads(w,stage[2])
            except Incomplete as exc: print(str(exc)); failed = True
        else:
            if args.action in ('submit','local') and args.weight_stage == 'all':
                raise ValueError('Use run for sequential submission, or select --weight-stage jet|ptll|njets')
            try: w.action(args.action)
            except Incomplete: failed = True
    if failed: raise Incomplete('One or more weight stages incomplete')
    return 0


def parser(kind):
    p = argparse.ArgumentParser(description=f'{kind}: shared histogram producer with guarded stage transitions')
    p.add_argument('action',nargs='?',default='check',choices=['check','submit','local','validate','hadd','merge-syst','merge-era','merge-eras','plot','finish','paths'] + (['run','fit','check-weights'] if kind == 'dy_weights' else ['start'] if kind == 'jet_horn_veto' else []))
    p.add_argument('--config', help='Shell campaign configuration')
    p.add_argument('--variables', help='Comma-separated histogram variables')
    p.add_argument('--threads', type=int, help='ROOT threads per job and matching Condor CPU request')
    p.add_argument('--memory', help='HTCondor memory request, e.g. 8GB')
    p.add_argument('--dy-weights', help='Custom weights: jet-component,ptll,njets (empty disables all three)')
    p.add_argument('--datasets', help='Comma-separated sample groups')
    p.add_argument('--systematics-layout', choices=['split', 'together'], default='split')
    if kind != 'jet_horn_veto': p.add_argument('--weights', choices=['analysis', 'none'], default='analysis')
    p.add_argument('--mode',choices=['central','syst','both'],default=None if kind == 'generic' else 'central' if kind in ('jet_horn_veto','dy_weights') else 'both')
    p.add_argument('--eras',help='Comma-separated physical eras; defaults to the campaign configuration')
    p.add_argument('--jes',choices=['regrouped','total'],default='regrouped',help='JES model for DNN/all_variables: regrouped uses simple across-year correlations')
    p.add_argument('--families',help='Comma-separated subset of systematic families; each is submitted separately')
    p.add_argument('--stage',choices=['histograms','hadded','merged-eras','merged-syst','merged','all'],default='histograms')
    p.add_argument('--check-level',choices=['root','files'],default='root',help='root checks readability, histogram keys and upstream freshness; files checks presence/size/freshness only')
    p.add_argument('--historical',action='store_true',help='Read-only audit: detect legacy all/ systematics and inspect each stage without certifying new correlation policies or merge receipts')
    p.add_argument('--merged-era',help='Name for the exact selected era combination')
    p.add_argument('--merged',action='store_true',help='Plot or merge systematics for the merged-era output')
    p.add_argument('--input-root','--input-dir',help='Override skim ROOT input base; horn no-veto variant appends _noJetHornVeto')
    p.add_argument('--json-root',help='Override skim bookkeeping JSON base (default: same as ROOT input)')
    p.add_argument('--manifest-root',help='Override manifest base; regenerate with validate when changing skims')
    p.add_argument('--output-root','--output-dir',help='Override campaign output root (weights: parent of jet/ptll/njets)')
    p.add_argument('--plot-output')
    p.add_argument('--regions',help='Override mass regions (comma-separated)')
    p.add_argument('--categories',help='Override categories (comma-separated)')
    p.add_argument('--dry-run',action='store_true',help='Print commands only; do not certify inputs or write/submit anything')
    p.add_argument('--force',action='store_true',help='Force histogram regeneration, including existing invalid/partial outputs')
    if kind == 'jet_horn_veto':
        p.add_argument('--no-horn-input-root',help='Exact no-veto ROOT base, overriding the automatic suffix')
        p.add_argument('--no-horn-json-root',help='Exact no-veto bookkeeping JSON base')
        p.add_argument('--no-horn-manifest-root',help='Exact no-veto manifest base')
        p.add_argument('--variant',choices=['WithHornVeto','NoHornVeto','both'],default='both')
        p.add_argument('--weights',choices=['none','analysis'],default='none',help='none disables custom DY reweights, retaining nominal MC weights')
    if kind == 'dy_weights': p.add_argument('--weight-stage',choices=['all','jet','ptll','njets'],default='all')
    return p


def main(kind, argv=None):
    args = parser(kind).parse_args(argv)
    os.environ['ANALYSIS_PATH'] = str(REPO)
    try:
        if args.historical and args.action != 'check':
            raise ValueError('--historical is available only with check')
        if args.action == 'check':
            print(f'[START] {kind}: preparing {args.stage} check ({args.check_level})', flush=True)
            if args.check_level == 'root':
                try: __import__('uproot')
                except ImportError:
                    raise ValueError('ROOT checks require uproot: run source env.sh, or use --check-level files for a file-only check') from None
        if kind == 'dy_weights': return weights(args)
        if kind == 'jet_horn_veto': horn(args)
        else: Workflow(make_campaign(kind,args),args).action(args.action)
        return 0
    except (Incomplete, ValueError, FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f'[STOP] {exc}',file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1],sys.argv[2:]))
