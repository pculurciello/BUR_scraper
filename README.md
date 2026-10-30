# Scraper dei sommari BUR Friuli Venezia Giulia

## Installazione ed esecuzione

Richiede Python 3.10 o successivo.

```bash
python -m pip install pypdf fonttools
python scrape_bur_fvg.py --dal 1999 --al 2026 --output bur_fvg
```

Lo script parte dal menu annualità del portale https://bur.regione.fvg.it/newbur/:
segue l'archivio moderno dal 2007 e quello ASP collegato dal portale per il
1999–2006. Segue tutti i collegamenti di paginazione individuati e raccoglie
tutti i fascicoli, senza escludere supplementi ordinari o straordinari.
Non enumera numeri presunti e non deduplica per solo numero: un supplemento e
un bollettino ordinario possono avere lo stesso numero.

## File prodotti

- `fascicoli.csv` e `fascicoli.json`: un record per fascicolo, con titolo, URL,
  stato di elaborazione e percorsi dei file.
- `ANNO/BUR_NUMERO_GIORNO_MESE_TIPO.pdf`: sommario PDF separato quando disponibile; in alternativa,
  PDF completo, se il ripiego storico è abilitato.
- `ANNO/BUR_NUMERO_GIORNO_MESE_TIPO.txt`: testo con frasi ricomposte, separatori tra periodi e rimozione dei trattini a fine riga.
- `copertura.csv`: pagine di archivio visitate, fascicoli scoperti, elaborati
  e anomalie di navigazione per anno. Non certifica la completezza dell'archivio.
- `errori.json`: anomalie di navigazione e annualità assenti. Gli errori dei
  singoli documenti sono nella colonna `errore` di `fascicoli.csv`.
- `scraping.log`: registro dell'esecuzione.
- `cache/`: risposte scaricate, riutilizzate alle esecuzioni successive.

## Stati e limiti

`ok` significa che è stato trovato il sommario separato ed estratto del testo.
Non significa che ogni voce sia stata strutturata o validata manualmente.
Il testo resta nel suo ordine PDF: lo script non ricostruisce automaticamente
una tabella dei singoli atti né filtra i soli decreti contributivi.

Per i fascicoli senza sommario separato, di default vengono scaricati i PDF
completi ed estratte **le prime 12 pagine come candidate da controllare**.
Queste pagine possono includere atti, non contenere alcun sommario, oppure
non contenere tutto il sommario. Lo stato è sempre `da_verificare`, mai `ok`.
`--legacy-pages 0` disabilita questo ripiego; un valore maggiore amplia il
numero di pagine iniziali estratte. Il ripiego è applicato a qualsiasi
fascicolo privo di sommario separato, indipendentemente dall'anno.

`ocr_necessario` segnala PDF dai quali non è stato estratto testo. Lo script
non esegue OCR e non rileva tutte le situazioni di OCR parziale.
`sommario_non_disponibile` indica che non è stato individuato un documento
utilizzabile secondo le opzioni impostate. `errore` richiede un nuovo tentativo
o un controllo manuale.

Gli anni indicano l'annualità dell'archivio, non quella del numero ordinario
a cui si riferisce un supplemento. Un supplemento pubblicato nel gennaio 2026
può riferirsi a un numero ordinario del dicembre 2025.
Il 2026 comprende soltanto i fascicoli pubblicati al momento dell'esecuzione.

Le pagine ASP storiche e i PDF possono presentare lacune o dati incongruenti.
Lo script segnala pagine diverse con identici elenchi e dettagli con titolo
incompatibile con quello di partenza. La copertura si riferisce ai collegamenti
raggiungibili: per un censimento certificato serve una verifica delle lacune
con la Regione. Le pagine non collegate e i documenti non pubblicati non possono
essere ricostruiti automaticamente.

## Opzioni utili

Solo scoperta dell'indice, senza PDF:

```bash
python scrape_bur_fvg.py --dal 1999 --al 2026 --solo-indice --output indice_bur
```

Prova su tre fascicoli del 2026 (la scoperta delle pagine dell'anno avviene
comunque integralmente):

