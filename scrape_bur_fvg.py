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
import re
import ssl
import time
from collections import deque
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.error import URLError
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


def tls_context(ca_file=None, use_certifi=False):
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
    return context


class Client:
    def __init__(self, root, delay, timeout, retries, refresh=False,
                 ca_file=None, use_certifi=False):
        self.cache = root / 'cache'
        self.cache.mkdir(parents=True, exist_ok=True)
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()),
                                   HTTPSHandler(context=tls_context(ca_file, use_certifi)))
        self.delay, self.timeout, self.retries = delay, timeout, retries
        self.refresh = refresh
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
                if pdf and not data.lstrip().startswith(b'%PDF-'):
                    raise ValueError('Il server ha restituito HTML o un file non PDF')
                if not pdf and b'<html' not in data.lower():
                    raise ValueError('Risposta non HTML')
                tmp = path.with_suffix('.tmp')
                tmp.write_bytes(data)
                tmp.replace(path)
                return data
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
                if attempt == self.retries:
                    raise
                time.sleep(min(30, 2 ** (attempt + 1)))
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


def fetch_summary(client, year, url, title, root, legacy_pages):
    uid = hashlib.sha256(url.encode()).hexdigest()[:16]
    folder = root / str(year)
    folder.mkdir(parents=True, exist_ok=True)
    row = dict(anno=year, id=uid, titolo=title, url_fascicolo=url,
               url_documento='', tipo_documento='', stato='', pdf='', testo='',
               pagine_pdf=0, pagine_estratte=0, errore='')
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
        pdfpath = folder / f'{uid}.pdf'
        pdfpath.write_bytes(data)
        row['pdf'] = str(pdfpath.relative_to(root))
        reader = PdfReader(io.BytesIO(data))
        count = len(reader.pages)
        row['pagine_pdf'] = count
        limit = count if summaries else min(count, legacy_pages)
        text = '\n\n'.join(f'--- Pagina {i+1} ---\n{reader.pages[i].extract_text() or ""}'
                           for i in range(limit))
        txtpath = folder / f'{uid}.txt'
        txtpath.write_text(text, encoding='utf-8')
        row['testo'] = str(txtpath.relative_to(root))
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
    ap.add_argument('--timeout', type=float, default=45)
    ap.add_argument('--retries', type=int, default=3)
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
    if min(args.delay, args.retries, args.legacy_pages, args.limit) < 0 or args.timeout <= 0:
        ap.error('Parametri numerici non validi')
    root = args.output
    root.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(), logging.FileHandler(root/'scraping.log', encoding='utf-8')])
    try:
        client = Client(root, args.delay, args.timeout, args.retries, args.refresh,
                        ca_file=args.ca_file, use_certifi=args.certifi)
        home = client.page(HOME)
    except Exception as exc:
        LOG.error('Impossibile inizializzare il download: %s', exc)
        return 2
    errors, rows, coverage = [], [], []
    seeds = {int(label): canonical(urljoin(HOME, value))
             for value, label in home.options if label.isdigit() and value}
    fields = ['anno', 'id', 'titolo', 'url_fascicolo', 'url_documento', 'tipo_documento',
              'stato', 'pdf', 'testo', 'pagine_pdf', 'pagine_estratte', 'errore']
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
