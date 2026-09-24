---
name: hmm-campaigns
description: >
  Map of the Hmm_newSkim production campaigns: which ones exist, the order
  they must run in, how to find out what is still missing, and the known
  blockers. Use when asked what still has to be produced, which campaign
  entry point to run, why a stage is blocked, or what is currently running.
---

# Campaigns: what runs, in what order, what is missing

Read `hmm-framework` first. `source env.sh` from the repository root.

## Check before assuming

Several agent sessions write to the same EOS trees at the same time. Counts
move between one command and the next; a production that had 533 files an hour
ago can have 131 now because someone is rebuilding it. **Never answer "what is
missing" from this file alone — run the checks.** Everything below the line
`## Snapshot` is dated and decays.

First question, always: is the chain already running?

```bash
ps -u "$USER" -o pid,etime,args --no-headers | grep -E "campaigns/|condorsubmit|hist_maker" | grep -v grep
condor_q -totals
condor_q -af JobBatchName JobStatus | sort | uniq -c | sort -rn | head
```

If `run3_post_skim_chain.sh` is alive, the campaigns are being driven already:
do not submit the same stage by hand, and do not kill it — it holds the
stage ordering and the Condor waits.

## The chain

One script drives everything after the skims:

```bash
nohup bash campaigns/run3_post_skim_chain.sh all > chain.log 2>&1 &
```

Five stages with real dependencies, each also callable alone to resume:

| Stage | Action | Produces | Depends on |
|---|---|---|---|
| 1 | `dy-weights` | `reweights/dy_{012j,ptll,njets}_reweight_skim_v4/<era>/*.json` | skims + manifests |
| 2 | `all-variables` | `post_dy/all_variables/` Central + 22 syst families | stage 1 |
| 3 | `dnn-vbf` | `post_dy/dnn_vbf_weighted/` 5 regions × VBF | stage 1 |
| 4 | `dnn-studies` | `results/skim_v4/dnn_{binning,performance}`, `sensitivity` | stage 3 |
| 5 | `flashsim` | `results/skim_v4/flashsim_comparison` | stage 2 |

Stage 1 is strictly ordered internally: jet-component → pT(ll) → N(jet). Each
sub-stage reads the JSON the previous one wrote, so it cannot be parallelised.
`run3_dy_weights_skim_v4.sh run` returns **3** when it has submitted and is
waiting for Condor; that is not an error, it means "call me again after the
jobs".

Defaults the chain uses (override with `V4_*` env vars):
`V4_INPUT=/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4_fixed`,
`V4_MANIFEST=/eos/user/v/vdamante/H_mumu/manifests_skim_v4`,
`V4_OUTPUT=/eos/user/v/vdamante/H_mumu/skim_v4/post_dy`,
`V4_ERAS=2022,2022EE,2023,2023BPix,2024,2025,2026`.

## Entry points

Upstream of the chain:

| Script | Produces |
|---|---|
| `campaigns/run3_skim_v4.sh {plan,dry-run,submit}` | the skims themselves; 2025/2026 also in the no-horn-veto variant |
| `campaigns/run3_dy_weights_skim_v4.sh {manifests,status,run}` | validation manifests, then the ordered DY fit |

Histogram campaigns, all sharing the `submit_campaign.sh` → `campaigns/workflow.py`
interface documented in `campaigns/README.md` (authoritative):

| Script | Produces |
|---|---|
| `campaigns/all_variables.sh` | every `store: true` region/category × maincfg variable |
| `campaigns/dnn_vbf_signal.sh` | DNN output, VBF, Signal Fit |
| `campaigns/dnn_vbf_z.sh` / `dnn_vbf_h.sh` | same in the Z / H sidebands |
| `campaigns/dy_weights.sh` | the DY derivation stages |
| `campaigns/jet_horn_veto.sh` | Data/DY with and without the horn veto |
| `campaigns/dnn_studies_skim_v4.sh` | binning-opt + DNN performance with/without weights |
| `campaigns/vbf_eta_regions.sh` | all variables, Central only, VBF split by jet eta into incl/CC/CF/FF |
| `campaigns/dnn_vbf_eta_regions.sh` | same split, DNN_NNOutput only, Central only |

