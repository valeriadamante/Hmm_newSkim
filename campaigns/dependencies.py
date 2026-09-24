#!/usr/bin/env python3
"""Stato delle dipendenze delle campagne skim_v4, stadio per stadio.

Ogni stadio dipende da quello prima: se uno non e' soddisfatto, i successivi
non si possono nemmeno tentare.  Questo script valuta ogni dipendenza con le
STESSE funzioni che usa campaigns/workflow.py per decidere cosa e' completo,
quindi non puo' divergere dai check delle campagne.

    python3 campaigns/dependencies.py
    python3 campaigns/dependencies.py --eras 2024,2025 --detail
    python3 campaigns/dependencies.py --campaign all_variables --next

La catena valutata, in ordine:

    skim -> manifest -> payload DY -> istogrammi Central -> istogrammi syst
         -> hadd Central -> hadd syst -> merge-syst -> merge-era -> plot

I DY sono l'unico punto in cui la catena si biforca: i loro payload servono
solo ai dataset DY, e tutto il resto si produce anche senza.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / 'campaigns'))
os.chdir(REPO)
# workflow.py legge sys.argv all'import: va nascosto e poi rimesso, altrimenti
# argparse qui sotto non vede piu' le opzioni e ogni flag viene ignorato.
_ARGV = list(sys.argv)
sys.argv = [sys.argv[0]]
import workflow as W              # noqa: E402
sys.argv = _ARGV

ERAS = ['2022', '2022EE', '2023', '2023BPix', '2024', '2025', '2026']

SKIM = Path(os.environ.get('V4_INPUT',
            '/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4'))
MANIFESTS = Path(os.environ.get('V4_MANIFEST',
                 '/eos/user/v/vdamante/H_mumu/manifests_skim_v4'))
POST_DY = Path(os.environ.get('V4_OUTPUT',
               '/eos/user/v/vdamante/H_mumu/skim_v4/post_dy'))

DNN_REGIONS = ['Z_sideband', 'Signal_Fit', 'H_sideband', 'Signal_ext', 'mass_inclusive']

CAMPAIGNS = {
    'all_variables': dict(
        config='config/campaigns/all_variables.sh', root=POST_DY / 'all_variables',
        regions=None, categories=None, syst=True),
    'dnn_vbf_weighted': dict(
        config='config/campaigns/dnn_vbf_signal_sep03.sh', root=POST_DY / 'dnn_vbf_weighted',
        regions=DNN_REGIONS, categories=['VBF'], syst=True),
    'dnn_vbf_dy_unweighted': dict(
        config='config/campaigns/dnn_vbf_signal_sep03.sh', root=POST_DY / 'dnn_vbf_dy_unweighted',
        regions=DNN_REGIONS, categories=['VBF'], syst=False),
    # VBF divisa per eta dei jet in incl/CC/CF/FF, solo Central.
    'vbf_eta_regions': dict(
        config='config/campaigns/vbf_eta_regions.sh', root=POST_DY / 'vbf_eta_regions',
        regions=None, categories=None, syst=False),
    'dnn_vbf_eta_regions': dict(
        config='config/campaigns/dnn_vbf_eta_regions.sh', root=POST_DY / 'dnn_vbf_eta_regions',
        regions=None, categories=None, syst=False),
}

# Pseudo-ere richieste per merge-era.
COMBOS = {'Run3_2022_2023': ['2022', '2023'],
          'Run3_2022_2025': ['2022', '2025'],
          'Run3_2022_2026': ['2022', '2026']}

PLOTS = Path(os.environ.get('V4_PLOTS', 'plots_Sep16'))
STUDIES = PLOTS / 'studies'

# Il DNN del 2026 non va prodotto: escluderlo qui evita di segnalarlo
# all'infinito come "da fare".
STUDY_ERAS = ['2022', '2022EE', '2023', '2023BPix', '2024', '2025']


def load(name):
    spec = CAMPAIGNS[name]
    c = W.load_campaign(spec['config'])
    # Stessa espansione che fa make_campaign con --jes regrouped, che e' il default.
    c.families = [p for f in c.families
                  for p in (W.JES_REGROUPED if f == 'JES_Total' else [f])]
    c = dataclasses.replace(c, root=spec['root'])
    if spec['regions']:
        c = dataclasses.replace(c, regions=spec['regions'])
    if spec['categories']:
        c = dataclasses.replace(c, categories=spec['categories'])
    return c, spec


def count(products):
    """(presenti, attesi) su un dizionario prodotto->input di workflow.py."""
    have = sum(1 for p in products if p.is_file() and p.stat().st_size > 0)
    return have, len(products)


def stale(products):
    """Prodotti piu' vecchi di un loro input: il check li rifiuta come STALE."""
    bad = []
    for path, inputs in products.items():
        if not path.is_file() or not inputs:
            continue
        try:
            newest = max(x.stat().st_mtime_ns for x in inputs if x.is_file())
        except ValueError:
            continue
        if path.stat().st_mtime_ns < newest:
            bad.append(path)
    return bad


