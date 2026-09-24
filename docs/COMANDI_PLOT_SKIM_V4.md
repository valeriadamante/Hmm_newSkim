# Comandi per produrre tutti i plot — skim_v4

Riferimento operativo: ogni comando e' completo, copiabile e non rimanda ad
altri paragrafi. Per il contesto e le spiegazioni vedi
`docs/RUNBOOK_CAMPAGNE_SKIM_V4.md` parte 10.

## Preambolo, da eseguire una volta per sessione

```bash
cd /afs/cern.ch/work/v/vdamante/Hmm_newSkim
source env.sh

V4_IN=/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4
V4_MAN=/eos/user/v/vdamante/H_mumu/manifests_skim_v4
V4_OUT=/eos/user/v/vdamante/H_mumu/skim_v4/post_dy
REG=Signal_Fit,Z_sideband,H_sideband,mass_inclusive
CAT=VBF,ggF,baseline
DNNREG=Z_sideband,Signal_Fit,H_sideband,Signal_ext,mass_inclusive
```

`--check-level files` va messo sempre: senza, il check apre ogni file ROOT e
confronta le chiavi degli istogrammi, che su `all_variables` sono ore di lavoro
prima ancora di disegnare.

## Prima di tutto: cosa e' pronto e cosa blocca

```bash
python3 campaigns/dependencies.py --next                 # la prossima azione per ogni era
python3 campaigns/dependencies.py                        # rapporto completo
python3 campaigns/dependencies.py --eras 2025 --detail   # quali famiglie sono incomplete
python3 campaigns/dependencies.py --campaign all_variables
```

Valuta la catena stadio per stadio

    skim -> manifest -> payload DY -> hist Central -> hist syst
         -> hadd Central -> hadd syst -> merge-syst -> merge-era

usando **le stesse funzioni di `campaigns/workflow.py`** che decidono cosa e'
completo, quindi non puo' divergere dai check delle campagne. Per ogni era
riporta il **primo blocco vero**, risalendo la catena: se manca `hist syst` non
segnala anche `hadd syst` e `merge-syst`, che ne sono solo la conseguenza.

Rileva anche gli `STALE`, cioe' i prodotti piu' vecchi di un loro input. E' il
modo in cui un rifit dei pesi DY invalida silenziosamente gli istogrammi di
un'era: i file ci sono tutti, ma sono vecchi, e l'hadd si ferma.

Gira in circa quattro minuti su tre campagne e sette ere, perche' fa uno `stat`
su ogni prodotto atteso: sono una ventina di migliaia. Con `--campaign` e
`--eras` scende a pochi secondi.

## Tutto in una volta

```bash
# produzione -> hadd -> merge-syst -> plot Central -> studi -> FlashSim
nohup bash campaigns/finish_and_plot_skim_v4.sh > finish_and_plot.log 2>&1 &

# le varianti: con/senza componenti, con sistematiche, ere combinate
nohup bash campaigns/plot_variants_skim_v4.sh all > plot_variants.log 2>&1 &
```

---

# 1. Data/MC di all_variables

## 1.1 Senza sistematiche, CON componenti di jet

Sotto ogni distribuzione compare la scomposizione in `0J`, `1J_Hard`, `1J_PU`,
`2J_Hard`, `2J_PU1`, `2J_PU2` per DY, EWK e i due segnali.

```bash
bash campaigns/all_variables.sh plot --mode central --eras 2025 --check-level files \
  --plot-regions $REG --plot-categories $CAT --component-composition \
  --input-dir $V4_IN --manifest-root $V4_MAN \
  --output-dir $V4_OUT/all_variables --plot-output plots_Sep16/central_components
```

## 1.2 Senza sistematiche, SENZA componenti

Identico, senza `--component-composition`. Restano i processi aggregati: e'
la versione leggibile per un talk.

```bash
bash campaigns/all_variables.sh plot --mode central --eras 2025 --check-level files \
  --plot-regions $REG --plot-categories $CAT \
  --input-dir $V4_IN --manifest-root $V4_MAN \
  --output-dir $V4_OUT/all_variables --plot-output plots_Sep16/central_plain
```

## 1.3 CON le bande di sistematica

Non e' un'opzione di disegno, e' `--mode`. Con `--mode both` la sorgente passa
da `Central_hadded` a `Hists_systMerged` e `plot` aggiunge da solo
`--systematics --totalSystematics`. Serve prima il merge.

```bash
bash campaigns/all_variables.sh merge-syst --mode both --eras 2025 --check-level files \
  --input-dir $V4_IN --manifest-root $V4_MAN --output-dir $V4_OUT/all_variables

bash campaigns/all_variables.sh plot --mode both --eras 2025 --check-level files \
  --plot-regions $REG --plot-categories $CAT --component-composition \
  --input-dir $V4_IN --manifest-root $V4_MAN \
  --output-dir $V4_OUT/all_variables --plot-output plots_Sep16/systematics
```

