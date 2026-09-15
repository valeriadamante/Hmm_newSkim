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

Muon details include raw/noCorr and corrected + FSR pT, charge, ID/isolation,
trigger matching and gen matching. Jet details include all jets and the indices
of selected jets, correction input pT, true raw pT, corrected pT, eta/phi,
horn/veto-map/selection flags. `Jet_pt_nocorr` is the NanoAOD pT before our
reapplication of JEC; true raw pT is explicitly stored as
`Sync_Jet_pt_raw = Jet_pt_nocorr * (1 - Jet_rawFactor)`.

Compare the event lists before comparing distributions:

```bash
python3 sync/python/compare_sync_events.py \
  ours/H_sideband_event_ids.txt theirs/H_sideband_event_ids.txt \
  --output comparison.json
```

Exit status is 0 only for identical event multisets. Differences and duplicate
counts are reported; no event deduplication is performed. Event IDs remain
integers throughout JSON export, including values above 2**53.
