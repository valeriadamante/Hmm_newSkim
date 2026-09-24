# Come scegliere la coppia di jet VBF

Quando piu' di due jet passano la selezione, quale coppia si prende?
Questo mini-studio confronta due definizioni a parita' di tutto il resto:

| strategia | coppia scelta |
|---|---|
| `leading` | i due jet di pT piu' alto fra quelli preselezionati |
| `maxmjj` | la coppia con m(jj) massima — quella che usa il framework oggi |

`maxmjj` non e' una proposta: e' gia' l'implementazione di
`analysis/AnalysisTools.h:FindVBFJets`, che scorre tutte le coppie e tiene
quella con la massa invariante piu' grande fra quelle sopra le soglie. Qui la
si rifa' **senza** soglie su m(jj) e |Δη| in modo che la scansione non parta
gia' tagliata a 400/2.5, e i tagli si applichino dopo.

## Come e' fatto

La coppia viene ridefinita **a monte di `prepare_rdf`**, sovrascrivendo nel nodo
grezzo solo tre colonne dello skim:

```
VBFJetIdx_1, VBFJetIdx_2, HasVBF
```

Da li' in avanti e' il framework a ricalcolare tutto il resto: `m_jj`,
`delta_eta_jj`, `vbfjet1_*`, `vbfjet2_*`, `Zeppenfeld_Var`, `pt_centrality`,
`R_pt`, `minDeltaPhi`, `minDeltaEtaSigned`, la soft activity ripulita contro i
due jet VBF, e quindi anche il **punteggio del DNN**, che prende dieci di quelle
variabili in ingresso. Nessuna e' riscritta a mano nello script: se cambia
`common/add_vars.py`, lo studio segue.

La preselezione dei jet e' `SelectedJet_IsOutsideHorn`, la stessa di
`FindVBFJets` (`--no-horn-preselection` per toglierla). La leg 1 e' sempre il
jet di pT piu' alto della coppia, anche per `maxmjj`: `vbfjet1_*` e `vbfjet2_*`
entrano nel DNN in quell'ordine.

## Segnale, fondo, punto di lavoro

| regione | segnale | fondo |
|---|---|---|
| `Signal_Fit` | `VBFHto2Mu_M125_powheg` | DY 105–160, tutte e due le meta' `GenVBFFilter==0/1` |
| `Z_sideband` | `EWK_2L2J_madgraph_herwig` | `DYto2Mu_M_50_amcatnloFXFX` |

Le due meta' del DY 105–160 si separano con il loro `additional_cuts` letto da
`samples.yaml`: senza, gli stessi eventi generati verrebbero contati due volte.

Punto di lavoro: pT ≥ 35/25 GeV sui due jet della coppia, m(jj) ≥ 400 GeV,
|Δη(jj)| ≥ 2.5 — cioe' la categoria `VBF_def` di `config/<era>/selections.yaml`.
Il denominatore delle efficienze e' `baseline && <regione di massa>`, prima di
qualunque richiesta sulla coppia.

Nella scansione in m(jj) il taglio in |Δη| resta fisso a 2.5 e viceversa:
muoverli insieme mescolerebbe due effetti in una curva sola.

## Uso

```bash
source env.sh
python3 studies/vbf_pair_definition/compare_vbf_pair_definitions.py \
    --era Run3_2024 --max-files-background 60
```

Un'era per invocazione: lo studio tira gli array in numpy e due ere insieme
riempiono la memoria. Per le altre ere basta cambiare `--era`:

```bash
for era in Run3_2022 Run3_2022EE Run3_2023 Run3_2023BPix Run3_2025; do
  python3 studies/vbf_pair_definition/compare_vbf_pair_definitions.py \
      --era "$era" --max-files-background 60
done
```

Il 2026 non ha il DNN: aggiungere `--no-dnn`.

Opzioni utili:

| opzione | effetto |
|---|---|
| `--regions Signal_Fit` | una regione sola |
| `--strategies leading` | una strategia sola |
| `--max-files-background N` | sottoinsieme dei file di DY, pesi riscalati di n_tutti/n_usati |
| `--max-files-signal N` | idem per il segnale; default 0 = tutti |
| `--no-dnn` | salta l'inferenza ONNX e i due pannelli che ne dipendono |
| `--no-horn-preselection` | ignora `SelectedJet_IsOutsideHorn` |
| `--threads N` | thread di RDataFrame; oltre 4 su lxplus si rischia l'OOM |

Il sottoinsieme di file e' preso a passo costante su tutto il dataset e i pesi
sono riscalati di `n_tutti/n_usati`: il denominatore di normalizzazione viene
dai report di **tutto** il dataset, quindi le rese restano non distorte.

## Cosa produce

Le immagini vanno sull'area web,
`/eos/user/v/vdamante/www/H_mumu/updates_September23/studies/vbf_pair_definition/<era>/`
(convenzione dal 23/09/2026); `json` e `root` restano in
`results/skim_v4/vbf_pair_definition/<era>/`. Con `--plot-output ''` finisce
tutto insieme nel repo.

Per ogni regione:

| file | contenuto |
|---|---|
| `<regione>_efficiency_vs_mjj.png/pdf` | efficienze S e B contro il taglio in m(jj), e S/√B |
| `<regione>_efficiency_vs_deta.png/pdf` | idem contro il taglio in \|Δη(jj)\| |
| `<regione>_dnn.png/pdf` | distribuzione del punteggio DNN al punto di lavoro, e S/√B contro il taglio sul DNN |
| `<regione>.json` | tutti i numeri: soglie, rese, efficienze, S/√B, miglior taglio sul DNN |
| `<regione>.root` | le stesse curve come TH1D |

Piu' una tabella riassuntiva a video con efficienza di segnale, di fondo e S/√B
al punto di lavoro, e il miglior taglio sul DNN per ciascuna strategia.

S/√B e' una cifra di merito per confrontare due definizioni sullo stesso
campione, non una sensibilita': non ha dentro ne' le sistematiche ne' la forma
del fit. Per quella servono le card di `combine/`.