`merge-syst` pretende l'hadd completo di **Central e di tutte e 22** le
famiglie: basta una a meta' e si ferma senza scrivere niente. Per vedere a che
punto sei:

```bash
for e in Run3_2022 Run3_2025; do
  raw=0; had=0
  for d in $V4_OUT/all_variables/*/; do
    b=$(basename "$d")
    if [[ "$b" == *_hadded ]]; then [[ -d "$d$e" ]] && had=$((had+1));
    else [[ -d "$d$e" ]] && raw=$((raw+1)); fi
  done
  echo "$e raw=$raw hadded=$had"   # servono 23 e 23
done
```

## 1.4 Ere combinate

Due passaggi: `merge-era` somma gli hadd in una pseudo-era, `plot --merged` la
disegna. Il nome non puo' coincidere con un'era fisica.

```bash
for combo in "2022,2023=Run3_2022_2023" "2022,2025=Run3_2022_2025" "2022,2026=Run3_2022_2026"; do
  pair="${combo%%=*}"; name="${combo##*=}"

  bash campaigns/all_variables.sh merge-era --mode central --eras "$pair" \
    --merged-era "$name" --check-level files \
    --input-dir $V4_IN --manifest-root $V4_MAN --output-dir $V4_OUT/all_variables

  bash campaigns/all_variables.sh plot --mode central --merged --eras "$pair" \
    --merged-era "$name" --check-level files \
    --plot-regions $REG --plot-categories $CAT --component-composition \
    --input-dir $V4_IN --manifest-root $V4_MAN \
    --output-dir $V4_OUT/all_variables --plot-output plots_Sep16/merged
done
```

`merge-era` vuole `Central_hadded` completo per **entrambe** le ere, altrimenti
esce con 1 senza scrivere. Unendo 2022 con 2025 o 2026 compariranno categorie
presenti da un lato solo: `plot --merged` prende l'unione, e i rapporti Data/MC
di quelle categorie vanno letti sapendolo.

---

# 2. Data/MC del DNN

Stessa interfaccia, ma `--regions` e `--categories` vanno ripetuti perche' la
campagna nasce con la sola `Signal_Fit`, e `--plot-regions` resta corto perche'
`Signal_ext` si produce ma non si mostra.

```bash
bash campaigns/dnn_vbf_signal.sh plot --mode central --eras 2025 --check-level files \
  --regions $DNNREG --categories VBF \
  --plot-regions $REG --plot-categories VBF --component-composition \
  --input-dir $V4_IN --manifest-root $V4_MAN \
  --output-dir $V4_OUT/dnn_vbf_weighted --plot-output plots_Sep16/central_components
```

Con le sistematiche, dopo il merge:

```bash
bash campaigns/dnn_vbf_signal.sh merge-syst --mode both --eras 2025 --check-level files \
  --regions $DNNREG --categories VBF \
  --input-dir $V4_IN --manifest-root $V4_MAN --output-dir $V4_OUT/dnn_vbf_weighted

bash campaigns/dnn_vbf_signal.sh plot --mode both --eras 2025 --check-level files \
  --regions $DNNREG --categories VBF \
  --plot-regions $REG --plot-categories VBF --component-composition \
  --input-dir $V4_IN --manifest-root $V4_MAN \
  --output-dir $V4_OUT/dnn_vbf_weighted --plot-output plots_Sep16/systematics
```

Non servono `dnn_vbf_z.sh` e `dnn_vbf_h.sh`: differiscono solo per
`--mass-regions`, e le cinque regioni qui sopra li coprono entrambi. In skim_v4
quelle due campagne sono vuote o parziali.

---

# 3. Studi sul DNN

Tutti e quattro passano da un solo script, che legge la composizione dei
processi da `config/dnn_studies.yaml` cosi' non divergono fra loro.

```bash
ERAS=2022,2022EE,2023,2023BPix,2025
RES=plots_Sep16/studies
```

## 3.1 Ottimizzazione del binning

Cerca il taglio singolo migliore e la partizione in al massimo cinque bin
contigui che massimizza l'Asimov combinato.

```bash
bash campaigns/dnn_studies_skim_v4.sh binning --eras $ERAS --results-dir $RES
# -> $RES/dnn_binning/{weighted,dy_unweighted}/<era>.{json,png}
```

## 3.2 Sensibilita' contro numero di bin

Scansione N = 1..N_max con bordi a fondo cumulativo uguale, per decidere quanti
bin tenere. E' una domanda diversa dalla 3.1 e usa una figura di merito diversa:
vedi `docs/DNN_binning_and_sensitivity.txt`.

