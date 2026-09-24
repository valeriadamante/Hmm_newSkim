# Campagne dell'analisi

Da root del repository: `source env.sh`.

| Script | Produzione |
|---|---|
| `dy_weights.sh` | Derivazione sequenziale componenti jet → pTμμ → N(jet) |
| `dnn_vbf_z.sh` | DNN, VBF, Z sideband (Sep03) |
| `dnn_vbf_h.sh` | DNN, VBF, H sidebands (Sep03) |
| `dnn_vbf_signal.sh` | DNN, VBF, Signal Fit (Sep03) |
| `all_variables.sh` | Variabili di maincfg in tutte le regioni/categorie con `store: true`, per era |
| `jet_horn_veto.sh` | Confronto centrale Data/DY con/senza horn veto |
| `dnn_studies_skim_v4.sh` | Binning-opt DNN e performance con/senza pesi, da skim_v4 |

Gli entry point usano `submit_campaign.sh` → `campaigns/workflow.py` → lo
stesso producer `histograms/scripts/{hists,systematics}.sh`. Le impostazioni di
fisica DNN e pesi sono lette dalle configurazioni esistenti in `config/campaigns`.
Gli script storici sono in `legacy/`; gli entry point degli skim restano separati.
`requested_workflow.sh` è stato rimosso.

## Interfaccia comune

```bash
bash campaigns/dnn_vbf_z.sh ACTION --mode central|syst|both --eras 2024,2025
```

`--mode` è `both` per DNN/all_variables, `central` per pesi/horn.
`--eras` omesso usa 2022,2022EE,2023,2023BPix,2024,2025; horn usa 2024,2025,2026.
Il default è `--systematics-layout split`; `--systematics-layout together` produce
le famiglie configurate insieme in `all/`. La scelta JES è rispettata in entrambi
i layout. `--families PU,Muon` seleziona un sottoinsieme nel layout split.

| Azione | Comportamento |
|---|---|
| `paths` | Mostra configurazione e percorsi |
| `check --stage histograms` | Controlla dataset e componenti attesi |
| `check --stage hadded` | Controlla raw e output per processo |
| `check --stage merged-eras` | Controlla gli hadd e la loro unione nelle ere richieste |
| `check --stage merged-syst` | Controlla Central + famiglie e merge sistematico per era |
| `check --stage merged` | Controlla il prodotto combinato ere + sistematiche |
| `check --stage all` | Riporta tutti gli stadi applicabili |
| `submit` | Sottomette mancanti e recupera dataset parziali/obsoleti |
| `local` | Stessa produzione in locale |
| `hadd` | Verifica i raw, ricostruisce gli hadd, verifica gli output |
| `merge-syst` | Verifica Central + tutte le famiglie selezionate e le unisce per era |
| `merge-era` | Verifica gli hadd, unisce le ere; con syst attive aggiorna anche i merge sistematici fisici e combinati |
| `plot` | Verifica gli input e produce i plot per era |
| `plot --merged` | Verifica e plotta la combinazione di ere |
| `finish` | Hadd → merge-syst se attivo → plot per era → merge-era → plot combinati |

`merge-eras` è un alias di `merge-era`. In modalità `syst` la produzione/hadd
riguarda solo le variazioni; merge e plot sistematici richiedono sempre anche
Central. `merge-syst --merged` aggiorna solo il merge sistematico dell'era
combinata, dopo aver verificato gli hadd delle ere combinate.

I controlli predefiniti aprono i ROOT con uproot, leggono gli istogrammi, verificano
file delle componenti, marker `failed_chunks`, dipendenze e timestamp. Gli output
aggregati devono contenere tutte le chiavi istogramma dei loro input. I raw DY
pesati devono essere successivi ai JSON dei pesi applicati. Questo non certifica
l'intera provenienza degli eventi o la correttezza numerica dei bin.

`submit` non considera completo un dataset solo perché esiste il file nominale:
se un componente manca, un ROOT non è leggibile, ci sono chunk falliti o i pesi
sono più recenti, forza il recupero del dataset interessato. `--force` forza
invece tutta la selezione. La gestione dei job già in coda resta quella del producer.

I merge scrivono piccoli file `.workflow_*.json` che registrano ere e famiglie:
un vecchio merge senza questa prova va ricostruito. Il nome combinato predefinito
è `Run3_2022_25` per le sei ere; per un sottoinsieme viene costruito dai nomi
espliciti (es. `Run3_2024_2025`). `--merged-era` lo personalizza. Il plotter riceve
l'elenco esatto delle ere per luminosità e sistematiche decorrelate.

