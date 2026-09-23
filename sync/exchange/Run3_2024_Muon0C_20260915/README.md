# H→μμ data synchronisation — Muon0 Run2024C, 15 Sep 2026

Event list from one NanoAOD file, produced with the skim_v4 selection and
corrections.

## Input

| | |
|---|---|
| Dataset | `/Muon0/Run2024C-MINIv6NANOv15-v1/NANOAOD` |
| File | `/store/data/Run2024C/Muon0/NANOAOD/MINIv6NANOv15-v1/2530000/677e3bb0-8199-4ffb-83af-165410a7b7a6.root` |
| Entries in file | 1 354 629 |
| Events in the list | **292** (175 in 110–115, 117 in 135–150) |
| Duplicate event IDs | 0 |

## Selection

Sideband definition (your first option):

```
(110 < m_mumu < 115) || (135 < m_mumu < 150)
```

Boundaries are **strict** (`>` and `<`), so an event exactly at 110, 115, 135 or
150 GeV would be rejected. The observed range is 110.013–149.277 GeV, so no
event in this file sits close enough to a boundary for the convention to matter.

The mass is evaluated on the corrected, FSR-recovered muons (see below), which
is what makes the window definition depend on the corrections.

Object selection, applied in this order (counts from `cutflow.json`):

| Step | Events |
|---|---|
| Initial | 1 354 629 |
| Golden JSON | 1 354 629 |
| MET filters | 1 344 500 |
| `HLT_IsoMu24` + trigger matching | 573 326 |
| Exactly 2 selected muons | 46 011 |
| Dimuon trigger matching | 45 861 |
| Dimuon mass window (skim-level) | 40 808 |
| No extra electrons | 40 793 |
| Analysis `baseline` | 36 277 |
| Sideband | **292** |

`baseline` is, in our configuration language:

```
muons_OS_presel_trg && mu_pt_sel && SelectedJetTagSel   (= base_sel)
&& mu1_ML && mu2_ML && pt_lessthan30_and_TT
```

which unpacks to:

- two opposite-sign muons with raw pT > 10 GeV and |η| < 2.4;
- leading muon pT > 26 GeV, subleading pT > 20 GeV (**corrected** pT);
- `HLT_IsoMu24` fired, and at least one of the two muons with pT > 26 GeV
  matched to the trigger object;
- both muons: `mediumId` and `pfIsoId >= 2` (loose PF isolation);
- a muon below 30 GeV must additionally satisfy tight ID and tight isolation;
- b-tag veto on the selected jets (`SelectedJetTagSel`);
- no additional electrons.

## Corrections

- **Muon pT**: beam-spot constrained pT (`Muon_bsConstrainedPt`) with the
  scale-and-resolution correction applied on top, then FSR photon recovery.
  The exported `mu1_pt`/`mu2_pt` are the final values, after all three.
  In this file FSR recovery changes the muon kinematics in 4 events out of 292.
  The intermediate stages are in the JSONL as `mu{1,2}_pt_raw_noCorr` (NanoAOD),
  `mu{1,2}_pt_raw_corr` (BSC + scale/resolution) and `mu{1,2}_pt_FSR_corr`.
- **Dimuon variables** (`dimuon_pt/eta/phi/mass`) are built from the corrected,
  FSR-recovered muon four-vectors.
- **Jets**: JEC reapplied from the true raw pT, jet ID, veto map, pileup-jet
  rejection and the horn veto. The JSONL keeps, per jet, `Jet_pt_nocorr`
  (NanoAOD pT before our reapplication), `Sync_Jet_pt_raw`
  (`= Jet_pt_nocorr * (1 - Jet_rawFactor)`), the corrected `Jet_pt`, and the
  `Jet_vetoMap` / `Jet_IsInsideHorn` / `Jet_preSel` / `goodJet` flags, plus
  `SelectedJet_idx`. That should let you localise any jet disagreement without
  another production round.

## Files

| File | Content |
|---|---|
| `H_sideband_event_list.txt` | the agreed column order |
| `H_sideband_event_list_extended.txt` | the same, plus the high-level ggH/VBF training inputs |
| `H_sideband_event_ids.txt` | `run:lumi:event`, sorted — the quickest first comparison |
| `H_sideband_events.jsonl` | one JSON object per event with every muon and **every** jet, including the rejected ones and their flags |
| `summary.json`, `cutflow.json` | exact input, region definition, counts, cutflow |

