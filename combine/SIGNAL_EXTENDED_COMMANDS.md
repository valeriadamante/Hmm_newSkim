# Signal Extended: datacards e comandi Combine

Canale **Signal Extended = SR + Higgs sideband**, variabile `DNN_NNOutput`
(binning esatto del DNN, nessun rebin), categoria **VBF**, ere
2022, 2022EE, 2023, 2023BPix, 2024, 2025.

`Signal_ext_VBF` **non** si usa: il routing di
`config/histogram_sample_routing.yaml` manda i campioni 105--160 (DY ed EWK che
forniscono i template del fondo sotto il picco) solo in `Signal_Fit` e
`H_sideband`, quindi in quei file la regione `Signal_ext` non esiste. La card ha
quindi **due canali per era**: `y<era>_sr` (`Signal_Fit_VBF`) e `y<era>_hsb`
(`H_sideband_VBF`).

Input: `/eos/user/v/vdamante/H_mumu/skim_v4/post_dy/dnn_vbf_weighted/Hists_systMerged/Run3_<era>/`.

## Le tre varianti DY

| variante | PU1 | PU2 | Hard |
|---|---|---|---|
| `lnn` | `DYVBFZ_fit_2JPU1_<gruppo>` lnN | `DYVBFZ_fit_2JPU2_<gruppo>` lnN | `DYVBFZ_fit_2JHard_<gruppo>` lnN |
| `rateparam-pu` | `DY_norm_PU_<gruppo>` rateParam | stesso rateParam | lnN |
| `rateparam-both` | `DY_norm_PU_<gruppo>` rateParam | stesso rateParam | `DY_norm_Hard_<gruppo>` rateParam |

I valori delle lnN sono ricalcolati dagli errori del fit 012J di skim_v4
(`reweights/dy_012j_reweight_skim_v4/<gruppo>/dy_012j_reweight_fit.json`,
parametri `VBFHard`, `VBFPU1`, `VBFPU2`, kappa = 1 + err/val) — non sono i
numeri hardcoded in `CombineCardWriter.py`, che vengono da un fit precedente.

I gruppi sono quelli del fit: `2022_2022EE`, `2023_2023BPix`, `2024`, `2025`.
Un rateParam per gruppo e' il default; `--rateparam-scope all` ne mette **uno
solo** per tutte le ere.

## Costruzione delle card

```bash
source env.sh
for model in lnn rateparam-pu rateparam-both; do
  python3 combine/build_signal_extended_datacards.py \
    --input /eos/user/v/vdamante/H_mumu/skim_v4/post_dy/dnn_vbf_weighted/Hists_systMerged \
    --eras 2022,2022EE,2023,2023BPix,2024,2025 \
    --dy-model "$model" \
    --output combine/results_signal_extended/$model/datacard_signal_extended_$model.txt
done
```

## Tutto in un colpo

```bash
bash combine/run_signal_extended_fits.sh                 # le tre varianti
bash combine/run_signal_extended_fits.sh rateparam-pu    # solo una
SE_ERAS=2024,2025 bash combine/run_signal_extended_fits.sh
```

Variabili d'ambiente: `SE_INPUT`, `SE_ERAS`, `SE_OUTPUT`, `SE_ASIMOV`
(`-t -1 --expectSignal 1`, svuotala per fittare i dati), `SE_RANGE`,
`SE_PARALLEL`, `SE_POINTS`.

## I comandi, uno per uno

Sostituire `MODEL` con `lnn`, `rateparam-pu` o `rateparam-both`.
`run_combine_tool` viene da `env.sh` ed esegue nel container ufficiale.

```bash
source env.sh
MODEL=lnn
OUT=combine/results_signal_extended/$MODEL
CARD=$OUT/datacard_signal_extended_$MODEL.txt
WS=$OUT/datacard_signal_extended_$MODEL.root
```

### 1. Workspace

```bash
run_combine_tool text2workspace.py $CARD -m 125 -o $WS
```

### 2. Sensitivity

Significanza attesa (Asimov, con i nuisance profilati sui toy):