Opzioni comuni:

- `--dry-run`: stampa il piano, senza scritture, submit o certificazione degli input.
- `--check-level files`: controllo rapido presenza/dimensione/timestamp, senza aprire ROOT.
- `--output-root PATH`: directory della produzione.
- `--plot-output PATH`: directory base dei plot (default `plots/campaigns`).
- `--regions CSV`, `--categories CSV`: selezioni esplicite per DNN/all_variables.

Se cambi selezioni su un percorso già prodotto, usa una nuova `--output-root`
o rigenera con `--force`: i timestamp non certificano le opzioni di una vecchia produzione.
Le azioni si fermano con codice 1 su input incompleti. `dy_weights run` ritorna 3
quando ha sottomesso uno stadio e attende Condor. Nessun comando attende i job in loop.

## DNN: esempio completo

Sostituire `dnn_vbf_z.sh` con `dnn_vbf_h.sh` o `dnn_vbf_signal.sh`:

```bash
bash campaigns/dnn_vbf_z.sh check --mode both --eras 2024,2025
bash campaigns/dnn_vbf_z.sh submit --mode central --eras 2024,2025
bash campaigns/dnn_vbf_z.sh submit --mode syst --eras 2024,2025
# Oppure un unico submit --mode both. Dopo il completamento dei job:
bash campaigns/dnn_vbf_z.sh finish --mode both --eras 2024,2025
```

Per controllare/eseguire ogni passaggio separatamente:

```bash
bash campaigns/dnn_vbf_z.sh hadd --mode both
bash campaigns/dnn_vbf_z.sh check --stage hadded --mode both
bash campaigns/dnn_vbf_z.sh merge-syst --mode both
bash campaigns/dnn_vbf_z.sh check --stage merged-syst --mode both
bash campaigns/dnn_vbf_z.sh plot --mode both
bash campaigns/dnn_vbf_z.sh merge-era --mode both
bash campaigns/dnn_vbf_z.sh check --stage merged --mode both
bash campaigns/dnn_vbf_z.sh plot --mode both --merged
```

Gli input/output rimangono sotto `Sep_03/DNN_VBF_{Z,H,Signal}_AllWeights`.
Per riprendere il layout storico Sep_03 usare `--systematics-layout together --jes total`.
I fit Combine restano negli script dedicati `combine/run_sr_fit.sh` e
`combine/run_sr_zcr_fit.sh`; vanno eseguiti dopo il check `merged-syst` di Signal/Z.

## Tutte le variabili

```bash
bash campaigns/all_variables.sh paths --eras 2024,2025
bash campaigns/all_variables.sh submit --mode both --eras 2024,2025
# Dopo i job:
bash campaigns/all_variables.sh finish --mode both --eras 2024,2025
```

Usa la directory `H_mumu/campaigns/AllVariables_AllWeights`.
Le variabili sono quelle di `maincfg.yaml`, incluse le DNN se configurate.

## Pesi sequenziali

```bash
bash campaigns/dy_weights.sh run --eras 2026
```

Ripetere dopo la conclusione dei job. Il comando verifica, sottomette se
necessario e ritorna; quando gli input sono completi esegue hadd/fit e passa
allo stadio successivo. Controlla anche che i payload finali siano aggiornati.
Non sottomette pTμμ prima del payload jet, né N(jet) prima dei due payload precedenti.

Azioni manuali:

```bash
bash campaigns/dy_weights.sh check --weight-stage jet --eras 2026
bash campaigns/dy_weights.sh submit --weight-stage jet --eras 2026
bash campaigns/dy_weights.sh hadd --weight-stage jet --eras 2026
bash campaigns/dy_weights.sh fit --weight-stage jet --eras 2026
bash campaigns/dy_weights.sh check-weights --weight-stage jet --eras 2026
```

Gli stadi sono `jet`, `ptll`, `njets`; `check --weight-stage all` li controlla
nell'ordine. `submit` manuale richiede uno stadio esplicito. Le ere 2022/2022EE e
2023/2023BPix richiedono entrambe le componenti della coppia, perché condividono
il fit/payload. Per 2024, 2025 e 2026 si fitta ciascuna era singolarmente.
I JSON vengono scritti nei percorsi configurati in `process_names.yaml`.
`--output-root` cambia gli input istogrammi (`jet/`, `ptll/`, `njets/`), non i JSON
usati dall'analisi. I fit producono anche i plot diagnostici dei pesi.

