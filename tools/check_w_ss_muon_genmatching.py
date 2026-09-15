#!/usr/bin/env python3
"""Compare muon-SF genmatching prescriptions in the same-sign W control region."""
import argparse
import glob
import json
from pathlib import Path
import ROOT
import yaml
import sys
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
sys.path.insert(0, str(REPO))
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

def files(patterns):
    found = sorted({p for pattern in patterns for p in glob.glob(pattern) if p.endswith('.root')})
    if not found:
        raise SystemExit(f'No ROOT files found for {patterns}')
    return found

def rdf(paths):
    vec = ROOT.std.vector('string')()
    for path in paths: vec.push_back(path)
    return ROOT.RDataFrame('Events', vec)

def require(df, names):
    missing = set(names) - {str(x) for x in df.GetColumnNames()}
    if missing: raise SystemExit('Missing skim columns: ' + ', '.join(sorted(missing)))

def prepared(paths, dataset, era, is_data, input_dir=None):
    sel = yaml.safe_load((REPO/'config'/era/'selections.yaml').read_text())
    syst = yaml.safe_load((REPO/'config'/era/'systematics.yaml').read_text())
    if is_data:
        seg = {}
    elif input_dir:
        reports = sorted(Path(input_dir).glob('report_*.json'))
        if not reports: raise SystemExit(f'No skim reports in {input_dir}')
        seg = get_segmentation_dict(reports)
        if not seg: raise SystemExit(f'No usable generator normalization in {input_dir}')
    else:
        seg = {'return true;':1.}
    node = prepare_rdf(rdf(paths),dataset_name=dataset,era=era,
        selections_cfg=sel,systematics_cfg=syst,is_data=is_data,seg_dict=seg,
        enable_dy012j=False,enable_dyptll=False,enable_dynjets=False,
        enable_custom_weights=False)['inclusive']
    return node.Filter('baseline_SS && mass_inclusive')

def sf(leg):
    prefix = f'weight_mu{leg}_'
    return (f'((mu{leg}_pt < 30) ? '
            f'{prefix}TightPFIso_TightID_Central * {prefix}TightID_Trk_Central : '
            f'{prefix}LoosePFIso_MediumID_Central * {prefix}MediumID_Trk_Central)')

def hist(df, name, weight):
    h = df.Histo1D((name, name, 18, 60., 150.), 'm_mumu', weight).GetValue().Clone()
    h.SetDirectory(0)
    return h

def shape_chi2(data, mc):
    total = mc.Integral()
    if total <= 0 or data.Integral() <= 0: return None
    scale = data.Integral() / total
    chi2 = 0.; bins = 0
    for i in range(1, data.GetNbinsX()+1):
        variance = data.GetBinError(i)**2 + (scale*mc.GetBinError(i))**2
        if variance > 0:
            chi2 += (data.GetBinContent(i)-scale*mc.GetBinContent(i))**2/variance
            bins += 1
    return {'chi2': chi2, 'bins': bins, 'mc_shape_scale': scale}