```bash
bash campaigns/dnn_studies_skim_v4.sh sensitivity --eras $ERAS --results-dir $RES
# -> $RES/sensitivity/<era>_{powheg,amcatnlo}.{png,pdf,root}
```

## 3.3 Performance con e senza pesi DY — dagli istogrammi

Confronta la campagna pesata contro `dnn_vbf_dy_unweighted`. Misura cosa fa il
reweighting DY. Richiede `Central_hadded` per **entrambe** le varianti.

```bash
bash campaigns/dnn_studies_skim_v4.sh performance --eras $ERAS --results-dir $RES
# -> $RES/dnn_performance/dy_weights_weighted/<era>.*
```

Se una delle due varianti non ha i DY, il confronto misura il DY mancante, non
l'effetto dei pesi. Per produrre la variante senza pesi:

```bash
bash campaigns/dnn_studies_skim_v4.sh submit-nondy  --eras $ERAS   # jobs non-DY
bash campaigns/dnn_studies_skim_v4.sh mirror-nondy  --eras $ERAS   # symlink, gratis
bash campaigns/dnn_studies_skim_v4.sh submit-dy     --eras $ERAS   # i DY, veri job
bash campaigns/dnn_studies_skim_v4.sh hadd          --eras $ERAS
```

## 3.4 ROC pesata contro non pesata — dagli skim

Due curve dallo stesso event loop, una con `weight__Central` e una con peso 1.
Non richiede Condor, solo gli skim.

```bash
bash campaigns/dnn_studies_skim_v4.sh roc --eras $ERAS --results-dir $RES --roc-max-files 30
# -> $RES/dnn_performance/roc_from_skims/weighted/all_eras{,_<era>}.{json,png}
```

**`--roc-max-files` non e' opzionale in pratica.** Il tool rilegge gli skim con
`AsNumpy` e su un'era grande arriva a 23 GB di RSS contro i 34 del cgroup: senza
tetto e' stato ucciso dall'OOM. Con 30 file per dataset scende sotto i 2 GB. I
file sono presi a passo costante su tutto il dataset, non i primi 30, e i pesi
vengono riscalati per `n_tot/n_letti`, quindi le rese restano corrette e cambia
solo la precisione statistica. Il tetto morde solo sui dataset grossi: il DY del
2025 ha 595 file, i segnali del 2022EE ne hanno 1 e 3.

Non mettergli un `timeout`: il tentativo precedente e' stato ucciso da un
`timeout 1500` troppo corto, non da un errore.

Il valore usato finisce in `max_files_per_dataset` dentro il JSON, cosi' un
risultato su sottoinsieme non si confonde con uno completo.

## 3.5 Tutti e quattro

```bash
bash campaigns/dnn_studies_skim_v4.sh studies --eras $ERAS --results-dir $RES
```

---

# 4. Mini-studi laterali

Entrambi leggono gli skim con RDataFrame. **Non lanciarli insieme alla ROC**: si
prendono a vicenda la memoria e vengono uccisi tutti e due.

## 4.1 BSC chi2: tagliare a 30 o tenere l'evento?

```bash
python3 tools/check_bsc_chi2.py --era 2025 \
  --input-root $V4_IN \
  --output plots_Sep16/studies/bsc_chi2/Run3_2025
# -> Run3_2025.{json,root}, _fractions.png, _mass[_<sample>].png,
#    _pt_chi2_ge30[_<sample>].png, _chi2_vs_gentruth_<sample>.png
```

## 4.2 Scale factor dei muoni: richiedere il gen matching?

```bash
python3 tools/check_w_ss_muon_genmatching.py --era 2025 \
  --input-root $V4_IN \
  --output plots_Sep16/studies/muon_sf_genmatching/Run3_2025
# -> Run3_2025.{json,root,png}
```

Conclusioni e tabelle: `docs/SIDE_STUDIES_AND_FLASHSIM_20260916.txt`.

---

# 5. Confronto FullSim / FlashSim

Legge gli hadd Central di `all_variables`, non richiede produzione dedicata.
La base e' `Central_hadded`, **non** `Hists_hadded`: con il percorso sbagliato
il tool gira e restituisce zero confronti senza lamentarsi.

```bash
python3 tools/compare_flashsim.py --era Run3_2025 \
  --input-base $V4_OUT/all_variables/Central_hadded \
  --output plots_Sep16/flashsim_comparison \
  --regions Signal_Fit_VBF --run
```

Senza `--run` stampa solo il piano delle coppie.

Il tool lancia un subprocess per ogni (coppia, regione, variabile), circa 25 s
l'uno: in serie su tutte le regioni sono ore. Una regione per processo:

