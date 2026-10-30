#!/usr/bin/env python3
"""Extract only the regional Part One summary from existing BUR TXT files.
Python >=3.10. Standard library only; no network, PDF conversion or LLM.
"""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
import re

TITLE = r'LEGGI\s*,?\s*REGOLAMENTI\s*,?\s*E\s+ATTI\s+DELLA\s+REGIONE\b'
SUMMARY = re.compile(r'\bSOMMARIO\s+PARTE\s+PRIMA\s+' + TITLE, re.I)
PART = re.compile(r'\b(?:(?P<summary>SOMMARIO)\s+)?PARTE\s+(?P<part>PRIMA|SECONDA|TERZA|QUARTA)\b', re.I)
REGIONAL_BODY = re.compile(r'\bPARTE\s+PRIMA\s+' + TITLE, re.I)
PAGE = re.compile(r'(?<!\w)pag(?:ina)?\.?\s*\d+(?:[ \t]*[-–,][ \t]*\d+)*(?!\w)', re.I)
BODY_FORMULA = re.compile(
    r'\b(?:IL\s+CONSIGLIO\s+REGIONALE\s+HA\s+APPROVATO|'
    r'IL\s+PRESIDENTE(?:\s+DELLA\s+GIUNTA)?(?:\s+REGIONALE|\s+DELLA\s+REGIONE)?\s+PROMULGA|'
    r'(?:IL\s+DIRETTORE(?:\s+CENTRALE)?|LA\s+GIUNTA\s+REGIONALE|'
    r'IL\s+PRESIDENTE\s+DELLA\s+GIUNTA\s+REGIONALE)\s+'
    r'(?:VIST[OAIE]|PREMESSO|CONSIDERATO|DECRETA|DELIBERA))\b', re.I)
FOOTER_WORDS = set('bollettino ufficiale della regione autonoma friuli venezia giulia '
                   'n numero so suppl supplemento ord ordinario straordinario pagina '
                   'gennaio febbraio marzo aprile maggio giugno luglio agosto settembre '
                   'ottobre novembre dicembre'.split())
HEADING = 'SOMMARIO PARTE PRIMA\nLEGGI, REGOLAMENTI E ATTI DELLA REGIONE'
EXCLUDED = {'cache', 'diagnostics', '.git', '.venv', '__pycache__'}


def footer_only(text):
    text = re.sub(r'---\s*Pagina\s+\d+\s*---', '', text, flags=re.I)
    words = re.findall(r'[^\W\d_]+', text, flags=re.UNICODE)
    return all(word.casefold() in FOOTER_WORDS for word in words)


def extract_section(text):
    """Fail closed when the summary heading or a reliable end is missing."""
    heading = SUMMARY.search(text)
    result = dict(stato='', testo='', voci=0, inizio='', fine='', confine='', errore='')
    if heading is None:
        result['stato'] = 'section_not_found'
        return result
    end, boundary = len(text), 'end_of_summary_file'
    for marker in PART.finditer(text, heading.end()):
        if marker['part'].upper() == 'PRIMA':
            if marker['summary'] and SUMMARY.match(text, marker.start()):
                continue  # Repeated summary header on a continuation page.
            if not marker['summary'] and REGIONAL_BODY.match(text, marker.start()):
                end, boundary = marker.start(), 'full_text_part_one'
                break
        else:
            # Explicit Sommario headings, all-caps headings and headings
            # at the start of a source line are structural boundaries.
            prefix = text[text.rfind('\n', 0, marker.start()) + 1:marker.start()]
            if marker['summary'] or marker.group().isupper() or not prefix.strip():
                end, boundary = marker.start(), 'next_part'
                break
    formula = BODY_FORMULA.search(text, heading.end(), end)
    if formula:
        end, boundary = formula.start(), 'full_text_formula'
    locators = list(PAGE.finditer(text, heading.end(), end))
    if not locators:
        result['stato'] = 'no_summary_entries'
        return result
    # End at the last summary page locator: omit trailing mastheads and,
    # when a body formula was found, its preceding repeated act title too.
    last = locators[-1].end()
    if boundary == 'end_of_summary_file' and not footer_only(text[last:end]):
        result.update(stato='ambiguous_end', confine='unrecognized_trailing_text')
        return result
    body = text[heading.end():last].strip()
    body = re.sub(r'---\s*Pagina\s+\d+\s*---', '', body, flags=re.I).strip()
    result.update(stato='ok', testo=HEADING + '\n\n' + body + '\n',
                  voci=len(locators), inizio=heading.start(), fine=last, confine=boundary)
    return result


