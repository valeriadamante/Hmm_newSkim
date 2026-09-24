# Comandi combine – produzione del 23/24 settembre

Canale VBF, variabile `DNN_NNOutput`, tre modelli DY (`lnn`, `rateparam-pu`,
`rateparam-both`), due configurazioni di canali (SR + H sideband, solo SR), ere
2022–2025 e poi 2022–2026. Tutto Asimov salvo dove indicato.

Il contesto e le motivazioni stanno in `SIGNAL_EXTENDED_COMMANDS.md` e in
`results_23Sep/RESOCONTO_differenza_vs_02Sep.md`.

## 0. Ambiente

```bash
cd /afs/cern.ch/work/v/vdamante/Hmm_newSkim
source env.sh          # definisce run_combine_tool (combine dentro apptainer)
```

`env.sh` fa `cd` nel repo: se lavori in un'altra cartella, fai `cd` **dopo**
`source env.sh`.

Variabili usate sotto:

```bash
IN=/eos/user/v/vdamante/H_mumu/skim_v4/post_dy/dnn_vbf_weighted/Hists_systMerged
ERAS=2022,2022EE,2023,2023BPix,2024,2025          # con il 2026: aggiungi ,2026
MODEL=lnn                                         # oppure rateparam-pu, rateparam-both
OUT=$PWD/combine/results_23Sep/eras_2022-2025/$MODEL
ASIMOV="-t -1 --expectSignal 1"                   # vuoto per fittare i dati
RANGE="--rMin -5 --rMax 10"
```

## 1. Tutto in un colpo

```bash
# SR + H sideband, tre modelli: significanza, limiti, FitDiagnostics, impacts, scan
SE_OUTPUT=$PWD/combine/results_23Sep/eras_2022-2025 SE_ERAS=$ERAS \
    bash combine/run_signal_extended_fits.sh              # oppure: ... lnn

# solo SR, tre modelli: significanza (completa e solo stat) e limiti
bash combine/results_23Sep/eras_2022-2025_SRonly/run_sr_only.sh

# 2026: aspetta Condor, hadd, merge-syst, poi rifà le fit con 7 ere
bash combine/results_23Sep/finish_2026_and_refit.sh

# solo SR con 7 ere (parte da solo quando esiste la ricevuta merge-syst del 2026)
bash combine/results_23Sep/sr_only_2026_when_ready.sh
# equivalente a mano:
SR_OUT=$PWD/combine/results_23Sep/eras_2022-2026_SRonly SR_ERAS=2022,2022EE,2023,2023BPix,2024,2025,2026 \
    bash combine/results_23Sep/eras_2022-2025_SRonly/run_sr_only.sh
```

Per rifare solo alcuni passi su card e workspace già esistenti:
`SE_STEPS=impacts,scan` (passi: `build,significance,limits,fitdiagnostics,impacts,scan`).
I tre modelli si possono lanciare in parallelo, uno per processo:

```bash
for m in lnn rateparam-pu rateparam-both; do
  SE_OUTPUT=$PWD/combine/results_23Sep/eras_2022-2025 SE_ERAS=$ERAS SE_PARALLEL=4 \
    nohup bash combine/run_signal_extended_fits.sh $m > combine/results_23Sep/eras_2022-2025/run_$m.log 2>&1 &
done
```

Da qui in poi, gli stessi passi uno per uno.

## 2. Datacard

```bash
mkdir -p $OUT
# SR + H sideband (canali y<era>_sr e y<era>_hsb)
python3 combine/build_signal_extended_datacards.py --input $IN --eras $ERAS \
    --dy-model $MODEL --output $OUT/datacard_signal_extended_$MODEL.txt

# solo SR
python3 combine/build_signal_extended_datacards.py --input $IN --eras $ERAS \
    --dy-model $MODEL --channels sr --output $OUT/card_sr_$MODEL.txt
```

Opzioni utili:
- `--rateparam-scope all`: un solo rateParam per tutte le ere invece di uno per gruppo;
- `--rate-param-range 0.2,5.0`: intervallo del rateParam;
- `--allow-unmerged`: accetta un'era senza ricevuta di merge-syst (card parziale!).

Il builder rifiuta un'era se manca `.workflow_syst_Run3_<era>.json`.

## 3. Workspace

```bash
cd $OUT
CARD=datacard_signal_extended_$MODEL          # oppure card_sr_$MODEL
run_combine_tool text2workspace.py $CARD.txt -m 125 -o $CARD.root
WS=$OUT/$CARD.root
```

## 4. Significanza attesa

```bash
mkdir -p $OUT/significance && cd $OUT/significance
run_combine_tool combine -M Significance $WS -m 125 $ASIMOV --toysFreq $RANGE -n .SigExt_$MODEL

# solo stat (i rateParam restano liberi)
run_combine_tool combine -M Significance $WS -m 125 $ASIMOV --toysFreq $RANGE \
    --freezeParameters allConstrainedNuisances -n .SigExt_${MODEL}_stat
```

Per il valore osservato togli `$ASIMOV` e `--toysFreq`.

