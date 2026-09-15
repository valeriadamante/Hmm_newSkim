#!/usr/bin/env python3
"""Measure the effect of keeping muons with BSC chi2 >= 30 in each category."""
import argparse
import glob
import json
from pathlib import Path
import sys
import ROOT
import yaml
import os
import threading
import time
from contextlib import contextmanager
os.environ.setdefault('MPLCONFIGDIR','/tmp/vdamante/matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT.gROOT.SetBatch(True)
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
from common.prepare_rdf import prepare_rdf
from common.utilities import get_segmentation_dict, initialize_root_runtime
from tools.study_inputs import configured_samples, DEFAULT_BACKGROUNDS, DEFAULT_SIGNALS
initialize_root_runtime()
DEFAULT_INPUT = Path('/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4')

@contextmanager
def progress(label):
    started=time.monotonic()
    done=threading.Event()
    print(f'[START] {label}',flush=True)
    def heartbeat():
        while not done.wait(30):
            print(f'[RUNNING] {label}: {time.monotonic()-started:.0f} s',flush=True)
    worker=threading.Thread(target=heartbeat,daemon=True)
    worker.start()
    try:
        yield
    finally:
        done.set(); worker.join(timeout=1)
        print(f'[DONE] {label}: {time.monotonic()-started:.1f} s',flush=True)

def paths(patterns):
    result = sorted({x for pattern in patterns for x in glob.glob(pattern) if x.endswith('.root')})
    if not result: raise SystemExit('No ROOT files matched')
    return result

def dataframe(inputs):
    v = ROOT.std.vector('string')()
    for x in inputs: v.push_back(x)
    return ROOT.RDataFrame('Events',v)

def require(df, required):
    missing = set(required)-{str(x) for x in df.GetColumnNames()}
    if missing: raise SystemExit('Missing skim columns: '+', '.join(sorted(missing)))

def resolve_muon_pt_columns(df):
    columns = {str(x) for x in df.GetColumnNames()}
    candidates = [
        ('mu1_pt', 'mu2_pt'),
        ('mu1_pt_nominal', 'mu2_pt_nominal'),
        ('mu1_pt_raw', 'mu2_pt_raw'),
    ]
    for mu1_pt, mu2_pt in candidates:
        if mu1_pt in columns and mu2_pt in columns:
            return mu1_pt, mu2_pt
    raise SystemExit(
        'Cannot find muon pT columns. Tried: ' +
        ', '.join(f'{a}/{b}' for a,b in candidates)
    )

def plot_report(report, prefix):
    cats=list(report['data']['categories'])
    samples={'data':report['data'],**report.get('mc',{})}
    fig,ax=plt.subplots(figsize=(max(9,2*len(samples)+5),4.5))
    x=np.arange(len(cats)); width=.8/len(samples)
    maximum=0
    for index,(name,entry) in enumerate(samples.items()):
        percentages=[(entry['categories'][c]['chi2_ge30_fraction'] or 0)*100
                     for c in cats]
        maximum=max(maximum,*percentages)
        ax.bar(x-.4+width*(index+.5),percentages,width,label=name)
    ax.set_ylim(0,max(1,maximum*1.2))
    ax.set_xticks(x)
    ax.set_xticklabels(cats)
    ax.set_ylabel('Eventi con BSC χ² ≥ 30 [%]')
    ax.tick_params(axis='x',rotation=35); ax.grid(axis='y',alpha=.25)
    ax.legend()
    fig.tight_layout(); fig.savefig(str(prefix)+'_fractions.png',dpi=160); plt.close(fig)

    source=ROOT.TFile.Open(str(prefix)+'.root','READ')
    for sample in samples:
        fig,axes=plt.subplots(4,2,figsize=(11,12),sharex=True)
        for ax,cat in zip(axes.flat,cats):
            all_h=source.Get(f'{sample}_{cat}_all')
            kept_h=source.Get(f'{sample}_{cat}_chi2_lt30')
            edges=np.array([all_h.GetBinLowEdge(i) for i in range(1,all_h.GetNbinsX()+2)])
            all_v=[all_h.GetBinContent(i) for i in range(1,all_h.GetNbinsX()+1)]
            kept_v=[kept_h.GetBinContent(i) for i in range(1,kept_h.GetNbinsX()+1)]
            ax.stairs(all_v,edges,label='Senza taglio χ²',color='tab:blue')
            ax.stairs(kept_v,edges,label='χ² < 30',color='tab:orange')
            ax.set_title(cat); ax.grid(alpha=.25)
        axes.flat[-1].axis('off'); axes.flat[0].legend()
        fig.supxlabel(r'$m_{\mu\mu}$ [GeV]')
        fig.supylabel(f'{sample}: eventi / 2.5 GeV')
        fig.tight_layout()
        suffix='' if sample=='data' else '_'+sample
        fig.savefig(str(prefix)+'_mass'+suffix+'.png',dpi=160)
        plt.close(fig)

        fig,axes=plt.subplots(4,2,figsize=(11,12),sharex=True)
        for ax,cat in zip(axes.flat,cats):
            h1=source.Get(f'{sample}_{cat}_mu1_pt_chi2_ge30')
            h2=source.Get(f'{sample}_{cat}_mu2_pt_chi2_ge30')
            if not h1 or not h2:
                ax.set_title(cat+' (missing pT hist)')
                continue
            edges=np.array([h1.GetBinLowEdge(i) for i in range(1,h1.GetNbinsX()+2)])
            v1=np.array([h1.GetBinContent(i) for i in range(1,h1.GetNbinsX()+1)])
            v2=np.array([h2.GetBinContent(i) for i in range(1,h2.GetNbinsX()+1)])
            ax.stairs(v1+v2,edges,label=r'$\mu$ with BSC $\chi^2\geq30$')
            ax.set_title(cat); ax.grid(alpha=.25)
        axes.flat[-1].axis('off'); axes.flat[0].legend()
        fig.supxlabel(r'$p_T(\mu)$ [GeV]')
        fig.supylabel(f'{sample}: muons')
        fig.tight_layout()
        fig.savefig(str(prefix)+'_pt_chi2_ge30'+suffix+'.png',dpi=160)
        plt.close(fig)

        if sample != 'data' and 'gen_truth' in samples[sample]:
            fig,axes=plt.subplots(4,2,figsize=(12,12),sharex=True,
                                  constrained_layout=True)
            plotted=None
            for index,(ax,cat) in enumerate(zip(axes.flat,cats)):
                h=source.Get(f'{sample}_{cat}_chi2_vs_gentruth')
                values=np.array([[h.GetBinContent(ix,iy)
                                  for ix in range(1,h.GetNbinsX()+1)]
                                 for iy in range(1,h.GetNbinsY()+1)])
                plotted=ax.imshow(np.log10(1+values),aspect='auto',origin='lower',
                                  extent=(0,500,-.5,2.5),cmap='viridis')
                ax.axvline(30,color='red',linestyle='--',linewidth=1)
                ax.set_yticks([0,1,2])
                if index % 2 == 0:
                    ax.set_yticklabels(['unmatched','prompt','other matched'])
                else:
                    ax.set_yticklabels([])
                truth=samples[sample]['gen_truth'][cat]
                fraction=truth['prompt_high_chi2_fraction']
                ax.set_title(f'{cat}: prompt χ²≥30 = {fraction:.1%}'
                             if fraction is not None else f'{cat}: no prompt muons')
            axes.flat[-1].axis('off')
            fig.supxlabel('BSC χ²'); fig.suptitle(sample)
            if plotted is not None:
                fig.colorbar(plotted,ax=list(axes.flat),label='log10(1 + muoni)',
                             shrink=.55)
            fig.savefig(str(prefix)+'_chi2_vs_gentruth_'+sample+'.png',dpi=160)
            plt.close(fig)
    source.Close()

def configured_data(era, root):
    process_cfg = yaml.safe_load((REPO/'config'/era/'process_names.yaml').read_text())
    skim_cfg = yaml.safe_load((REPO/'config'/era/'skim_cfg.yaml').read_text())
    if 'Data_Muon' not in skim_cfg.get('process_to_select', []):
        raise SystemExit(f'Data_Muon is not selected in {era}/skim_cfg.yaml')
    entry = process_cfg['Data_Muon']
    excluded = set(skim_cfg.get('datasets_exclude', []))
    datasets = [x for x in entry.get('datasets', []) + entry.get('sub_processes', [])
                if x not in excluded]
    inputs = []
    for dataset in datasets:
        directory = root/era/dataset
        if not directory.is_dir(): raise SystemExit(f'Missing data skim: {directory}')
        inputs += paths([str(directory/'skim_*.root')])
    return sorted(set(inputs))

def run_sample(inputs, sample, era, is_data):
    raw = dataframe(inputs)
    sel = yaml.safe_load((REPO/'config'/era/'selections.yaml').read_text())
    syst = yaml.safe_load((REPO/'config'/era/'systematics.yaml').read_text())
    if is_data:
        seg = {}
    else:
        parents = {str(Path(x).parent) for x in inputs}
        if len(parents) != 1:
            raise SystemExit('MC inputs must come from one dataset directory')
        directory = Path(next(iter(parents)))
        reports = sorted(directory.glob('report_*.json'))
        if not reports: raise SystemExit(f'Missing skim reports in {directory}')
        seg = get_segmentation_dict(reports)
        if not seg: raise SystemExit(f'No usable generator normalization in {directory}')
    df = prepare_rdf(raw,dataset_name=sample,era=era,
        selections_cfg=sel,systematics_cfg=syst,is_data=is_data,
        seg_dict=seg,
        enable_dy012j=False,enable_dyptll=False,enable_dynjets=False,
        enable_custom_weights=False)['inclusive']
    require(df,['mass_inclusive','baseline','ggF','VBF','ggF_0J','ggF_1J',
                'ggF_ge2J','VBF_ge2J','chi2_sel','weight__Central',
                'mu1_bsConstrainedChi2','mu2_bsConstrainedChi2'])
    base = df.Filter('mass_inclusive')
    mu1_pt, mu2_pt = resolve_muon_pt_columns(df)
    categories = ('baseline','VBF','ggF','ggF_0J','ggF_1J','ggF_ge2J','VBF_ge2J')
    report = {'files':inputs,'sample':sample,'is_data':is_data,
              'region':'analysis OS baseline, mass_inclusive (60,150) GeV',
              'categories':{}}
    if not is_data:
        require(df,['mu1_GenMatched','mu2_GenMatched','mu1_genPartFlav',
                    'mu2_genPartFlav','mu1_bsConstrainedChi2','mu2_bsConstrainedChi2'])
        # Prompt genmatched is an observable proxy for a Higgs daughter; the
        # skim does not retain GenPart ancestry to prove a Higgs mother.
        base=base.Define('check_truth_mu1',
            'mu1_GenMatched ? (int(mu1_genPartFlav)==1 ? 1 : 2) : 0')
        base=base.Define('check_truth_mu2',
            'mu2_GenMatched ? (int(mu2_genPartFlav)==1 ? 1 : 2) : 0')
        report['gen_truth_definition']={
            '0':'unmatched','1':'prompt genmatched (H-daughter proxy)',
            '2':'other genmatched',
            'limitation':'GenPart Higgs ancestry is not stored in these skims'}
        report['gen_truth']={}
    booked={}; actions=[]
    for name in categories:
        selected = base.Filter(name)
        retained = selected.Filter('chi2_sel')
        entry={}
        for label,node in [('all',selected),('chi2_lt30',retained)]:
            entry[label]={
                'count':node.Count(),
                'sum':node.Sum('weight__Central'),
                'hist':node.Histo1D((f'{sample}_{name}_{label}', '', 36,60.,150.),
                                    'm_mumu','weight__Central')}
            actions.extend(entry[label].values())

        entry['pt_fail'] = {
            1: selected.Filter('mu1_bsConstrainedChi2 >= 30').Histo1D(
                (f'{sample}_{name}_mu1_pt_chi2_ge30','',60,0.,300.),
                mu1_pt,'weight__Central'),
            2: selected.Filter('mu2_bsConstrainedChi2 >= 30').Histo1D(
                (f'{sample}_{name}_mu2_pt_chi2_ge30','',60,0.,300.),
                mu2_pt,'weight__Central'),
        }
        actions.extend(entry['pt_fail'].values())

        if not is_data:
            entry['truth']={leg:selected.Histo2D(
                (f'{sample}_{name}_truth_mu{leg}','',50,0.,500.,3,-.5,2.5),
                f'mu{leg}_bsConstrainedChi2',f'check_truth_mu{leg}')
                for leg in (1,2)}
            actions.extend(entry['truth'].values())
        booked[name]=entry
    with progress(f'Elaborazione {sample} ({len(inputs)} file)'):
        ROOT.RDF.RunGraphs(actions)
    for name,entry in booked.items():
        all_counts={'events':int(entry['all']['count'].GetValue()),
                    'sum_weights':float(entry['all']['sum'].GetValue())}
        kept={'events':int(entry['chi2_lt30']['count'].GetValue()),
              'sum_weights':float(entry['chi2_lt30']['sum'].GetValue())}
        removed = all_counts['events']-kept['events']
        report['categories'][name] = {
            'without_chi2_cut':all_counts,'with_chi2_cut':kept,
            'chi2_ge30_events':removed,
            'chi2_ge30_fraction':removed/all_counts['events'] if all_counts['events'] else None,
            'signed_weight_fraction_removed':
                1-kept['sum_weights']/all_counts['sum_weights']
                if all_counts['sum_weights'] else None}
        print(f'[CATEGORY] {sample}/{name}: {all_counts["events"]} eventi, '
              f'{removed} con BSC χ² ≥ 30',flush=True)
        for label in ('all','chi2_lt30'):
            entry[label]['hist'].GetValue().Write()
        for hist in entry['pt_fail'].values():
            hist.GetValue().Write()
        if not is_data:
            truth=entry['truth'][1].GetValue().Clone(f'{sample}_{name}_chi2_vs_gentruth')
            truth.Add(entry['truth'][2].GetValue())
            truth.Write()
            prompt_total=sum(truth.GetBinContent(ix,2)
                             for ix in range(0,truth.GetNbinsX()+2))
            first_high=truth.GetXaxis().FindFixBin(30.)
            prompt_high=sum(truth.GetBinContent(ix,2)
                            for ix in range(first_high,truth.GetNbinsX()+2))
            report['gen_truth'][name]={
                'prompt_muons':int(prompt_total),
                'prompt_high_chi2_muons':int(prompt_high),
                'prompt_high_chi2_fraction':prompt_high/prompt_total if prompt_total else None}
            print(f'[GEN TRUTH] {sample}/{name}: {prompt_high:.0f}/{prompt_total:.0f} '
                  'prompt genmatched muons with BSC χ² ≥ 30',flush=True)
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--era',default='2022',help='Run3 era (default: 2022)')
    p.add_argument('--input-root',type=Path,default=DEFAULT_INPUT)
    p.add_argument('--data',action='append',help='Override data ROOT glob; repeatable')
    p.add_argument('--mc',action='append',help='Optional MC ROOT glob; repeatable')
    p.add_argument('--backgrounds',default=DEFAULT_BACKGROUNDS,
                   help='Comma-separated background processes or datasets')
    p.add_argument('--signals',default=DEFAULT_SIGNALS,
                   help='Comma-separated signal processes or datasets; empty disables signals')
    p.add_argument('--output',help='Output prefix for ROOT and JSON')
    a=p.parse_args()
    ROOT.EnableImplicitMT()
    era=a.era if a.era.startswith('Run3_') else 'Run3_'+a.era
    out=Path(a.output or f'results/check_bsc_chi2_{era}')
    out.parent.mkdir(parents=True,exist_ok=True)
    f=ROOT.TFile(str(out)+'.root','RECREATE')
    with progress('Scoperta ntuple dati'):
        if a.data or a.mc:
            data_inputs=paths(a.data) if a.data else configured_data(era,a.input_root)
            configured_mc={}
        else:
            try:
                data_inputs,configured_mc=configured_samples(
                    REPO,era,a.input_root,a.backgrounds,a.signals)
            except (ValueError,FileNotFoundError) as exc:
                raise SystemExit(str(exc)) from exc
    print(f'[INPUT] {era}: {len(data_inputs)} file dati',flush=True)
    report={'data':run_sample(data_inputs,'data',era,True)}
    if a.mc or configured_mc:
        grouped={}
        if a.mc:
            for path in paths(a.mc): grouped.setdefault(str(Path(path).parent),[]).append(path)
        else:
            grouped={info['input_dir']:info['files'] for info in configured_mc.values()}
        report['mc']={}
        for directory,inputs in grouped.items():
            dataset=Path(directory).name
            print(f'[INPUT] MC {dataset}: {len(inputs)} file',flush=True)
            report['mc'][dataset]=run_sample(inputs,dataset,era,False)
            if dataset in configured_mc:
                report['mc'][dataset]['process']=configured_mc[dataset]['process']
                report['mc'][dataset]['kind']=configured_mc[dataset]['kind']
    f.Close()
    (out.parent/(out.name+'.json')).write_text(json.dumps(report,indent=2)+'\n')
    with progress('Produzione plot'):
        plot_report(report,out)
    print(f'[OUTPUT] {out}.json, {out}.root, '
          f'{out}_fractions.png, {out}_mass.png',flush=True)
    print(f'[OUTPUT] {out}_pt_chi2_ge30.png',flush=True)
    for dataset in report.get('mc',{}):
        print(f'[OUTPUT] {out}_mass_{dataset}.png',flush=True)
        print(f'[OUTPUT] {out}_pt_chi2_ge30_{dataset}.png',flush=True)
        print(f'[OUTPUT] {out}_chi2_vs_gentruth_{dataset}.png',flush=True)
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()
