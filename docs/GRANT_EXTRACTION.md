# Estrazione delle voci contenenti «bando»

`extract_bur_grants.py` legge soltanto i TXT di `./bur_parte_prima`, incluse le
sottocartelle annuali. L'input è già limitato alla Parte Prima regionale: non
vengono cercate intestazioni, convertiti PDF o ritagliate sezioni.

## Formato dell'input: una voce per riga

Ogni riga fisica non vuota deve contenere una sola voce completa:

```text
[atto: tipo, data e numero] [eventuale base normativa] [titolo completo] pag. NN.
```

Il riferimento `pag. NN` alla fine della riga è la pagina BUR del testo integrale
di **quell'atto**. Non viene mai ricavato dalla riga precedente o successiva.
I punti interni, gli atti citati nel titolo e i riferimenti a pagine precedenti
non creano altre voci. Non usare TXT in cui la stessa voce è spezzata su più
righe o più voci sono unite sulla stessa riga: completare prima la preparazione.

L'unico criterio di selezione resta **`\bbando\b`**, senza distinzione tra
maiuscole e minuscole. `bandi`, `abbandono` e le voci con soli riferimenti a
contributi non vengono selezionati. Anche bandi di gara o di concorso passano
il primo stadio: l'eventuale conferma semantica resta al modello vLLM.

## Esecuzione senza modello

Python 3.10 o successivo; nessuna dipendenza per il client:

```bash
python extract_bur_grants.py --output results --candidates-only
```

Il percorso predefinito è `./bur_parte_prima`, relativo alla directory di
esecuzione. Per un percorso esplicito:

```bash
python extract_bur_grants.py /dati/bur_parte_prima --output results --candidates-only
```

Si leggono anche estensioni `.TXT`. PDF e altri formati sono saltati e registrati
nell'inventario; `cache`, `.git`, `__pycache__` e l'output annidato sono esclusi.
Il programma non ripiega sulla cartella grezza `bur_fvg` se l'input manca.
I TXT sono decodificati UTF-8 (anche con BOM), con ripiego CP1252.

## Campi di candidates.json e candidates.jsonl

Esempio di una riga sorgente:

```text
Deliberazione della Giunta regionale 6 febbraio 2026, n. 143 LR 24/2021, art. 3, commi 17-29. Bando recante i criteri e le modalità per la concessione e l’erogazione di aiuti a favore delle PMI, con unità operativa in regione e attive nella produzione agricola primaria, a supporto delle spese sostenute per la realizzazione di nuovi impianti arborei per l’anno 2026. Adozione. pag. 101.
```

Se è la prima riga di `2026/esempio.txt`, `candidates.json` contiene:

```json
[
  {
    "text": "Bando recante i criteri e le modalità per la concessione e l’erogazione di aiuti a favore delle PMI, con unità operativa in regione e attive nella produzione agricola primaria, a supporto delle spese sostenute per la realizzazione di nuovi impianti arborei per l’anno 2026. Adozione.",
    "act": "Deliberazione della Giunta regionale 6 febbraio 2026, n. 143",
    "legal_references": "LR 24/2021, art. 3, commi 17-29.",
    "page": 101,
    "source": "2026/esempio.txt",
    "line_number": 1,
    "parse_warnings": []
  }
]
```

| Campo comune ai due output | Significato |
| --- | --- |
| `text` | Titolo completo dell'atto, senza citazione iniziale, base normativa iniziale e `pag. NN` finale |
| `act` | Citazione dell'atto emittente: tipo, data se presente e numero |
| `legal_references` | Base normativa iniziale separata dal titolo; `null` se assente o non separabile con certezza |
| `page` | Numero intero della pagina BUR indicata alla fine della stessa riga; `null` se manca |
| `source` | Percorso del TXT relativo alla directory di input |
| `line_number` | Numero di riga sorgente, a partire da 1; conta anche le righe vuote |
| `parse_warnings` | Anomalie da controllare; lista vuota per una voce riconosciuta |

Il titolo non viene più tagliato alla sola frase contenente bando. Per esempio,
«Approvazione della graduatoria. Bando 2026. Adozione.» resta interamente in
`text`. Riferimenti a leggi e atti **dentro il titolo** restano nel titolo e non
sostituiscono `act`. Più occorrenze di bando nella stessa riga producono un solo
record. Lo stesso atto in documenti diversi resta distinto per fonte.

La separazione della base normativa riconosce prefissi come `LR 24/2021`,
`L. R. 24/2021`, `Legge regionale ...`, articoli e commi, seguiti dal titolo.
I punti delle abbreviazioni e i numeri degli articoli non sono confini di frase.
Non si inventano valori quando una citazione o il confine con il titolo non è
riconoscibile: si conserva il testo e si segnala l'anomalia. Queste restano regole
strutturali deterministiche, quindi impaginazioni non conformi o prefissi insoliti
richiedono revisione.

