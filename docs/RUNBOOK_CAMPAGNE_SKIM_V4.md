# Runbook skim_v4 — anno per anno

Guida operativa. Ogni era ha la sua sezione autosufficiente: puoi seguirne una
sola dall'inizio alla fine senza saltare altrove. I comandi sono ripetuti per
esteso in ogni sezione apposta, così non devi ricomporli.

Prima di qualsiasi cosa:

```bash
cd /afs/cern.ch/work/v/vdamante/Hmm_newSkim
source env.sh
```

---

# PARTE 1 — Concetti che servono ovunque

## 1.1 L'ordine delle operazioni

Sempre questo, per ogni era, senza scorciatoie:

```
skim
  -> manifest di validazione
       -> pesi DY stadio jet      (submit, hadd, fit)
            -> pesi DY stadio pTll     (submit, hadd, fit)
                 -> pesi DY stadio N(jet)  (submit, hadd, fit)
                      -> istogrammi finali (all_variables, DNN VBF, horn veto)
                           -> hadd
                                -> merge-syst
                                     -> merge-era
                                          -> studi (DNN, FlashSim)
```

Le tre fasi dei pesi DY non sono parallelizzabili: ognuna legge il JSON scritto
dalla precedente. Gli istogrammi finali non partono senza i payload, perché il
controllo dei pesi è globale e blocca il submit.

## 1.2 Dove sono le cose

Skim con veto: `/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4`

Skim senza veto: `/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4_noJetHornVeto`

Manifest: `/eos/user/v/vdamante/H_mumu/manifests_skim_v4`

Manifest senza veto: `/eos/user/v/vdamante/H_mumu/manifests_skim_v4_noJetHornVeto`

Istogrammi dei pesi DY: `/eos/user/v/vdamante/H_mumu/skim_v4/DY_weights`

Istogrammi finali: `/eos/user/v/vdamante/H_mumu/skim_v4/post_dy`

Payload dei pesi: `reweights/dy_012j_reweight_skim_v4/<era>/`,
`reweights/dy_ptll_reweight_skim_v4/<era>/`,
`reweights/dy_njets_reweight_skim_v4/<era>/`

C'è **un solo albero di skim con veto**, `skim_v4`, completo per tutte e sette
le ere. Il 16 settembre 2026 i 42 file che la produzione di patch aveva
riscritto (tutti in Run3_2024) sono stati copiati dentro `skim_v4`, i 555
manifest sono stati riportati a quel percorso e `skim_v4_fixed` non è più un
riferimento valido: non usarlo.

## 1.3 Usa sempre `find -L`

`find` senza `-L` non scende nelle directory collegate e riporta **zero file**
dove ce ne sono migliaia: parte dei file di skim sono symlink. Ogni conteggio va
fatto così:

```bash
find -L /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4/Run3_2024 -name '*.root' | wc -l
```

## 1.4 Il codice di ritorno dei pesi DY

`run3_dy_weights_skim_v4.sh run` avanza **uno stadio per invocazione**:

- ritorna **3** = ha sottomesso e sta aspettando Condor. Non è un errore. Aspetta i job e rilancia lo stesso identico comando.
- ritorna **0** = stadio completato. Rilancia per passare al successivo.
- altro = errore vero, leggi il log.

Servono quindi almeno sei invocazioni per era: submit jet, fit jet + submit
pTll, fit pTll + submit N(jet), fit N(jet).

## 1.5 Il DNN ha bisogno di due opzioni obbligatorie

`config/campaigns/dnn_vbf_signal_sep03.sh` contiene
`CAMPAIGN_OPTIONS=(--mode both --systematics-layout together --jes total)`.
Quel `--jes total` collassa il JES in **una sola** nuisance
`CMS_scale_j_total` invece delle 11 famiglie regrouped che usa `all_variables`.

Ogni comando DNN va quindi passato con:

```
--systematics-layout split --jes regrouped
```

Gli argomenti da riga di comando prevalgono su `CAMPAIGN_OPTIONS`. Nei driver
`campaigns/dnn_studies_skim_v4.sh` e `campaigns/run3_full_chain.sh` l'override è
già inserito stabilmente.

## 1.6 Controlla sempre se qualcosa sta già girando

Più sessioni scrivono sugli stessi alberi EOS. Prima di sottomettere:

```bash
ps -u "$USER" -o pid,etime,args --no-headers | grep -E "campaigns/|condorsubmit" | grep -v grep
condor_q -totals
condor_q -af JobBatchName | cut -d/ -f2 | sed -E 's/_(Central|Run3).*//' | sort | uniq -c | sort -rn | head
```

Quadro completo per era, senza scrivere niente:

```bash
bash campaigns/run3_full_chain.sh status
```

## 1.7 Chiedi allo script cosa blocca, prima di lanciare qualsiasi cosa

```bash
python3 campaigns/dependencies.py --next
```

Stampa, per ogni campagna e per ogni era, **la prossima azione utile**: se e'
`hist syst` non ha senso tentare l'hadd, se e' `hadd Central` non ha senso
tentare `merge-syst`. Risale la catena da sola e riporta solo il blocco vero,
non le sue conseguenze.

La catena valutata:

    skim -> manifest -> payload DY -> hist Central -> hist syst
         -> hadd Central -> hadd syst -> merge-syst -> merge-era

