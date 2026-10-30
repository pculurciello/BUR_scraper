# Estrazione delle voci contenenti «bando»

`extract_bur_grants.py` legge soltanto i file `.txt` (anche `.TXT`) nella cartella
**`bur_parte_prima`**, incluse le sottocartelle annuali. I TXT devono essere
**già filtrati alla Parte Prima regionale**.
Non verifica intestazioni, non ritaglia sezioni e non converte PDF.

L'unico criterio di selezione è la regex **`\bbando\b`**, senza distinzione tra
maiuscole e minuscole. Passano `bando`, `BANDO`, `Bando`; non passano il plurale
`bandi`, parole come `abbandono` o voci che parlano soltanto di contributi.
Non si applicano più regole strict/broad, liste di beneficiari, requisiti di
finanziamento o esclusioni per argomento. Perciò anche un bando di gara o di
concorso passa questo primo stadio; l'eventuale conferma semantica resta a vLLM.

## Esecuzione senza modello

Python 3.10 o successivo; il client usa soltanto la libreria standard.

```bash
python extract_bur_grants.py bur_parte_prima --output results --candidates-only
```

La cartella predefinita è `./bur_parte_prima`, relativa alla directory da cui
si esegue il comando. L'argomento input è facoltativo:

```bash
python extract_bur_grants.py --output results --candidates-only
```

Si può indicare esplicitamente `bur_parte_prima` oppure un suo percorso assoluto
come argomento input. Il programma non cerca TXT nelle cartelle vicine, come
`bur_fvg`, e non effettua ripieghi su di esse se `bur_parte_prima` manca: termina
con codice 2.

I PDF e gli altri formati vengono ignorati e registrati nell'inventario. I TXT
UTF-8 (anche con BOM) sono letti direttamente, con ripiego CP1252 quando necessario.
Le directory `cache`, `.git`, `__pycache__` e l'output annidato sono escluse.
Un TXT vuoto è un errore; un TXT privo della parola bando produce zero risultati.
Non serve alcuna intestazione «PARTE PRIMA».

Se si parte dai TXT grezzi dello scraper, preparare separatamente la sezione con
`extract_bur_part_one.py`. Questo passaggio non viene avviato dal grant extractor.

## JSON prodotto

`results/candidates.json` è un array JSON UTF-8 con due campi per ogni voce:

```json
[
  {
    "text": "Bando recante i criteri e le modalità per la concessione e l’erogazione di aiuti a favore delle PMI, con unità operativa in regione e attive nella produzione agricola primaria, a supporto delle spese sostenute per la realizzazione di nuovi impianti arborei per l’anno 2026. Adozione.",
    "act": "Deliberazione della Giunta regionale 6 febbraio 2026, n. 143"
  }
]
```

Questo è l'output verificato per l'esempio:

```text
pag. 101 Deliberazione della Giunta regionale 6 febbraio 2026, n. 143 LR 24/2021, art. 3, commi 17-29. Bando recante i criteri e le modalità per la concessione e l’erogazione di aiuti a favore delle PMI, con unità operativa in regione e attive nella produzione agricola primaria, a supporto delle spese sostenute per la realizzazione di nuovi impianti arborei per l’anno 2026. Adozione.
```

- `text` comprende la frase che contiene la prima occorrenza di bando e le frasi
  conclusive della stessa voce, per esempio «Adozione.» o «Approvazione.».
  Se la frase inizia «Approvazione del bando», viene mantenuta anche quella parte.
