# Ricomposizione delle parole spezzate nei TXT BUR

`bur_vllm.py` è un passaggio facoltativo fra l'estrazione del testo dai PDF e
l'estrazione della Parte Prima. Richiede Python 3.10+ (come il resto del
repository), TXT in UTF-8 e un server vLLM con endpoint Chat Completions
compatibile con OpenAI e supporto per il formato di risposta JSON.
Lo script usa la libreria standard di Python.

## Vocabolario italiano

Prepara un file UTF-8 con una forma alfabetica per riga. Usa forme flesse e
coniugate, per esempio `attrezzature`, `concessioni`, `approvato` e
`approvavano`. Lo script confronta direttamente le lettere dei due frammenti
concatenati con il vocabolario, ignorando maiuscole e minuscole. Se usi
Hunspell, espandi prima il dizionario `.dic` con le regole del relativo
file `.aff`. Le forme assenti dal vocabolario vengono saltate.

Con `--corpus-min 3` puoi aggiungere le forme alfabetiche osservate almeno
tre volte nei TXT in ingresso, escludendo i frammenti dei candidati già
riconosciuti dal vocabolario. Il valore predefinito `0` disattiva questa
scansione preliminare.

## Esecuzione

Prova su un singolo fascicolo:

```bash
python bur_vllm.py bur_fvg/2004/BUR_legacy_510_514_ordinario.txt bur_riparati_prova \
  --vocab italian_words.txt --model NOME_MODELLO
```

Per elaborare tutte le sottocartelle:

```bash
python bur_vllm.py bur_fvg bur_riparati \
  --vocab italian_words.txt --model NOME_MODELLO \
  --url http://localhost:8000/v1/chat/completions --workers 4

python extract_bur_part_one.py bur_riparati --output bur_parte_prima
```

Usa il nome del modello pubblicato dal server vLLM. Imposta la variabile
d'ambiente `VLLM_API_KEY` se il server richiede autenticazione.
`--workers` limita le richieste simultanee (predefinito: 4).
`--timeout` imposta il timeout delle operazioni di rete in secondi
(predefinito: 90).

La directory di output deve essere separata dall'albero sorgente. La scansione
di una directory è ricorsiva e conserva i percorsi relativi, per esempio
`bur_fvg/2004/maggio/bur.txt` diventa `bur_riparati/2004/maggio/bur.txt`.

## Candidati, output e riesecuzione

Lo script propone coppie alfabetiche separate da spazi, da un trattino con
spazi o da un trattino a fine riga. Per esempio, propone `conc essione`
e `attrez - zature` se soddisfano i criteri descritti sotto. Invia i
candidati insieme al periodo individuato da
punteggiatura e a capo. Il server risponde con `join`, `keep` o `uncertain`
per ciascun candidato. Lo script applica soltanto i `join` validati e
mantiene il testo originale per le altre decisioni e per le unioni
sovrapposte. I frammenti numerici e le parole divise in più di due parti
esulano da questo passaggio.

- I TXT corretti sono copie dei sorgenti.
- Ogni file `.txt.edits.jsonl` registra i candidati, la forma proposta, la
  decisione e gli offset nel TXT sorgente. Gli offset contano caratteri,
  partono da zero e indicano un intervallo con estremo finale escluso.
- `decisions.sqlite3` conserva le decisioni validate in base al contesto,
  ai candidati, all'endpoint, al nome del modello e al prompt. Una
  riesecuzione con la stessa directory riusa le decisioni disponibili.
  Se sostituisci il modello sul server mantenendo lo stesso nome, usa una
  nuova directory di output per rivalutare i candidati.
- Se una richiesta fallisce o restituisce decisioni non valide, il file
  corrente non viene riscritto. L'elaborazione prosegue con gli altri file
  e termina con codice 1. Esegui di nuovo lo stesso comando per riprovare.

Prima di elaborare l'intero archivio, confronta alcuni TXT corretti con gli
originali. Controlla sia le unioni errate sia le parole spezzate ancora presenti.

## Come evitare unioni errate

La forma ricomposta deve essere nel vocabolario, e almeno un frammento
deve esserne assente. Per un'unione con soli spazi, serve almeno una delle
seguenti condizioni:

- entrambi i frammenti hanno almeno tre lettere;
- la forma ricomposta compare anche come parola intera nei TXT sorgenti.

Il programma raccoglie le occorrenze con una scansione preliminare,
anche quando `--corpus-min` è disattivato. Un trattino di sillabazione
consente di proporre la coppia a vLLM senza queste due condizioni.

Questa regola consente di valutare `tecnolo gico` anche se `tecnologico`
compare nel vocabolario ma manca come parola intera nei TXT. Per
`in corso`, la presenza di entrambi i frammenti nel vocabolario blocca
la proposta; la forma breve `in` richiederebbe comunque un'occorrenza
intera di `incorso` nei TXT. Per i nomi propri e le forme flesse assenti
dal vocabolario, aggiungi la grafia intera al file passato a `--vocab`.

Il registro contiene solo le coppie che hanno superato il filtro. Una
coppia assente dal registro non è stata valutata da vLLM; una coppia con
decisione `uncertain` è stata valutata e resta separata.

Per correggere le unioni prodotte da una versione precedente, riesegui lo
script sui TXT originali, per esempio da `bur_fvg` verso `repaired`.
I TXT corretti e i registri vengono riscritti per i file completati.
La versione aggiornata usa un prompt diverso, quindi le decisioni
precedenti non vengono riutilizzate.

## HTTP 404 da vLLM

Un HTTP 404 nella richiesta indica che il server ha risposto. Può mancare
il percorso Chat Completions, oppure il nome dato a `--model` può essere
diverso dall'identificativo pubblicato da vLLM.

Per un server locale, verifica gli identificativi pubblicati:

```powershell
curl.exe http://localhost:8000/v1/models
```

Se il server richiede autenticazione, aggiungi
`-H "Authorization: Bearer $env:VLLM_API_KEY"`. Copia il valore esatto
di `data[].id` in `--model` e usa `--url http://localhost:8000/v1`.
Puoi indicare anche l'URL completo `http://localhost:8000/v1/chat/completions`.
`--base-url` è un alias di `--url`. In assenza di un argomento esplicito
viene usato `VLLM_BASE_URL`, se impostato. Se il server è dietro un proxy,
includi nell'URL il prefisso configurato per l'API.

Con HTTP 401, 403 o 404 il programma interrompe l'elaborazione e mostra
l'endpoint, il modello e l'eventuale messaggio restituito dal server.
La prima richiesta non in cache di ogni file viene effettuata prima di
accodare le altre. I file già completati e la cache restano disponibili.

## Recupero delle parole escluse dal filtro

Se il registro omette molte parole spezzate, esegui una prova su un
fascicolo sorgente con `--recover-missing`:

```bash
python bur_vllm.py bur_fvg/2004/BUR_legacy_510_514_ordinario.txt repaired_review \
  --vocab italian_words.txt --model NOME_MODELLO --recover-missing
```

Questa modalità chiede a vLLM di valutare anche le coppie con supporto
lessicale o di corpus insufficiente, come una forma flessa assente dal
vocabolario o un frammento di una sola lettera. Esclude ancora le coppie
i cui due frammenti sono entrambi nel vocabolario. Il registro include
`in_vocabulary` per indicare se la forma ricomposta è nel vocabolario
usato dal programma. La scansione può produrre più richieste e più
falsi positivi. Controlla i `join` del fascicolo di prova prima di
eseguire la stessa modalità sull'intero archivio.