```bash
cd $OUT/significance
run_combine_tool combine -M Significance $WS -m 125 \
  -t -1 --expectSignal 1 --toysFreq --rMin -5 --rMax 10 -n .SigExt_$MODEL
```

Limiti asintotici su r, come riferimento:

```bash
cd $OUT/limits
run_combine_tool combine -M AsymptoticLimits $WS -m 125 \
  -t -1 --rMin -5 --rMax 10 -n .SigExt_$MODEL
```

Incertezza su r dal fit:

```bash
cd $OUT/fitdiagnostics
run_combine_tool combine -M FitDiagnostics $WS -m 125 \
  -t -1 --expectSignal 1 --robustFit 1 --rMin -5 --rMax 10 \
  --saveShapes --saveWithUncertainties --saveNormalizations -n .SigExt_$MODEL
```

### 3. Pulls e impacts

```bash
cd $OUT/impacts
run_combine_tool combineTool.py -M Impacts -d $WS -m 125 \
  --doInitialFit --robustFit 1 -t -1 --expectSignal 1 --rMin -5 --rMax 10
run_combine_tool combineTool.py -M Impacts -d $WS -m 125 \
  --robustFit 1 --doFits --parallel 8 -t -1 --expectSignal 1 --rMin -5 --rMax 10
run_combine_tool combineTool.py -M Impacts -d $WS -m 125 \
  -o impacts_$MODEL.json -t -1 --expectSignal 1 --rMin -5 --rMax 10
run_combine_tool plotImpacts.py -i impacts_$MODEL.json -o impacts_$MODEL
```

I pull si leggono dallo stesso `impacts_$MODEL.json` (campo `fit` per ogni
nuisance) e da `fitDiagnostics.SigExt_$MODEL.root` (`tree_fit_sb`,
`nuisances_prefit` / `fit_b` / `fit_s`).

### 4. Likelihood scan

Scan totale piu' scan stat-only, sullo stesso grafico:

```bash
cd $OUT/scan
run_combine_tool combine -M MultiDimFit $WS -m 125 \
  --algo grid --points 60 -t -1 --expectSignal 1 --rMin -5 --rMax 10 \
  --saveWorkspace -n .SigExt_$MODEL.total

run_combine_tool combine -M MultiDimFit \
  higgsCombine.SigExt_$MODEL.total.MultiDimFit.mH125.root -m 125 \
  --algo grid --points 60 -t -1 --expectSignal 1 --rMin -5 --rMax 10 \
  --snapshotName MultiDimFit --freezeParameters allConstrainedNuisances \
  -n .SigExt_$MODEL.statonly

run_combine_tool plot1DScan.py \
  higgsCombine.SigExt_$MODEL.total.MultiDimFit.mH125.root \
  --others higgsCombine.SigExt_$MODEL.statonly.MultiDimFit.mH125.root:"Stat only":2 \
  --main-label Total --output scan_r_$MODEL
```

Per congelare solo il DY invece di tutti i nuisance, per esempio per vedere
quanto pesa la normalizzazione delle componenti:

```bash
--freezeParameters DY_norm_PU_2024,DY_norm_Hard_2024
```

### 5. Confronto fra le tre varianti

```bash
grep -h "Significance:" combine/results_signal_extended/*/significance/*.log
grep -h "Expected 50.0%" combine/results_signal_extended/*/limits/*.log
```

## Note

- `CMS_scale_j_total_<era>` viene scartata: la campagna produce il JES nelle 11
  famiglie regrouped, quindi quegli istogrammi non esistono. Le nuisance
  regrouped ci sono tutte.
- Alcuni processi a bassa statistica (`W`, `TTX`, e nel H sideband
  `DYto2Mu_MLL105To160_2J_PU2`) hanno variazioni sistematiche vuote o con bin
  negativi: la colonna resta, ma quelle nuisance sono disattivate per quel
  processo. Il builder lo stampa a video e lo salva in `build.log`.
- `SingleH` e' assente in alcune ere: la colonna viene saltata.