Common actions: `paths`, `check --stage {histograms,hadded,merged-eras,merged-syst,merged,all}`,
`submit`, `local`, `hadd`, `merge-syst`, `merge-era`, `plot`, `finish`.
`--dry-run` prints the plan. Actions exit 1 on incomplete inputs.

## Finding what is missing

Per campaign, in increasing cost:

```bash
bash campaigns/dnn_studies_skim_v4.sh paths          # inputs, payloads, hadd per era
bash campaigns/all_variables.sh check --stage all --mode both --eras "$V4_ERAS" \
     --input-dir "$V4_INPUT" --manifest-root "$V4_MANIFEST" \
     --output-dir "$V4_OUTPUT/all_variables"
bash campaigns/run3_dy_weights_skim_v4.sh status --eras 2022,2022EE,2023,2023BPix,2024,2025,2026
```

DY payloads, which gate stages 2–4, resolved exactly as the framework resolves them:

```bash
for era in Run3_2022 Run3_2022EE Run3_2023 Run3_2023BPix Run3_2024 Run3_2025 Run3_2026; do
  python3 - "$era" <<'PY'
import sys, pathlib, yaml
era = sys.argv[1]
cfg = yaml.safe_load(open(f"config/{era}/process_names.yaml"))
for p in sorted({p for i in cfg.values() if isinstance(i, dict)
                 and isinstance(i.get("reweight_jsons"), dict)
                 for p in i["reweight_jsons"].values()}):
    print(era, "OK " if pathlib.Path(p).is_file() else "MISSING", p)
PY
done
```

Skim datasets that exist but hold no events (they break downstream tools, see below):

```bash
cd "$V4_INPUT" && for era in */; do for d in "$era"*/; do
  ls -l "$d"*.root 2>/dev/null | awk -v d="$d" '$5>10000{ok=1} END{if(!ok) print "EMPTY", d}'
done; done
```

## The two readings of "DNN performance with and without weights"

They are different studies and both are produced by
`campaigns/dnn_studies_skim_v4.sh`; do not substitute one for the other.

- `performance` → `compare_dnn_performance.py` on **histograms**: the weighted
  campaign against `dnn_vbf_dy_unweighted`. Measures what the DY reweighting
  does. Needs `Central_hadded` for **both** variants, so it needs Condor.
  Comparing them while one variant has no DY histograms measures the missing
  DY, not the weights.
- `roc` → `dnn_roc_from_skims.py` on the **skims**: weighted (`weight__Central`)
  against unit weight, both from one event loop. Needs no Condor, only the
  skims — and the DY payloads if the reweights are switched on. For an era
  without payloads, run it with `--dy-weights ''`.

Only AUC/ROC compares across the two curves: `S/sqrt(S+B)` on raw counts is not
a sensitivity, which is why the tool does not draw it.

## VBF split by jet eta (CC / CF / FF)

Two Central-only campaigns share the same split at `|eta| = 2.5` on the two
selected VBF jets:

- `campaigns/vbf_eta_regions.sh` — companion to `all_variables`: same datasets,
  every maincfg variable.
- `campaigns/dnn_vbf_eta_regions.sh` — `DNN_NNOutput` only. The DNN output is
  commented out of the maincfg variable lists, so it has to be asked for
  explicitly with `--variables`; that is why it is a separate campaign and not
  one more variable in the first.

The machinery is `--vbf-eta-regions` (alias `--eta-components`) in
`hist_maker.py`, backed by `vbf_eta_region_expressions` in
`common/jet_component_splitting.py`. The split lands as **nested
subdirectories**, not as extra top-level categories:

    Signal_Fit_VBF/incl/m_mumu
    Signal_Fit_VBF/CC/m_mumu      both VBF jets |eta| < 2.5
    Signal_Fit_VBF/CF/m_mumu      exactly one of the two central
    Signal_Fit_VBF/FF/m_mumu      neither central

Two things to know before using it:

- It is **mutually exclusive with `--pu-hard-jet-components`**. The branch at
  `hist_maker.py:1245` runs only `if args.vbf_eta_regions and not
  args.dy_jet_components`, and it **overwrites** `args.categories` with the four
  `VBF_eta_*` entries. So this campaign carries no DY jet-component splitting,
  and passing `--categories` to it has no effect.