## Jet horn veto

```bash
# Check con/senza per 2025/2026, più riferimento 2024 con veto:
bash campaigns/jet_horn_veto.sh check --check-level files
# Sottomette il riferimento 2024 e controlla 2025/2026:
bash campaigns/jet_horn_veto.sh start
# Recupera tutti i mancanti/parziali della selezione:
bash campaigns/jet_horn_veto.sh submit
# Dopo i job:
bash campaigns/jet_horn_veto.sh finish
```

`--variant WithHornVeto|NoHornVeto|both` limita i check/submit/hadd.
Il 2024 resta il riferimento con veto; il confronto con/senza riguarda 2025/2026.
`validate` genera i manifest per le ere e varianti selezionate.

```bash
bash campaigns/jet_horn_veto.sh submit --weights analysis --eras 2024,2025
bash campaigns/jet_horn_veto.sh finish --weights analysis --eras 2024,2025
# Dopo aver derivato i pesi 2026:
bash campaigns/jet_horn_veto.sh submit --weights analysis --eras 2026
bash campaigns/jet_horn_veto.sh finish --weights analysis --eras 2026
```

`--weights none` (default) disabilita solo i reweight custom DY, mantenendo i
pesi nominali MC. Le due produzioni sono distinte: `JetHornVetoComparison` e
`JetHornVetoComparison_AllWeights`. I plot non rinormalizzano DY all'integrale
dei dati. La variante senza veto usa skim/manifest senza veto e disabilita il
veto anche nel produttore degli istogrammi.

## Sovrascrivere input e output

Tutti i sei script accettano `--input-dir` (alias `--input-root`) e
`--output-dir` (alias `--output-root`). I percorsi sono directory base, senza
l'era finale. `paths` mostra anche input ROOT, JSON e manifest effettivi.
`--json-root` permette di separare i JSON di bookkeeping dagli skim ROOT;
per default usa lo stesso percorso degli skim.

Quando cambi skim, specifica anche i manifest corrispondenti con
`--manifest-root`: i manifest possono contenere i percorsi dei vecchi file.
Se non esistono ancora, l'azione `validate` li genera. Esempio:

```bash
opts=(--eras 2024,2025
      --input-dir /percorso/skim
      --manifest-root /percorso/manifests
      --output-dir /percorso/istogrammi/DNN_Z)
bash campaigns/dnn_vbf_z.sh paths "${opts[@]}"
bash campaigns/dnn_vbf_z.sh validate "${opts[@]}"
bash campaigns/dnn_vbf_z.sh submit --mode both "${opts[@]}"
# Dopo i job, mantenendo gli stessi opts:
bash campaigns/dnn_vbf_z.sh finish --mode both "${opts[@]}"
bash campaigns/dnn_vbf_z.sh check --stage all --mode both "${opts[@]}"
```

Usa una directory di output distinta per ogni campagna. Gli override vanno
ripetuti a ogni comando; non modificano i default degli script.

Per horn, `--input-root` e `--manifest-root` indicano i percorsi con veto;
la variante senza veto aggiunge `_noJetHornVeto`. Per layout diversi usa
`--no-horn-input-root`, `--no-horn-manifest-root` e, se necessario,
`--no-horn-json-root`, che indicano percorsi esatti senza suffissi automatici.
Per i pesi, l'override dell'output riguarda gli istogrammi dei tre stadi:
i payload JSON restano nei percorsi configurati in `process_names.yaml`.

Il `finish` horn verifica ed esegue anche il merge delle ere per ciascuna
variante con almeno due ere selezionate. I plot di confronto restano per era
(con/senza veto e riferimento 2024–2025); `check --stage all` include i merge
applicabili. `merge-era` salta le varianti con una sola era.

## Pesi da skim_v4 e fit χ²

