import json
from pathlib import Path
import tempfile
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import extract_bur_grants as e

EXAMPLE_ACT = 'Deliberazione della Giunta regionale 6 febbraio 2026, n. 143'
EXAMPLE_TEXT = ('Bando recante i criteri e le modalità per la concessione e l’erogazione '
                'di aiuti a favore delle PMI, con unità operativa in regione e attive '
                'nella produzione agricola primaria, a supporto delle spese sostenute '
                'per la realizzazione di nuovi impianti arborei per l’anno 2026. Adozione.')
EXAMPLE = 'pag. 101 ' + EXAMPLE_ACT + ' LR 24/2021, art. 3, commi 17-29. ' + EXAMPLE_TEXT

class ExtractionTests(unittest.TestCase):
    def test_user_example_exact_output(self):
        rows = list(e.candidates(EXAMPLE))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['page_before'], '101')
        self.assertEqual({k: rows[0][k] for k in ['text', 'act']},
                         {'text': EXAMPLE_TEXT, 'act': EXAMPLE_ACT})

    def test_case_insensitive_word_only(self):
        for word in ['bando', 'BANDO', 'Bando', 'BaNdO']:
            self.assertEqual(len(list(e.candidates(word + ' per contributi.'))), 1)
        for text in ['Bandi aperti.', 'Abbandono del progetto.', 'Contributi alle imprese.',
                     'Regolamento per sovvenzioni.', 'Avviso pubblico.']:
            self.assertEqual(list(e.candidates(text)), [])

    def test_no_topic_or_act_filter(self):
        for text in ['Bando di concorso pubblico.', 'Bando di gara.', 'Bando culturale.']:
            rows = list(e.candidates(text))
            self.assertEqual(len(rows), 1)
            self.assertIsNone(rows[0]['act'])
            self.assertEqual(rows[0]['text'], text)

    def test_sentence_beginning_before_keyword_is_preserved(self):
        text = EXAMPLE_ACT + '. LR 24/2021. Approvazione del bando per aiuti alle imprese. Adozione.'
        row = next(e.candidates(text))
        self.assertEqual(row['text'], 'Approvazione del bando per aiuti alle imprese. Adozione.')

    def test_multiline_text_and_act_are_compacted(self):
        text = EXAMPLE.replace('Giunta regionale', 'Giunta\nregionale').replace('Bando recante', 'Bando\nrecante')
        row = next(e.candidates(text))
        self.assertEqual(row['act'], EXAMPLE_ACT)
        self.assertEqual(row['text'], EXAMPLE_TEXT)
        self.assertEqual(row['raw_text'], text[row['start']:row['end']])

    def test_no_truncation_of_long_call(self):
        text = 'Bando per ' + 'interventi ' * 2000 + 'Adozione.'
        self.assertEqual(next(e.candidates(text))['text'], text)

    def test_repeated_keyword_produces_one_record_per_entry(self):
        self.assertEqual(len(list(e.candidates('Bando regionale. Modifica del bando.'))), 1)

    def test_entries_separated_by_page_markers(self):
        text = EXAMPLE_ACT + '. Bando regionale. Adozione. pag. 101 '
        text += 'Decreto del direttore 7 febbraio 2026, n. 144. Nessuna chiamata. pag. 102 '
        text += 'Decreto del Presidente della Regione 8 febbraio 2026, n. 145/Pres. Bando turismo. pag. 103'
        rows = list(e.candidates(text))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['act'], EXAMPLE_ACT)
        self.assertNotIn('Nessuna', rows[0]['text'])
        self.assertEqual(rows[1]['act'], 'Decreto del Presidente della Regione 8 febbraio 2026, n. 145/Pres')
        self.assertEqual(rows[1]['text'], 'Bando turismo.')

    def test_full_headings_without_page_markers(self):
        text = EXAMPLE_ACT + '. Bando uno.\nDecreto del direttore 7 febbraio 2026, n. 144. Bando due.'
        rows = list(e.candidates(text))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['text'], 'Bando uno.')
        self.assertEqual(rows[1]['text'], 'Bando due.')

    def test_legal_references_inside_description_stay(self):
        text = EXAMPLE_ACT + '. Bando ai sensi della LR 24/2021, art. 3, comma 17. Adozione.'
        self.assertEqual(next(e.candidates(text))['text'],
                         'Bando ai sensi della LR 24/2021, art. 3, comma 17. Adozione.')

    def test_short_act_citation_without_date(self):
        row = next(e.candidates('Decreto del direttore n. 144. Bando per contributi.'))
        self.assertEqual(row['act'], 'Decreto del direttore n. 144')
        self.assertEqual(row['text'], 'Bando per contributi.')

    def test_cli_json_shape_and_traceability_without_heading(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'BUR_fvg'
            source.mkdir()
            (source / 'example.txt').write_text(EXAMPLE, encoding='utf-8')
            (source / 'ignored.pdf').write_bytes(b'not a PDF')
            output = Path(tmp) / 'results'
            with patch.object(sys, 'argv',
                              ['extract_bur_grants.py', str(source), '--output', str(output), '--candidates-only']), \
                 patch.object(e, 'confirm', side_effect=AssertionError('No model in candidate mode')):
                self.assertEqual(e.main(), 0)
            self.assertEqual(json.loads((output / 'candidates.json').read_text()),
                             [{'text': EXAMPLE_TEXT, 'act': EXAMPLE_ACT}])
            audit = json.loads((output / 'candidates.jsonl').read_text())
            self.assertEqual(audit['source'], 'example.txt')
            self.assertEqual(audit['raw_text'], EXAMPLE[audit['start']:audit['end']])

    def test_default_folder_reads_only_its_txt_files_recursively(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'bur_parte_prima' / '2026').mkdir(parents=True)
            (root / 'bur_parte_prima' / '2026' / 'call.TXT').write_text(EXAMPLE, encoding='utf-8')
            (root / 'bur_parte_prima' / 'ignored.pdf').write_bytes(b'not a PDF')
            (root / 'bur_parte_prima' / 'ignored.json').write_text('{}')
            (root / 'bur_fvg').mkdir()
            (root / 'bur_fvg' / 'outside.txt').write_text('Bando outside the chosen input.')
            previous = e.os.getcwd()
            try:
                e.os.chdir(root)
                with patch.object(sys, 'argv', ['extract_bur_grants.py', '--output', 'results', '--candidates-only']):
                    self.assertEqual(e.main(), 0)
            finally:
                e.os.chdir(previous)
            rows = json.loads((root / 'results' / 'candidates.json').read_text())
            self.assertEqual(rows, [{'text': EXAMPLE_TEXT, 'act': EXAMPLE_ACT}])
            audit = json.loads((root / 'results' / 'candidates.jsonl').read_text())
            self.assertEqual(Path(audit['source']), Path('2026/call.TXT'))

    def test_missing_default_folder_does_not_fall_back_to_bur_fvg(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'bur_fvg').mkdir()
            (root / 'bur_fvg' / 'outside.txt').write_text('Bando outside.')
            previous = e.os.getcwd()
            try:
                e.os.chdir(root)
                with patch.object(sys, 'argv', ['extract_bur_grants.py', '--candidates-only']), \
                     patch('sys.stderr'):
                    with self.assertRaises(SystemExit) as raised:
                        e.main()
                    self.assertEqual(raised.exception.code, 2)
                self.assertFalse((root / 'bur_grants_output').exists())
            finally:
                e.os.chdir(previous)

    def test_empty_txt_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'input'
            source.mkdir()
            (source / 'empty.txt').write_text(' ')
            with patch('sys.argv', ['extract_bur_grants.py', str(source), '--output', str(Path(tmp) / 'out'), '--candidates-only']):
                self.assertEqual(e.main(), 2)

    def test_pdf_reader_is_disabled(self):
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
                    self.assertEqual(e.confirm({'act': EXAMPLE_ACT, 'text': EXAMPLE_TEXT}, args)['decision'], 'include')
                self.assertEqual(call.call_count, 1)
                payload = json.loads(call.call_args.args[0].data)
                self.assertIn(EXAMPLE_ACT, payload['messages'][1]['content'])
                self.assertIn(EXAMPLE_TEXT, payload['messages'][1]['content'])

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