### Audit aggiuntivo nel JSONL

`candidates.json` è un array JSON UTF-8; `candidates.jsonl` ha un oggetto per riga.
Tutti i campi della tabella hanno **gli stessi valori** nei due formati. Il JSONL
aggiunge:

- `start` e `end`: offset Python della porzione di titolo, fine esclusa;
- `raw_text`: titolo prima della compressione degli spazi, uguale a `txt[start:end]`;
- `raw_entry`: intera riga originale normalizzata, senza terminatore di riga.

Gli offset riguardano il TXT fornito dopo sostituzione di CRLF, spazi non separabili
e trattini morbidi, non il PDF o il documento prima del prefiltraggio.
`page_before` e `page_after` sono rimossi: il campo corretto è `page` e appartiene
alla stessa riga. `source`, `act` e `page` consentono di individuare il fascicolo
e la pagina dell'atto; il programma non scarica il testo integrale né inventa URL.

### Anomalie

Una riga con bando resta candidata anche in presenza di:

- `missing_trailing_page`: nessun riferimento `pag. NN` valido a fine riga;
- `unrecognized_act`: nessuna citazione iniziale riconoscibile, quindi `act=null`;
- `ambiguous_legal_basis`: base normativa iniziale riconosciuta ma confine con il
  titolo incerto; il testo resta in `text`, senza eliminarlo;
- `empty_title`: titolo vuoto dopo la separazione dei metadati.

Non si cerca una pagina, un atto o un titolo nelle altre righe. `inventory.jsonl`
registra letture, salti, errori, numero di candidati e `candidates_with_warnings`.
I vecchi report `filter_summary.json` e `rejected.jsonl` non sono prodotti.
Usare una directory pulita per distinguere gli output correnti da file preesistenti.

## Conferma opzionale con vLLM

Omettere `--candidates-only` per avviare la conferma con un modello già servito
tramite API OpenAI Chat Completions compatibile con `response_format=json_schema`:

```bash
python extract_bur_grants.py --output results \
  --base-url http://localhost:8000/v1 \
  --model Qwen/Qwen2.5-14B-Instruct-AWQ --workers 1
```

Il modello riceve **act + legal_references + text**, in modo da poter controllare
anche la base normativa separata. Deve confermare misure contributive promosse
dall'amministrazione regionale, distinguendo promotore e beneficiari. I programmi
regionali cofinanziati da fondi europei restano ammessi; appalti e assunzioni senza
legame con contributi possono essere esclusi dal modello.

Il nome passato deve corrispondere a quello servito da vLLM; hardware e memoria
necessari dipendono dal modello e dalla quantizzazione. L'accuratezza sul corpus
non è stata misurata. `--model` sovrascrive `VLLM_MODEL`; in loro assenza il default
resta `Qwen/Qwen2.5-32B-Instruct`. `--base-url` sovrascrive `VLLM_BASE_URL`, altrimenti
si usa `http://localhost:8000/v1`. La chiave, se richiesta, è `VLLM_API_KEY`.
`--workers` controlla la concorrenza (default 4).

Il client verifica JSON strutturato e citazioni/prove presenti esattamente nel
contesto inviato. `decisions.jsonl` conserva decisioni `include`, `exclude`,
`uncertain` o errori del client; `confirmed.jsonl` soltanto `include`.
La cache in `cache/` comprende URL, modello, prompt e contesto: la nuova
separazione dei campi può richiedere nuove inferenze. Gli errori non sono salvati.
Timeout socket 180 secondi, fino a tre tentativi, temperatura 0 e massimo 4096
token di risposta. Titoli molto lunghi possono superare il contesto del modello;
non vengono troncati o reinterpretati come esclusioni.

Gli output aggregati sono riscritti; la modalità `--candidates-only` non aggiorna
vecchi file di decisione. Un'uscita 0 indica assenza di errori di lettura/inferenza,
anche con zero candidati o anomalie di parsing da rivedere. Un'uscita 2 indica
errori di lettura/inferenza o argomenti CLI non validi.

## Test

```bash
python -m unittest -v test_extract_bur_grants.py test_scrape_bur_fvg.py test_extract_bur_part_one.py
```

Sono verificati i campi dell'esempio, pagine associate alla riga corretta,
conservazione del titolo completo, separazione delle norme iniziali, citazioni
interne al titolo, abbreviazioni, righe vuote, metadati mancanti, coerenza
JSON/JSONL, input TXT predefinito e API/cache simulate. Nessun modello reale è
contattato dai test. I candidati sono mantenuti in memoria: per archivi grandi
si possono usare esecuzioni separate per anno con directory di output distinte.
