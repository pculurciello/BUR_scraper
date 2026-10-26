# Scraper dei sommari BUR Friuli Venezia Giulia

## Installazione ed esecuzione

Richiede Python 3.10 o successivo.

```bash
python -m pip install pypdf
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
- `BUR_NUMERO/ANNO_TIPO.pdf`: sommario PDF separato quando disponibile; in alternativa,
  PDF completo, se il ripiego storico è abilitato.
- `BUR_NUMERO/ANNO_TIPO.txt`: testo estratto, con separatori di pagina.
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



## Nomi dei documenti

I file PDF e TXT usano il percorso `BUR_[NUMBER]/[YEAR]_[TYPE].pdf` e `.txt`.
Lo slash è un separatore di directory: per esempio:

```text
bur_fvg/
  BUR_42/
    2026_ordinario.pdf
    2026_ordinario.txt
  BUR_30/
    2026_supplemento_ordinario.pdf
    2026_supplemento_ordinario.txt
  BUR_4/
    1999_supplemento_straordinario.pdf
    1999_supplemento_straordinario.txt
```

Per un supplemento, NUMBER è il suo numero, non quello del BUR ordinario
richiamato nel titolo. YEAR è l'annualità di pubblicazione nell'archivio.
TYPE distingue `ordinario`, `straordinario`, `supplemento_ordinario`,
`supplemento_straordinario` e `supplemento` quando il sottotipo non è indicato.
Gli indici CSV/JSON riportano i nuovi percorsi relativi.

`file_sources.json` associa i percorsi agli URL di origine. Se due fascicoli
con URL diversi produrrebbero lo stesso percorso, il secondo viene segnalato
come errore invece di sovrascrivere il primo. Non eliminare questo registro
per forzare una sovrascrittura. Un numero o tipo non riconosciuto viene
segnalato come errore, senza creare un nome arbitrario.

I precedenti file con nomi basati su hash non vengono cancellati o rinominati.
Una nuova esecuzione genera i nomi descrittivi riutilizzando i download in cache.