def payload_state(era):
    """I tre stadi di reweight DY, nell'ordine in cui vanno derivati."""
    out = {}
    for stage, folder in (('012j', 'dy_012j_reweight_skim_v4'),
                          ('ptll', 'dy_ptll_reweight_skim_v4'),
                          ('njets', 'dy_njets_reweight_skim_v4')):
        d = REPO / 'reweights' / folder / f'Run3_{era}'
        out[stage] = d.is_dir() and any(d.glob('*.json'))
    return out


def evaluate(name, era, detail=False):
    """Uno stadio per riga: (etichetta, stato, nota)."""
    c, spec = load(name)
    rows = []

    skim_dir = SKIM / f'Run3_{era}'
    n_skim = len(list(skim_dir.iterdir())) if skim_dir.is_dir() else 0
    rows.append(('skim', n_skim > 0, f'{n_skim} dataset'))

    man = MANIFESTS / f'Run3_{era}'
    n_man = len(list(man.glob('*.json'))) if man.is_dir() else 0
    rows.append(('manifest', n_man > 0, f'{n_man} manifest'))

    pay = payload_state(era)
    rows.append(('payload DY', all(pay.values()),
                 ' '.join(f'{k}={"ok" if v else "--"}' for k, v in pay.items())))

    try:
        central = W.raw_products(c, era, 'Central')
    except Exception as exc:
        rows.append(('hist Central', False, f'errore: {exc}'))
        return rows
    have, exp = count(central)
    st = stale(central)
    note = f'{have}/{exp}' + (f', {len(st)} STALE' if st else '')
    rows.append(('hist Central', have == exp and not st, note))

    if spec['syst']:
        done = []
        partial = []
        for fam in c.families:
            h, e = count(W.raw_products(c, era, fam))
            (done if h == e else partial).append((fam, h, e))
        note = f'{len(done)}/{len(c.families)} famiglie complete'
        if detail and partial:
            note += ' | mancano: ' + ', '.join(f'{f}({e-h})' for f, h, e in partial[:6])
            if len(partial) > 6:
                note += f' +{len(partial)-6}'
        rows.append(('hist syst', len(done) == len(c.families), note))

    try:
        hc = W.hadded_products(c, era, 'Central')
        have, exp = count(hc)
        st = stale(hc)
        note = f'{have}/{exp}' + (f', {len(st)} STALE' if st else '')
        rows.append(('hadd Central', have == exp and not st, note))
    except Exception as exc:
        rows.append(('hadd Central', False, str(exc)[:50]))

    if spec['syst']:
        ok = 0
        for fam in c.families:
            try:
                h, e = count(W.hadded_products(c, era, fam))
            except Exception:
                h, e = 0, 1
            ok += (h == e)
        rows.append(('hadd syst', ok == len(c.families),
                     f'{ok}/{len(c.families)} famiglie'))

        merged = c.root / 'Hists_systMerged' / f'Run3_{era}'
        n = len(list(merged.glob('*.root'))) if merged.is_dir() else 0
        rows.append(('merge-syst', n > 0, f'{n} file' if n else 'assente'))

    return rows


BLOCKS = {
    'hist Central': 'payload DY',
    'hist syst': 'payload DY',
    'hadd Central': 'hist Central',
    'hadd syst': 'hist syst',
    'merge-syst': 'hadd syst',
}


def first_blocker(rows):
    state = {label: ok for label, ok, _ in rows}
    for label, ok, _ in rows:
        if not ok:
            dep = BLOCKS.get(label)
            if dep and not state.get(dep, True):
                continue          # il vero blocco e' piu' a monte
            return label
    return None


def flashsim_eras():
    """Ere che hanno davvero coppie FlashSim/FullSim dichiarate in configurazione."""
    sys.path.insert(0, str(REPO / 'tools'))
    try:
        import compare_flashsim as CF
    except Exception:
        return {}
    import contextlib, io
    out = {}
    for era in ERAS:
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                pairs = CF.flashsim_pairs(f'Run3_{era}', dict(CF.EXTRA_PAIRS))
        except Exception:
            pairs = []
        out[era] = pairs
    return out


