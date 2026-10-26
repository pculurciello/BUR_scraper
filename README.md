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
- `AAAA/ID.pdf`: sommario PDF separato quando disponibile; in alternativa,
  PDF completo, se il ripiego storico è abilitato.
- `AAAA/ID.txt`: testo estratto, con separatori di pagina.
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