Per la produzione completa 2022–2026 (incluse 2022EE e 2023BPix), usare
`bash campaigns/run3_dy_weights_skim_v4.sh manifests` per sottomettere la
validazione degli ntuple selezionati da `skim_cfg`. `status` controlla i
manifest necessari ai tre stadi; quando è completo, `run` produce in ordine
gli istogrammi e i fit DY_012J → DY_ptll → DY_nRecoJet. Ripetere `run` dopo
la conclusione di ciascun blocco Condor. Gli input sono in `skim_v4`, i
manifest in `manifests_skim_v4` e gli istogrammi in `skim_v4/DY_weights`.
Il 2026 usa solo i processi attivati nel proprio `skim_cfg`.

Se ometti l'azione, lo script esegue `check`. Usa `bash`, perché gli entry point
usano opzioni Bash. Per controllare solo gli istogrammi jet di 2022 e 2023:

```bash
opts=(--eras 2022,2023 --mode central --weight-stage jet
      --input-dir /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4
      --manifest-root /eos/user/v/vdamante/H_mumu/manifests_skim_v4
      --output-dir /eos/user/v/vdamante/H_mumu/skim_v4/DY_weights)
bash campaigns/dy_weights.sh --stage histograms "${opts[@]}"
# Se occorre generare i manifest, poi produrre gli istogrammi:
bash campaigns/dy_weights.sh validate "${opts[@]}"
bash campaigns/dy_weights.sh submit "${opts[@]}"
# Dopo i job:
bash campaigns/dy_weights.sh hadd "${opts[@]}"
```

Per `fit` e `run` seleziona `2022,2022EE,2023,2023BPix`: i payload sono condivisi
per coppia. Check/submit/local/hadd consentono anche una singola era della coppia.
Gli output istogrammi dell'esempio sono sotto `skim_v4/DY_weights/jet/`.
Per la sequenza completa usa `run --weight-stage all` con le coppie complete,
e ripeti dopo la conclusione dei job.

Il fit jet (ggF 2J → 1J → 0J e VBF) usa ora χ² con scale non negative (NNLS).
Il precedente Poisson è commentato in `tools/derive_dy_012j_reweight.py`.
La varianza fissa è la somma delle varianze degli istogrammi di dati, background
(incluso DY già fittato, scalato) e componenti DY attive a normalizzazione nominale.
I bin con varianza nulla sono esclusi. La covarianza è quella della curvatura
locale senza vincoli; non propaga l'incertezza delle scale degli stadi precedenti.
I fit dei pesi pTμμ e N(jet) non sono modificati. Per rigenerare un vecchio payload
jet usa esplicitamente `fit --weight-stage jet`; `run` decide in base ai timestamp.
L'override output non sposta i payload configurati in `process_names.yaml`.

## Correlazioni delle sistematiche e JES

La modalità `--jes regrouped` (default di all_variables) usa:
11 famiglie separate, con correlazioni fra anni secondo il modello “simple”.
`--jes total` mantiene l'alternativa JES Total. Non usare entrambe nello stesso
prodotto. La configurazione `isCorrelated` / `Eras_correlated`, i dettagli dei
merge e i comandi per skim_v4 sono in
[../docs/SYSTEMATIC_CORRELATIONS.md](../docs/SYSTEMATIC_CORRELATIONS.md).

## Controllare le produzioni già esistenti (v3/v4)

I sei entry point accettano ora anche `sh campaigns/<script>.sh ...`.
Il check stampa subito campagna/stadio e poi l'avanzamento. `source env.sh`
abilita le dipendenze per aprire i ROOT; `--check-level files` controlla
presenza, dimensione e timestamp senza richiedere uproot.

Per la DNN H storica da skim_v3, prodotta sotto `Sep_03`:

```bash
sh campaigns/dnn_vbf_h.sh check --historical --mode both --check-level files
# Tutti gli stadi, inclusi quelli ancora mancanti:
sh campaigns/dnn_vbf_h.sh check --historical --mode both --stage all --check-level files
```

`--historical` è consentito solo con `check`: riconosce il vecchio layout
`all/` e `all_hadded/` quando `all/` esiste e riporta gli aggregati indipendentemente
dalla completezza dei raw. Continua a segnalare dipendenze mancanti/obsolete;
non richiede i nuovi receipt e **non certifica la nuova politica di correlazione**.
Per produzioni storiche a famiglie separate con JES Total aggiungere `--jes total`.

Per gli istogrammi jet dei pesi da skim_v4, nel percorso verificato:

```bash
sh campaigns/dy_weights.sh check --eras 2022,2023 --weight-stage jet \
  --mode central --stage histograms --check-level files \
  --output-dir /eos/user/v/vdamante/H_mumu/skim_v4/DY_weights
```