## 5. Limiti asintotici

```bash
mkdir -p $OUT/limits && cd $OUT/limits
run_combine_tool combine -M AsymptoticLimits $WS -m 125 -t -1 $RANGE -n .SigExt_$MODEL
```

## 6. FitDiagnostics (shape pre/post-fit, pull)

```bash
mkdir -p $OUT/fitdiagnostics && cd $OUT/fitdiagnostics
run_combine_tool combine -M FitDiagnostics $WS -m 125 $ASIMOV --robustFit 1 $RANGE \
    --saveShapes --saveWithUncertainties --saveNormalizations -n .SigExt_$MODEL
```

Con SR + H sideband e 6 ere impiega più di un'ora: il tempo va quasi tutto in
`--saveWithUncertainties`. Toglilo se ti servono solo i pull.

## 7. Pull e impacts

```bash
mkdir -p $OUT/impacts && cd $OUT/impacts
run_combine_tool combineTool.py -M Impacts -d $WS -m 125 --doInitialFit --robustFit 1 $ASIMOV $RANGE
run_combine_tool combineTool.py -M Impacts -d $WS -m 125 --doFits --robustFit 1 --parallel 8 $ASIMOV $RANGE
run_combine_tool combineTool.py -M Impacts -d $WS -m 125 -o impacts_$MODEL.json $ASIMOV $RANGE
run_combine_tool plotImpacts.py -i impacts_$MODEL.json -o impacts_$MODEL
```

`--doFits` lancia un fit per nuisance, circa 150: `--parallel` va tarato sulle
CPU libere. In alternativa, `--job-mode condor --sub-opts '+JobFlavour="workday"'`.

## 8. Likelihood scan con breakdown stat-only

```bash
mkdir -p $OUT/scan && cd $OUT/scan
run_combine_tool combine -M MultiDimFit $WS -m 125 --algo grid --points 60 $ASIMOV $RANGE \
    --saveWorkspace -n .SigExt_$MODEL.total
run_combine_tool combine -M MultiDimFit higgsCombine.SigExt_$MODEL.total.MultiDimFit.mH125.root -m 125 \
    --algo grid --points 60 $ASIMOV $RANGE \
    --snapshotName MultiDimFit --freezeParameters allConstrainedNuisances -n .SigExt_$MODEL.statonly
run_combine_tool plot1DScan.py higgsCombine.SigExt_$MODEL.total.MultiDimFit.mH125.root \
    --others "higgsCombine.SigExt_$MODEL.statonly.MultiDimFit.mH125.root:Stat only:2" \
    --main-label Total --output scan_r_$MODEL
```

## 9. Leggere i risultati

```bash
grep -h "^Significance" $OUT/significance/*.log
grep -h "Expected" $OUT/limits/limits.log
python3 -c "import ROOT,sys; t=ROOT.TFile.Open(sys.argv[1]).Get('limit'); t.GetEntry(0); print(t.limit)" \
    $OUT/significance/higgsCombine.SigExt_$MODEL.Significance.mH125.root
```

## 10. Diagnostica contro il 2 settembre

```bash
D=$PWD/combine/results_23Sep/diagnostica_vs_02Sep
# card attuale con solo SR, ma con le lnN DY della card del 2 Sep
python3 - <<'EOF'
d='combine/results_23Sep/diagnostica_vs_02Sep/'
old={}
for l in open('combine/datacard_02Sep_DYfit_lnN.txt'):
    if l.startswith('DYVBFZ'):
        t=l.split(); old[t[0]]=next(x for x in t[2:] if x!='-')
out=[]
for l in open(d+'card_sr_only_lnn.txt'):
    if l.startswith('DYVBFZ'):
        t=l.split(); l=l.replace(next(x for x in t[2:] if x!='-'), old[t[0]])
    out.append(l)
open(d+'card_sr_only_oldDYlnN.txt','w').writelines(out)
EOF
cd $D
run_combine_tool text2workspace.py card_sr_only_oldDYlnN.txt -m 125 -o card_sr_only_oldDYlnN.root
run_combine_tool combine -M Significance card_sr_only_oldDYlnN.root -m 125 $ASIMOV --toysFreq $RANGE -n .sr_oldDYlnN
```

## 11. Con il 2026

Quando esiste `/eos/user/v/vdamante/H_mumu/skim_v4/post_dy/dnn_vbf_weighted/.workflow_syst_Run3_2026.json`:

```bash
SE_OUTPUT=$PWD/combine/results_23Sep/eras_2022-2026 \
SE_ERAS=2022,2022EE,2023,2023BPix,2024,2025,2026 \
    bash combine/run_signal_extended_fits.sh
```

Per il solo SR, gli stessi passi da 2 a 5 con `--channels sr` e `ERAS` a 7 ere.
Nota: `CombineCardWriter.lumidict` non ha il 2026, quindi le card con il 2026
non hanno lnN di luminosità per quell'era. La DNN del 2026 usa l'`era_code` del
2025 (`common/dnn_application.py`).