```bash
python scrape_bur_fvg.py --dal 2026 --al 2026 --limit 3 --output prova_bur
```

Aggiornamento, ignorando la cache:

```bash
python scrape_bur_fvg.py --dal 2026 --al 2026 --refresh --output bur_2026
```

Usare cartelle diverse per intervalli diversi: CSV/JSON vengono riscritti per
l'intervallo richiesto. La cache e i PDF precedenti non vengono cancellati.
Un'interruzione conserva la cache e il CSV aggiornato dopo ogni fascicolo;
la successiva esecuzione rielabora l'indice usando i download già disponibili.
Gli indici JSON e la copertura sono aggiornati a fine annualità o esecuzione.

Il download è sequenziale, con un secondo minimo fra richieste, timeout e
ritentativi con attesa crescente. Il codice di uscita è 0 se tutti i documenti
elaborati sono `ok` (o `solo_indice`) e non ci sono anomalie; è 2 quando
occorrono controlli. Una prova con `--limit` non è una raccolta completa anche
se termina con codice 0.

## Verifica effettuata

Sono stati verificati il parsing di pagine reali del 1999 e del 2026,
il riconoscimento della paginazione e dei supplementi ordinari e straordinari,
il download con estrazione del sommario di un supplemento del 2026 e il
ripiego sul PDF integrale di un supplemento del 1999.
Non è stata eseguita la raccolta completa 1999–2026.


## Errore SSL: CERTIFICATE_VERIFY_FAILED

Questo errore indica che Python non riesce a costruire una catena di fiducia
per il certificato presentato dal sito o dal proxy. Può dipendere dai
certificati CA dell'installazione Python, da un proxy aziendale oppure dalla
catena inviata dal server; il solo messaggio non identifica la causa.

Aggiornare lo script e provare con il bundle CA di certifi:

```bash
python -m pip install --upgrade certifi
python scrape_bur_fvg.py --dal 1999 --al 2026 --output bur_fvg --certifi
```

Usare lo stesso interprete Python per l'installazione e per lo script.
L'opzione `--certifi` aggiunge le CA di certifi al trust predefinito di Python;
non disabilita la verifica dei certificati o del nome host.
Non è garantito che risolva una catena incompleta inviata dal server.

Se la connessione attraversa un proxy che usa una CA privata, richiedere
all'amministratore il relativo certificato CA in formato PEM e usare:

```bash
python scrape_bur_fvg.py --dal 1999 --al 2026 --output bur_fvg --ca-file /percorso/ca-aziendale.pem
```

Il file deve contenere certificati CA attendibili, non chiavi private.
`--ca-file` aggiunge le CA indicate al trust predefinito.
Le opzioni `--certifi` e `--ca-file` sono alternative.
È possibile anche configurare il trust di Python tramite `SSL_CERT_FILE`.
Per ispezionare i percorsi usati dall'interprete:

```bash
python -c "import ssl; print(ssl.get_default_verify_paths())"
```

Con Python installato da python.org su macOS, eseguire anche il comando
`Install Certificates.command` presente nella cartella della propria versione
Python, se disponibile. Se il problema persiste anche con CA aggiornate,
verificare la catena del server e l'eventuale proxy con l'amministratore.
Gli errori di verifica TLS producono un messaggio specifico senza ritentativi
inutili. La verifica TLS è abilitata per impostazione predefinita.



## Risposte lente e ritentativi silenziosi

Ogni richiesta di rete usa un timeout di 30 secondi per le operazioni socket
(non un limite alla durata totale del download) e fino a 5 ritentativi dopo
il primo: al massimo 6 tentativi. Sono incluse le richieste della home page,
degli archivi, dei dettagli e dei PDF.

Timeout, errori di connessione, risposte interrotte o di formato inatteso e
HTTP 408, 425, 429, 500, 502, 503, 504 vengono ritentati senza stampare
messaggi intermedi. Le pause crescono da 2 secondi, con una piccola variazione
casuale, fino a un massimo di 60 secondi. Se presente, `Retry-After` viene
usato al posto della pausa esponenziale, con lo stesso massimo di 60 secondi.
Un errore viene segnalato soltanto dopo l'ultimo tentativo. Gli errori permanenti
come HTTP 404 e gli errori di verifica dei certificati falliscono subito.
I normali messaggi di avanzamento per anno rimangono visibili.

