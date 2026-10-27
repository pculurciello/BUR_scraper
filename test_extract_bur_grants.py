import json
from pathlib import Path
import tempfile
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import extract_bur_grants as e
class Tests(unittest.TestCase):
    def test_positive_types(self):
        for act in ['Legge regionale 12 marzo 2000, n. 3', 'Decreto del Presidente della Regione 5 maggio 2024, n. 15/Pres.', 'Decreto del direttore centrale 5 maggio 2024, n. 55', 'Deliberazione della Giunta regionale 8 giugno 2025, n. 600', 'D.G.R. n. 100/2025', 'L.R. 4/1999']:
            self.assertEqual(len(list(e.candidates(act + '\nApprovazione bando per contributi alle imprese.'))), 1)
    def test_adjacent_entries(self):
        text = 'Decreto del direttore n. 1\nContributi alle imprese.\nDecreto del direttore n. 2\nAssunzione personale.'
        found = list(e.candidates(text))
        self.assertEqual(len(found), 1)
        self.assertNotIn('Assunzione', found[0]['text'])
    def test_no_act(self):
        self.assertEqual(list(e.candidates('Bando contributi alle imprese')), [])
    def test_offsets(self):
        text = 'INTRO\nLegge regionale 2/2000\nContributi. ' + 'x' * 25000
        found = list(e.candidates(text))
        self.assertGreater(len(found), 1)
        for item in found:
            self.assertEqual(item['text'], text[item['start']:item['end']])
            self.assertLessEqual(len(item['text']), 10000)
    def test_hallucination_rejected(self):
        with self.assertRaises(ValueError):
            e.validate({'decision': 'include', 'reason': '', 'references': [{'kind': 'law', 'role': 'subject', 'citation': 'Invented', 'evidence': 'contributi'}]}, 'contributi')
    def test_empty_include_rejected(self):
        with self.assertRaises(ValueError):
            e.validate({'decision': 'include', 'reason': '', 'references': []}, 'text')
    def test_scraper_directory_integration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'BUR_fvg'
            (source / '2026').mkdir(parents=True)
            (source / 'cache').mkdir()
            base = source / '2026' / 'BUR_1_02_01_ordinario'
            base.with_suffix('.txt').write_text(
                'Decreto del direttore n. 1\nBando per contributi alle imprese.', encoding='utf-8')
            base.with_suffix('.pdf').write_bytes(b'Not parsed: TXT is preferred')
            (source / 'fascicoli.json').write_text('{}')
            (source / 'cache' / 'ignored.txt').write_text('Legge regionale 1. Contributi.')
            output = root / 'results'
            completed = subprocess.run([
                sys.executable, str(Path(e.__file__)), str(source),
                '--output', str(output), '--candidates-only'], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            inventory = [json.loads(line) for line in (output / 'inventory.jsonl').read_text().splitlines()]
            self.assertEqual(len(inventory), 3)
            self.assertEqual({r.get('reason') for r in inventory if r['status'] == 'skipped'},
                             {'pdf_ignored_text_only', 'unsupported_format'})
            candidates = [json.loads(line) for line in (output / 'candidates.jsonl').read_text().splitlines()]
            self.assertEqual(len(candidates), 1)
            self.assertTrue(candidates[0]['source'].endswith('.txt'))

    def test_pdf_reader_is_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / 'bulletin.pdf'
            pdf.write_bytes(b'not a real PDF')
            with self.assertRaisesRegex(ValueError, 'Only TXT'):
                e.read(pdf)

    def test_empty_txt_does_not_fall_back_to_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'BUR_fvg'
            source.mkdir()
            (source / 'bulletin.txt').write_text('   ')
            (source / 'bulletin.pdf').write_bytes(b'not a real PDF')
            (source / 'unpaired.PDF').write_bytes(b'also ignored')
            output = root / 'results'
            completed = subprocess.run([
                sys.executable, str(Path(e.__file__)), str(source),
                '--output', str(output), '--candidates-only'], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 2, completed.stderr)
            rows = [json.loads(line) for line in (output / 'inventory.jsonl').read_text().splitlines()]
            self.assertEqual(sum(r['status'] == 'read_error' for r in rows), 1)
            self.assertEqual(sum(r.get('reason') == 'pdf_ignored_text_only' for r in rows), 2)
            self.assertEqual((output / 'candidates.jsonl').read_text(), '')

    def test_api_and_cache(self):
        result = {'decision': 'include', 'reason': 'Contributi', 'references': [{'kind': 'law', 'role': 'subject', 'citation': 'Legge regionale 1/2000', 'evidence': 'Contributi'}]}
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(result)}}]}).encode()
        with tempfile.TemporaryDirectory() as tmp:
            args = SimpleNamespace(output=Path(tmp), base_url='http://localhost:8000/v1', model='test')
            (args.output / 'cache').mkdir()
            with patch.object(e.urllib.request, 'urlopen', return_value=Response()) as call:
                for _ in range(2):
                    out = e.confirm({'text': 'Legge regionale 1/2000. Contributi'}, args)
                    self.assertEqual(out['decision'], 'include')
                self.assertEqual(call.call_count, 1)
                payload = json.loads(call.call_args.args[0].data)
                self.assertEqual(payload['response_format']['type'], 'json_schema')
    def test_errors_remain_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = SimpleNamespace(output=Path(tmp), base_url='http://localhost:8000/v1', model='test')
            (args.output / 'cache').mkdir()
            with patch.object(e.urllib.request, 'urlopen', side_effect=OSError('offline')), patch.object(e.time, 'sleep'):
                self.assertEqual(e.confirm({'text': 'Legge contributi'}, args)['decision'], 'error')
            self.assertEqual(list((args.output / 'cache').iterdir()), [])
if __name__ == '__main__': unittest.main()
