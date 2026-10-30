# Estrazione degli atti relativi a contributi

`extract_bur_grants.py` analizza ricorsivamente una directory di sommari BUR FVG
(ad esempio `BUR_fvg` o `bur_parte_prima`) contenente TXT **già limitati** a
PARTE PRIMA — LEGGI, REGOLAMENTI E ATTI DELLA REGIONE. Non cerca intestazioni
é ritaglia nuovamente la sezione: applica direttamente due passaggi:

1. **Filtro deterministico:** separa le voci usando intestazioni di atti e
   richiede indizi specifici di una misura contributiva (`--filter-mode strict`,
   predefinito). Il precedente filtro a parole generiche resta disponibile come
   `--filter-mode broad` per confronti e controlli di richiamo.
2. **Conferma semantica:** invia solo le voci candidate a un server vLLM con API
   OpenAI compatibile; richiede JSON strutturato ed estratti letterali verificabili.

Sono ammesse soltanto misure promosse dall'amministrazione della Regione Autonoma
Friuli Venezia Giulia. Comuni e altri enti possono essere beneficiari, senza
essere i promotori. Le misure regionali cofinanziate con fondi europei sono
ammesse; la semplice citazione di una legge regionale da parte di un diverso
promotore non basta. Questo vincolo è richiamato anche nel prompt del modello.

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

L'estrattore usa soltanto la libreria standard Python e legge **esclusivamente
file `.txt`** (estensione senza distinzione tra maiuscole e minuscole). Il file
`requirements-extraction.txt` non contiene dipendenze. Non importa `pypdf`,
non apre PDF e non effettua conversione PDF/testo né OCR. I PDF vengono registrati
come saltati anche quando manca il TXT corrispondente o quando questo è vuoto.
Per gli input TXT vuoti viene segnalato un errore: rigenerare il testo prima
dell'estrazione. I TXT UTF-8 (anche con BOM) vengono letti direttamente; per file
non UTF-8 è previsto un ripiego CP1252.

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
python extract_bur_part_one.py bur_fvg --output bur_parte_prima
python extract_bur_grants.py bur_parte_prima --output results --candidates-only
python extract_bur_grants.py bur_parte_prima --output results
```

Lo scraper deve avere terminato; controllare prima i suoi avvisi e stati di
copertura. L'estrattore non certifica né corregge `da_verificare`, i ripieghi
sulle prime pagine dell'integrale o i titoli discordanti. Gli anni indicano
la raccolta da fornire: l'estrattore non impone un filtro cronologico, perché
una voce del 2026 può richiamare una legge antecedente al 1999.

Sono elaborati soltanto i TXT. I PDF sono sempre ignorati, senza ripiego sulla
conversione e senza necessità di abbinare i nomi; quindi PDF e TXT dello stesso
bollettino non producono doppie elaborazioni. In `inventory.jsonl` il motivo del
salto dei PDF è `pdf_ignored_text_only`. Gli altri formati (inclusi HTML, XML,
DOCX, CSV e JSON) sono registrati come `unsupported_format`. Le directory `cache`,
`.git` e `__pycache__` sono escluse. Usare una directory di output dedicata,
diversa dall'input. Se un bollettino ha soltanto il PDF, occorre produrne il TXT
prima di usare questo estrattore; il PDF saltato da solo non genera codice 2.

## Input già filtrato: nessuna verifica della sezione

L'intero contenuto di ogni TXT fornito viene passato ai filtri contributivi.
L'intestazione `PARTE PRIMA` può essere presente oppure essere stata rimossa:
non è richiesta né verificata. Non vengono generati stati `section_not_found`
e non si scartano documenti per la sola assenza di un titolo. I metadati di
ritaglio `section_start`, `section_end` ed `excluded_characters` non sono più
prodotti. Gli offset dei candidati e degli scarti si riferiscono al TXT
fornito e normalizzato, non al documento originario prima del prefiltraggio.

L'utente prepara i TXT limitati agli atti regionali prima di eseguire questo
script. Chi parte dai file grezzi dello scraper può usare separatamente
`extract_bur_part_one.py`; la sua verifica delle sezioni non viene eseguita
dal grant extractor. Il modello continua a verificare che il promotore della
misura sia l'amministrazione regionale, non semplicemente un beneficiario.

## Filtro più selettivo e confronto con il precedente

Il filtro `strict` riduce le richieste al modello seguendo queste regole:

- I riferimenti di sommario su una riga come `pag. 218` chiudono la voce.
  Un decreto non assorbe quindi gli avvisi successivi fino al prossimo decreto.

- `bando`, `avviso`, `fondi`, `aiuti` o `sostegno`, isolati, non sono sufficienti.
  Non basta neppure una generica menzione di finanziamento.
- Passano strumenti espliciti come contributi, sovvenzioni, sussidi, voucher,
  ristori, borse di studio, aiuti di Stato/de minimis, finanziamenti agevolati,
  incentivi economici e agevolazioni finanziarie o fiscali.
- Finanziamenti, incentivi, agevolazioni e sostegno meno specifici richiedono
  sia una procedura (bando, criteri, domande, graduatoria, concessione ecc.) sia
  beneficiari riconoscibili entro 200 caratteri prima/dopo il termine.
  In questa via meno specifica, riferimenti vicini ad appalti, affidamenti o
  reclutamento impediscono la selezione. Non è un'esclusione globale: una misura
  esplicita di contributo per nuove assunzioni resta candidata.
- Sono neutralizzati usi non contributivi come contributi previdenziali,
  obbligatori, di bonifica, contributo unificato, contributo ANAC o scientifico.
  Un'altra menzione autentica di contributo nella stessa voce resta valida.
- Ogni finestra di una voce lunga deve contenere propri indizi contributivi;
  non vengono inviate al modello tutte le finestre solo perché la prima contiene
  una parola pertinente. In modalità `broad` resta il comportamento precedente.

Le verifiche sulle frasi comprimono gli spazi e gli a capo su una copia di lavoro;
non modificano il testo inviato al modello né i suoi offset. Non si impone un
bando aperto: regolamenti, proroghe, concessioni, liquidazioni e revoche con
riferimenti espliciti a contributi restano nel perimetro.

Per ricalcolare il numero di richieste senza chiamare vLLM:

```bash
python extract_bur_grants.py BUR_fvg --output results --candidates-only
```

Il comando stampa il numero di candidati selezionati e quello del filtro ampio
sugli stessi TXT già filtrati. `filter_summary.json` conserva i conteggi e le ragioni di scarto;
`inventory.jsonl` contiene i conteggi anche per singolo file. Per ispezionare gli
scarti, leggere `rejected.jsonl`: include fonte, testo, offset e ragione
(`no_act_reference`, `no_grant_evidence`, `no_grant_evidence_in_window`). Ogni
candidato include `filter_reason`, con la regola che lo ha ammesso.
I conteggi degli scarti mescolano voci intere e finestre: non rappresentano una
misura di accuratezza e non vanno sottratti direttamente dal numero di candidati.

Per ripristinare le parole chiave del filtro originale sugli stessi TXT
preparati dall’utente e confrontare le voci:

```bash
python extract_bur_grants.py BUR_fvg --output results_broad \
  --filter-mode broad --candidates-only
