# Estrazione degli atti relativi a contributi

`extract_bur_grants.py` analizza ricorsivamente una directory di sommari BUR FVG
(ad esempio `BUR_fvg` o `bur_fvg`) in due passaggi:

1. **Filtro deterministico:** separa le voci usando intestazioni di atti e cerca
   espressioni regolari per leggi, decreti, deliberazioni e termini contributivi.
2. **Conferma semantica:** invia solo le voci candidate a un server vLLM con API
   OpenAI compatibile; richiede JSON strutturato ed estratti letterali verificabili.

La classificazione comprende leggi, decreti del Presidente della Regione,
decreti di direttori anche centrali/di servizio e deliberazioni. Comprende
istituzione e disciplina delle misure, bandi, criteri, proroghe, graduatorie,
concessioni, revoche e liquidazioni. Il modello deve escludere appalti, assunzioni
e contabilità senza un collegamento esplicito a contributi. Si tratta quindi
di un censimento ampio degli atti contributivi, non soltanto di bandi aperti.

## Installazione

Python **3.10 o successivo**. Dalla radice del repository:

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-extraction.txt
```

L'estrattore usa la libreria standard per l'API; non richiede il client OpenAI.
Le dipendenze documentali sono importate soltanto per il formato richiesto.
Sono supportati TXT, Markdown, PDF con testo, HTML/HTM, XML e DOCX. I PDF
scansionati richiedono OCR preventivo; lo script non esegue OCR.

## Configurazione vLLM e modello

Un punto di partenza è **Qwen/Qwen2.5-32B-Instruct**, modello multilingue istruito
che supporta l'italiano. Non è stato confrontato su un campione annotato di
questo archivio: la scelta non garantisce accuratezza o completezza.
Installare vLLM nell'ambiente del server, separatamente dal client:

```bash
python -m pip install vllm
vllm serve Qwen/Qwen2.5-32B-Instruct --max-model-len 16384
```

Servono GPU e memoria adeguate ai pesi, alla precisione e alla concorrenza.
Configurare parallelismo o quantizzazione secondo l'hardware e la versione
vLLM. Il modello da 32 miliardi di parametri non è adatto a ogni GPU.
Se si usa `--served-model-name` sul server, passare lo stesso nome a `--model`.
Il server deve supportare `response_format` di tipo `json_schema`; una risposta
HTTP 400 relativa a questo parametro richiede una versione/configurazione
compatibile. Lo script non ripiega silenziosamente su risposte non strutturate.

Per server remoto e autenticato (esempio shell POSIX):

```bash
export VLLM_BASE_URL='http://SERVER:8000/v1'
export VLLM_MODEL='Qwen/Qwen2.5-32B-Instruct'
# Impostare VLLM_API_KEY nell'ambiente se il server richiede una chiave.
python extract_bur_grants.py BUR_fvg --output results
```

L'estrattore invia il testo delle voci candidate al server indicato. Il valore
predefinito è `http://localhost:8000/v1`; non contatta servizi di inferenza
esterni automaticamente. I certificati HTTPS sono verificati dal trust Python.

## Esecuzione

Prima controllare i candidati senza avviare il modello:

```bash
python extract_bur_grants.py BUR_fvg --output results --candidates-only
```

Poi eseguire la conferma:

```bash
python extract_bur_grants.py BUR_fvg --output results \
  --base-url http://localhost:8000/v1 \
  --model Qwen/Qwen2.5-32B-Instruct --workers 4
```

Per usare i risultati dello scraper di questo repository:

```bash
python scrape_bur_fvg.py --dal 1999 --al 2026 --output bur_fvg
python extract_bur_grants.py bur_fvg --output results --candidates-only
python extract_bur_grants.py bur_fvg --output results
```

Lo scraper deve avere terminato; controllare prima i suoi avvisi e stati di
copertura. L'estrattore non certifica né corregge `da_verificare`, i ripieghi
sulle prime pagine dell'integrale o i titoli discordanti. Gli anni indicano
la raccolta da fornire: l'estrattore non impone un filtro cronologico, perché
una voce del 2026 può richiamare una legge antecedente al 1999.

Quando trova un PDF e un TXT UTF-8 non vuoto con lo stesso nome base, preferisce
il TXT e registra il PDF come saltato. Questo evita di elaborare entrambe le
copie prodotte dallo scraper. Se il TXT non è leggibile in UTF-8 o è vuoto,
il PDF resta elaborabile. Le directory `cache`, `.git` e `__pycache__` sono
escluse; CSV, JSON e gli altri formati non supportati sono registrati come
saltati. Usare una directory di output dedicata, diversa dall'input.

## Opzioni

