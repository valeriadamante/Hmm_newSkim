# DY reweighting

This page summarizes the data-driven corrections applied to the Drell--Yan
(DY) simulation. The payloads are selected in the era-dependent
`process_names.yaml` files.

## Available eras

The corrections are derived for four statistically combined period groups:

| Payload era | Applied to |
|---|---|
| `Run3_2022_2022EE` | 2022 and 2022EE |
| `Run3_2023_2023BPix` | 2023 and 2023BPix |
| `Run3_2024` | 2024 |
| `Run3_2025` | 2025 |

All three derivations use the Z sideband in data. The non-DY prediction is
subtracted before forming or fitting the DY correction. Depending on the
available process files, the subtraction includes EWK, single-top, single-H,
top-pair, ttX, tW, diboson, triboson and W+jets backgrounds.

## DY 0/1/2J component reweighting

### Method

- **Purpose:** correct the relative normalization of DY hard-scatter and
  pileup-jet components.
- **Inputs:** separate DY templates for `0J`, `1J_Hard`, `1J_PU`, `2J_Hard`,
  `2J_PU1` and `2J_PU2`, plus data and non-DY simulation.
- **ggF control regions:** data and non-DY use the disjoint reconstructed-jet
  categories `Z_sideband_ggF_0J`, `Z_sideband_ggF_1J` and
  `Z_sideband_ggF_2J`; every MC sample is additionally split by generator
  matching. Data are split only by reconstructed-jet count.
- **Exclusive MC components:** `(N_SelectedJets, N_matched)` is
  `(0,0)`, `(1,1)`, `(1,0)`, `(2,2)`, `(2,1)` or `(2,0)`;
  `N_matched = N_SelectedJets - N_PU_FirstTwoJets`. Events with more than two
  selected jets are outside these six ggF components.
- **Fit model:** binned chi-square with non-negative Minuit parameters.
- **Sequential fit order:**
    1. fit `2JHard`, `2JPU1` and `2JPU2` in
       `eta_signed_vs_pt_subleadingjet`;
    2. fit `1JHard` and `1JPU` in the disjoint 1J data region using
       `eta_signed_vs_pt_leadingjet`;
    3. fit the exclusive `0J`
       normalization in `m_mumu`.
- **VBF control region:** an independent fit is performed in
  `Z_sideband_VBF` using `eta_signed_vs_pt_vbfjet1`. `VBFPU1` and `VBFPU2`
  share one parameter; `VBFHard` has its own.
- **Output:** one multiplicative normalization per exclusive component. An
  unmatched component receives the correctionlib default weight of `1.0`.
- **Uncertainty:** the quoted error is the square root of the corresponding
  diagonal element of the inverse-Hessian covariance matrix. Correlations
  between parameters fitted in the same stage are stored in
  `dy_012j_reweight_fit.json`.

### Fitted weights

The skim_v4 payloads must be regenerated before numerical weights are reported here.

## DY selected-jet multiplicity reweighting

### Method

- **Purpose:** correct the DY distribution of the number of selected jets.
- **Control region and categories:** `Z_sideband_ggF` and
  `Z_sideband_VBF` are treated independently.
- **Observable:** `N_SelectedJets`, with bins for 0 through 9 jets and an
  inclusive overflow bin for 10 or more jets.
- **Weight definition:** the correction is evaluated bin by bin as
  
  $$w(N_{\mathrm{jets}}) =
  \frac{N_{\mathrm{data}}-N_{\mathrm{non-DY}}}{N_{\mathrm{DY}}}.$$
- **Statistical error:** propagated from the data, non-DY and DY histogram bin
  errors. These errors are retained in the diagnostic ROOT histograms during
  derivation; the correctionlib JSON contains the nominal bin weights only.
- **Protection:** bins with insufficient DY yield fall back to unity, and the
  configured weight range is enforced. Values outside the tabulated jet range
  are clamped to the first or last bin.
- **Output inputs:** `isVBF` and `nSelectedJets`; an unknown category receives
  the default weight `1.0`.

## DY dilepton-pT reweighting

### Method

- **Purpose:** correct the shape of the dilepton transverse momentum,
  $p_{T}(\ell\ell)$ (`pt_mumu`).
- **Control region:** the Z sideband, split into `ggF_0J`, `ggF_1J`,
  `ggF_ge2J` and `VBF_ge2J` categories.
- **Raw ratio:** in every category, the starting points are
  $(N_{\mathrm{data}}-N_{\mathrm{non-DY}})/N_{\mathrm{DY}}$ with propagated
  histogram uncertainties.
- **Fit:** the ratio is fitted between 0 and 200 GeV with a constant plus two
  Gaussian terms and a falling-power term:

  $$f(x)=p_0+p_1e^{-\frac{1}{2}((x-p_2)/p_3)^2}
  +p_4e^{-\frac{1}{2}((x-p_5)/p_6)^2}
  +p_7\left(\frac{\max(x,p_8)}{p_8}\right)^{-p_9}.$$

- **Category behavior:** the fitted function is used for all three ggF jet
  bins and for the VBF category with at least two jets. VBF events with zero or
  one selected jet receive unity.
- **Uncertainty:** bin errors enter the fit and parameter errors are available
  in the derivation payload/ROOT output. The production correctionlib JSON
  stores the central fit parameters only; it does not expose an event-level
  up/down variation.
- **Output inputs:** `isVBF`, `N_selectedJets` and `ptll`; jet-count underflow
  and overflow are clamped and an unknown category receives `1.0`.

## Payload locations and application

The active files live under:

```text
reweights/dy_012j_reweight_skim_v4/<payload-era>/dy_012j_reweight.json
reweights/dy_njets_reweight_skim_v4/<payload-era>/dy_njets_reweight.json
reweights/dy_ptll_reweight_skim_v4/<payload-era>/dy_ptll_reweight_smart.json
```

The era-specific `config/Run3_<era>/process_names.yaml` selects the appropriate
payload group. The selected-jet and dilepton-$p_T$ corrections are evaluated as
event weights during histogram production. The 0/1/2J correction acts on the
separately produced DY component templates.