- `act` identifica l'atto della voce, fino al numero, senza includere la normativa
  richiamata successivamente come base (nell'esempio `LR 24/2021...`). Si riconoscono
  forme estese di deliberazioni, decreti e leggi con date italiane o numeriche e
  alcune abbreviazioni. Se manca una data, si conserva l'eventuale citazione breve
  esplicita con `n.`. Non si inventano date o numeri: se non riconoscibile, `act`
  è `null` e la voce resta comunque nel JSON per revisione.
- Più occorrenze di bando nella stessa voce producono un solo record. Le voci
  distinte e le ricorrenze in documenti diversi non vengono deduplicate globalmente.

Le regex strutturali servono a separare le voci tramite `pag. N` e intestazioni
di atti, e a leggere la citazione: **non aggiungono criteri di pertinenza**.
Si gestiscono TXT multilinea e continui; gli a capo interni diventano spazi.
Non si applicano più finestre sovrapposte o troncamenti delle descrizioni lunghe.
In layout senza separatori riconoscibili, voci adiacenti possono risultare unite;
citazioni complesse o titoli spezzati possono richiedere revisione. La separazione
tra frasi usa punteggiatura e maiuscole, non un modello linguistico.

## Tracciabilità

`candidates.jsonl` conserva un record per riga con `text`, `act` e:

| Campo | Significato |
| --- | --- |
| `source` | Percorso relativo del TXT di origine |
| `start`, `end` | Offset Python, fine esclusa, della descrizione nel TXT normalizzato |
| `raw_text` | Descrizione prima di comprimere gli spazi: uguale a `txt[start:end]` |
| `page_before` | Ultimo riferimento `pag. N` prima della voce, oppure `null` |
| `page_after` | Primo riferimento `pag. N` dopo la voce, oppure `null` |

I riferimenti di pagina prima/dopo sono contesto documentale: non si presume
che il riferimento precedente o successivo sia quello corretto in ogni layout.
`act`, il TXT sorgente e questi riferimenti permettono di risalire al fascicolo;
lo script non scarica il testo integrale né costruisce URL non presenti nei dati.
Gli offset riguardano il TXT fornito dopo sostituzione CRLF, spazi non separabili
e trattini morbidi, non il PDF né il documento prima del prefiltraggio.

`inventory.jsonl` registra file letti, saltati o falliti e conteggi delle voci.
`filter_summary.json`, `rejected.jsonl` e `--filter-mode` non vengono più prodotti
(o accettati): le regole strict/broad sono state rimosse. Usare un output nuovo
oppure distinguere i vecchi report rimasti da esecuzioni precedenti.

## Conferma semantica opzionale con vLLM

Omettere `--candidates-only` per confermare semanticamente i risultati attraverso
un server compatibile con OpenAI Chat Completions e `response_format=json_schema`:

```bash
python extract_bur_grants.py bur_parte_prima --output results \
  --base-url http://localhost:8000/v1 \
  --model Qwen/Qwen2.5-14B-Instruct-AWQ --workers 1
```

Il modello indicato deve essere già caricato sul server. Ad esempio, per hardware
compatibile e memoria adeguata, installare vLLM separatamente sul server e avviare:

```bash
vllm serve Qwen/Qwen2.5-14B-Instruct-AWQ \
  --quantization awq --dtype half --max-model-len 16384 \
  --max-num-seqs 1 --gpu-memory-utilization 0.85
```

La quantizzazione e i requisiti hardware dipendono dalla versione vLLM e dalla
GPU. L'accuratezza del modello sui dati dell'utente non è stata misurata.
`--model` sovrascrive `VLLM_MODEL`; in loro assenza il nome predefinito del client
resta `Qwen/Qwen2.5-32B-Instruct`. `--base-url` sovrascrive `VLLM_BASE_URL`,
altrimenti si usa `http://localhost:8000/v1`. `VLLM_API_KEY` imposta la chiave
quando richiesta. `--workers` controlla la concorrenza (predefinito 4).

Il modello riceve **act + text**, così la citazione dell'atto resta disponibile
anche se separata dalla descrizione. Deve confermare misure contributive promosse
dall'amministrazione regionale e distinguere promotore e beneficiari; i programmi
regionali cofinanziati da fondi europei restano ammessi. Può escludere appalti o
assunzioni senza legame con contributi. Il primo stadio non anticipa tali giudizi.

Il client richiede JSON strutturato e verifica che citazioni e prove siano
sottostringhe esatte del contesto inviato. `decisions.jsonl` conserva tutti i
risultati (`include`, `exclude`, `uncertain`, oppure `error` del client);
`confirmed.jsonl` conserva solo quelli `include`. Questi report comprendono
anche il record estratto e il dettaglio delle referenze; `candidates.json`
resta il JSON compatto di primo stadio richiesto nell'esempio.

Le risposte validate sono salvate in `cache/`; la chiave comprende URL, modello,
prompt e contesto. Gli errori non vengono salvati. Il cambiamento di contesto
rispetto alle vecchie finestre può richiedere nuove inferenze. Ogni esecuzione
riscrive i risultati aggregati; una modalità `--candidates-only` non aggiorna
vecchi file di decisione. Timeout socket 180 secondi, fino a tre tentativi,
temperatura 0 e massimo 4096 token di risposta. Poiché le descrizioni non sono
troncate, quelle molto lunghe possono superare il contesto del modello e produrre
un errore da esaminare invece di una falsa esclusione.

## Codici di uscita e test

0 indica nessun errore di lettura/inferenza, anche con zero candidati o decisioni
incerte; 2 indica errori di lettura/inferenza o argomenti CLI non validi.

```bash
python -m unittest -v test_extract_bur_grants.py test_scrape_bur_fvg.py test_extract_bur_part_one.py
```

I test includono l'esempio esatto dell'utente, maiuscole/minuscole, confini di
parola, frasi complete e conclusive, separazione dalle norme citate, TXT multilinea
e continui, tracciabilità, citazioni mancanti, API simulata e cache. Non contattano
un modello reale. I candidati in memoria e l'array JSON possono richiedere
esecuzioni separate per anno su raccolte grandi.
