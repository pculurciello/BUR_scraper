# Revisione dei titoli del sommario BUR con vLLM

`review_bur_titles.py` rilegge i titoli del sommario della Parte Prima
per correggere artefatti di estrazione PDF, come `conc ernente` e
`attrez - zature`. Richiede Python 3.10+, un file TXT UTF-8 con una voce
per riga e un server vLLM compatibile con OpenAI Chat Completions
che supporti `response_format: json_object`. Il client usa la libreria
standard di Python.

## Esecuzione

Passa un fascicolo già estratto con `extract_bur_part_one.py` e scegli
un nome nuovo per il TXT di destinazione:

```bash
python review_bur_titles.py bur_parte_prima/2004/BUR_legacy_510_514_ordinario.txt BUR_reviewed.txt \
  --base-url http://localhost:8000/v1 --model /models/Qwen2.5-14B-Instruct-AWQ
```

- `--model` è l'identificativo esatto pubblicato da `GET /v1/models`.
- `--base-url` accetta la base dell'API o l'endpoint completo che
  termina con `/chat/completions`. Il valore predefinito è
  `VLLM_BASE_URL`, se impostato, oppure `http://localhost:8000/v1`.
- Imposta `VLLM_API_KEY` se il server richiede autenticazione.
- `--workers` regola il numero di richieste contemporanee (4 per
  impostazione predefinita). `--timeout` imposta il timeout di rete
  in secondi (90 per impostazione predefinita).

## Quale testo viene inviato

Per ogni voce con riferimento di pagina finale, il programma individua
il titolo ed esclude dalla richiesta il riferimento iniziale riconosciuto
e il riferimento di pagina. Riconosce i riferimenti formali datati,
le intestazioni di ufficio maiuscole e le intestazioni comunali con
punto finale. Se manca un riferimento iniziale, usa come titolo tutto
il testo prima di `pag. N`. Le citazioni che fanno parte del titolo
restano nel titolo. Le righe senza riferimento di pagina vengono
copiate. Se un riferimento formale iniziale ha un formato ambiguo,
la voce viene conservata e il programma segnala il numero della riga.

Ogni titolo individuato viene valutato integralmente, anche se è già
corretto. La cache riusa le valutazioni dei titoli identici. Il modello valuta gli errori e restituisce il
titolo completo. Il programma reinserisce il risultato nella stessa
riga conservando il riferimento iniziale, il riferimento di pagina e
gli a capo originali. Se una richiesta fallisce o restituisce una
risposta incompleta, il programma segnala la riga e termina prima
di creare il TXT di destinazione.

Il prompt chiede di conservare il testo in caso di dubbio. Controlla
le modifiche su un fascicolo di prova per valutare la qualità del
modello prima di usare il passaggio su altri fascicoli.

## Elaborazione dell'archivio

Passa la cartella sorgente e una cartella di destinazione separata.
La scansione include le sottocartelle e conserva i percorsi relativi.

```bash
python review_bur_titles.py bur_parte_prima bur_revisionato   --base-url http://localhost:8000/v1 --model /models/Qwen2.5-14B-Instruct-AWQ   --batch-size 8 --workers 4
```

`--batch-size` raggruppa fino a 8 titoli per richiesta per impostazione
predefinita. Ogni titolo ha un ID e il modello restituisce `null` per
i titoli da conservare, riducendo il testo generato. Per riprodurre
una richiesta per titolo usa `--batch-size 1`.

La cache `.title_review.sqlite3` è nella cartella di destinazione
(accanto al TXT di destinazione in modalità file singolo). È condivisa
fra i fascicoli e si aggiorna a ogni richiesta completata. Usa la stessa
destinazione per riprendere un'elaborazione interrotta in modalità
cartella. I risultati sono distinti per endpoint, nome del modello e
prompt. Se sostituisci il modello conservandone il nome, usa una nuova
cartella di destinazione per forzare una nuova valutazione.

Per misurare la velocità, esegui la prova su una cartella rappresentativa
e leggi il riepilogo finale con titoli, richieste e secondi trascorsi.
Usa destinazioni nuove per confrontare configurazioni senza la cache.
Prova `--batch-size 8 --workers 4` come punto di partenza e confrontalo
con `--batch-size 16 --workers 4` sullo stesso campione. Controlla
anche le correzioni, perché raggruppare più titoli può influenzare le
risposte del modello.
