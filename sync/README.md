# skim_v4_sync

One exact NanoAOD input file per run, using the current skim corrections and
nominal analysis selection. The default is Muon0 Run2024C MINIv6NANOv15-v1,
first file in `config/Run3_2024/samples_withfiles.yaml`. Agree on that exact
input file with the other analysis before comparing counts.

```bash
source env.sh
# Print the input, output and command without running:
python3 sync/python/run_sync_skim.py
# Process the complete file and write to the production EOS area:
python3 sync/python/run_sync_skim.py --run
# Use an agreed file or an MC sample instead:
python3 sync/python/run_sync_skim.py --run --era Run3_2024 \
  --dataset DATASET_KEY --input-file /path/to/exact/nanoaod.root
```

Default output root:
`/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4_sync`.
Subdirectories are `ERA/DATASET/INPUT_FILE_STEM/CATEGORY`.
Use `--output-dir` to change the root. Existing output directories are refused
so an earlier comparison cannot be silently overwritten. `--n-events N`
creates a distinct `test_N` subdirectory; omit it for an exact full-file comparison.

The default category is `baseline`; `--category VBF` and `--category ggF` are
also available. Definitions are read from the era's `selections.yaml`.
OS remains a flag in the general skim; the sync `baseline` requires OS through
its normal analysis definition. Trigger matching, muon 26/20 GeV cuts, muon ID,
isolation and b-tag veto therefore follow the current analysis selection.
Data output contains only `H_sideband`: 110 < m_mumu < 115 or
135 < m_mumu < 150 GeV. MC also includes `Signal_Fit`: 115 < m_mumu < 135 GeV.
The strict boundaries are inherited from the YAML. Systematic variations are
disabled for sync. MC retains the normal skim's sample/era splitting and weights;
synchronization counts and distributions are unweighted.

Each run writes:

- `events.root`: the selected sync events and skim branches, plus raw jet pT.
- `H_sideband_events.jsonl`: sorted per-event muon and jet details.
- `H_sideband_event_ids.txt`: sorted `run:luminosityBlock:event` identifiers.
- Corresponding `Signal_Fit_*` files for MC only.
- `summary.json`: exact input, region definitions, counts and duplicate IDs.
- `cutflow.json`: the skim and sync selection counts.
- `distributions.root`: unweighted mass, muon pT/eta, jet multiplicity and
  selected-jet pT/eta histograms, separated by region. Jet histograms include
  every selected jet, so their entries count jets rather than events.
- `manifest.json`, `configuration/` and `production.log`: input dataset,
  command, source/configuration hashes, configuration copies and correction log.

Besides the objects, the export also carries the dimuon variables and the
high-level ggH/VBF training inputs (`pt_mumu`, `eta_mumu`, `phi_mumu`, `y_mumu`,
`dR_mumu`, `cosTheta_CS`, `phi_CS`, `R_pt`, `minDeltaEtaSigned`, `minDeltaPhi`,
`Zeppenfeld_Var`, `pt_centrality`, `m_jj`, `m_jj_ls`, `delta_eta_jj`,
`delta_eta_jj_ls`, `pt_vbfj1j2`, `era_code` and the soft-activity counts), so a
disagreement can be traced to the DNN inputs and not only to the objects.

Muon details include raw/noCorr and corrected + FSR pT, charge, ID/isolation,
trigger matching and gen matching. Jet details include all jets and the indices
of selected jets, correction input pT, true raw pT, corrected pT, eta/phi,
horn/veto-map/selection flags. `Jet_pt_nocorr` is the NanoAOD pT before our
reapplication of JEC; true raw pT is explicitly stored as
`Sync_Jet_pt_raw = Jet_pt_nocorr * (1 - Jet_rawFactor)`.

Write the event list in the column order agreed with the other analysis:

```bash
python3 sync/python/export_event_list.py ours/H_sideband_events.jsonl \
  --output ours/H_sideband_event_list.txt
```

`--precision N` sets the number of decimals, `--missing STR` the placeholder for
absent values, `--extra` adds the supplementary columns, `--mc-weights` the MC
weights, and `--no-header` drops the header line.

Compare the event lists before comparing distributions:

```bash
python3 sync/python/compare_sync_events.py \
  ours/H_sideband_event_ids.txt theirs/H_sideband_event_ids.txt \
  --output comparison.json
```

Exit status is 0 only for identical event multisets. Differences and duplicate
counts are reported; no event deduplication is performed. Event IDs remain
integers throughout JSON export, including values above 2**53.

## Compact sync tuple and VBF cutflow

`studies/prepare_tuple_forSync.py` re-reads an existing skim and writes the
compact sync tuple plus its cutflow. The selections come from
`config/Run3_2024/selections_sync.yaml`; `--cutflow-key` chooses which
cumulative step list in that file drives the cutflow, `--selection` the filter
applied to the output tuple.

```bash
source env.sh
SKIM=/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4/Run3_2024
python3 studies/prepare_tuple_forSync.py $SKIM/Muon0_Run2024H $SKIM/Muon1_Run2024H \
  -o /eos/user/v/vdamante/H_mumu/Sync/sync_tuple_Run2024H_VBF_Z_CR_H_SB.root \
  --selection "VBF && Z_CR_H_SB" --cutflow-key cutflow_vbf_Z_CR_H_SB --threads 12
```

The steps before `muon_pre_sel_check` are the skim `report_*.json` counts, so
the cutflow starts from the NanoAOD events before any cut. `cutflow_vbf_Z_CR_H_SB`
splits `HasVBF` into `vbf_jets_ge2`, `vbf_pair_pt`, `vbf_pair_mjj` and
`vbf_pair_deta` in the order `FindVBFJets` applies them; `vbf_pair_deta` must
reproduce `VBF_def` exactly. Steps that the skim already enforces stay in the
list on purpose and show zero rejected events.

`cutflow_vbf_Z_CR_H_SB_mu2_20` and the `VBF_mu2_20` category repeat the same
chain with the subleading muon at 20 GeV instead of 26. `VBF_mu2_20` is not
stored, so the tuple keeps the nominal column set:

```bash
python3 studies/prepare_tuple_forSync.py $SKIM/Muon0_Run2024H $SKIM/Muon1_Run2024H \
  -o /eos/user/v/vdamante/H_mumu/Sync/sync_tuple_Run2024H_VBF_Z_CR_H_SB_mu2pt20.root \
  --selection "VBF_mu2_20 && Z_CR_H_SB" \
  --cutflow-key cutflow_vbf_Z_CR_H_SB_mu2_20 --threads 12
```

`studies/compare_cutflow_pisa.py` reconciles our VBF cutflow with the Pisa one.
It runs on our skim only and takes their numbers from the table hard-coded in
the file; it writes our cutflow in their step order, the same cutflow with
their jet and muon definitions, and a bridge that switches the definition
differences on one at a time.