def plot_shapes(hists, output):
    data = hists['data']
    edges = np.array([data.GetBinLowEdge(i) for i in range(1,data.GetNbinsX()+2)])
    centers = (edges[:-1]+edges[1:])/2
    observed = np.array([data.GetBinContent(i) for i in range(1,data.GetNbinsX()+1)])
    errors = np.array([data.GetBinError(i) for i in range(1,data.GetNbinsX()+1)])
    fig,(top,bottom)=plt.subplots(2,1,sharex=True,figsize=(8,7),
                                  gridspec_kw={'height_ratios':[3,1]})
    top.errorbar(centers,observed,yerr=errors,fmt='ko',label='Data SS')
    if data.Integral() <= 0:
        top.text(.5,.5,'Nessun evento data SS nel campione',
                 transform=top.transAxes,ha='center',va='center')
    for key,label,color in [('all_sf','SF a tutti','tab:blue'),
                            ('genmatched_sf','SF solo genmatched','tab:orange'),
                            ('no_sf','Senza SF muoni','tab:green')]:
        h=hists[key]
        vals=np.array([h.GetBinContent(i) for i in range(1,h.GetNbinsX()+1)])
        if h.Integral() > 0 and data.Integral() > 0:
            vals *= data.Integral()/h.Integral()
        else: vals[:]=np.nan
        top.stairs(vals,edges,label=label,color=color)
        ratio=np.divide(vals,observed,out=np.full_like(vals,np.nan),where=observed>0)
        bottom.plot(centers,ratio,'o-',color=color,markersize=3)
    top.set_ylabel('Eventi / 5 GeV'); top.legend(); top.grid(alpha=.25)
    bottom.axhline(1,color='k',lw=1); bottom.set_ylabel('MC / dati')
    bottom.set_xlabel(r'$m_{\mu\mu}$ [GeV]'); bottom.grid(alpha=.25)
    fig.tight_layout(); fig.savefig(str(output)+'.png',dpi=160); plt.close(fig)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--era', default='Run3_2022', help='Run3 era (default: Run3_2022)')
    p.add_argument('--input-root', type=Path, default=DEFAULT_INPUT)
    p.add_argument('--backgrounds', default=DEFAULT_BACKGROUNDS,
                   help='Comma-separated background processes or datasets')
    p.add_argument('--signals', default=DEFAULT_SIGNALS,
                   help='Comma-separated signal processes or datasets; empty disables signals')
    p.add_argument('--data', action='append', help='Override: data ROOT glob; repeatable')
    p.add_argument('--mc', action='append', help='Override: MC ROOT glob; repeatable')
    p.add_argument('--output', help='Output prefix for ROOT and JSON')
    args = p.parse_args()
    ROOT.EnableImplicitMT()
    with progress('Scoperta ntuple e report'):
        if args.data or args.mc:
            if not (args.data and args.mc): raise SystemExit('--data and --mc must be given together')
            data_files = files(args.data)
            groups = {'explicit_mc':{'process':'explicit','files':files(args.mc),'input_dir':None}}
        else:
            try:
                data_files, groups = configured_samples(REPO,
                    args.era if args.era.startswith('Run3_') else 'Run3_'+args.era,
                    args.input_root,args.backgrounds,args.signals)
            except (ValueError, FileNotFoundError) as exc:
                raise SystemExit(str(exc)) from exc
    era = args.era if args.era.startswith('Run3_') else 'Run3_'+args.era
    print(f'[INPUT] {era}: {len(data_files)} file dati, {len(groups)} dataset MC, '
          f'{sum(len(info["files"]) for info in groups.values())} file MC',flush=True)
    out = Path(args.output or f'results/check_w_ss_{era}')
    out.parent.mkdir(parents=True, exist_ok=True)
    with progress(f'Dati SS ({len(data_files)} file)'):
        data = prepared(data_files,'Data_Muon',era,True)
        hists = {'data':hist(data,'data','weight__Central')}
    print(f'[DATA] {hists["data"].Integral():.0f} eventi nella regione SS',flush=True)
    mc_events = 0; matched_events = 0
    for index,(dataset, info) in enumerate(groups.items(),start=1):
      with progress(f'MC {index}/{len(groups)} {dataset} ({len(info["files"])} file)'):
        mc = prepared(info['files'],dataset,era,False,info['input_dir'])
        require(mc, ['mu1_GenMatched','mu2_GenMatched','weight__Central'])
    # Shape comparison: no cross-section normalization is needed. Genmatching
    # gates ID/iso SF per muon, while trigger SF still follows trigger matching.
        mc = mc.Define('sf1', sf(1)).Define('sf2', sf(2))
        require(mc, ['mu1_HasTriggerMatching_singleMu',
                 'weight_mu1_IsoMu24_CutBasedIdMedium_and_PFIsoMedium_Central'])
    # mu1 is the pT-leading muon in the skim, matching the nominal trigger
    # weight helper's choice of leg.
        mc = mc.Define('trg_sf',
                   '(mu1_HasTriggerMatching_singleMu ? '
                   'weight_mu1_IsoMu24_CutBasedIdMedium_and_PFIsoMedium_Central : 1.f)')
        mc = mc.Define('trg_sf_matched',
                   '(mu1_GenMatched ? trg_sf : 1.f)')
        mc = mc.Define('w_all', 'weight__Central')
        mc = mc.Define('w_matched', 'weight__Central / (mu1_GenMatched ? 1.f : sf1) / '
                   '(mu2_GenMatched ? 1.f : sf2) / '
                   '(mu1_GenMatched ? 1.f : trg_sf)')
        mc = mc.Define('w_no_sf', 'weight__Central / sf1 / sf2 / trg_sf')
        booked={name:mc.Histo1D((name+'_'+dataset,'',18,60.,150.),
                                 'm_mumu',column)
                for name,column in [('all_sf','w_all'),
                                    ('genmatched_sf','w_matched'),('no_sf','w_no_sf')]}
        count_action=mc.Count()
        matched_action=mc.Filter('mu1_GenMatched && mu2_GenMatched').Count()
        ROOT.RDF.RunGraphs([*booked.values(),count_action,matched_action])
        for name,action in booked.items():
            part=action.GetValue().Clone(name+'_'+dataset+'_copy')
            part.SetDirectory(0)
            if info.get('kind') == 'signal':
                hists[name+'__'+dataset] = part
            elif name in hists: hists[name].Add(part)
            else: hists[name] = part.Clone(name)
        count = int(count_action.GetValue())
        mc_events += count
        matched_events += int(matched_action.GetValue())
        print(f'[MC] {dataset}: {count} eventi SS; cumulativo {mc_events}',flush=True)
    with progress('Scrittura ROOT e plot'):
        f = ROOT.TFile(str(out)+'.root','RECREATE')
        for h in hists.values(): h.Write()
        f.Close()
        plot_shapes(hists,out)
    report = {'era':era,'data_files':data_files,
              'samples':{name:{'process':info['process'], 'kind':info.get('kind','background'),
                                   'n_files':len(info['files'])}
                             for name,info in groups.items()},
              'region':'same-sign analysis baseline, 60 < m_mumu < 150 GeV',
              'normalization':'prepare_rdf Central weight; MC shapes normalized separately to data for chi2',
              'data_events':hists['data'].Integral(), 'mc_events':mc_events,
              'mc_genmatched_fraction':matched_events/mc_events if mc_events else None,
              'scenarios':{key:{'sum_weights':h.Integral(), **(shape_chi2(hists['data'],h) or {})}
                           for key,h in hists.items() if key != 'data' and '__' not in key}}
    (out.parent/(out.name+'.json')).write_text(json.dumps(report,indent=2)+'\n')
    print(f'[OUTPUT] {out}.json, {out}.root, {out}.png',flush=True)
    print(json.dumps(report,indent=2))

if __name__ == '__main__': main()