- The campaign is Central only on purpose: it is a categorisation study, and the
  systematic families would multiply the cost for nothing.

## Traps

- **Empty skim datasets crash `dnn_roc_from_skims.py`.** A dataset whose ROOT
  files hold zero events has no weight branches, and `prepare_rdf` fails in RDF
  JIT with `use of undeclared identifier 'genWeight'`, killing the whole
  multi-era run. Known: `Run3_2022/ZZto2Nu2Q_powheg`,
  `Run3_2026/{DYto2E_M_50_amcatnloFXFX,ggZH_Hto2B_Zto2Q}`. Work around it with
  `--background-process` overrides until the tool skips empty inputs.
- **OOM on lxplus.** `read_dataset` pulls every selected event into numpy via
  `AsNumpy`; a full-era run reached 6.9 GB RSS and was OOM-killed. The user
  cgroup cap is `/sys/fs/cgroup/user.slice/user-<uid>.slice/memory.max`
  (~34 GB) and the node is shared with other tenants. Run one era per
  invocation, `--threads` ≤ 4, never two of these at once.
- **`skim_v4_fixed` is not a second production.** Its files are hardlinks to
  `skim_v4` (same inodes) except where the patch/unification pass replaced
  them, mostly in Run3_2024. Do not budget disk or re-skim time for it.
- **EOS delete permissions**: see the `eos-skim-v4-acl-pflanaga` memory —
  overwriting a file owned by another user fails with
  `Unable to remove file for truncation`.
- `submit-nondy` passes `--dy-weights ''`. That is not physics: the non-DY
  histograms are identical either way, it just lifts the global payload check
  so the submit is not blocked while the weights are being re-derived.
- Changing selections on an already-produced `--output-root` needs a new
  directory or `--force`; timestamps do not certify the options of an old run.

## Snapshot — 2026-09-15, verify before relying on it

`run3_post_skim_chain.sh all` has been running since ~15:35 and is at **stage 1**
(`dy_weights`, all seven eras), with ~5900 Run3_2025 skim jobs still queued from
`run3_skim_v4.sh submit --era 2025 --variant both`. So stages 2–5 have not
started for the eras they are missing.

| Era | skim | manifest | DY payload | all_variables | dnn_vbf_weighted | dnn_vbf_dy_unweighted |
|---|---|---|---|---|---|---|
| Run3_2022 | ✅ | ✅ | ✅ | Central | Central + hadd | Central, no DY |
| Run3_2022EE | ✅ | ✅ | ✅ | Central | Central | Central, no DY |
| Run3_2023 | ✅ | ✅ | ✅ | Central | Central + hadd | Central, no DY |
| Run3_2023BPix | ✅ | ✅ | ✅ | Central | Central + hadd | Central, no DY |
| Run3_2024 | ✅ | ❌ | ❌ | ❌ nothing | ❌ | ❌ |
| Run3_2025 | ✅ | ✅ | ✅ | Central | Central | Central, no DY |
| Run3_2026 | ✅ | ✅ | ❌ | Central | 1 file | ❌ |

Missing, in the order that unblocks the most:

1. DY payloads for **Run3_2024 and Run3_2026** — gate stages 2–4 for those eras.
   Run3_2024 also has no validation manifest yet.
2. **DY histograms in both DNN variants, every era.** `dnn_vbf_dy_unweighted`
   has none at all, so the histogram-based with/without-weights comparison
   cannot be produced yet.
3. **`all_variables` for Run3_2024** — the other six eras have Central plus all
   22 systematic families; 2024 has nothing.
4. `hadd` / `merge-syst` / `merge-era` for every production: only
   `dnn_vbf_weighted` has `Central_hadded`, and only for 2022/2023/2023BPix.
5. Stage 4 studies and stage 5 FlashSim comparison, which follow from the above.
6. Combine fits (`combine/run_sr_fit.sh`, `combine/run_sr_zcr_fit.sh`) run after
   the `merged-syst` check of the Signal and Z campaigns.