Per un portale particolarmente lento:

```bash
python scrape_bur_fvg.py --dal 1999 --al 2026 --output bur_fvg --timeout 180 --retries 8 --retry-backoff 3 --retry-max-wait 60
```

`--retries 0` disabilita i ritentativi. Le risposte fallite o incomplete non
vengono salvate in cache. Per eseguire i test senza contattare il portale:

```bash
python -m unittest -v test_scrape_bur_fvg.py
```


### Workaround TLS esplicito

La verifica TLS è attiva per impostazione predefinita. Se occorre continuare
con il workaround richiesto in precedenza, usare `--insecure` per la singola
esecuzione. L'opzione disabilita la verifica del certificato e del nome host
per le richieste dello scraper; una connessione intercettata può passare
inosservata. Preferire un bundle CA attendibile quando disponibile.

```bash
python scrape_bur_fvg.py --dal 1999 --al 2026 --output bur_fvg --timeout 180 --retries 8 --insecure
```



## Nomi dei documenti derivati dall'URL

Per gli URL `visionaBUR?bnum=AAAA/MM/GG/NUMERO`, anno, numero, giorno e mese
provengono esclusivamente da `bnum`, anche quando è codificato con `%2F`.
I metadati PDF e il titolo della pagina determinano soltanto TYPE.

Esempio:

- URL: `https://bur.regione.fvg.it/newbur/visionaBUR?bnum=2020%2F04%2F08%2F17`
- PDF: `2020/BUR_17_08_04_ordinario.pdf`
- TXT: `2020/BUR_17_08_04_ordinario.txt`

Il formato è `[YEAR]/BUR_[NUMBER]_[DAY]_[MONTH]_[TYPE].pdf` (e `.txt`).
Giorno e mese hanno sempre due cifre. L'anno è presente nella cartella.
Un numero di BUR citato nel titolo o nei metadati non modifica quello nell'URL.
TYPE distingue `ordinario`, `straordinario`, `supplemento_ordinario`,
`supplemento_straordinario` e `supplemento`.
Gli indici CSV/JSON riportano i percorsi relativi prodotti.

### Eccezione per gli URL ASP del 1999–2006

Gli URL storici `archivioDettaglio.asp?num=5&nodo=73` non includono `bnum`,
né una data o un numero di BUR affidabili. Per questi documenti si usano gli
identificativi dell'URL e la cartella dell'annualità di archivio, per esempio
`1999/BUR_legacy_5_73_supplemento_ordinario.pdf` e `.txt`.
Le date e il numero di BUR non vengono ricostruiti dal titolo. Gli URL moderni
con `bnum` assente o non valido sono segnalati come errori.

`file_sources.json` associa i percorsi agli URL di origine e conserva
l'assegnazione dei suffissi descritta sotto.
I file creati con le precedenti convenzioni non vengono cancellati o rinominati.
Una nuova esecuzione genera i nuovi nomi riutilizzando i download in cache.


## Tipo del fascicolo dai metadati PDF

Il componente TYPE del nome viene ricavato prima dal campo `Title` del PDF
scaricato. Se `pdfinfo` (Poppler) è disponibile nel PATH, viene eseguito sul
PDF passando i byte tramite stdin. Se manca, fallisce o non restituisce un
titolo, viene letto lo stesso campo `/Title` tramite `pypdf`.
Non è necessario installare Poppler per usare lo script.

Se il titolo PDF non identifica un tipo, per esempio `bur-99.PDF`, viene
usato il titolo della pagina del fascicolo. Numero, anno, giorno e mese provengono dall'URL
come descritto sopra; l'archivio ASP usa gli identificativi storici. Se i metadati indicano solo “Supplemento”,
TYPE diventa `supplemento`, senza aggiungere un sottotipo non esplicitato.
Esempio: `2026/BUR_30_19_10_supplemento.pdf`.