Usa le stesse funzioni di `campaigns/workflow.py` (`raw_products`,
`hadded_products`, con l'espansione `--jes regrouped`), quindi quello che dice
coincide con quello che diranno i `check` delle campagne.

Varianti utili:

```bash
python3 campaigns/dependencies.py --eras 2025 --detail        # quali famiglie mancano
python3 campaigns/dependencies.py --campaign all_variables    # una campagna sola
python3 campaigns/dependencies.py                             # rapporto per esteso
```

Segnala anche gli `STALE`: prodotti piu' vecchi di un loro input. Per il DY
l'input sono i payload JSON, quindi un rifit rende stantii tutti gli istogrammi
DY di quell'era senza che manchi un file. E' il modo piu' subdolo in cui una
produzione sembra completa e non lo e'.

Attenzione a una cosa che confonde: un conteggio tipo `170/171` spesso **non**
e' un buco, e' un file che un job sta riscrivendo in quel momento. Prima di
concludere che manca qualcosa, controlla se c'e' un job in coda per quel
dataset:

```bash
condor_q -constraint 'regexp("Run3_2025_DYto2Mu_M_50_amcatnloFXFX$", JobBatchName)' -af JobBatchName JobStatus
```

## 1.8 Verifica profonda dopo ogni hadd

Il check di campagna apre i ROOT ma **non decomprime gli istogrammi**: file
corrotti o con chiavi mancanti passano per buoni. In una sola serata sono
comparsi tre hadd difettosi su EOS.

```bash
bash campaigns/run3_full_chain.sh deep-check
```

Se segnala un file, rigenera l'hadd di quella sola era e ricontrolla.

## 1.9 Trappole note

Il submit **esce con codice 1** quando alcuni manifest mancano, pur avendo
sottomesso il resto. In uno script con `set -e` questo interrompe i comandi
successivi: il driver del DNN ci era già cascato, lasciando la variante senza
pesi priva di DY.

Cambiare selezioni su un output già prodotto richiede `--force` o una directory
nuova: i timestamp non certificano le opzioni di una vecchia produzione.

`condor_hold` su job **running** butta via il lavoro già fatto. Limita sempre a
`JobStatus == 1`.

`condor_prio -p 100 <cluster>` ordina **solo i tuoi job fra loro**, non aumenta
la quota rispetto agli altri utenti del pool.

`dnn_roc_from_skims.py` va in OOM su un'era intera: carica in numpy tutti gli
eventi selezionati. Una sola era per invocazione, `--threads` ≤ 4, mai due in
parallelo.

Cancellare o sovrascrivere file di altri utenti su EOS fallisce con
`Unable to remove file for truncation`.

## 1.10 Dataset a schema misto — risolto nel codice

Alcuni dataset contengono file prodotti da versioni diverse dello skim, con rami
di selezione presenti solo in alcuni. RDF ricava le colonne dai primi file della
catena, quindi un ramo presente solo lì sembrava disponibile e la lettura
falliva sugli altri con `TTreeReader status code 6`.

`common/add_vars.py` ora ricalcola **sempre** le selezioni dall'espressione,
anche quando un ramo omonimo esiste. Prima le `muons_selection` erano
un'eccezione e si fidavano del ramo memorizzato. Non serve fare nulla: il fix
copre tutte le ere.

Situazione rilevata al momento della scansione:

- Run3_2024: 95 dataset su 97 senza il ramo, 1 con, **1 misto** (`Muon1_Run2024G`, 12 file su 204)
- Run3_2026: 46 con, 41 senza, **6 misti**
- Run3_2025: tutti e 95 senza il ramo, nessuno misto

Un dataset interamente "senza ramo" non è un problema: la selezione viene creata
a runtime. Erano i misti a fallire.

---

# PARTE 2 — Stato al 16 settembre 2026

```
era              skim   manif    jet   ptll  njets  payload   noHorn
Run3_2022        1390      76    416     48     48      3/3        0
Run3_2022EE      3126      62    346     48     48      3/3        0
Run3_2023        2300      80    365     52     52      3/3        0
Run3_2023BPix    1080      52    284     40     40      3/3        0
Run3_2024       10454      97    351      0      0      0/3        0
Run3_2025       11342      95    385     62     62      3/3     8477
Run3_2026        9994      93    348      0      0      0/3     9994
```

Verifica sempre prima di fidarti: questa tabella decade.

---

# PARTE 3 — Run3_2022

Era standard, nessuna eccezione di rilievo. Pesi completi.

Particolarità: usa `W_NJets` invece di `W`. Il veto horn non ha limite
superiore in eta: `|eta| >= 2.5 && pt <= 50`, diverso da 2024–2026.

## 3.1 Verifica dello stato

```bash
find -L /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4/Run3_2022 -name '*.root' | wc -l
ls /eos/user/v/vdamante/H_mumu/manifests_skim_v4/Run3_2022/*.json | wc -l
bash campaigns/run3_dy_weights_skim_v4.sh status --eras 2022
```

## 3.2 Pesi DY — già completi

I tre payload esistono. Per riverificarli:

```bash
bash campaigns/dy_weights.sh check-weights --weight-stage all --eras 2022 --mode central \
  --input-root /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4 \
  --json-root /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4 \
  --manifest-root /eos/user/v/vdamante/H_mumu/manifests_skim_v4 \
  --output-root /eos/user/v/vdamante/H_mumu/skim_v4/DY_weights
```

Per rifarli da zero, tre giri con attesa Condor in mezzo:

```bash
bash campaigns/run3_dy_weights_skim_v4.sh run --eras 2022
```

## 3.3 all_variables

```bash
bash campaigns/all_variables.sh submit --mode central --eras 2022 \
  --input-dir /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4 \
  --manifest-root /eos/user/v/vdamante/H_mumu/manifests_skim_v4 \
  --output-dir /eos/user/v/vdamante/H_mumu/skim_v4/post_dy/all_variables

bash campaigns/all_variables.sh submit --mode syst --eras 2022 \
  --input-dir /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4 \
  --manifest-root /eos/user/v/vdamante/H_mumu/manifests_skim_v4 \
  --output-dir /eos/user/v/vdamante/H_mumu/skim_v4/post_dy/all_variables
```

Dopo i job:

```bash
bash campaigns/all_variables.sh check --stage histograms --mode both --eras 2022 \
  --input-dir /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4 \
  --manifest-root /eos/user/v/vdamante/H_mumu/manifests_skim_v4 \
  --output-dir /eos/user/v/vdamante/H_mumu/skim_v4/post_dy/all_variables
```

Il check a livello ROOT su 13809 file richiede ore. Per una verifica rapida
aggiungi `--check-level files`, che controlla presenza, dimensione e timestamp.

## 3.4 DNN VBF — ricorda le due opzioni

```bash
bash campaigns/dnn_vbf_signal.sh submit --mode central --eras 2022 \
  --regions Z_sideband,Signal_Fit,H_sideband,Signal_ext,mass_inclusive --categories VBF \
  --systematics-layout split --jes regrouped \
  --input-dir /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4 \
  --manifest-root /eos/user/v/vdamante/H_mumu/manifests_skim_v4 \
  --output-dir /eos/user/v/vdamante/H_mumu/skim_v4/post_dy/dnn_vbf_weighted

bash campaigns/dnn_vbf_signal.sh submit --mode syst --eras 2022 \
  --regions Z_sideband,Signal_Fit,H_sideband,Signal_ext,mass_inclusive --categories VBF \
  --systematics-layout split --jes regrouped \
  --input-dir /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4 \
  --manifest-root /eos/user/v/vdamante/H_mumu/manifests_skim_v4 \
  --output-dir /eos/user/v/vdamante/H_mumu/skim_v4/post_dy/dnn_vbf_weighted
```

Non servono `dnn_vbf_z.sh` e `dnn_vbf_h.sh`: differiscono solo per
`--mass-regions`, e le cinque regioni qui sopra li coprono entrambi.

## 3.5 Variante DNN senza pesi DY

Serve per il confronto performance con e senza reweighting. I reweight toccano
solo i dataset DY, quindi tutto il resto si produce una volta sola e si
rispecchia.

```bash
bash campaigns/dnn_studies_skim_v4.sh submit-nondy --eras 2022
bash campaigns/dnn_studies_skim_v4.sh mirror-nondy --eras 2022
bash campaigns/dnn_studies_skim_v4.sh submit-dy    --eras 2022
```

## 3.6 Aggregazione

```bash
bash campaigns/all_variables.sh hadd       --mode both --eras 2022 --input-dir /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4 --manifest-root /eos/user/v/vdamante/H_mumu/manifests_skim_v4 --output-dir /eos/user/v/vdamante/H_mumu/skim_v4/post_dy/all_variables
bash campaigns/all_variables.sh merge-syst --mode both --eras 2022 --input-dir /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4 --manifest-root /eos/user/v/vdamante/H_mumu/manifests_skim_v4 --output-dir /eos/user/v/vdamante/H_mumu/skim_v4/post_dy/all_variables
bash campaigns/run3_full_chain.sh deep-check
```

---

# PARTE 4 — Run3_2022EE

Identica al 2022 in tutto: stesse eccezioni (`W_NJets`, veto horn senza limite
in eta), pesi completi, stessi comandi con `--eras 2022EE`.

Unica differenza pratica: lo skim è più grande (3126 file contro 1390), quindi
i job durano di più.

Nota storica sui pesi: il payload jet è ora **per-era**, non più condiviso con
il 2022. Quando erano accoppiati, il fit combinato dava valori intermedi fra le
due ere, che sulle componenti PU differiscono parecchio: 1JPU 0.83 nel 2022
contro 0.52 nel 2022EE. Se torni a un payload condiviso, aspettati una media
pesata verso il 2022EE, che ha tripla statistica.

Tutti i comandi della Parte 3 valgono sostituendo `--eras 2022` con
`--eras 2022EE`.

---

# PARTE 5 — Run3_2023

Era standard, pesi completi. Usa `W_NJets`. Veto horn senza limite superiore in
eta, come 2022.

Tutti i comandi della Parte 3 valgono con `--eras 2023`.

Osservazione sui pesi: è l'era con le componenti PU più alte, 1JPU ≈ 1.46 e
2JPU ≈ 1.69, contro valori sotto 1 nelle ere 2022 e nel 2025. La direzione della
correzione è opposta. Non è un errore di procedura, ma se confronti i pesi fra
periodi tienilo presente.

---

# PARTE 6 — Run3_2023BPix

Pesi completi. Ha un insieme di processi **ridotto** rispetto alle altre ere.

Eccezioni sui processi: mancano `VH_inclusive` e `TTH_inclusive`, e sono esclusi
`ggZH_Hto2B_Zto2L`, `ggZH_Hto2B_Zto2Q`, `ZH_Hto2B_Zto2L`, `ZH_Hto2B_Zto2Q`,
`WminusH_Hto2B_WtoLNu`, `WplusH_Hto2B_WtoLNu`, `TTHto2B_M125`,
`TTHtoNon2B_M125`. Il framework lo sa già e restringe le attese da solo: non
devi passare selezioni speciali.

Usa `W_NJets`. Veto horn senza limite superiore in eta.

Tutti i comandi della Parte 3 valgono con `--eras 2023BPix`. Aspettati conteggi
più bassi ovunque (52 manifest contro 76–80 delle altre).

---

# PARTE 7 — Run3_2024

**Era con il maggior numero di eccezioni. Leggila tutta prima di lanciare.**

Skim completo: 10454 file, 97 manifest. Pesi DY: **0 su 3**, in produzione.

## 7.1 Eccezione: usa `skim_v4`, non `skim_v4`

Il 2024 è l'era che la patch ha effettivamente riscritto. `skim_v4` è
l'unico albero con i file corretti. Per le altre ere i due percorsi coincidono
via link, per il 2024 no.

## 7.2 Eccezione: nomi dei processi

Dal 2024 in poi il W si chiama `W` e non più `W_NJets`. Compare anche
`DYto2Mu_minnlo` e le varianti FlashSim (`DYto2Mu_MLL105To160_FlashSim`,
`EWK_Flashsim`, `TTto2L2Nu_Flashsim`, `VBFHto2Mu_m125_Flashsim`).

## 7.3 Eccezione: veto horn limitato in eta

```
2.5 <= |eta| < 3.0  &&  pt <= 50
```

Diverso da 2022–2023, dove non c'è il limite superiore. Conseguenza fisica: i
jet forward soffici oltre |eta| = 3 sopravvivono, e sono in larga maggioranza da
pile-up. Questo alza la frazione PU nelle regioni a jet e rende i pesi PU non
confrontabili con le ere precedenti.

## 7.4 Eccezione: un dataset non leggibile

`VBFHto2Mu_m125_Flashsim` ha la directory di proprietà di un altro utente
(`pflanaga`, permessi `-rw-------`) e non è accessibile. È in `skim_cfg` per il
2024, quindi la validazione lo segnalerà come non disponibile. È una variante
FlashSim, esclusa comunque dagli studi: ignora la segnalazione.

## 7.5 Eccezione: `Muon1_Run2024G` a schema misto

12 file su 204 hanno il ramo `muons_SS_presel_trg`, gli altri 192 no. Prima del
fix in `common/add_vars.py` questo faceva fallire il job con
`TTreeReader status code 6`, e la catena dei pesi lo risottometteva all'infinito
— sei volte in tre ore e mezza senza avanzare. Ora è risolto nel codice.

Se vedi la catena ripetere lo stesso stadio senza progredire, il sintomo è
questo: controlla quanti file mancano davvero.

```bash
bash campaigns/dy_weights.sh check --stage histograms --mode central --weight-stage jet \
  --check-level files --eras 2024 \
  --input-root /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4 \
  --json-root /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4 \
  --manifest-root /eos/user/v/vdamante/H_mumu/manifests_skim_v4 \
  --output-root /eos/user/v/vdamante/H_mumu/skim_v4/DY_weights
```

Se manca **un solo file su 700**, è un job che fallisce, non lavoro da fare.
Vai a leggere il suo stderr:

```bash
D=$(ls -dt htcondor/hists/Run3_2024_DY012J* | head -1)
cat $D/error/*
```

## 7.6 Pesi DY — da produrre

Tre giri, aspettando i job fra uno e l'altro:

```bash
bash campaigns/run3_dy_weights_skim_v4.sh status --eras 2024     # deve dare N/N
bash campaigns/run3_dy_weights_skim_v4.sh run    --eras 2024     # submit jet, ritorna 3
# aspetta:  condor_q -constraint 'regexp("DY012J", JobBatchName)' -af ClusterId | wc -l
bash campaigns/run3_dy_weights_skim_v4.sh run    --eras 2024     # fit jet + submit pTll
# aspetta:  condor_q -constraint 'regexp("DYPTLL", JobBatchName)' -af ClusterId | wc -l
bash campaigns/run3_dy_weights_skim_v4.sh run    --eras 2024     # fit pTll + submit N(jet)
# aspetta:  condor_q -constraint 'regexp("DYNJETS", JobBatchName)' -af ClusterId | wc -l
bash campaigns/run3_dy_weights_skim_v4.sh run    --eras 2024     # fit N(jet)
```

Oppure lascia fare alla catena, che gestisce le attese da sola:

```bash
nohup env V4_ERAS=2024 bash campaigns/run3_full_chain.sh dy-weights > dy_2024.log 2>&1 &
```

## 7.7 Istogrammi — solo dopo i payload

Finché i payload sono 0/3, `all_variables` e DNN falliscono con
`Missing histogram reweight JSON`. Non è aggirabile con `--force`: il controllo
è sui pesi, non sugli output.

Quando i payload ci sono, valgono i comandi della Parte 3 con `--eras 2024`.

---

# PARTE 8 — Run3_2025

Skim completo, 11342 file, 95 manifest, pesi completi 3/3. Ha anche la variante
senza veto horn, incompleta.

## 8.1 Eccezione: due dataset non esistono

`DYto2L_M_50_amcatnloFXFX_Flashsim` e `DYto2Mu_M_50_amcatnloFXFX_Flashsim` sono
in `skim_cfg` ma **la directory di skim non esiste proprio**. Non è un manifest
perso: è un campione mai prodotto, e nessuna validazione può crearlo.

Finché restano nella selezione, ogni aggregazione si fermerà aspettandoli. Le
opzioni sono due: produrne lo skim, oppure escluderli da `skim_cfg`. Non c'è una
terza strada, e in particolare **non** serve rilanciare `validate`.

## 8.2 Eccezione: veto horn limitato in eta

Come il 2024: `2.5 <= |eta| < 3.0 && pt <= 50`.

Conseguenza misurata: nella regione 1J la frazione PU del DY è **32%**, contro
6–7% nelle ere 2022 e 2023. Oltre |eta| = 3 il campione è all'82% pile-up e
sopravvive al veto. Non è una differenza di condizioni fra anni: è la
definizione del veto.

## 8.3 Eccezione: variante senza veto incompleta

`skim_v4_noJetHornVeto/Run3_2025` ha 8477 file contro gli 11342 della variante
con veto, e **zero manifest**. Gli skim per completarla sono attualmente in
hold.

Per riprenderli:

```bash
condor_release -constraint 'regexp("^Skim", JobBatchName)'
```

Poi, quando lo skim è completo, generare i manifest:

```bash
base=/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4_noJetHornVeto
bash analysis/scripts/validate.sh --era Run3_2025 --datasets skim_cfg \
  --root-input-folder "$base" --json-input-folder "$base" \
  --output-dir /eos/user/v/vdamante/H_mumu/manifests_skim_v4_noJetHornVeto \
  --condor --missing-only --condor-label Validate_noHorn_2025
```

Solo a quel punto il confronto horn con/senza è producibile per il 2025.

## 8.4 Qualità dei fit

È l'era con i χ² peggiori: nel 1J il fit dei pesi jet arriva a χ²/ndof ≈ 923,
contro 15–28 delle altre ere. Il difetto è concentrato nei bin
2.5 < |eta| < 3.5 con 45 < pT < 80 GeV, dove il bordo del veto a 50 GeV cade
**dentro** il bin di pT. I pesi sono utilizzabili, ma quel numero non va letto
come una misura di bontà.

## 8.5 Comandi

Tutti quelli della Parte 3 con `--eras 2025`.

---

# PARTE 9 — Run3_2026

Skim completo, 9994 file, 93 manifest. Pesi DY: **0 su 3**, stadio jet
in produzione. È l'unica era con la variante senza veto **completa**.

## 9.1 Eccezione: insieme di processi ridotto

`skim_cfg` del 2026 attiva meno processi delle altre ere. Il framework
restringe già le attese ai dataset effettivamente selezionati
(`datasets_for_histogram_groups` lo fa da solo), quindi non devi passare
selezioni speciali. Aspettati semplicemente conteggi diversi.

## 9.2 Eccezione: sei dataset a schema misto

La scansione ha trovato 46 dataset con il ramo `muons_SS_presel_trg`, 41 senza e
**6 misti**, fra cui `DYto2Mu_MLL_4000to6000_powheg_minnlo`,
`DYto2Mu_MLL_400to600_powheg_minnlo`, `DYto2Mu_MLL_6000to13600_powheg_minnlo`.
Il fix in `common/add_vars.py` li copre: le selezioni si ricalcolano sempre.

È l'era con la frammentazione di schema più alta, quindi se vedi errori
`does not have a branch` su un dataset del 2026, il primo sospetto è questo.

## 9.3 Eccezione: veto horn limitato, e variante senza veto pronta

Veto come 2024–2025: `2.5 <= |eta| < 3.0 && pt <= 50`.

La variante senza veto ha **9994 file e 93 manifest**, cioè è completa quanto
quella con veto. Il confronto horn è quindi producibile subito, e non dipende
dai pesi DY perché usa `--weights none`:

```bash
bash campaigns/jet_horn_veto.sh paths  --eras 2026 --variant both

bash campaigns/jet_horn_veto.sh submit --eras 2026 --variant both \
  --input-root /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4 \
  --manifest-root /eos/user/v/vdamante/H_mumu/manifests_skim_v4 \
  --output-dir /eos/user/v/vdamante/H_mumu/skim_v4/post_dy/horn_veto

bash campaigns/jet_horn_veto.sh hadd   --eras 2026 --variant both \
  --output-dir /eos/user/v/vdamante/H_mumu/skim_v4/post_dy/horn_veto
```

## 9.4 Pesi DY — da completare

Lo stadio jet ha già 348 file. Mancano pTll e N(jet):

```bash
bash campaigns/run3_dy_weights_skim_v4.sh run --eras 2026
```

Ripeti dopo ogni blocco Condor, finché non ritorna 0 su tutti gli stadi. Poi:

```bash
bash campaigns/dy_weights.sh check-weights --weight-stage all --eras 2026 --mode central \
  --input-root /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4 \
  --json-root /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4 \
  --manifest-root /eos/user/v/vdamante/H_mumu/manifests_skim_v4 \
  --output-root /eos/user/v/vdamante/H_mumu/skim_v4/DY_weights
```

## 9.5 Istogrammi

Come per il 2024: bloccati finché i payload non esistono. Poi valgono i comandi
della Parte 3 con `--eras 2026`.

---

# PARTE 10 — Plot e aggregazione fra ere

Questa parte e' autoconclusiva: contiene i comandi per intero, senza rimandi.
Le tre variabili che ricorrono ovunque sono sempre le stesse:

```bash
V4_IN=/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4
V4_MAN=/eos/user/v/vdamante/H_mumu/manifests_skim_v4
V4_OUT=/eos/user/v/vdamante/H_mumu/skim_v4/post_dy
```

## 10.1 Plottare il Central mentre gli hadd delle sistematiche girano

`plot --mode central` guarda **solo** `Central_hadded`. Non tocca le famiglie
JES/PU/PDF e non aspetta `merge-syst`. Quindi si puo' lanciare appena l'hadd
Central di un'era e' finito, anche con migliaia di job di sistematiche ancora
in coda.

Due opzioni sono obbligatorie perche' la cosa funzioni:

- `--mode central`, altrimenti il check pretende `merged-syst`, che non esiste
  ancora, e il comando esce con 1 senza disegnare niente;
- `--check-level files`, altrimenti il controllo apre ogni file ROOT e confronta
  le chiavi degli istogrammi: su `all_variables` sono ore di lavoro solo per
  arrivare al disegno.

`all_variables`, un'era:

```bash
bash campaigns/all_variables.sh plot --mode central --eras 2023 --check-level files \
  --plot-regions Signal_Fit,Z_sideband,H_sideband,mass_inclusive \
  --plot-categories VBF,ggF,baseline --component-composition \
  --input-dir $V4_IN --manifest-root $V4_MAN \
  --output-dir $V4_OUT/all_variables \
  --plot-output plots_Sep16
```

DNN VBF, un'era. Qui `--regions` e `--categories` vanno ripetuti perche' la
campagna nasce con la sola `Signal_Fit`:

```bash
bash campaigns/dnn_vbf_signal.sh plot --mode central --eras 2023 --check-level files \
  --regions Z_sideband,Signal_Fit,H_sideband,Signal_ext,mass_inclusive --categories VBF \
  --plot-regions Signal_Fit,Z_sideband,H_sideband,mass_inclusive \
  --plot-categories VBF --component-composition \
  --input-dir $V4_IN --manifest-root $V4_MAN \
  --output-dir $V4_OUT/dnn_vbf_weighted \
  --plot-output plots_Sep16
```

Piu' ere insieme: **non** passare `--eras 2022,2023` a `plot`. Senza `--merged`
il comando cicla comunque un'era per volta, ma in un solo processo e in serie.
Meglio un processo per era, in parallelo:

```bash
for era in 2022EE 2023 2023BPix 2025; do
  bash campaigns/all_variables.sh plot --mode central --eras $era --check-level files \
    --input-dir $V4_IN --manifest-root $V4_MAN \
    --output-dir $V4_OUT/all_variables --plot-output plots_Sep16 \
    > logs_plots_Sep16/plot_av_$era.log 2>&1 &
done
wait
```

Prima di lanciare, verifica che l'era sia davvero pronta. Il check e' veloce e
dice esattamente cosa manca:

```bash
bash campaigns/all_variables.sh check --stage hadded --mode central --eras 2023 \
  --check-level files --input-dir $V4_IN --manifest-root $V4_MAN \
  --output-dir $V4_OUT/all_variables
```

Attenzione a `STALE`: significa che l'istogramma esiste ma e' piu' vecchio di un
suo input. Per il DY l'input sono i payload JSON dei pesi, quindi un rifit dei
pesi rende stantii tutti gli istogrammi DY di quell'era. Non basta rifare
l'hadd, vanno **riprodotti** gli istogrammi:

```bash
bash campaigns/all_variables.sh submit --mode central --eras 2022 \
  --datasets region_auto --force --memory 8GB \
  --input-dir $V4_IN --manifest-root $V4_MAN --output-dir $V4_OUT/all_variables
```

`--datasets region_auto` limita la risottomissione ai soli DY; `--force` serve
perche' di default la sottomissione salta gli output gia' presenti, e questi
ci sono, sono solo vecchi.

## 10.2 Quali categorie disegnare, e le componenti di jet

`--regions` e `--categories` dicono alla campagna **cosa produrre e cosa
controllare**; `--plot-regions` e `--plot-categories` dicono soltanto **cosa
disegnare**. Sono opzioni distinte apposta: restringere il disegno non deve
allentare il check sulla produzione.

Serve perche' `all_variables` dichiara 19 categorie, quasi tutte di controllo.
Le combinazioni che contano per mostrare un risultato sono nove:

| regione | categorie |
|---|---|
| `Z_sideband` | `ggF`, `VBF` |
| `Signal_Fit` | `ggF`, `VBF` |
| `H_sideband` | `ggF`, `VBF` |
| `mass_inclusive` | `baseline`, `ggF`, `VBF` |

che si ottengono con:

```bash
  --plot-regions Signal_Fit,Z_sideband,H_sideband,mass_inclusive \
  --plot-categories VBF,ggF,baseline
```

Il prodotto cartesiano aggiunge tre combinazioni in piu' rispetto alle nove:
`Z_sideband_baseline`, `Signal_Fit_baseline`, `H_sideband_baseline`. Il
plotter non accetta coppie esplicite, quindi o si tengono o si cancellano a
mano; costano poco e non danno fastidio.

`--component-composition` aggiunge sotto ogni distribuzione la scomposizione in
componenti di jet — `0J`, `1J_Hard`, `1J_PU`, `2J_Hard`, `2J_PU1`, `2J_PU2` —
per DY, EWK e i due segnali. Senza l'opzione il disegno resta ai processi
aggregati: `workflow.py` passa `--no-component-composition` di default perche' i
file per componente non esistono in tutte le campagne.

Il DNN e' un caso a parte. La campagna deve continuare a girare su tutte e
cinque le regioni, `Signal_ext` compresa, perche' serve altrove; ma nei plot
`Signal_ext` non si mostra. Quindi `--regions` resta lungo e `--plot-regions`
corto:

```bash
  --regions Z_sideband,Signal_Fit,H_sideband,Signal_ext,mass_inclusive --categories VBF \
  --plot-regions Signal_Fit,Z_sideband,H_sideband,mass_inclusive --plot-categories VBF
```

## 10.3 Blinding

Il blinding non e' un'opzione da riga di comando: sta in
`config/plot/histograms.yaml`, per variabile, sotto `blind_range`, e vale per
ogni plot prodotto da qualunque campagna. Il valore e' un dizionario indicizzato
su `<regione>_<categoria>`, la stessa chiave usata da `x_rebin`.

Stato dal 16/09/2026:

| variabile | regioni nascoste | intervallo |
|---|---|---|
| `m_mumu` | `Signal_Fit_*`, `mass_inclusive_*`, `H_sideband_*`, `Signal_ext_*`, `other` | 120 - 130 GeV |
| `DNN_NNOutput` | `Signal_Fit_*`, `mass_inclusive_*` | 0.8 - 1.0 |

Prima c'erano solo `Signal_Fit_{VBF,ggF}` a `[122,129]` per la massa e il solo
`Signal_Fit_VBF` per il DNN: `mass_inclusive` mostrava i dati sotto il picco, e
`Signal_Fit_baseline` non era coperta affatto.

Sul DNN, `0.8` non e' un bordo dell'istogramma ma cade fra `0.77` e `0.82`
dell'`x_rebin`, quindi nasconde le ultime cinque colonne — quelle dove si
concentra il segnale e dove l'ottimizzazione del binning mette gli ultimi due
bin (vedi `docs/DNN_binning_and_sensitivity.txt`).

Per verificare che il blinding sia attivo, cerca la riga nel log del plot:

```bash
grep BLIND logs_plots_Sep16/plot_av_2025.log
#   [BLIND] m_mumu in category mass_inclusive_VBF: range [120.0, 130.0]
```

Se la riga non compare, la chiave non e' stata trovata: controlla che
`<regione>_<categoria>` sia scritta esattamente come nel file di configurazione.
Una chiave assente **non** e' un errore e non ferma il plot, semplicemente non
nasconde niente — e' il modo piu' facile di pubblicare dati non blinded.

I plot gia' prodotti non si aggiornano da soli: dopo una modifica a
`blind_range` vanno rifatti.

## 10.4 Le quattro varianti, e come tenerle separate

Le combinazioni utili sono quattro: componenti di jet si', componenti no,
sistematiche si', sistematiche no. `campaigns/plot_variants_skim_v4.sh` le
produce tutte scrivendo ognuna in una sua sottocartella, cosi' non si
sovrascrivono e dal percorso si capisce cosa si sta guardando.

```bash
bash campaigns/plot_variants_skim_v4.sh all
bash campaigns/plot_variants_skim_v4.sh syst --eras 2022,2025
bash campaigns/plot_variants_skim_v4.sh merged
```

| variante | cartella | opzioni che la definiscono |
|---|---|---|
| Central, con componenti | `plots_Sep16/central_components/` | `--mode central --component-composition` |
| Central, senza componenti | `plots_Sep16/central_plain/` | `--mode central` |
| Con sistematiche | `plots_Sep16/systematics/` | `--mode both --component-composition` |
| Ere combinate | `plots_Sep16/merged/` | `--merged --merged-era <nome>` |

### 10.4.1 Con e senza componenti di jet

L'unica differenza e' `--component-composition`. Con l'opzione, sotto ogni
distribuzione compare la scomposizione in `0J`, `1J_Hard`, `1J_PU`, `2J_Hard`,
`2J_PU1`, `2J_PU2` per DY, EWK e i due segnali; senza, restano i processi
aggregati, che e' quello che serve per un talk.

```bash
# CON le componenti
bash campaigns/all_variables.sh plot --mode central --eras 2025 --check-level files \
  --plot-regions Signal_Fit,Z_sideband,H_sideband,mass_inclusive \
  --plot-categories VBF,ggF,baseline --component-composition \
  --input-dir $V4_IN --manifest-root $V4_MAN \
  --output-dir $V4_OUT/all_variables --plot-output plots_Sep16/central_components

# SENZA: basta togliere --component-composition
bash campaigns/all_variables.sh plot --mode central --eras 2025 --check-level files \
  --plot-regions Signal_Fit,Z_sideband,H_sideband,mass_inclusive \
  --plot-categories VBF,ggF,baseline \
  --input-dir $V4_IN --manifest-root $V4_MAN \
  --output-dir $V4_OUT/all_variables --plot-output plots_Sep16/central_plain
```

### 10.4.2 Con e senza sistematiche

Non e' un'opzione di disegno, e' `--mode`. Con `--mode central` la sorgente e'
`Central_hadded`; con `--mode both` diventa `Hists_systMerged` e `plot` aggiunge
da solo `--systematics --totalSystematics`.

```bash
# SENZA bande
bash campaigns/all_variables.sh plot --mode central --eras 2025 --check-level files \
  --plot-regions Signal_Fit,Z_sideband,H_sideband,mass_inclusive \
  --plot-categories VBF,ggF,baseline --component-composition \
  --input-dir $V4_IN --manifest-root $V4_MAN \
  --output-dir $V4_OUT/all_variables --plot-output plots_Sep16/central_components

# CON le bande: prima il merge, poi il plot
bash campaigns/all_variables.sh merge-syst --mode both --eras 2025 --check-level files \
  --input-dir $V4_IN --manifest-root $V4_MAN --output-dir $V4_OUT/all_variables

bash campaigns/all_variables.sh plot --mode both --eras 2025 --check-level files \
  --plot-regions Signal_Fit,Z_sideband,H_sideband,mass_inclusive \
  --plot-categories VBF,ggF,baseline --component-composition \
  --input-dir $V4_IN --manifest-root $V4_MAN \
  --output-dir $V4_OUT/all_variables --plot-output plots_Sep16/systematics
```

`merge-syst` pretende che l'hadd sia completo per **Central e per tutte e 22**
le famiglie dell'era: basta una famiglia a meta' e si ferma senza scrivere
niente. Per sapere a che punto sei:

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

## 10.5 Dove finiscono i plot

Senza `--plot-output` la base e' `plots/campaigns`. Il percorso completo e':

```
<base>/<CAMPAIGN_LABEL>/<era>/<era>/<regione>_<categoria>/all_plots.pdf
```

`CAMPAIGN_LABEL` viene da `config/campaigns/*.sh`, non dal nome dello script:

| script | etichetta, quindi cartella |
|---|---|
| `all_variables.sh` | `AllVariables_AllWeights` |
| `dnn_vbf_signal.sh` | `Sep03_DNN_VBF_Signal_AllWeights` |
| `dnn_vbf_z.sh` | `Sep03_DNN_VBF_Z_AllWeights` |
| `dnn_vbf_h.sh` | `Sep03_DNN_VBF_H_AllWeights` |
| `jet_horn_veto.sh` | `JetHornVeto_WithHornVeto` e `JetHornVeto_NoHornVeto` |

`jet_horn_veto.sh` e' l'unica che di default punta ancora a `skim_v3` e a
`manifests_skim_v3`: per la produzione skim_v4 passale sempre `--input-dir` e
`--manifest-root` esplicitamente.

L'era compare due volte perche' `workflow.py` mette l'era nel percorso di
output e `plot_all_regions.sh` ne aggiunge un'altra al suo interno. Non e' un
bug ed e' meglio non "sistemarlo": i tool a valle si aspettano questa forma.

Il formato prodotto e' PDF, non PNG: uno per coppia regione/categoria piu' un
`all_plots.pdf` multipagina per l'era.

Per tenere la produzione skim_v4 separata da tutto il resto, passa sempre
`--plot-output plots_Sep16`. La cartella `plots/` contiene materiale di
produzioni precedenti ed e' stata archiviata in
`/eos/user/v/vdamante/H_mumu/archive/results_20260914/plots.tar`.

## 10.6 Plot con le bande di sistematica

Servono le sistematiche gia' unite. Il comando diventa `--mode both` e la
sorgente non e' piu' `Central_hadded` ma `Hists_systMerged`; `plot` aggiunge da
solo `--systematics --totalSystematics`.

```bash
bash campaigns/all_variables.sh merge-syst --mode both --eras 2023 \
  --input-dir $V4_IN --manifest-root $V4_MAN --output-dir $V4_OUT/all_variables

bash campaigns/all_variables.sh plot --mode both --eras 2023 --check-level files \
  --input-dir $V4_IN --manifest-root $V4_MAN \
  --output-dir $V4_OUT/all_variables --plot-output plots_Sep16
```

`merge-syst` pretende che l'hadd sia completo per **Central e per tutte** le
famiglie sistematiche dell'era: basta una famiglia a meta' e si ferma.

## 10.7 Unire piu' ere

Due passaggi distinti. `merge-era` somma gli hadd delle ere scelte in una
pseudo-era nuova; `plot --merged` disegna quella pseudo-era.

Il nome della pseudo-era lo decidi tu con `--merged-era`. Deve essere diverso da
ogni era fisica presente in `--eras`, altrimenti `workflow.py` si rifiuta di
partire per non sovrascrivere un'era vera.

**2022 + 2023**

```bash
bash campaigns/all_variables.sh merge-era --mode central --eras 2022,2023 \
  --merged-era Run3_2022_2023 --check-level files \
  --input-dir $V4_IN --manifest-root $V4_MAN --output-dir $V4_OUT/all_variables

bash campaigns/all_variables.sh plot --mode central --merged --eras 2022,2023 \
  --merged-era Run3_2022_2023 --check-level files \
  --input-dir $V4_IN --manifest-root $V4_MAN \
  --output-dir $V4_OUT/all_variables --plot-output plots_Sep16
```

**2022 + 2025**

```bash
bash campaigns/all_variables.sh merge-era --mode central --eras 2022,2025 \
  --merged-era Run3_2022_2025 --check-level files \
  --input-dir $V4_IN --manifest-root $V4_MAN --output-dir $V4_OUT/all_variables

bash campaigns/all_variables.sh plot --mode central --merged --eras 2022,2025 \
  --merged-era Run3_2022_2025 --check-level files \
  --input-dir $V4_IN --manifest-root $V4_MAN \
  --output-dir $V4_OUT/all_variables --plot-output plots_Sep16
```

**2022 + 2026**

```bash
bash campaigns/all_variables.sh merge-era --mode central --eras 2022,2026 \
  --merged-era Run3_2022_2026 --check-level files \
  --input-dir $V4_IN --manifest-root $V4_MAN --output-dir $V4_OUT/all_variables

bash campaigns/all_variables.sh plot --mode central --merged --eras 2022,2026 \
  --merged-era Run3_2022_2026 --check-level files \
  --input-dir $V4_IN --manifest-root $V4_MAN \
  --output-dir $V4_OUT/all_variables --plot-output plots_Sep16
```

Per il DNN vale lo stesso, con in piu' le solite due opzioni di regione e
categoria:

```bash
bash campaigns/dnn_vbf_signal.sh merge-era --mode central --eras 2022,2023 \
  --merged-era Run3_2022_2023 --check-level files \
  --regions Z_sideband,Signal_Fit,H_sideband,Signal_ext,mass_inclusive --categories VBF \
  --input-dir $V4_IN --manifest-root $V4_MAN --output-dir $V4_OUT/dnn_vbf_weighted

bash campaigns/dnn_vbf_signal.sh plot --mode central --merged --eras 2022,2023 \
  --merged-era Run3_2022_2023 --check-level files \
  --regions Z_sideband,Signal_Fit,H_sideband,Signal_ext,mass_inclusive --categories VBF \
  --input-dir $V4_IN --manifest-root $V4_MAN \
  --output-dir $V4_OUT/dnn_vbf_weighted --plot-output plots_Sep16
```

Cose da sapere prima di lanciare:

- `merge-era` vuole **almeno due** ere fisiche, e prima di partire controlla
  l'hadd di tutte. Se una delle due non ha `Central_hadded` completo, esce con 1
  senza scrivere niente.
- Le categorie non sono le stesse in tutte le ere. `plot --merged` prende
  l'unione delle regioni e delle categorie delle ere selezionate, quindi
  unendo 2022 con 2025 o 2026 compariranno categorie presenti solo da un lato.
  Non e' un errore, ma i rapporti Data/MC di quelle categorie vanno letti
  sapendolo.
- Ogni combinazione lascia una ricevuta
  `.workflow_eras_<pseudo-era>.json` nella radice della campagna, con l'elenco
  esatto delle ere unite. Se cambi combinazione riusando lo stesso nome, il
  check successivo segnala `WRONG_MERGE_SELECTION`: usa un nome nuovo.
- Con `--mode both`, `merge-era` unisce anche tutte le famiglie sistematiche e
  poi lancia `merge-syst` due volte, per era e per pseudo-era. E' molto piu'
  lungo: per un primo sguardo resta su `--mode central`.

## 10.8 Confronto FullSim / FlashSim

Non richiede produzione dedicata: legge gli hadd Central di `all_variables`.
La base e' `Central_hadded`, non `Hists_hadded`.

```bash
python3 tools/compare_flashsim.py --era Run3_2025 \
  --input-base $V4_OUT/all_variables/Central_hadded \
  --output plots_Sep16/flashsim_comparison --run
```

Senza `--run` stampa solo il piano delle coppie, utile per capire cosa
confrontera'. L'output e'
`plots_Sep16/flashsim_comparison/<era>/<flash>_vs_<full>/<regione>/` piu' un
`index.json` per era.

Ha senso solo per le ere che hanno davvero campioni FlashSim, cioe' 2024, 2025
e 2026. Per 2022, 2022EE, 2023 e 2023BPix il tool gira ma trova zero coppie.

---

# PARTE 11 — Studi finali

Si fanno una volta sola su tutte le ere disponibili, non era per era.

## 11.1 Studi DNN

```bash
bash campaigns/dnn_studies_skim_v4.sh studies --eras 2022,2022EE,2023,2023BPix,2025
```

Oppure una fase alla volta: `binning`, `performance`, `roc`, `sensitivity`.
Aggiungi `--dry-run` per vedere i comandi senza eseguirli.

Le due letture di "performance con e senza pesi" sono **studi diversi** e
vengono prodotti entrambi.

`performance` confronta due produzioni di **istogrammi**, con e senza i reweight
DY. Richiede `Central_hadded` per entrambe le varianti. Se una delle due non ha
il DY, il confronto misura il DY mancante, non l'effetto dei pesi.

`roc` confronta due curve calcolate nello **stesso event loop sugli skim**, una
con `weight__Central` e una con peso 1. Non richiede Condor.

Solo AUC/ROC è confrontabile fra le due curve. `S/sqrt(S+B)` su conteggi grezzi
non è una sensibilità, per questo il tool non lo disegna.

## 11.2 Confronto FlashSim, senza sistematiche

Legge gli hadd Central di `all_variables`, quindi non richiede produzione
aggiuntiva:

```bash
python3 tools/compare_flashsim.py --era Run3_2025 \
  --input-base /eos/user/v/vdamante/H_mumu/skim_v4/post_dy/all_variables/Hists_hadded \
  --output results/skim_v4/flashsim_comparison --run
```

---

# PARTE 12 — Chiudere la produzione e rifare tutto

Un solo comando porta dalla coda Condor ai plot finali:

```bash
nohup bash campaigns/finish_and_plot_skim_v4.sh > finish_and_plot.log 2>&1 &
tail -f finish_and_plot.log
```

Fa, in quest'ordine:

1. **fill-gaps** — attende che la coda si svuoti, risottomette quello che manca
   in tutte le campagne, e ripete fino a tre giri. Un job fallito o un dataset
   saltato lascia buchi che solo un nuovo submit riempie, e il submit e'
   `--missing-only` per default, quindi non rifa' niente di gia' buono. Dopo tre
   giri prosegue comunque: se manca ancora qualcosa non e' un problema di coda.
2. **hadd** — tutte le ere in parallelo, per `all_variables`,
   `dnn_vbf_weighted` e `dnn_vbf_dy_unweighted`.
3. **merge-syst** — dove Central e tutte le famiglie sono complete.
4. **plot** — solo le categorie principali, con le componenti di jet e il
   blinding; a fine stadio stampa le righe `[BLIND]` trovate, cosi' si vede
   subito se qualcosa non e' stato nascosto.
5. **studies** — binning, performance, sensitivity e ROC.
6. **flashsim** — una regione per processo, in parallelo.

Ogni stadio e' invocabile da solo per riprendere:

```bash
bash campaigns/finish_and_plot_skim_v4.sh hadd
bash campaigns/finish_and_plot_skim_v4.sh plot
bash campaigns/finish_and_plot_skim_v4.sh studies
```

I job **in hold non contano** nell'attesa: sono le skim 2025 noJetHornVeto, che
sono state deprioritizzate apposta. Se un giorno servono, vanno rilasciate a
mano con `condor_release`.

Variabili d'ambiente: `V4_ERAS`, `V4_INPUT`, `V4_MANIFEST`, `V4_OUTPUT`,
`V4_PLOTS`, `V4_LOGS`, `V4_POLL`, `V4_ROC_MAX_FILES`.

## La ROC e la memoria

`dnn_roc_from_skims.py` rilegge gli skim con `AsNumpy`: su un'era grande arriva
a **23 GB di RSS** contro i 34 del cgroup, ed e' stata uccisa due volte, una
dall'OOM e una da un `timeout` troppo corto. Non metterle un timeout e non
farla girare insieme ad altro di pesante.

Da adesso c'e' anche la via breve:

```bash
bash campaigns/dnn_studies_skim_v4.sh roc --eras 2025 --roc-max-files 30
```

Legge al massimo 30 file ROOT per dataset, presi a passo costante su tutto il
dataset e non i primi 30, e riscala i pesi per `n_tot/n_letti`. Il peso per
evento viene dalla normalizzazione nei report, che e' globale e non dipende da
quanti file apri: quindi le rese restano corrette e cambia solo la precisione
statistica. Il tetto morde solo sui dataset grossi — il DY del 2025 ha 595 file,
i segnali del 2022EE ne hanno 1 e 3 — quindi non tocca niente dove non serve.
Con 30 file la ROC scende da 23 GB a meno di 2.

Il valore usato finisce in `max_files_per_dataset` dentro il JSON, cosi' un
risultato ottenuto su un sottoinsieme non si confonde con uno completo.

---

# PARTE 13 — Tutto in automatico

```bash
nohup bash campaigns/run3_full_chain.sh all > chain_full.log 2>&1 &
tail -f chain_full.log
```

Attende Condor fra uno stadio e l'altro e alza la priorità dei job che
sottomette. Stadi invocabili singolarmente per riprendere:

```bash
bash campaigns/run3_full_chain.sh skims
bash campaigns/run3_full_chain.sh manifests
bash campaigns/run3_full_chain.sh dy-weights
bash campaigns/run3_full_chain.sh histograms
bash campaigns/run3_full_chain.sh hadd
bash campaigns/run3_full_chain.sh deep-check
bash campaigns/run3_full_chain.sh studies
bash campaigns/run3_full_chain.sh status
```

Restringere a poche ere:

```bash
V4_ERAS=2024,2026 bash campaigns/run3_full_chain.sh dy-weights
```

Variabili d'ambiente riconosciute: `V4_ERAS`, `V4_NOHORN_ERAS`, `V4_SKIM_BASE`,
`V4_MANIFEST`, `V4_OUTPUT`, `V4_DY_OUTPUT`, `V4_DNN_REGIONS`, `V4_POLL`,
`V4_PRIORITY`.

Attenzione a `V4_DY_OUTPUT`: gli istogrammi dei pesi DY **non** stanno sotto
`post_dy`, hanno un albero proprio. Derivarlo da `V4_OUTPUT` rifarebbe da zero
quello che esiste e spezzerebbe la produzione su due percorsi.

---

# PARTE 14 — Gestione della coda

Alzare la priorità dei propri job:

```bash
CL=$(condor_q -constraint 'regexp("DYNJETS", JobBatchName)' -af ClusterId | sort -un)
condor_prio -p 100 $CL
```

Sospendere una produzione meno urgente per liberare slot:

```bash
condor_hold    -constraint 'regexp("AllVariables", JobBatchName) && JobStatus == 1'
condor_release -constraint 'regexp("AllVariables", JobBatchName)'
```

Se un submitter è ancora vivo, continuerà ad aggiungere job e ogni hold sarà
temporaneo. Controlla e, se serve, fermalo:

```bash
ps -u "$USER" -o pid,etime,args --no-headers | grep -E "run3_skim_v4|condorsubmit" | grep -v grep
```

Fermare un submitter non perde nulla di prodotto: la sottomissione riprende da
dove si era fermata al successivo `submit`.
