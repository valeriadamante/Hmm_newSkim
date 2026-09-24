# VBF cut-based optimization

This study scans lower cuts on:

- maximum-mass dijet pair \(m_{jj}\);
- \(|\Delta\eta_{jj}|\);
- leading and subleading jet \(p_T\);
- dijet \(p_T\).

The default figure of merit is \(S/\sqrt{B}\), with VBF+ggH as signal and
DY+EWK as background. Samples and scan points are configured in `config.yaml`.

The primary output follows the cut-based reference layout: three
\(S/\sqrt{B}\) maps in the \(m_{jj}^{cut}\)-\(|\Delta\eta_{jj}|^{cut}\)
plane for:

- \(N_j\ge2\);
- \(N_j>2\);
- \(N_j=2\).

The default non-topological thresholds used in these maps are
\(p_T^{j1}>35\) GeV, \(p_T^{j2}>25\) GeV and \(p_T^{jj}>0\) GeV.
The displayed \(m_{jj}\) axis reaches 1000 GeV in 100 GeV steps, while
\(|\Delta\eta_{jj}|\) reaches 8 in steps of 0.5.
The maps print \(S/\sqrt B\) in each statistically valid cell. Grey cells are
points where the expected background does not exceed `--min-background`; they
are deliberately excluded from the optimization rather than assigned a
physical significance of zero.

The study also separates two questions that otherwise become entangled:

1. how the dijet pair is selected;
2. which observables are actually useful as cuts.

The compared pair assignments are maximum \(m_{jj}\), the two highest-\(p_T\)
jets, maximum \(|\Delta\eta_{jj}|\), maximum \(p_T^{jj}\), and highest-\(p_T\)
pair after fixed topological requirements. For each assignment the code
optimizes the configured two-variable combinations while keeping the other cuts
at the common loose baseline in `comparison_baseline_cuts`.

The dijet pair is rebuilt without the existing `HasVBF` requirement. This is
necessary because `HasVBF` already contains the fixed cuts
\(m_{jj}\ge400\) GeV and \(|\Delta\eta_{jj}|\ge2.5\).

## Run

From the repository directory:

```bash
source env.sh
python3 studies/vbf_cut_optimization/optimize_vbf_cuts.py \
  --era Run3_2024 \
  --input-base /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v1_noUnc/Run3_2024 \
  --output studies/vbf_cut_optimization/output_Run3_2024 \
  --skip-file-validation
```

Use the corresponding skim directory for another year, for example
`--era Run3_2022 --input-base .../Run3_2022`. The datasets used as signal and
background are listed in `studies/vbf_cut_optimization/config.yaml`.

For a faster exploratory run using at most approximately one million entries
per dataset:

```bash
python3 studies/vbf_cut_optimization/optimize_vbf_cuts.py \
  --era Run3_2024 \
  --input-base /path/to/skim_v1_noUnc/Run3_2024 \
  --output studies/vbf_cut_optimization/output_Run3_2024_1M \
  --max-events-per-sample 1000000 \
  --threads 8 \
  --skip-file-validation
```

The reduction is performed uniformly with an entry stride, rather than by
taking the first million events. The retained events are reweighted by the
stride so that the relative process normalization is approximately preserved.
Use the full samples for the final quoted optimization.

Adding \(p_T^{jj}\) makes the full threshold grid five-dimensional. If memory is
tight during development, either keep `--max-events-per-sample` small or reduce
the number of scan points in `config.yaml`, especially the jet-\(p_T\) and
\(p_T^{jj}\) lists.

## Comparison with the former `makeEffPlot.py`

The numerical significance is not expected to agree unless the following are
made identical:

- the former script used the two leading-\(p_T\) selected jets, while the
  primary map here uses the maximum-\(m_{jj}\) pairing;
- the former runs used only VBF signal against
  `DYto2L_InclusivePlusBinned`; this study defaults to VBF+ggH against DY+EWK;
- the former result was produced for Run3 2022, while the run command may use
  another era and luminosity;
- `weight_base` and `weight__Central` belong to different production chains;
- the former selected-jet collection removed horn-region jets before counting
  \(N_j\), while the current skim keeps the collection and excludes those jets
  from the tested pair;
- the former scan did not add the 35/25 GeV pair thresholds used by the
  reference-style map here.

Use `pairing_and_variables_comparison.*` to inspect the leading-\(p_T\)
assignment alongside the other pairing choices. A strict reproduction should
also use the same era, process lists, baseline, horn treatment and weights.

The default preselection is:

```text
baseline && Signal_Fit && N_SelectedJets >= 2
```

It can be replaced with `--preselection`. To suppress statistically fragile
points, for example, require at least 10 expected background events:

```bash
--min-background 10
```

## Outputs

- `cut_based_optimization_njets.png/pdf`: reference-style three-panel result;
- `efficiency_mjj_detajj_njets.png/pdf`: cumulative signal and background
  efficiencies for the same \(m_{jj}\)-\(|\Delta\eta_{jj}|\) scans and jet
  categories;
- `result.json`: best point in every jet category;
- `ranking_nj_ge2.csv`, `ranking_nj_gt2.csv`, `ranking_nj_eq2.csv`: full-scan rankings;
- `scan_grids.npz`: complete yield and sum-of-weights-squared grids;
- `signal_mjj_detajj.png` and `background_mjj_detajj.png`: weighted 2D distributions;
- `signal_jet1pt_jet2pt.png` and `background_jet1pt_jet2pt.png`: jet-\(p_T\) distributions;
- `significance_mjj_detajj.png`: scan at the best jet-\(p_T\) cuts;
- `significance_jet1pt_jet2pt.png`: jet-\(p_T\) scan at the best dijet cuts.
- `pairing_and_variables_comparison.png/pdf`: best significance for every
  pair-assignment and cut-variable combination;
- `pairing_and_variables_comparison.csv/json`: corresponding optimal cuts and
  yields for all three jet-multiplicity categories.

To add backgrounds later, append datasets to an existing background group or
create another group with `role: background`.

An entry can also carry a custom path and an extra event selection:

```yaml
  DY:
    role: background
    datasets:
      - name: DYto2Mu_MLL_105to160_amcatnloFXFX
        path: "{input_base}/{dataset}"
        selection: "GenVBFFilter == 0"
```