| Opzione | Valore predefinito | Significato |
| --- | --- | --- |
| `input` | obbligatorio | Cartella dei sommari, ricerca ricorsiva |
| `--output` | `bur_grants_output` | Cartella dei risultati e della cache |
| `--base-url` | `VLLM_BASE_URL` oppure `http://localhost:8000/v1` | URL API con `/v1` |
| `--model` | `VLLM_MODEL` oppure `Qwen/Qwen2.5-32B-Instruct` | Nome del modello servito |
| `--workers` | `4` | Richieste concorrenti, almeno 1 |
| `--candidates-only` | disattivato | Esegue soltanto lettura e filtro regex |

Il client usa temperatura 0, massimo 4096 token di risposta, timeout socket di
180 secondi e fino a tre tentativi con pause di 1 e 2 secondi. Le voci lunghe
sono divise in finestre da 10000 caratteri, con sovrapposizione di 1500.
Il limite in caratteri non garantisce di rispettare qualsiasi contesto in token:
un errore di contesto o una risposta troncata resta un errore, mai un'esclusione.

## Risultati e schema

Ogni riga JSONL è un oggetto JSON indipendente, codificato UTF-8.

| File | Contenuto |
| --- | --- |
| `inventory.jsonl` | Un record per file: lettura, conteggi, errori o motivo del salto |
| `candidates.jsonl` | Voci selezionate dalle regex con fonte, testo e offset |
| `decisions.jsonl` | Tutte le decisioni del modello, anche incerte e fallite |
| `confirmed.jsonl` | Solo voci con decisione `include` e relativi riferimenti |
| `cache/*.json` | Risposte validate, riutilizzate nei rerun |

Una decisione comprende:

```json
{
  "source": "2026/BUR_1_02_01_ordinario.txt",
  "start": 0,
  "end": 77,
  "text": "Legge regionale 1/2026. Disposizioni per la concessione di contributi alle imprese.",
  "decision": "include",
  "reason": "La voce disciplina contributi alle imprese.",
  "references": [
    {
      "kind": "law",
      "citation": "Legge regionale 1/2026",
      "role": "subject",
      "evidence": "Disposizioni per la concessione di contributi alle imprese."
    }
  ]
}
```

L'esempio è inventato e non identifica un atto reale. Gli offset `start` e `end`
sono indici Python (fine esclusa) nel testo estratto e normalizzato, non nei byte
originali né nelle pagine del PDF. Il codice sostituisce CRLF, spazi non separabili
e trattini morbidi prima del filtro.

`kind` assume `law`, `presidential_decree`, `directors_decree` o `deliberation`.
`role=subject` identifica l'atto oggetto della voce; `cited_basis` una norma
richiamata come base della misura. Non si inventano campi di numero o data mancanti.
`citation` ed `evidence` devono essere sottostringhe esatte del testo candidato:
il client verifica tale condizione. Questa verifica impedisce citazioni testuali
inesistenti, ma non prova da sola la correttezza dell'associazione semantica.

`decision` assume `include`, `exclude`, `uncertain`; il client aggiunge `error`
per problemi API, risposte troncate o JSON non validabile. Le voci `uncertain`
richiedono revisione umana; gli errori richiedono diagnosi e nuovo tentativo.
Lo stesso atto può ricorrere in più fascicoli o finestre: non viene applicata
una deduplicazione globale dei riferimenti.

## Ripresa, codici di uscita e controlli

Rieseguire lo stesso comando per riutilizzare la cache. La chiave comprende
URL del server, modello, prompt, schema e testo candidato; gli errori non sono
salvati. Se cambiano i pesi dietro lo stesso nome del modello, rimuovere la cache
o usare un'altra cartella di output. La cache contiene i testi citati come prove.
I file aggregati vengono riscritti, non accodati. Le decisioni sono salvate
progressivamente; un'interruzione conserva le risposte già in cache.
`--candidates-only` non aggiorna gli eventuali vecchi file di decisione.

- **0:** nessun errore di lettura o inferenza; non certifica la completezza,
  non implica la presenza di candidati e può includere decisioni `uncertain`.
- **2:** errori di lettura/inferenza, oppure argomenti CLI non validi.

Prima del censimento completo, annotare manualmente un campione di anni e
formati e misurare precisione e richiamo, includendo anche voci scartate dalle
regex. Voci su più colonne, intestazioni spezzate o assenti, estrazione PDF
imprecisa, OCR parziale e lessico non coperto possono causare omissioni.
L'estrattore lavora sui sommari: non recupera informazioni presenti soltanto
nel testo integrale. Per grandi archivi la lista dei candidati è mantenuta in
memoria e può richiedere esecuzioni separate per anno, con output distinti.

## Test

Dalla radice del repository:

```bash
python -m unittest -v test_extract_bur_grants.py test_scrape_bur_fvg.py
```

I test non contattano siti o modelli reali. Coprono tipi di atto, separazione
delle voci, finestre e offset, validazione delle prove, API simulata e cache,
errori API e integrazione con le coppie PDF/TXT dello scraper. La raccolta
1999–2026 e l'inferenza con vLLM reale non sono state eseguite per questa aggiunta.
