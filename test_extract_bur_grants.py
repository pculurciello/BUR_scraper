import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import extract_bur_grants as e

EXAMPLE_ACT = 'Deliberazione della Giunta regionale 6 febbraio 2026, n. 143'
EXAMPLE_TEXT = ('Bando recante i criteri e le modalità per la concessione e l’erogazione '
                'di aiuti a favore delle PMI, con unità operativa in regione e attive '
                'nella produzione agricola primaria, a supporto delle spese sostenute '
                'per la realizzazione di nuovi impianti arborei per l’anno 2026. Adozione.')
EXAMPLE = EXAMPLE_ACT + ' LR 24/2021, art. 3, commi 17-29. ' + EXAMPLE_TEXT + ' pag. 101.'

class ExtractionTests(unittest.TestCase):
    def test_exact_line_fields(self):
        row = next(e.candidates(EXAMPLE))
        self.assertEqual(row['act'], EXAMPLE_ACT)
        self.assertEqual(row['text'], EXAMPLE_TEXT)
        self.assertEqual(row['legal_references'], 'LR 24/2021, art. 3, commi 17-29.')
        self.assertEqual(row['page'], 101)
        self.assertEqual(row['line_number'], 1)
        self.assertEqual(row['parse_warnings'], [])
        self.assertEqual(row['raw_text'], EXAMPLE[row['start']:row['end']])

    def test_adjacent_lines_do_not_exchange_pages_acts_or_titles(self):
        text = (EXAMPLE_ACT + '. Bando uno. pag. 10.\n'
                'Decreto del direttore 7 febbraio 2026, n. 144. Assunzioni. pag. 20.\n'
                'Decreto del direttore 8 febbraio 2026, n. 145. Bando due. pag. 30.')
        rows = list(e.candidates(text))
        self.assertEqual([r['page'] for r in rows], [10, 30])
        self.assertEqual([r['line_number'] for r in rows], [1, 3])
        self.assertEqual([r['text'] for r in rows], ['Bando uno.', 'Bando due.'])
        self.assertEqual(rows[1]['act'], 'Decreto del direttore 8 febbraio 2026, n. 145')
        for row in rows:
            self.assertEqual(row['raw_text'], text[row['start']:row['end']])

    def test_preserve_full_title_before_keyword(self):
        title = 'Approvazione della graduatoria. Bando 2026. Adozione.'
        row = next(e.candidates(EXAMPLE_ACT + '. ' + title + ' pag. 17'))
        self.assertEqual(row['text'], title)
        self.assertIsNone(row['legal_references'])

    def test_legal_citations_inside_title_are_not_other_acts(self):
        title = 'Bando ai sensi della legge regionale 3 marzo 2020, n. 5. Approvazione.'
        row = next(e.candidates(EXAMPLE_ACT + '. ' + title + ' pag. 99.'))
        self.assertEqual(row['act'], EXAMPLE_ACT)
        self.assertEqual(row['text'], title)

    def test_optional_basis_is_separate_and_abbreviations_are_not_sentences(self):
        for basis in ['L. R. 24/2021, art. 3, commi 17-29.',
                      'LR 24/2021. Art. 3, comma 2.',
                      'Legge regionale 3 marzo 2020, n. 5.']:
            with self.subTest(basis=basis):
                row = next(e.candidates(EXAMPLE_ACT + ' ' + basis + ' Bando regionale. pag. 6.'))
                self.assertEqual(row['legal_references'], basis)
                self.assertEqual(row['text'], 'Bando regionale.')

    def test_trailing_page_only_internal_pages_remain_in_title(self):
        row = next(e.candidates(EXAMPLE_ACT + '. Bando già pubblicato a pag. 15. Proroga. pag. 77.'))
        self.assertEqual(row['page'], 77)
        self.assertEqual(row['text'], 'Bando già pubblicato a pag. 15. Proroga.')

    def test_missing_metadata_is_not_borrowed_from_next_line(self):
        rows = list(e.candidates('Bando senza riferimento\n' + EXAMPLE))
        self.assertIsNone(rows[0]['act'])
        self.assertIsNone(rows[0]['page'])
        self.assertEqual(rows[0]['parse_warnings'], ['missing_trailing_page', 'unrecognized_act'])
        self.assertEqual(rows[1]['page'], 101)

    def test_case_insensitive_standalone_bando_only(self):
        for word in ['bando', 'BANDO', 'Bando', 'BaNdO']:
            row = next(e.candidates(word + ' di gara. pag. 4.'))
            self.assertEqual(row['page'], 4)
        for word in ['bandi', 'abbandono', 'contributi', 'avviso']:
            self.assertEqual(list(e.candidates(word + ' regionali. pag. 4.')), [])

    def test_short_act_and_number_suffix(self):
        for citation in ['Decreto del direttore n. 144',
                         'Decreto del Presidente della Regione 8 febbraio 2026, n. 145/Pres.']:
            row = next(e.candidates(citation + ' Bando. pag. 2.'))
            self.assertEqual(row['act'], citation.rstrip('.'))
            self.assertEqual(row['text'], 'Bando.')

    def test_blank_lines_and_offsets(self):
        text = '\n  ' + EXAMPLE + '\n\n' + EXAMPLE + '\n'
        rows = list(e.candidates(text))
        self.assertEqual([r['line_number'] for r in rows], [2, 4])
        for row in rows:
            self.assertEqual(row['raw_text'], text[row['start']:row['end']])

    def test_ambiguous_basis_is_preserved_and_flagged(self):
        title = 'LR 24/2021 Bando regionale senza separatore'
        row = next(e.candidates(EXAMPLE_ACT + ' ' + title + ' pag. 10.'))
        self.assertEqual(row['text'], title)
        self.assertIn('ambiguous_legal_basis', row['parse_warnings'])

    def test_cli_default_folder_and_consistent_json_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'bur_parte_prima' / '2026').mkdir(parents=True)
            (root / 'bur_parte_prima' / '2026' / 'call.TXT').write_text(EXAMPLE, encoding='utf-8')
            (root / 'bur_parte_prima' / 'ignored.pdf').write_bytes(b'not a PDF')
            (root / 'bur_fvg').mkdir()
            (root / 'bur_fvg' / 'outside.txt').write_text('Bando fuori cartella. pag. 5.')
            previous = e.os.getcwd()
            try:
                e.os.chdir(root)
                with patch('sys.argv', ['extract_bur_grants.py', '--output', 'results', '--candidates-only']), \
                     patch.object(e, 'confirm', side_effect=AssertionError('No model')):
                    self.assertEqual(e.main(), 0)
            finally:
                e.os.chdir(previous)
            rows = json.loads((root / 'results' / 'candidates.json').read_text())
            audit = json.loads((root / 'results' / 'candidates.jsonl').read_text())
            self.assertEqual(rows, [{key: audit[key] for key in e.PUBLIC_FIELDS}])
            self.assertEqual(Path(rows[0]['source']), Path('2026/call.TXT'))
            self.assertEqual(rows[0]['page'], 101)
            self.assertNotIn('page_before', audit)
            self.assertNotIn('page_after', audit)

    def test_missing_default_folder_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'bur_fvg').mkdir()
            previous = e.os.getcwd()
            try:
                e.os.chdir(root)
                with patch('sys.argv', ['extract_bur_grants.py', '--candidates-only']), patch('sys.stderr'):
                    with self.assertRaises(SystemExit) as raised:
                        e.main()
                    self.assertEqual(raised.exception.code, 2)
            finally:
                e.os.chdir(previous)

    def test_pdf_read_is_disabled(self):
        with self.assertRaises(ValueError):
            e.read(Path('unused.pdf'))

