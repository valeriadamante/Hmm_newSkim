# Correlazioni delle sistematiche fra ere

Le proprietà sono lette da `config/Run3_<era>/systematics.yaml` nello stesso
blocco che contiene `name`. Funzionano per `systematics`, `weights`,
`derived_systematics` e `qcd_scale` (con override nelle singole `variations`).
Il nome della nuisance è risolto da `common/systematic_correlations.py`.

```yaml
# Una nuisance comune a tutte le ere
isCorrelated: true
Eras_correlated: all

# Una nuisance indipendente per ogni era fisica (2022 e 2022EE incluse)
isCorrelated: false

# Una nuisance comune solo a queste sub-ere; le altre rimangono indipendenti
isCorrelated: true
Eras_correlated: [2022, 2022EE]

# Due gruppi indipendenti, ciascuno correlato internamente
isCorrelated: true
Eras_correlated: [[2022, 2022EE], [2023, 2023BPix]]
```

Configurare coerentemente i blocchi corrispondenti nelle ere coinvolte.
Sono accettati nomi con o senza `Run3_`, anni YAML numerici o stringhe.
Con `isCorrelated: false`, `Eras_correlated` viene ignorato. Con `true` e senza
`Eras_correlated` si assume `all`. Se entrambi i campi sono assenti, resta la
convenzione precedente, determinata dal placeholder `{era}` nel nome.
Gruppi vuoti, sovrapposti o con duplicati vengono rifiutati.

Esempio con `name: CMS_example_{era}`:

| Configurazione | Era | Nome della nuisance |
|---|---|---|
| `false` | 2022EE | `CMS_example_2022EE` |
| `true`, `all` | qualsiasi | `CMS_example` |
| `true`, `[2022, 2022EE]` | 2022 oppure 2022EE | `CMS_example_2022_2022EE` |
| `true`, `[2022, 2022EE]` | 2023 | `CMS_example_2023` |

Se il nome non contiene `{era}`, il suffisso necessario viene aggiunto.
Non cambiano i nomi delle colonne degli skim: cambia il nome della nuisance
nei template ROOT e quindi nelle datacard. I builder che scoprono le coppie
Up/Down dagli istogrammi ereditano automaticamente queste correlazioni.

## JES: modello “simple” della tabella fornita

Si usano le sorgenti JetMET regrouped già disponibili negli skim, non JES Total
insieme alle sorgenti. La configurazione copre tutte le sette ere 2022–2026.

| Nuisance regrouped | Sorgenti della tabella | Fra anni |
|---|---|---|
| Absolute | AbsoluteMPFBias, AbsoluteScale, Fragmentation, PileUpDataMC, PileUpPtRef, RelativeFSR, SinglePionECAL, SinglePionHCAL | 100% |
| BBEC1 | PileUpPtBB, PileUpPtEC1, RelativePtBB | 100% |
| EC2 | PileUpPtEC2 | 100% |
| HF | PileUpPtHF, RelativeJERHF, RelativePtHF | 100% |
| FlavorQCD | FlavorQCD | 100% |
| RelativeBal | RelativeBal | 100% |
| Absolute_year | AbsoluteStat, RelativeStatFSR, TimePtEta | indipendenti |
| BBEC1_year | RelativeJEREC1, RelativePtEC1, RelativeStatEC | indipendenti |
| EC2_year | RelativeJEREC2, RelativePtEC2 | indipendenti |
| HF_year | RelativeStatHF | indipendenti |
| RelativeSample_year | RelativeSample | indipendenti |

Le sorgenti indipendenti fra anni sono correlate fra 2022/2022EE e fra
2023/2023BPix. 2024, 2025 e 2026 hanno ciascuno una nuisance distinta.
Questa è un'applicazione della colonna “simple” della tabella dell'utente;
non implementa coefficienti parziali del modello “realistic”.
Le altre sistematiche mantengono la precedente politica, ora esplicita:
JER, muoni, PU ed EWK PS separate per era; QCD/PDF correlate fra ere secondo
le rispettive etichette di processo.

## Produzione, merge e plot

Le campagne DNN/all_variables usano per default `--jes regrouped`, con 11
famiglie JES prodotte separatamente. Le famiglie con suffisso `_year` vengono
tradotte nella sorgente dello skim dell'era corrente: ad esempio
`JESRegrouped_Absolute_year` → `JESRegrouped_Absolute_2022EE`.
`--jes total` seleziona il precedente modello JES Total. Mantieni la stessa
opzione in submit/check/hadd/merge/plot. Il plot rifiuta il doppio conteggio di
Total e regrouped quando entrambi sono presenti.

```bash
opts=(--eras 2022,2022EE,2023,2023BPix --jes regrouped
      --input-dir /eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4
      --manifest-root /eos/user/v/vdamante/H_mumu/manifests_skim_v4
      --output-dir /eos/user/v/vdamante/H_mumu/skim_v4/DNN_VBF_Z_JESRegrouped)
bash campaigns/dnn_vbf_z.sh submit --mode both "${opts[@]}"
# Dopo i job:
bash campaigns/dnn_vbf_z.sh finish --mode both "${opts[@]}"
bash campaigns/dnn_vbf_z.sh check --mode both --stage all "${opts[@]}"
```

Per una sola componente: `--families JESRegrouped_Absolute_year --mode syst`.
Per H/Signal/all_variables sostituire lo script e usare un output dedicato.

Il merge ere costruisce **template con la resa totale**, variando soltanto
le ere interessate dalla nuisance. Esempio: nominali 10 e 20, variazione +2
nella prima era → nominale combinato 30, template variato 32 (non 12).
Per input contenenti solo variazioni, il comando diretto richiede Central:

```bash
python3 tools/hmumu.py merge-eras /produzione/PU_hadded \
  --nominal-dir /produzione/Central_hadded \
  --eras 2022,2022EE --output-era 2022_2022EE --run
```

Le campagne passano automaticamente `--nominal-dir`. Le scritture sono atomiche
per file. I plot risolvono i nomi dalla stessa configurazione, sommano le
variazioni correlate e combinano le nuisance indipendenti in quadratura.

Dopo una modifica delle correlazioni, rigenerare i template interessati
(`submit --force`, o una nuova directory di output), quindi hadd e merge.
Rinominare soltanto i file o rifare soltanto i plot non applica la nuova policy.
I vecchi merge non completati con i nominali vanno ricostruiti; i receipt delle
campagne hanno una nuova versione e non certificano i vecchi merge.
