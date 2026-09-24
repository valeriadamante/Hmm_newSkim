# Preparazione RDF e istogrammi per i pesi DY

`common.prepare_rdf.prepare_rdf` prepara variabili, selezioni e pesi finali,
partendo da un RDF di skim grezzo oppure da file ROOT. Va chiamata una sola
volta per grafo, prima di `Histo1D`, `Snapshot`, `AsNumpy`, ecc.
Usare l'ambiente di analisi (`source env.sh`) e inizializzare il runtime ROOT
come negli altri script del progetto.

```python
from common.utilities import initialize_root_runtime
from common.prepare_rdf import prepare_rdf

initialize_root_runtime()
nodes = prepare_rdf(
    rdf=raw_skim_rdf,
    dataset_name=dataset_name, era=era, is_data=False,
    selections_cfg=sel_cfg, systematics_cfg=syst_cfg,
    seg_dict=dataset_seg_dict,
    enable_dy012j=True, enable_dyptll=False, enable_dynjets=False,
    split_jet_multiplicity=True,
)
rdf = nodes['inclusive']
for label, node in nodes.items():
    # Ad esempio: node.Snapshot('Events', f'{label}.root', columns)
    pass
```

Il risultato è un dizionario ordinato: `inclusive` per primo, poi le componenti
nominate ggF 0J/1J/>=2J hard/PU e VBF hard/PU, incluse le viste inclusive delle
categorie. `list(nodes.values())` dà la lista degli RDF. Le componenti ggF/VBF
sono esclusive entro la rispettiva selezione; le viste `DY_inclusive_*` sono
somme delle componenti e non vanno sommate di nuovo. I dati restituiscono solo
`inclusive`; input vuoti restituiscono `{}`. Il matching richiede gli indici
reco/gen. Le componenti restituite sono nominali; le selezioni delle variazioni
rimangono disponibili nel nodo inclusivo. `prepare_region_dataframes` costruisce
le viste per regione/categoria/sistematica, compresi i DNN nelle sideband.

`seg_dict` deve contenere la normalizzazione dell'intero dataset anche quando
si lavora per batch. `enable_custom_weights=False` disattiva i tre ripesamenti
custom, mantenendo i pesi nominali e la normalizzazione DY. I payload seguono
la configurazione per era; si possono passare esplicitamente con `reweight_jsons`,
altrimenti vengono riletti dal blocco `reweight_jsons` del processo del dataset in
`config/<era>/process_names.yaml`. Non esiste un percorso di default cablato nel
codice: le posizioni dei payload cambiano solo modificando la configurazione.
Per lavori DNN ripetuti, il chiamante libera il registro delle predizioni al
termine, come fa `hist_maker`.

I tre entry point condividono gli argomenti input/output di `hist_maker`:

| Script | Pesi custom applicati | Variabili e categorie |
|---|---|---|
| `hist_maker_dy012j_reweighting.py` | Nessuno | massa e eta signed vs pt dei jet; ggF/VBF con componenti |
| `hist_maker_dyptll_reweighting.py` | DY012J | pt_mumu; ggF_0J, ggF_1J, ggF_ge2J, VBF_ge2J |
| `hist_maker_dynjet_reweighting.py` | DY012J e DYptll | N_SelectedJets; ggF, VBF |

Tutti usano `Z_sideband` e `Central`. I parametri di fase in `STAGE_SETTINGS`
prevalgono sugli argomenti CLI di variabili, categorie, sistematiche e pesi.
Eseguire ciascuno script anche sui dati e sui background necessari al fit.
La divisione in file del primo passaggio segue l'abilitazione per processo già
usata da `hist_maker`; sui dati produce gli istogrammi inclusivi.

```bash
python3 histograms/hist_maker_dyptll_reweighting.py \
  --era Run3_2024 --dataset-name DYto2L_M_50_amcatnloFXFX \
  --root-input /path/to/skim --json-input /path/to/reports \
  --output-file /path/to/ptll_inputs.root
```

Gli script producono gli input: la derivazione dei nuovi payload resta nei
rispettivi `tools/derive_dy_*_reweight.py`.