class SemanticTests(unittest.TestCase):
    def test_context_contains_act_and_description_and_uses_cache(self):
        result = {'decision': 'include', 'reason': 'Bando', 'references': [{
            'kind': 'deliberation', 'role': 'subject', 'citation': EXAMPLE_ACT, 'evidence': EXAMPLE_TEXT}]}
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self):
                return json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(result)}}]}).encode()
        with tempfile.TemporaryDirectory() as tmp:
            args = SimpleNamespace(output=Path(tmp), base_url='http://localhost:8000/v1', model='test')
            (args.output / 'cache').mkdir()
            with patch.object(e.urllib.request, 'urlopen', return_value=Response()) as call:
                for _ in range(2):
                    self.assertEqual(e.confirm({'act': EXAMPLE_ACT, 'legal_references': 'LR 24/2021.', 'text': EXAMPLE_TEXT}, args)['decision'], 'include')
                self.assertEqual(call.call_count, 1)
                payload = json.loads(call.call_args.args[0].data)
                self.assertIn(EXAMPLE_ACT, payload['messages'][1]['content'])
                self.assertIn(EXAMPLE_TEXT, payload['messages'][1]['content'])
                self.assertIn('LR 24/2021.', payload['messages'][1]['content'])

    def test_invented_reference_is_rejected(self):
        with self.assertRaises(ValueError):
            e.validate({'decision': 'include', 'reason': '', 'references': [{
                'kind': 'law', 'role': 'subject', 'citation': 'Invented', 'evidence': 'Bando'}]}, 'Bando')

    def test_errors_are_not_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = SimpleNamespace(output=Path(tmp), base_url='http://localhost:8000/v1', model='test')
            (args.output / 'cache').mkdir()
            with patch.object(e.urllib.request, 'urlopen', side_effect=OSError('offline')), patch.object(e.time, 'sleep'):
                self.assertEqual(e.confirm({'act': None, 'text': 'Bando.'}, args)['decision'], 'error')
            self.assertEqual(list((args.output / 'cache').iterdir()), [])

if __name__ == '__main__':
    unittest.main()