Gli indici CSV/JSON includono `titolo_pdf`, `tipo_fascicolo` e `fonte_tipo`
(`pdfinfo`, `pdf_metadata` o `titolo_pagina`). `tipo_documento` mantiene il
significato di sommario separato oppure ripiego sulle pagine dell'integrale.
Questa inferenza dipende dalla qualità dei metadati pubblicati dalla Regione.
I vecchi file non vengono rinominati; la nuova esecuzione riusa la cache per
generare i nuovi percorsi.




## Documenti con stessa data, numero e tipo

Il parametro `bnum` può terminare con identificativi come `1_1` o `1_2`.
Il numero di base rimane `1`; i segmenti aggiuntivi identificano documenti
diversi e non vengono interpretati come un nuovo numero di BUR.

Se più documenti produrrebbero lo stesso nome (anno, numero, giorno, mese e
TYPE uguali), il primo usa il nome base, il secondo `_2`, il terzo `_3`, ecc.,
prima dell'estensione e con lo stesso suffisso per PDF e TXT. Per esempio,
con TYPE `supplemento`:

- `2020/BUR_1_02_01_supplemento.pdf`
- `2020/BUR_1_02_01_supplemento_2.pdf`
- `2020/BUR_1_02_01_supplemento_3.pdf`

L'assegnazione dipende dall'ordine di elaborazione iniziale. Nei rerun, il
registro `file_sources.json` permette a ciascun URL di conservare il proprio
nome, anche se l'ordine cambia. Forme codificate con `%2F` e non codificate
dello stesso URL vengono normalizzate. File già presenti senza provenienza
registrata sono preservati e il relativo nome viene saltato.

Documenti con TYPE diversi hanno già nomi distinti e non richiedono suffissi.
Non cancellare `file_sources.json` se vuoi mantenere le assegnazioni dei nomi.



## Pagina iniziale dell'archivio moderno