Sostituire `histograms` con `hadded` per controllare gli hadd, o con `all`
per tutti gli stadi applicabili (può segnalare aggregati non ancora prodotti).
Togliere `--check-level files` dopo `source env.sh` per aprire i ROOT e
controllarne leggibilità/contenuto.

**È `--output-dir` che seleziona gli istogrammi da controllare.**
`--input-dir .../skim_v4` da solo non cambia la produzione verificata e il check
non ricostruisce la provenienza v3/v4 dal contenuto degli istogrammi.
Usare la directory di output effettivamente indicata al submit.
Al momento della verifica in questa sessione, `H_mumu/skim_v4/` conteneva
`DY_weights/`; non risultava una directory DNN H sotto quella base.

## Submitter generico e selezione dei sample

Le campagne DNN passano il proprio file di configurazione al submitter comune:

```bash
sh campaigns/submit_campaign.sh config/campaigns/dnn_vbf_h_sep03.sh paths
sh campaigns/dnn_vbf_h.sh submit --mode both --systematics-layout together --jes total
```

`validate`, `submit`, `local`, `hadd`, `merge-syst`, `merge-eras`, `check`, `plot`
e `finish` condividono lo stesso motore. I file di campagna definiscono gruppi,
variabili, regioni, categorie, input ROOT/JSON, manifest, output, risorse e
famiglie. Gli override includono `--variables CSV`, `--datasets CSV`,
`--weights analysis|none` e `--dy-weights jet-component,ptll,njets` (anche vuoto).
`--weights none` disabilita i reweight custom, mantenendo i pesi nominali MC.

`region_auto` si risolve in `region_higgs` per Signal_Fit/H_sideband e
`region_inclusive` per Z_sideband/mass_inclusive. DY **ed EWK**, inclusi i
FlashSim configurati, seguono rispettivamente i campioni 105–160 e inclusivi.
La stessa regola è applicata dal produttore ai singoli istogrammi; per studi
espliciti esiste `hist_maker.py --no-region-sample-routing`.
Il gruppo `signals` contiene solo ggH/VBF nominali a massa 125, amcatnlo,
powheg e FlashSim quando configurati. I cataloghi dei dataset restano disponibili;
le varianti di segnale superflue sono escluse dalle selezioni di produzione.

Il submit segnala e salta dataset privi del manifest di validazione, prosegue
con gli input disponibili e ritorna 1 se ne restano indisponibili. I check
continuano a considerarli attesi. I recuperi forzati saltano comunque output con
job già attivi in Condor. Gli hadd della campagna ricevono la lista esatta dei
dataset selezionati: file di altre produzioni non vengono aggiunti all'hadd.

La risottomissione del 9 settembre 2026 e l'inventario degli input sono registrati
in `reports/sep03_recovery_20260909/`. Le directory `Flashsim_New` vuote dello
skim_v3 richiedono prima skim e validazione; non sono sostituite implicitamente
con le versioni FlashSim precedenti.


I file shell possono impostare anche i default del workflow:

```bash
CAMPAIGN_OPTIONS=(--mode both --systematics-layout together --jes total)
```

Il submitter generico legge questi argomenti prima di quelli della riga di
comando: gli override espliciti prevalgono. Le configurazioni Sep_03 includono
questi default per mantenere il layout esistente. Per una nuova produzione
separata usare `--systematics-layout split --jes regrouped --output-dir PATH`.

La verifica dei requisiti jet 2022–2026, i test e il limite legato agli skim
preesistenti sono descritti in
[../reports/sep03_recovery_20260909/jet_requirements.md](../reports/sep03_recovery_20260909/jet_requirements.md).

## Esecuzione parallela

Le tre DNN Sep_03 richiedono ora 8 CPU Condor e usano 8 thread ROOT per job.
`--threads N` cambia entrambi insieme; i job già sottomessi mantengono le risorse
con cui sono stati creati.

```bash
# Avvia le tre campagne contemporaneamente, con log separati:
sh campaigns/dnn_sep03.sh submit --threads 8
sh campaigns/dnn_sep03.sh check --check-level files
```

`CAMPAIGN_LOG_DIR` sceglie la directory dei tre log. Il launcher attende tutti
i processi e restituisce un errore se una campagna segnala input incompleti.
Le azioni interne di ciascuna campagna mantengono l'ordine delle dipendenze.