### Column format

```
event:run:lumi:mu1_pt:mu1_eta:mu1_phi:mu2_pt:mu2_eta:mu2_phi:
dimuon_pt:dimuon_eta:dimuon_phi:dimuon_mass:njets:
jet1_pt:jet1_eta:jet1_phi:jet1_mass:jet2_pt:jet2_eta:jet2_phi:jet2_mass
```

(one line per event, no wrapping; the first line of the file is this header).

Conventions:

- all floating-point values to **three decimals**; `event`, `run`, `lumi` and
  `njets` are integers;
- **999.000** wherever a jet does not exist — all four jet-2 columns for a
  one-jet event, all eight for a zero-jet event;
- `mu1` is the higher-pT muon **after** corrections, `mu2` the lower-pT one.
  The ordering is applied after the corrections, so it can in principle differ
  from the ordering on uncorrected pT;
- `njets` counts the selected jets, and `jet1`/`jet2` are the two
  highest-pT selected jets, ordered by corrected pT. Note these are **not**
  necessarily the two VBF-tagged jets; the VBF pair is in the extended list as
  `vbfjet1_*`/`vbfjet2_*`;
- jet multiplicities in this file: 192 events with 0 jets, 71 with 1, 18 with 2,
  7 with 3, 3 with 4, 1 with 6.

The extended list appends, in the order of our DNN input configuration:

```
dR_mumu, y_mumu, cosTheta_CS, phi_CS, R_pt, minDeltaEtaSigned, minDeltaPhi,
Zeppenfeld_Var, pt_centrality, vbfjet1_pt, vbfjet1_eta, vbfjet1_y,
vbfjet1_btagPNetQvG, vbfjet2_pt, vbfjet2_eta, vbfjet2_y, vbfjet2_btagPNetQvG,
m_jj, delta_eta_jj, pt_vbfj1j2, SoftJetCleanedActivity_N,
SoftJetCleanedActivity_ptSum
```

The VBF-only quantities are set to −10000 by construction when the event has no
VBF jet pair; they are left at that value rather than replaced by 999, so the
two conventions stay distinguishable.

## Notes and suggestions

A few things worth agreeing on explicitly before comparing, because they are the
usual sources of spurious disagreement:

1. **Event IDs exceed 2^53.** Please read `event` as a 64-bit integer. Parsing
   the list with anything that goes through a double (some CSV/JSON readers do)
   silently corrupts the last digits and makes the event sets look disjoint.
2. **Compare the ID list first**, then the kinematics. If the ID sets already
   differ there is little point in looking at pT differences.
3. **Muon ordering after corrections** — worth confirming you also sort after
   applying them.
4. **jet1/jet2 = leading selected jets, not the VBF pair.** If you order by the
   VBF tagging instead, the jet columns will differ on multi-jet events even
   with identical objects. Both are in the extended list.
5. **Rounding at the window edges.** A value printed as 115.000 may be below or
   above 115 before rounding. It does not bite in this file, but it would in a
   wider sample.
6. **The wider sideband is probably the better test.** Your second option
   (70 < m_μμ < 200 excluding 115–135) gives far more events from the same
   file, so a small inefficiency shows up as a real discrepancy instead of
   hiding in 292 events. We can produce it on request — it is one extra region
   definition, same production.
7. **For the MC synchronisation**, we can add `genWeight`, the pileup weight and
   the per-muon ID/ISO scale factors as extra columns; the exporter already has
   the switch. We would need to agree on the exact MC file, and on whether the
   weights are the raw per-event values or already normalised.
8. Happy to exchange next week, no rush on our side.

## Reproducing

```bash
source env.sh
python3 sync/python/run_sync_skim.py --run --era Run3_2024 \
  --dataset Muon0_Run2024C \
  --input-file /eos/cms//store/data/Run2024C/Muon0/NANOAOD/MINIv6NANOv15-v1/2530000/677e3bb0-8199-4ffb-83af-165410a7b7a6.root
python3 sync/python/export_event_list.py <out>/H_sideband_events.jsonl \
  --output <out>/H_sideband_event_list.txt
```

Comparison helper, once both lists exist:

```bash
python3 sync/python/compare_sync_events.py \
  ours/H_sideband_event_ids.txt theirs/H_sideband_event_ids.txt \
  --output comparison.json
```
