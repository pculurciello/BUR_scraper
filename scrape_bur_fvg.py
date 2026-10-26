#!/usr/bin/env python3
"""Scarica sommari BUR FVG, inclusi supplementi, dagli archivi 1999-2026.
Python >=3.10; dipendenza: pypdf. Vedere --help.
Non certifica la completezza dell'archivio pubblicato dalla Regione.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import logging
import os
import shutil
import subprocess
import re
import ssl
import random
import time
from collections import deque
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from http.client import HTTPException
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.error import URLError, HTTPError
from urllib.request import Request, build_opener, HTTPCookieProcessor, HTTPSHandler
from pypdf import PdfReader

HOME = 'https://bur.regione.fvg.it/newbur/'
HOSTS = {'bur.regione.fvg.it', 'www.regione.fvg.it'}
LOG = logging.getLogger('bur')


def clean(s):
    return ' '.join(s.split())


def canonical(url, **overrides):
    p = urlsplit(url)
    if p.hostname not in HOSTS:
        raise ValueError(f'Host fuori archivio: {p.hostname}')
    q = dict(parse_qsl(p.query, keep_blank_values=True))
    q.update({k: str(v) for k, v in overrides.items()})
    q.pop('session', None)
    # Codifica anche gli slash di bnum: evita risposte diverse da quella richiesta.
    return urlunsplit(('https', p.netloc, p.path, urlencode(sorted(q.items())), ''))


class Page(HTMLParser):
    """Legge solo link, opzioni anno e titoli; ignora script e commenti."""
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.links, self.options, self.titles = [], [], []
        self.anchor = self.option = None
        self.title_depth = 0
        self.title_text = []
        self.skip = 0
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('script', 'style'):
            self.skip += 1
        if self.skip:
            return
        if tag == 'a':
            self.anchor = [a.get('href', ''), a.get('title', ''), []]
        if tag == 'option':
            self.option = [a.get('value', ''), []]
        if tag == 'div':
            if self.title_depth:
                self.title_depth += 1
            elif 'box-titolo' in a.get('class', '').split():
                self.title_depth = 1
                self.title_text = []

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == 'a' and self.anchor is not None:
            href, title, parts = self.anchor
            self.links.append((href, clean(' '.join(parts)) or title))
            self.anchor = None
        if tag == 'option' and self.option is not None:
            value, parts = self.option
            self.options.append((value, clean(' '.join(parts))))
            self.option = None
        if tag == 'div' and self.title_depth:
            self.title_depth -= 1
            if not self.title_depth:
                self.titles.append(clean(' '.join(self.title_text)))

    def handle_data(self, data):
        if self.skip:
            return
        if self.anchor is not None:
            self.anchor[2].append(data)
        if self.option is not None:
            self.option[1].append(data)
        if self.title_depth:
            self.title_text.append(data)


def issue_links(page, base):
    found = {}
    for href, title in page.links:
        path = urlsplit(urljoin(base, href)).path.lower()
        if path.endswith('/visionabur') or path.endswith('/archiviodettaglio.asp'):
            url = canonical(urljoin(base, href))
            found[url] = title
    return found


def pagination(page, base, year):
    out = set()
    for href, _ in page.links:
        u = urljoin(base, href)
        p = urlsplit(u)
        if p.path.lower() != urlsplit(base).path.lower():
            continue
        q = dict(parse_qsl(p.query))
        if any(k in q for k in ('pag', 'num_pag', 'trimestre')):
            out.add(canonical(u, anno=year))
    return sorted(out)


def tls_context(ca_file=None, use_certifi=False, insecure=False):
    """Mantiene il trust di sistema e aggiunge un bundle CA se richiesto."""
    context = ssl.create_default_context()
    if use_certifi:
        try:
            import certifi
        except ImportError as exc:
            raise ValueError('Installare certifi: python -m pip install --upgrade certifi') from exc
        context.load_verify_locations(cafile=certifi.where())
    if ca_file:
        context.load_verify_locations(cafile=str(ca_file))
    if insecure:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


class InvalidResponseError(ValueError):
    """Risposta vuota, incompleta o diversa dal documento richiesto."""


RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}


def retry_after_seconds(headers):
    """Interpreta Retry-After in secondi o come data HTTP."""
    value = headers.get('Retry-After') if headers else None
    if not value:
        return None
    try:
        seconds = float(value)
        return max(0.0, seconds) if seconds < float('inf') else None
    except (TypeError, ValueError):
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return max(0.0, (date - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


class Client:
    def __init__(self, root, delay, timeout, retries, refresh=False,
                 ca_file=None, use_certifi=False, retry_backoff=2.0, retry_max_wait=60.0,
                 insecure=False):
        self.cache = root / 'cache'
        self.cache.mkdir(parents=True, exist_ok=True)
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()),
                                   HTTPSHandler(context=tls_context(ca_file, use_certifi, insecure)))
        self.delay, self.timeout, self.retries = delay, timeout, retries
        self.refresh = refresh
        self.retry_backoff, self.retry_max_wait = retry_backoff, retry_max_wait
        self.last = 0.0

    def get(self, url, pdf=False):
        url = canonical(url)
        key = hashlib.sha256(url.encode()).hexdigest()
        path = self.cache / (key + ('.pdf' if pdf else '.html'))
        if path.exists() and not self.refresh:
            return path.read_bytes()
        for attempt in range(self.retries + 1):
            try:
                time.sleep(max(0, self.delay - (time.monotonic() - self.last)))
                self.last = time.monotonic()
                req = Request(url, headers={
                    'User-Agent': 'BUR-FVG-research-scraper/1.0',
                    'Accept': 'application/pdf' if pdf else 'text/html',
                })
                with self.opener.open(req, timeout=self.timeout) as response:
                    if urlsplit(response.url).hostname not in HOSTS:
                        raise ValueError('Redirect fuori dai domini regionali')
                    data = response.read()
                    expected = response.headers.get('Content-Length')
                    if expected and expected.isdigit() and len(data) != int(expected):
                        raise InvalidResponseError('Download incompleto')
                if pdf and not data.lstrip().startswith(b'%PDF-'):
                    raise InvalidResponseError('Il server ha restituito HTML o un file non PDF')
                if not pdf and b'<html' not in data.lower():
                    raise InvalidResponseError('Risposta non HTML')
            except Exception as exc:
                reason = exc.reason if isinstance(exc, URLError) else exc
                if isinstance(reason, ssl.SSLCertVerificationError):
                    raise RuntimeError(
                        f'Verifica TLS fallita per {urlsplit(url).hostname}: {reason}. '
                        'Aggiornare i certificati di Python oppure usare --certifi '
                        '(python -m pip install --upgrade certifi). '
                        'Con proxy aziendale, usare --ca-file /percorso/ca-aziendale.pem '
                        'con un certificato fornito dal proprio amministratore.'
                    ) from exc
                # Errori permanenti (es. 404) e problemi locali non migliorano
                # ripetendo la richiesta. Nessun log per i tentativi intermedi.
                retryable = (exc.code in RETRYABLE_HTTP if isinstance(exc, HTTPError)
                             else isinstance(exc, (URLError, TimeoutError,
                                                   ConnectionError, HTTPException,
                                                   InvalidResponseError)))
                requested_wait = (retry_after_seconds(exc.headers)
                                  if isinstance(exc, HTTPError) else None)
                if isinstance(exc, HTTPError):
                    exc.close()
                if not retryable or attempt == self.retries:
                    raise
                if requested_wait is None:
                    pause = min(self.retry_max_wait,
                                self.retry_backoff * 2 ** min(attempt, 30))
                    pause = min(self.retry_max_wait, pause + random.uniform(0, pause * 0.2))
                else:
                    pause = min(self.retry_max_wait, requested_wait)
                time.sleep(pause)
                continue
            # Cache solo dopo un download completo. Un errore del filesystem
            # deve emergere subito, senza ripetere richieste di rete riuscite.
            tmp = path.with_suffix('.tmp')
            tmp.write_bytes(data)
            tmp.replace(path)
            return data
        raise RuntimeError('Download fallito')

    def page(self, url):
        data = self.get(url)
        try:
            html = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            html = data.decode('cp1252', errors='replace')
        return Page(html)


def discover(client, year, seed, errors):
    seed = canonical(seed, anno=year)
    todo, visited, signatures, found = deque([seed]), set(), {}, {}
    while todo:
        url = todo.popleft()
        if url in visited:
            continue
        visited.add(url)
        try:
            page = client.page(url)
            links = issue_links(page, url)
            if not links:
                raise ValueError('Nessun fascicolo: verificare archivio o selettori')
            signature = tuple(sorted(links))
            if signature in signatures:
                # Non troncare: le altre pagine in coda possono comunque essere valide.
                errors.append({'fase': 'paginazione', 'anno': year, 'url': url,
                               'errore': 'Elenco identico a ' + signatures[signature]})
            else:
                signatures[signature] = url
            found.update(links)
            for nxt in pagination(page, url, year):
                if nxt not in visited:
                    todo.append(nxt)
            if len(visited) > 1000:
                raise RuntimeError('Superato limite di 1000 pagine per anno')
        except Exception as exc:
            errors.append({'fase': 'archivio', 'anno': year, 'url': url, 'errore': str(exc)})
            LOG.warning('%s: %s', url, exc)
    return found, len(visited)


def infer_document_type(title):
    title = clean(title).upper()
    if 'SUPPLEMENTO' in title:
        if 'STRAORDINARIO' in title:
            return 'supplemento_straordinario'
        if 'ORDINARIO' in title:
            return 'supplemento_ordinario'
        return 'supplemento'
    if 'STRAORDINARI' in title:
        return 'straordinario'
    if (title.startswith('NUMERO') or 'ORDINARIO' in title
            or re.search(r'\bBUR\s+(?:N[.°º]?\s*)?\d+\b', title)):
        return 'ordinario'
    return None


def pdf_document_title(data, reader):
    """Legge Title con pdfinfo, oppure /Title con pypdf senza dipendenze native."""
    if shutil.which('pdfinfo'):
        try:
            result = subprocess.run(
                ['pdfinfo', '-enc', 'UTF-8', '-'], input=data,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
                env={**os.environ, 'LC_ALL': 'C'}, check=False)
            if result.returncode == 0:
                match = re.search(r'^Title:[ \t]*(.*)$',
                                  result.stdout.decode('utf-8', errors='replace'), re.M)
                if match and clean(match.group(1)):
                    return clean(match.group(1)), 'pdfinfo'
        except (OSError, subprocess.TimeoutExpired):
            pass
    metadata = reader.metadata
    title = metadata.title if metadata else None
    return (clean(str(title)), 'pdf_metadata') if title else ('', '')


def document_basename(root, year, title, document_type=None):
    """Numero dal fascicolo; tipo dai metadati PDF quando disponibile."""
    title = clean(title).upper()
    number = re.search(r'\b(?:NUMERO|N[.°º]?)\s*(\d+)', title)
    if not number:
        raise ValueError('Numero del fascicolo non riconosciuto: ' + title)
    kind = document_type or infer_document_type(title)
    if kind not in {'ordinario', 'straordinario', 'supplemento',
                    'supplemento_ordinario', 'supplemento_straordinario'}:
        raise ValueError('Tipo del fascicolo non riconosciuto: ' + title)
    return root / str(year) / f'BUR_{int(number.group(1))}-{year}-{kind}'


def save_document_files(root, base, source_url, data, text):
    """Evita di sovrascrivere un altro fascicolo con numero/anno/tipo uguali."""
    registry_path = root / 'file_sources.json'
    registry = json.loads(registry_path.read_text(encoding='utf-8')) if registry_path.exists() else {}
    pdfpath, txtpath = base.with_suffix('.pdf'), base.with_suffix('.txt')
    key = pdfpath.relative_to(root).as_posix()
    owner = registry.get(key)
    if owner is not None and owner != source_url:
        raise ValueError(f'Collisione del nome {key}: gia assegnato a {owner}')
    payloads = ((pdfpath, data), (txtpath, text.encode('utf-8')))
    if owner is None:
        for path, payload in payloads:
            if path.exists() and path.read_bytes() != payload:
                raise ValueError(f'File preesistente senza provenienza verificabile: {path}')
    base.parent.mkdir(parents=True, exist_ok=True)
    for path, payload in payloads:
        tmp = path.with_suffix(path.suffix + '.tmp')
        tmp.write_bytes(payload)
        tmp.replace(path)
    registry[key] = source_url
    tmp = registry_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(registry_path)
    return pdfpath, txtpath


def fetch_summary(client, year, url, title, root, legacy_pages):
    uid = hashlib.sha256(url.encode()).hexdigest()[:16]
    row = dict(anno=year, id=uid, titolo=title, url_fascicolo=url,
               url_documento='', tipo_documento='', stato='', pdf='', testo='',
               pagine_pdf=0, pagine_estratte=0, errore='',
               titolo_pdf='', tipo_fascicolo='', fonte_tipo='')
    try:
        page = client.page(url)
        if page.titles and clean(page.titles[0]).casefold() != clean(title).casefold():
            raise ValueError('Titolo del dettaglio diverso da quello in archivio: '
                             + page.titles[0])
        summaries, full = [], []
        for href, label in page.links:
            if not href or href.startswith(('#', 'javascript:')):
                continue
            if 'sommario' in (label + ' ' + href).lower():
                summaries.append(canonical(urljoin(url, href)))
            elif re.search(r'testo completo|copia per consultazione', label, re.I):
                full.append(canonical(urljoin(url, href)))
        if summaries:
            target = summaries[0]
            row['tipo_documento'] = 'sommario_separato'
        elif full and legacy_pages > 0:
            target = full[0]
            row['tipo_documento'] = 'prime_pagine_integrale_da_verificare'
        else:
            row['stato'] = 'sommario_non_disponibile'
            return row
        row['url_documento'] = target
        data = client.get(target, pdf=True)
        reader = PdfReader(io.BytesIO(data))
        pdf_title, metadata_source = pdf_document_title(data, reader)
        kind = infer_document_type(pdf_title)
        row['titolo_pdf'] = pdf_title
        row['fonte_tipo'] = metadata_source if kind else 'titolo_pagina'
        kind = kind or infer_document_type(title)
        base = document_basename(root, year, title, document_type=kind)
        row['tipo_fascicolo'] = kind
        count = len(reader.pages)
        row['pagine_pdf'] = count
        limit = count if summaries else min(count, legacy_pages)
        text = '\n\n'.join(f'--- Pagina {i+1} ---\n{reader.pages[i].extract_text() or ""}'
                           for i in range(limit))
        pdfpath, txtpath = save_document_files(root, base, url, data, text)
        row['pdf'] = pdfpath.relative_to(root).as_posix()
        row['testo'] = txtpath.relative_to(root).as_posix()
        row['pagine_estratte'] = limit
        has_text = any((reader.pages[i].extract_text() or '').strip() for i in range(limit))
        row['stato'] = ('ok' if summaries else 'da_verificare') if has_text else 'ocr_necessario'
    except Exception as exc:
        row['stato'], row['errore'] = 'errore', str(exc)
        LOG.warning('%s: %s', url, exc)
    return row


def write_csv(path, rows, fields):
    tmp = path.with_suffix('.tmp')
    with tmp.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dal', type=int, default=1999)
    ap.add_argument('--al', type=int, default=2026)
    ap.add_argument('--output', type=Path, default=Path('bur_fvg'))
    ap.add_argument('--delay', type=float, default=1.0)
    ap.add_argument('--timeout', type=float, default=30,
                    help='Timeout delle operazioni socket in secondi (default: 30)')
    ap.add_argument('--retries', type=int, default=5,
                    help='Ritentativi silenziosi dopo il primo tentativo (default: 5)')
    ap.add_argument('--retry-backoff', type=float, default=2.0,
                    help='Pausa iniziale fra ritentativi in secondi (default: 2)')
    ap.add_argument('--retry-max-wait', type=float, default=60.0,
                    help='Pausa massima fra ritentativi in secondi (default: 60)')
    ap.add_argument('--insecure', action='store_true',
                    help='Disabilita esplicitamente la verifica TLS per questa esecuzione')
    ca = ap.add_mutually_exclusive_group()
    ca.add_argument('--ca-file', type=Path, help='Bundle CA PEM aggiuntivo, anche per proxy aziendali')
    ca.add_argument('--certifi', action='store_true', help='Aggiunge il bundle CA del pacchetto certifi')
    ap.add_argument('--refresh', action='store_true', help='Ignora cache, utile per annualità corrente')
    ap.add_argument('--legacy-pages', type=int, default=12,
                    help='Senza sommario separato, estrae N pagine iniziali dal PDF completo; '
                         'sono candidate da verificare. 0 disabilita il ripiego.')
    ap.add_argument('--limit', type=int, default=0, help='Elabora solo N fascicoli per anno (prova)')
    ap.add_argument('--solo-indice', action='store_true', help='Scopre i fascicoli senza scaricare PDF')
    args = ap.parse_args()
    if not 1999 <= args.dal <= args.al <= 2026:
        ap.error('Intervallo consentito: 1999–2026')
    numeric = (args.delay, args.timeout, args.retry_backoff, args.retry_max_wait)
    if (not all(0 <= v < float('inf') for v in numeric)
            or min(args.retries, args.legacy_pages, args.limit) < 0
            or args.timeout <= 0 or args.retry_max_wait <= 0):
        ap.error('Parametri numerici non validi')
    root = args.output
    root.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(), logging.FileHandler(root/'scraping.log', encoding='utf-8')])
    try:
        client = Client(root, args.delay, args.timeout, args.retries, args.refresh,
                        ca_file=args.ca_file, use_certifi=args.certifi,
                        retry_backoff=args.retry_backoff, retry_max_wait=args.retry_max_wait,
                        insecure=args.insecure)
        home = client.page(HOME)
    except Exception as exc:
        LOG.error('Impossibile inizializzare il download: %s', exc)
        return 2
    errors, rows, coverage = [], [], []
    seeds = {int(label): canonical(urljoin(HOME, value))
             for value, label in home.options if label.isdigit() and value}
    fields = ['anno', 'id', 'titolo', 'url_fascicolo', 'url_documento', 'tipo_documento',
              'stato', 'pdf', 'testo', 'pagine_pdf', 'pagine_estratte', 'errore',
              'titolo_pdf', 'tipo_fascicolo', 'fonte_tipo']
    for year in range(args.dal, args.al + 1):
        LOG.info('Anno %s', year)
        if year not in seeds:
            errors.append(dict(fase='anno', anno=year, url=HOME, errore='Anno assente nel menu'))
            coverage.append(dict(anno=year, pagine_archivio=0, fascicoli=0, elaborati=0, anomalie=1))
            continue
        nerr = len(errors)
        issues, pages = discover(client, year, seeds[year], errors)
        items = sorted(issues.items())
        if args.limit:
            items = items[:args.limit]
        for url, title in items:
            if args.solo_indice:
                rows.append(dict(anno=year, titolo=title, url_fascicolo=url, stato='solo_indice'))
            else:
                rows.append(fetch_summary(client, year, url, title, root, args.legacy_pages))
            # Checkpoint: se interrotto, i file scaricati restano in cache.
            write_csv(root/'fascicoli.csv', rows, fields)
        coverage.append(dict(anno=year, pagine_archivio=pages, fascicoli=len(issues),
                             elaborati=len(items), anomalie=len(errors)-nerr))
        write_csv(root/'copertura.csv', coverage,
                  ['anno', 'pagine_archivio', 'fascicoli', 'elaborati', 'anomalie'])
        write_csv(root/'fascicoli.csv', rows, fields)
        (root/'errori.json').write_text(json.dumps(errors, ensure_ascii=False, indent=2), encoding='utf-8')
    (root/'fascicoli.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    problematic = sum(r.get('stato') not in ('ok', 'solo_indice') for r in rows)
    LOG.info('Fascicoli elaborati: %d; da controllare: %d; anomalie archivio: %d',
             len(rows), problematic, len(errors))
    return 2 if errors or problematic else 0


if __name__ == '__main__':
    raise SystemExit(main())