```

`strict` privilegia la precisione: può omettere bandi che non esplicitano né lo
strumento economico né i beneficiari, e finestre che dipendono solo da contesto
lontano. Verificare un campione degli scarti, soprattutto per annate e impaginazioni
diverse, prima del censimento. Non è stata misurata la riduzione sui 16 mila
candidati dell'archivio dell'utente: tale cartella non è disponibile qui. Un
numero elevato di candidati può includere molti atti autentici in 28 annualità.

### Esempi del 2006 forniti dall'utente

I tre estratti in `tests/fixtures/filter_examples_2006.json` passavano tutti con
il filtro precedente. Il filtro `strict` scarta i primi due e mantiene il terzo:

1. Decreto di esproprio seguito da concorsi sanitari: il decreto termina a
   `pag. 218` e le voci successive non gli vengono attribuite.
2. Prelevamento dal fondo spese impreviste per la protezione civile: è un
   trasferimento di bilancio senza indizi espliciti di contributi.
3. DGR 1582/2006, ulteriore finanziamento di progetti formativi FSE: resta
   candidata grazie alla combinazione di finanziamento, approvazione e beneficiari
   vicini (imprese). È una misura di finanziamento da confermare semanticamente,
   non un falso positivo da escludere per il solo settore formativo.

Non esiste una blacklist per FSE, formazione o protezione civile. Regole e bandi
contributivi di questi settori restano nel perimetro. Il terzo esempio è un test
positivo per evitare di perdere finanziamenti pertinenti durante la riduzione
delle richieste al modello.

## Opzioni

| Opzione | Valore predefinito | Significato |
| --- | --- | --- |
| `input` | obbligatorio | Cartella dei sommari, ricerca ricorsiva |
| `--output` | `bur_grants_output` | Cartella dei risultati e della cache |
| `--base-url` | `VLLM_BASE_URL` oppure `http://localhost:8000/v1` | URL API con `/v1` |
| `--model` | `VLLM_MODEL` oppure `Qwen/Qwen2.5-32B-Instruct` | Nome del modello servito |
| `--workers` | `4` | Richieste concorrenti, almeno 1 |
| `--candidates-only` | disattivato | Esegue soltanto lettura e filtro regex |
| `--filter-mode` | `strict` | `strict` selettivo oppure `broad` con parole chiave originali, entrambi su tutto il TXT già filtrato |

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
| `candidates.jsonl` | Voci selezionate dalle regex con fonte, testo, offset e regola di ammissione |
| `rejected.jsonl` | Voci/finestre scartate con fonte, testo, offset e motivo |
| `filter_summary.json` | Conteggi selettivi e ampi sugli stessi TXT; `input_scope=prefiltered_regional_text` |
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
sono indici Python (fine esclusa) nel testo TXT letto e normalizzato, non nei byte
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
regex. Voci su più colonne, intestazioni spezzate o assenti, testo TXT
impreciso, OCR parziale preesistente e lessico non coperto possono causare omissioni.
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
errori API, integrazione con le coppie PDF/TXT dello scraper, PDF sempre
ignorati e assenza di ripiego sui PDF quando il TXT è vuoto. I test del filtro
coprono anche avvisi generici, fondi, appalti, assunzioni, contributi obbligatori,
strumenti e fasi delle misure contributive, contesto vicino, frasi su più righe
e finestre prive di indizi pertinenti. La raccolta
1999–2026 e l'inferenza con vLLM reale non sono state eseguite per questa aggiunta.

## Verifica dell'input prefiltrato

I test verificano che un TXT senza intestazione produca candidati e raggiunga
la conferma semantica simulata, con codice di uscita 0 in assenza di errori.
Coprono inoltre testi multilinea, continui e con paragrafi: i separatori `pag. N`
continuano a delimitare le singole voci senza modificare gli offset del TXT.
Non viene eseguito alcun riconoscimento o ritaglio della sezione regionale.
La rimozione del controllo preliminare non modifica il prompt né il formato
delle richieste API; la cache rimane riutilizzabile per testo e modello identici.