La raccolta annuale parte direttamente da
`archivioBollettini?anno=2021&num_pag=1` (con l'anno richiesto), senza visitare
prima l'alias `archivioBollettini?anno=2021`. I link alla prima pagina vengono
normalizzati allo stesso URL: la pagina non viene scaricata due volte e non
produce la falsa anomalia “Elenco identico” tra alias implicito e pagina 1.
Il controllo degli elenchi identici tra pagine distinte rimane attivo.
L'archivio ASP storico mantiene il proprio schema di paginazione.



## Titolo del dettaglio diverso da quello nell'archivio

Un titolo discordante non impedisce piu il download. Lo script rilegge una
volta la pagina del dettaglio bypassando la cache locale e inviando gli header
`Cache-Control: no-cache` e `Pragma: no-cache`. Anche `--refresh` invia questi
header. Un server o proxy puo comunque restituire contenuti incoerenti.

Se la discordanza persiste, il sommario viene scaricato dal link presente
nel dettaglio e salvato usando data e numero dell'URL richiesto. Il titolo
non sostituisce questi identificativi. Il record CSV/JSON contiene:

- `titolo`: titolo nell'archivio;
- `titolo_dettaglio`: titolo osservato nella pagina usata;
- `titolo_discordante`: indicatore della discordanza persistente;
- `avviso`: spiegazione non bloccante e richiesta di verifica.

Se il documento sarebbe stato `ok`, diventa `da_verificare`; i casi senza
text layer mantengono `ocr_necessario`. Il PDF e il TXT sono comunque salvati,
salvo altri errori di download, lettura o scrittura. Un fallimento della
rilettura fresca lascia utilizzabile la risposta gia ottenuta.

Il solo messaggio non permette di distinguere tra cache locale, risposta
errata del server/proxy e metadati incoerenti. Il link PDF potrebbe anch'esso
riferirsi a un altro fascicolo: controllare i record discordanti prima di usare
i documenti come fonte. Per recuperare i documenti saltati in precedenza,
rieseguire lo script per l'annualita interessata con la stessa directory di output:

```bash
python scrape_bur_fvg.py --dal 2021 --al 2021 --output bur_fvg
```

Come per gli altri rerun, gli indici della directory vengono riscritti per
l'intervallo richiesto; i PDF e TXT delle altre annualita non vengono cancellati.


## Estrazione degli atti relativi a contributi con vLLM

`extract_bur_grants.py` legge soltanto i TXT già presenti (ignora sempre i PDF,
senza convertirli), seleziona le voci candidate con regex e conferma tramite
un modello servito da vLLM i riferimenti a leggi, decreti presidenziali e di
direttori, e deliberazioni relative a contributi. Conserva prove testuali,
fonti, decisioni incerte e errori per revisione.

```bash
python -m pip install -r requirements-extraction.txt
python extract_bur_grants.py bur_fvg --output results --candidates-only
# Con un server vLLM già avviato su localhost:8000:
python extract_bur_grants.py bur_fvg --output results
```

Per installazione del server, scelta del modello, opzioni, schema JSONL,
cache e limiti di copertura, vedere la [guida all'estrazione](docs/GRANT_EXTRACTION.md).



## Scaricare manualmente una pagina di un anno

Per elaborare soltanto la pagina 3 dei risultati dell'archivio 2021:

```bash
python scrape_bur_fvg.py --year 2021 --page 3 --output bur_2021_pagina3
```

Sono scaricati i sommari di tutti i fascicoli elencati nella pagina selezionata,
senza seguire la paginazione verso le altre pagine. `--page` indica la pagina
dei risultati dell'archivio, non il numero di BUR ne una pagina interna al PDF.
Per il portale moderno l'URL usa `anno=2021&num_pag=3`; per l'archivio ASP
storico viene usato `anno=1999&pag=3`.

`--year` imposta un solo anno; in alternativa si puo usare
`--dal 2021 --al 2021 --page 3`. `--page` rifiuta valori inferiori a 1 e
intervalli di piu anni. Omettendo `--page` resta attiva la raccolta completa.
Le altre opzioni funzionano normalmente, inclusi `--refresh`, `--insecure`,
`--limit` e `--solo-indice`. Per ignorare eventuali risposte in cache:

```bash
python scrape_bur_fvg.py --year 2021 --page 3 --refresh --output bur_2021_pagina3
```

Usare una directory separata se si vogliono conservare gli indici di una
raccolta precedente: CSV e JSON vengono riscritti con i risultati di questa
esecuzione. I PDF/TXT gia presenti non vengono cancellati.



## Risposta di archivio senza fascicoli

Una risposta HTTP 200 puo contenere una pagina temporanea o incompleta senza
link ai fascicoli. Per gli archivi, lo script valida anche la presenza dei
link `visionaBUR` o `archivioDettaglio.asp` prima di accettare e salvare la
risposta in cache. L'assenza dei link attiva gli stessi ritentativi silenziosi
configurati con `--retries`, senza dichiarare subito fallita la pagina.

Le vecchie risposte in cache prive di fascicoli vengono scartate e richieste
nuovamente. I ritentativi inviano header no-cache. Se anche l'ultimo tentativo
non contiene fascicoli, la risposta HTML viene conservata in `diagnostics/`
e il percorso viene incluso nell'errore finale, per distinguere una pagina
realmente vuota da problemi del server o da una struttura cambiata.

Per riprovare soltanto la pagina segnalata:

```bash
python scrape_bur_fvg.py --year 2022 --page 5 --refresh --output bur_2022_page5
```

La validazione riguarda solo le pagine dei risultati dell'archivio: la home
e le pagine di dettaglio non richiedono lo stesso tipo di link.


## Estrazione semplice delle voci con «bando»

Il primo stadio di `extract_bur_grants.py` cerca soltanto la parola intera
**bando**, senza distinzione tra maiuscole e minuscole. Le precedenti regole
strict/broad sono state rimosse. Ogni voce produce in `candidates.json`:

```json
{"text": "Bando per contributi alle imprese. Adozione.", "act": "Deliberazione della Giunta regionale 6 febbraio 2026, n. 143"}
```

L'output è un array JSON; `candidates.jsonl` aggiunge fonte, offset e contesto
dei riferimenti di pagina. La descrizione conserva frasi conclusive come
«Adozione.» e la citazione dell'atto è separata dalle norme richiamate.

```bash
python extract_bur_grants.py BUR_fvg --output results --candidates-only
```

Questo comando non richiede vLLM. Omettere `--candidates-only` per la conferma
semantica opzionale. Schema e limiti nella [guida](docs/GRANT_EXTRACTION.md).

## Estrazione contributi da TXT già filtrati

`extract_bur_grants.py` assume che i TXT siano già limitati alla Parte Prima
regionale. Legge direttamente l'intero testo fornito, senza cercare o richiedere
l'intestazione e senza eseguire di nuovo il ritaglio. Anche i file senza titolo
vengono elaborati normalmente; resta la verifica semantica del promotore regionale.

```bash
python extract_bur_grants.py BUR_fvg --output results --candidates-only
python extract_bur_grants.py BUR_fvg --output results
```

Se si parte dai TXT grezzi dello scraper, la preparazione può essere eseguita
separatamente con `extract_bur_part_one.py`. Dettagli nella
[guida all'estrazione](docs/GRANT_EXTRACTION.md#input-già-filtrato-nessuna-verifica-della-sezione).


## Conversione PDF → TXT: frasi e a capo

Gli a capo all'interno di una frase vengono sostituiti con spazi. Gli a capo
gia presenti dopo la fine di un periodo (`.`, `!`, `?`, `…`, anche seguiti
da virgolette o parentesi chiuse) sono conservati, inclusi i separatori tra
paragrafi. Non vengono inseriti nuovi a capo in corrispondenza dei punti.
Le abbreviazioni comuni (`art.`, `n.`, `D.G.R.`, ecc.) non sono considerate
una fine di frase. Il riconoscimento resta euristico nei casi ambigui.
Non vengono aggiunti separatori artificiali `--- Pagina N ---`.

Ogni trattino `-` a fine riga, anche seguito da spazi prima dell'a capo,
viene eliminato assieme all'a capo e a tutti gli spazi circostanti, inclusi
spazi non separabili Unicode e indentazione della riga successiva. Le due
parti della parola sono unite senza separatori, indipendentemente dalla
lunghezza: `finanzia -` + a capo + ` menti` diventa `finanziamenti`.
Si applica la stessa regola ai trattini
tipografici di sillabazione. La regola vale senza eccezioni: anche
`socio-` + a capo + `economico` diventa `socioeconomico` e `1998-` + a capo +
`2003` diventa `19982003`. I trattini interni a una riga sono conservati.
Le parole spezzate possono essere ricomposte anche fra due pagine.

Questa pulizia non corregge errori OCR, intestazioni gia presenti nel PDF o
un ordine di lettura errato di colonne; il PDF originale resta il riferimento.
Per rigenerare soltanto i TXT usare `--convert-only --output bur_fvg`.
L'estrattore di contributi accetta sia i TXT precedenti sia il testo con frasi
ricomposte e mantiene gli offset nel file originale.


## Sola conversione locale PDF → TXT

Per rigenerare i TXT dei PDF gia scaricati, senza richieste al portale:

```bash
python scrape_bur_fvg.py --convert-only --output bur_fvg
```

La directory deve esistere. Lo script cerca ricorsivamente file `.pdf` (anche
`.PDF`), salta le directory `cache`, `diagnostics`, `.git`, `.venv` e
`__pycache__`, ignora i PDF che sono link simbolici e salva il TXT accanto al
PDF con lo stesso nome di base. I TXT esistenti vengono sostituiti solo dopo
una conversione riuscita. Tutte le pagine di ogni PDF vengono convertite:
anche i PDF integrali storici, senza il limite `--legacy-pages` dello scraping.
Si applica la stessa pulizia degli a capo e della sillabazione.

Per una sola annualita organizzata in una cartella con il nome dell'anno:

```bash
python scrape_bur_fvg.py --convert-only --year 2021 --output bur_fvg
```

In alternativa indicare direttamente una sottocartella con `--output`.
`--limit 10` converte soltanto i primi 10 PDF, in ordine di percorso.
In questa modalita `--year` filtra le cartelle; `--dal` e `--al` non filtrano
la conversione. Le opzioni di rete e `--legacy-pages` non sono usate.
`--page` e `--solo-indice` sono incompatibili con `--convert-only`.

Il report `conversione.csv` elenca PDF, TXT, pagine e stato (`ok`,
`ocr_necessario`, `errore`) ed e aggiornato durante l'esecuzione. Gli indici
dello scraping e `file_sources.json` non vengono riscritti; il report descrive
la nuova conversione, mentre quei file conservano i metadati dello scraping.
Un PDF privo di testo richiede OCR: non viene creato un TXT vuoto e un TXT
preesistente resta intatto. Il codice di uscita e 2 se non ci sono PDF
selezionati o se almeno un file richiede controllo; altrimenti e 0.





## Estrarre soltanto il Sommario Parte Prima in un'altra directory

Lo script separato `extract_bur_part_one.py` legge i TXT gia esistenti e salva
soltanto la sezione **SOMMARIO PARTE PRIMA — LEGGI, REGOLAMENTI E ATTI DELLA
REGIONE**, mantenendo nomi e sottocartelle delle annualita:

```bash
python extract_bur_part_one.py bur_fvg --output bur_parte_prima
```

Esempio: `bur_fvg/2021/BUR_49_09_12_ordinario.txt` produce
`bur_parte_prima/2021/BUR_49_09_12_ordinario.txt`. I TXT sorgenti non vengono
modificati. Lo script usa soltanto la libreria standard di Python 3.10+, senza
rete, PDF, OCR o modelli. Accetta sia gli a capo originali sia i TXT ripuliti.

Per una sola annualita o un singolo file:

```bash
python extract_bur_part_one.py bur_fvg --year 2000 --output bur_parte_prima
python extract_bur_part_one.py bur_fvg/1999/BUR_legacy_5_18_ordinario.txt --output bur_parte_prima
```

### Esclusione del testo integrale, anche per il 1999–2000

L'estrazione parte solo da un'intestazione esplicita del **sommario regionale**.
Si ferma alla parte successiva del sommario o alla nuova intestazione
**PARTE PRIMA** che introduce i testi integrali. Riconosce inoltre alcune
formule tipiche del corpo degli atti, come “IL CONSIGLIO REGIONALE HA APPROVATO”
e “IL PRESIDENTE … PROMULGA”. L'output termina all'ultimo riferimento `pag. N`
precedente al confine individuato. Non riprende l'estrazione nelle parti successive.

Sono conservate le intestazioni del sommario ripetute sulle pagine di
continuazione. L'intestazione iniziale dell'output viene uniformata, mentre
il corpo selezionato mantiene il testo del TXT di origine. Le ripetizioni di
intestazioni o pie di pagina gia nel corpo non vengono corrette automaticamente.

Se mancano l'intestazione, i riferimenti di pagina o un confine sufficientemente
riconoscibile, il file viene segnalato invece di includere potenzialmente
il testo integrale. I confini sono riconosciuti con regole testuali, non con
una comprensione semantica: controllare il report, soprattutto per layout insoliti.

`estrazione_sezioni.csv` e `estrazione_sezioni.json` riportano per ogni sorgente
il risultato: `ok`, `section_not_found`, `no_summary_entries`, `ambiguous_end`
o `error`, gli offset del testo selezionato e il motivo del confine.
`voci` conta i riferimenti di pagina rilevati ed e indicativo.
Un file senza sezione valida non genera un nuovo TXT; un suo eventuale output
precedente e preservato e segnalato nel report. Il codice di uscita e 2 se ci
sono file da controllare o nessun TXT selezionato, altrimenti 0.

`--limit 10` limita la prova ai primi dieci TXT. Le cartelle `cache` e
`diagnostics` sono escluse; un'eventuale directory di output annidata
nell'input e esclusa dalla scansione. L'output non puo coincidere con la
directory dei sorgenti o con una sua directory antenata, per evitare di
sovrascrivere i file originali. I report descrivono solo l'esecuzione corrente.

```bash
python -m unittest -v test_extract_bur_part_one.py
```