def studies_report():
    """Studi e confronti: cosa serve a ciascuno e se il risultato c'e' gia'."""
    c_w, _ = load('dnn_vbf_weighted')
    c_u, _ = load('dnn_vbf_dy_unweighted')
    c_a, _ = load('all_variables')
    flash = flashsim_eras()
    rows = []

    for era in STUDY_ERAS:
        hadd_w = (c_w.root / 'Central_hadded' / f'Run3_{era}').is_dir()
        hadd_u = (c_u.root / 'Central_hadded' / f'Run3_{era}').is_dir()
        hadd_a = (c_a.root / 'Central_hadded' / f'Run3_{era}').is_dir()
        pay = all(payload_state(era).values())
        skim = (SKIM / f'Run3_{era}').is_dir()

        rows.append(('binning weighted', era, hadd_w,
                     'hadd Central di dnn_vbf_weighted',
                     (STUDIES / 'dnn_binning' / 'weighted' / f'Run3_{era}.json').is_file()))
        rows.append(('binning dy_unweighted', era, hadd_u,
                     'hadd Central di dnn_vbf_dy_unweighted',
                     (STUDIES / 'dnn_binning' / 'dy_unweighted' / f'Run3_{era}.json').is_file()))
        rows.append(('sensitivity', era, hadd_w,
                     'hadd Central di dnn_vbf_weighted',
                     (STUDIES / 'sensitivity' / f'Run3_{era}_powheg.root').is_file()))
        rows.append(('performance con/senza pesi', era, hadd_w and hadd_u,
                     'hadd Central di ENTRAMBE le varianti DNN',
                     (STUDIES / 'dnn_performance' / 'dy_weights_weighted' / f'Run3_{era}.json').is_file()))
        rows.append(('BSC chi2', era, skim, 'solo gli skim',
                     (STUDIES / 'bsc_chi2' / f'Run3_{era}.json').is_file()))
        rows.append(('muon SF genmatching', era, skim, 'solo gli skim',
                     (STUDIES / 'muon_sf_genmatching' / f'Run3_{era}.json').is_file()))
        # Le coppie sono dichiarate in process_names.yaml anche dove i campioni
        # FlashSim non esistono: 2022-2023BPix le hanno in configurazione ma non
        # su disco, e il tool girerebbe producendo zero confronti. Conta solo le
        # coppie i cui due file sono davvero nell'hadd.
        era_dir = c_a.root / 'Central_hadded' / f'Run3_{era}'
        usable = [1 for flash_p, full_p in flash.get(era, [])
                  if (era_dir / f'{flash_p}.root').is_file() and (era_dir / f'{full_p}.root').is_file()]
        rows.append(('FlashSim', era, bool(usable),
                     f'{len(usable)} coppie con entrambi i file' if usable
                     else 'nessun campione FlashSim su disco per questa era',
                     (PLOTS / 'flashsim_comparison' / f'Run3_{era}' / 'index.json').is_file()))

    # La ROC e' una sola invocazione multi-era: dipende dagli skim e dai payload.
    ready = all((SKIM / f'Run3_{e}').is_dir() and all(payload_state(e).values())
                for e in STUDY_ERAS)
    rows.append(('ROC (tutte insieme)', f'{len(STUDY_ERAS)} ere', ready,
                 'skim + payload DY, nessun hadd',
                 (STUDIES / 'dnn_performance' / 'roc_from_skims' / 'weighted' / 'all_eras.json').is_file()))
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--eras', default=','.join(ERAS))
    p.add_argument('--campaign', action='append', choices=list(CAMPAIGNS),
                   help='Ripetibile; default: tutte.')
    p.add_argument('--detail', action='store_true',
                   help='Elenca le famiglie sistematiche incomplete.')
    p.add_argument('--next', action='store_true',
                   help='Solo la prossima azione utile per ogni era.')
    args = p.parse_args()

    eras = [e.strip() for e in args.eras.split(',') if e.strip()]
    names = args.campaign or list(CAMPAIGNS)

    todo = []
    for name in names:
        print(f'\n{"="*78}\n{name}\n{"="*78}')
        for era in eras:
            rows = evaluate(name, era, args.detail)
            blocker = first_blocker(rows)
            if args.next:
                nxt = blocker or 'tutto soddisfatto: plot e studi'
                print(f'  Run3_{era:<10} -> {nxt}')
                continue
            print(f'\n  Run3_{era}')
            for label, ok, note in rows:
                mark = 'OK  ' if ok else 'MANCA'
                print(f'    {mark:<6} {label:<14} {note}')
            if blocker:
                print(f'    --> prossima azione: {blocker}')
                todo.append((name, era, blocker))
            else:
                print('    --> pronto per plot, merge-era e studi')

    if not args.next and todo:
        print(f'\n{"="*78}\nda fare, nell\'ordine\n{"="*78}')
        for name, era, blocker in todo:
            print(f'  {name:<24} Run3_{era:<10} {blocker}')

    print(f'\n{"="*78}\nstudi e confronti\n{"="*78}')
    print(f'  {"studio":<28}{"era":<16}{"stato":<12}{"prodotto":<10}dipende da')
    for study, era, ready, dep, done in studies_report():
        state = 'pronto' if ready else 'bloccato'
        print(f'  {study:<28}{era:<16}{state:<12}{"si" if done else "no":<10}{dep}')

    # merge-era: dipende dall'hadd Central di entrambe le ere della coppia.
    if not args.next:
        print(f'\n{"="*78}\nmerge-era\n{"="*78}')
        c, _ = load('all_variables')
        for pseudo, pair in COMBOS.items():
            ready = []
            for era in pair:
                try:
                    h, e = count(W.hadded_products(c, era, 'Central'))
                except Exception:
                    h, e = 0, 1
                ready.append(h == e)
            done = (c.root / 'Central_hadded' / pseudo).is_dir()
            state = 'gia\' fatto' if done else ('pronto' if all(ready) else 'bloccato')
            miss = [f'Run3_{e}' for e, r in zip(pair, ready) if not r]
            print(f'  {pseudo:<18} {state:<12}' + (f' manca hadd Central di {", ".join(miss)}' if miss else ''))


if __name__ == '__main__':
    main()
