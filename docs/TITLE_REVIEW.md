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

Ogni titolo individuato viene inviato integralmente al modello,
anche se è già corretto. Il modello valuta gli errori e restituisce il
titolo completo. Il programma reinserisce il risultato nella stessa
riga conservando il riferimento iniziale, il riferimento di pagina e
gli a capo originali. Se una richiesta fallisce o restituisce una
risposta incompleta, il programma segnala la riga e termina prima
di creare il TXT di destinazione.

Il prompt chiede di conservare il testo in caso di dubbio. Controlla
le modifiche su un fascicolo di prova per valutare la qualità del
modello prima di usare il passaggio su altri fascicoli.