```bash
for region in Signal_Fit_VBF Z_sideband_VBF H_sideband_VBF mass_inclusive_VBF \
              Signal_Fit_ggF Z_sideband_ggF H_sideband_ggF mass_inclusive_ggF \
              mass_inclusive_baseline; do
  python3 tools/compare_flashsim.py --era Run3_2025 \
    --input-base $V4_OUT/all_variables/Central_hadded \
    --output plots_Sep16/flashsim_comparison --regions "$region" --run \
    > logs_plots_Sep16/flashsim_2025_$region.log 2>&1 &
done
wait
```

Ha senso solo per 2024, 2025 e 2026: le altre ere non hanno campioni FlashSim.

Il pannello del rapporto riporta **`FullSim / FlashSim`** e non i nomi di
processo per esteso, che erano illeggibili; i nomi completi restano nella
legenda in alto. Si cambia con `--ratio-label` di `studies/compare_hists.py`.

---

# 6. Diagnostici dei pesi DY

Non c'e' un comando di plot: i PNG escono dai fit stessi e stanno nel
repository accanto ai payload JSON.

```
reweights/dy_012j_reweight_skim_v4/<era>/    dy_012j_{0J,1J,2J,VBF}_{pre,post}fit.{png,pdf}
reweights/dy_ptll_reweight_skim_v4/<era>/    {ggF_0J,ggF_1J,ggF_ge2J,VBF_ge2J}_ptll_*.{png,pdf}
reweights/dy_njets_reweight_skim_v4/<era>/   {ggF,VBF}_njets_*.{png,pdf}
```

Per rigenerarli serve rifare il fit, nell'ordine jet -> pT(ll) -> N(jet):

```bash
bash campaigns/dy_weights.sh fit --weight-stage jet   --eras 2025
bash campaigns/dy_weights.sh fit --weight-stage ptll  --eras 2025
bash campaigns/dy_weights.sh fit --weight-stage njets --eras 2025
```

Attenzione: rifare un fit rende **stantii** tutti gli istogrammi DY di
quell'era. Il check li marca `STALE` e l'hadd si ferma; vanno riprodotti, non
solo riaggregati:

```bash
bash campaigns/all_variables.sh submit --mode central --eras 2025 \
  --datasets region_auto --force --memory 8GB \
  --input-dir $V4_IN --manifest-root $V4_MAN --output-dir $V4_OUT/all_variables
```

`--datasets region_auto` limita ai soli DY; `--force` serve perche' la
sottomissione salta gli output gia' presenti, e questi ci sono, sono solo
vecchi.

---

# 7. Dove finisce tutto

```
plots_Sep16/central_components/<campagna>/<era>/<era>/<regione>_<categoria>/all_plots.pdf
plots_Sep16/central_plain/      idem, senza componenti di jet
plots_Sep16/systematics/        idem, con le bande
plots_Sep16/merged/             ere combinate
plots_Sep16/studies/dnn_binning/         ottimizzazione del binning
plots_Sep16/studies/sensitivity/         sensibilita' vs numero di bin
plots_Sep16/studies/dnn_performance/     con/senza pesi, istogrammi e ROC
plots_Sep16/studies/bsc_chi2/            mini-studio BSC chi2
plots_Sep16/studies/muon_sf_genmatching/ mini-studio gen matching
plots_Sep16/flashsim_comparison/<era>/<flash>_vs_<full>/<regione>/<var>.png
plots_Sep16/dy_weights/<era>/            copia dei diagnostici dei pesi
reweights/dy_*_reweight_skim_v4/<era>/   originali dei diagnostici
```

L'era compare due volte nel percorso dei plot di campagna: `workflow.py` la
mette nella directory di output e `plot_all_regions.sh` ne aggiunge un'altra.
Non e' un bug, e i tool a valle si aspettano questa forma.

Il formato e' PDF: uno per coppia regione/categoria piu' un `all_plots.pdf`
multipagina per l'era. Il FlashSim invece scrive PNG.

---

# 8. Blinding

Sta in `config/plot/histograms.yaml`, chiave `blind_range` per variabile,
indicizzata su `<regione>_<categoria>`. Vale per ogni plot di ogni campagna.

| variabile | regioni nascoste | intervallo |
|---|---|---|
| `m_mumu` | `Signal_Fit_*`, `mass_inclusive_*`, `H_sideband_*`, `Signal_ext_*`, `other` | 120 - 130 GeV |
| `DNN_NNOutput` | `Signal_Fit_*`, `mass_inclusive_*` | 0.8 - 1.0 |

Verifica sempre che sia scattato:

```bash
grep BLIND logs_plots_Sep16/plot_av_2025.log
#   [BLIND] m_mumu in category mass_inclusive_VBF: range [120.0, 130.0]
```

Una chiave assente **non** e' un errore e non ferma il plot: semplicemente non
nasconde niente. E' il modo piu' facile di pubblicare dati non blinded.

I plot gia' fatti non si aggiornano da soli: dopo una modifica a `blind_range`
vanno rigenerati.