def read_text(path):
    data = path.read_bytes()
    try:
        return data.decode('utf-8-sig')
    except UnicodeDecodeError:
        return data.decode('cp1252')


def select_files(source, output, year=None):
    if source.is_file():
        paths, root = [source], source.parent
    else:
        paths, root = source.rglob('*'), source
    selected = []
    for path in paths:
        if not path.is_file() or path.is_symlink() or path.suffix.lower() != '.txt':
            continue
        relative = path.relative_to(root)
        if any(part.lower() in EXCLUDED for part in relative.parts[:-1]):
            continue
        if output.is_relative_to(root) and path.resolve().is_relative_to(output):
            continue
        if year is not None and str(year) not in path.parent.parts:
            continue
        selected.append((path, relative))
    return sorted(selected, key=lambda item: item[1].as_posix())


def write_report(output, rows):
    fields = ['source', 'output', 'stato', 'voci', 'inizio', 'fine', 'confine', 'errore', 'output_precedente_preservato']
    temporary = output/'estrazione_sezioni.csv.tmp'
    with temporary.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(output/'estrazione_sezioni.csv')
    temporary = output/'estrazione_sezioni.json.tmp'
    temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(output/'estrazione_sezioni.json')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='Directory dei TXT oppure un singolo TXT')
    parser.add_argument('--output', type=Path, default=Path('bur_parte_prima'))
    parser.add_argument('--year', type=int, help='Filtra la cartella di una sola annualita')
    parser.add_argument('--limit', type=int, default=0, help='Elabora solo i primi N TXT (0=tutti)')
    args = parser.parse_args(argv)
    source, output = args.input.resolve(), args.output.resolve()
    if not source.exists() or (not source.is_dir() and not source.is_file()):
        parser.error('Il percorso di input non esiste o non e un file/directory')
    if source.is_file() and source.suffix.lower() != '.txt':
        parser.error('Sono accettati soltanto file TXT')
    if source.is_relative_to(output):
        parser.error('L output deve essere distinto dall input e non puo essere una sua directory antenata')
    if args.limit < 0:
        parser.error('--limit deve essere >= 0')
    if args.year is not None and not 1000 <= args.year <= 9999:
        parser.error('--year deve essere un anno a quattro cifre')
    files = select_files(source, output, args.year)
    if args.limit:
        files = files[:args.limit]
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for path, relative in files:
        target = output/relative
        row = dict(source=relative.as_posix(), output='', stato='', voci=0,
                   inizio='', fine='', confine='', errore='', output_precedente_preservato=False)
        try:
            result = extract_section(read_text(path))
            text = result.pop('testo')
            row.update(result)
            if row['stato'] == 'ok':
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix('.txt.tmp')
                temporary.write_text(text, encoding='utf-8')
                temporary.replace(target)
                row['output'] = relative.as_posix()
            else:
                row['output_precedente_preservato'] = target.exists()
        except Exception as exc:
            row.update(stato='error', errore=str(exc), output_precedente_preservato=target.exists())
        rows.append(row)
        write_report(output, rows)
    if not rows:
        write_report(output, rows)
    succeeded = sum(row['stato'] == 'ok' for row in rows)
    print(f'{succeeded}/{len(rows)} sezioni estratte; {len(rows)-succeeded} file da controllare. Report: {output}')
    return 0 if rows and succeeded == len(rows) else 2


if __name__ == '__main__':
    raise SystemExit(main())
