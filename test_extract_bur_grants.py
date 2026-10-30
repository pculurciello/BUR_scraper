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
        text = 'INTRO\nLegge regionale 2/2000\n' + ('Contributi alle imprese. ' + 'x' * 6000 + '\n') * 5
        found = list(e.candidates(text))
        self.assertGreater(len(found), 1)
        for item in found:
            self.assertEqual(item['text'], text[item['start']:item['end']])
            self.assertLessEqual(len(item['text']), 10000)
    def test_generic_notices_and_funds_are_not_enough(self):
        titles = [
            'Avviso di deposito variante urbanistica.',
            'Approvazione bando di concorso per assunzione di personale.',
            'Avviso di gara per affidamento del servizio di pulizia.',
            'Ripartizione del fondo di riserva e variazione di bilancio.',
            'Piano di sostegno alla rete ospedaliera.',
            'Finanziamento del progetto di costruzione di una strada.',
            'Aiuto alla lettura dei documenti amministrativi.',
            'Disciplina degli obblighi contributivi e della regolarità contributiva.',
        ]
        for title in titles:
            with self.subTest(title=title):
                text = 'Deliberazione della Giunta regionale n. 12\n' + title
                self.assertEqual(list(e.candidates(text)), [])
                self.assertEqual(len(list(e.candidates(text, mode='broad'))), 1)

    def test_mandatory_contributions_are_not_grants(self):
        for phrase in ['contributi previdenziali',
                       'contributi pensionistici', 'contributi obbligatori',
                       'contributo unificato', 'contributo ANAC',
                       'contributi di bonifica', 'contributo scientifico',
                       'contributo alla conoscenza']:
            with self.subTest(phrase=phrase):
                text = 'Decreto del direttore n. 2\nLiquidazione del ' + phrase
                self.assertEqual(list(e.candidates(text)), [])

    def test_grant_lifecycle_and_instruments_survive(self):
        titles = [
            'Regolamento per la concessione di contributi alle associazioni.',
            'Contributi assistenziali alle famiglie in difficoltà.',
            'Proroga termini delle domande di contributo.',
            'Approvazione graduatoria dei beneficiari di sovvenzioni.',
            'Liquidazione di contributi ai comuni.',
            'Revoca di contributi concessi alle imprese.',
            'Borse di studio per studenti universitari.',
            'Assegnazione di voucher formativi.',
            'Erogazione ristori per danni alle aziende.',
            'Aiuti di Stato in regime de minimis.',
            'Finanziamenti agevolati per investimenti.',
            'Agevolazioni fiscali per le imprese.',
            'Concessione di incentivi economici.',
            'Bando per il sostegno alle imprese artigiane.',
            'Criteri di finanziamento delle associazioni culturali.',
            'Regolamento degli incentivi alle cooperative.',
        ]
        for title in titles:
            with self.subTest(title=title):
                self.assertEqual(len(list(e.candidates('Legge regionale 3/2025\n' + title))), 1)

    def test_weak_finance_requires_nearby_context(self):
        self.assertIsNone(e.grant_reason('Finanziamento. ' + 'x' * 500 +
                                         ' Bando destinato alle imprese.'))
        self.assertIsNone(e.grant_reason('Bando per finanziamento e affidamento di lavori alle imprese.'))
        self.assertIsNone(e.grant_reason('Concorso pubblico per assunzione di giovani con finanziamento.'))
        self.assertIsNone(e.grant_reason('Finanziamento destinato alle imprese.'))
        self.assertIsNone(e.grant_reason('Approvazione criteri di finanziamento.'))
        self.assertIsNotNone(e.grant_reason('Bando di finanziamento alle imprese.'))

    def test_real_grants_are_not_blacklisted_by_other_terms(self):
        for title in [
            'Contributi alle imprese per il pagamento dei contributi previdenziali.',
            'Concessione di contributi alle associazioni e avviso di gara per altro servizio.',
            'Contributi per favorire nuove assunzioni nelle imprese.',
        ]:
            with self.subTest(title=title):
                self.assertIsNotNone(e.grant_reason(title))

    def test_multiline_phrases_and_original_offsets(self):
        text = 'Decreto del direttore n. 1\nBorse di\nstudio per studenti.'
        found = list(e.candidates(text))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['text'], text[found[0]['start']:found[0]['end']])
        self.assertIsNone(e.grant_reason('Contributi\nprevidenziali.'))

    def test_long_entry_does_not_send_irrelevant_windows(self):
        text = 'Decreto del direttore n. 1\nContributi alle imprese. ' + 'x' * 25000
        strict = list(e.candidates(text))
        broad = list(e.candidates(text, mode='broad'))
        self.assertEqual(len(strict), 1)
        self.assertGreater(len(broad), len(strict))

    def test_rejections_have_offsets_and_reasons(self):
        text = 'Legge regionale 1/2025\nFondo di riserva.'
        rejected = []
        self.assertEqual(list(e.candidates(text, rejected=rejected)), [])
        self.assertEqual(rejected[0]['reason'], 'no_grant_evidence')
        for row in rejected:
            self.assertEqual(row['text'], text[row['start']:row['end']])

    def test_summary_page_locator_prevents_spillover(self):
        text = ('Decreto di esproprio n. 8\nLavori della pista ciclabile.\npag. 218\n'
                'Azienda sanitaria:\nBando contributi per attività formative.\npag. 219\n')
        self.assertEqual(list(e.candidates(text)), [])
        self.assertEqual(len(list(e.candidates(text, mode='broad'))), 1)

    def test_page_locator_keeps_relevant_voice_and_its_offsets(self):
        text = ('Decreto del direttore n. 1\nBando per contributi alle imprese.\npag. 20\n'
                'Azienda sanitaria:\nAvviso di concorso pubblico.\npag. 25\n')
        found = list(e.candidates(text))
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0]['text'].endswith('pag. 20\n'))
        self.assertNotIn('Azienda sanitaria', found[0]['text'])
        self.assertEqual(found[0]['text'], text[found[0]['start']:found[0]['end']])

    def test_user_supplied_2006_examples(self):
        fixture = Path(__file__).parent / 'tests' / 'fixtures' / 'filter_examples_2006.json'
        for index, item in enumerate(json.loads(fixture.read_text(encoding='utf-8'))):
            with self.subTest(example=index):
                # First two are false positives; the FSE funding measure stays.
                self.assertEqual(len(list(e.candidates(item['text']))), 1 if index == 2 else 0)
                self.assertEqual(len(list(e.candidates(item['text'], mode='broad'))), 1)

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
            summary = json.loads((output / 'filter_summary.json').read_text())
            self.assertEqual(summary['filter_mode'], 'strict')
            self.assertEqual(summary['candidates'], 1)
            self.assertEqual(summary['broad_candidates'], 1)
            self.assertTrue((output / 'rejected.jsonl').exists())

    def test_cli_reports_reduction_and_preserves_broad_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'BUR_fvg'
            source.mkdir()
            (source / 'sample.txt').write_text(
                'Decreto del direttore n. 1\nBando per contributi alle imprese.\n'
                'Decreto del direttore n. 2\nAvviso di concorso pubblico.\n'
                'Deliberazione n. 3\nRipartizione del fondo di riserva.', encoding='utf-8')
            for mode, expected in [('strict', 1), ('broad', 3)]:
                output = root / mode
                completed = subprocess.run([
                    sys.executable, str(Path(e.__file__)), str(source),
                    '--output', str(output), '--filter-mode', mode, '--candidates-only'],
                    capture_output=True, text=True)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                summary = json.loads((output / 'filter_summary.json').read_text())
                self.assertEqual(summary['candidates'], expected)
                self.assertEqual(summary['broad_candidates'], 3)
                rows = [json.loads(line) for line in (output / 'rejected.jsonl').read_text().splitlines()]
                self.assertEqual(len(rows), 3 - expected)
                self.assertTrue(all(row['source'] == 'sample.txt' for row in rows))

    def test_headingless_prefiltered_input_reaches_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'BUR_fvg'
            source.mkdir()
            text = 'Decreto del direttore n. 1. Contributi alle imprese.'
            (source / 'regional.txt').write_text(text)
            output = Path(tmp) / 'results'
            def mock_confirm(candidate, args):
                return {**candidate, 'decision': 'uncertain', 'reason': 'mocked', 'references': []}
            with patch.object(sys, 'argv', ['extract_bur_grants.py', str(source), '--output', str(output)]), \
                 patch.object(e, 'confirm', side_effect=mock_confirm) as confirm:
                self.assertEqual(e.main(), 0)
            self.assertEqual(confirm.call_count, 1)
            row = json.loads((output / 'candidates.jsonl').read_text())
            self.assertEqual(row['text'], text[row['start']:row['end']])
            inventory = json.loads((output / 'inventory.jsonl').read_text())
            self.assertEqual(inventory['status'], 'ok')
            self.assertNotIn('section_start', inventory)
            summary = json.loads((output / 'filter_summary.json').read_text())
            self.assertEqual(summary['input_scope'], 'prefiltered_regional_text')
            self.assertNotIn('section_not_found', summary)

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




class PrefilteredLayoutTests(unittest.TestCase):
    def test_prefiltered_multiline_continuous_and_sentence_layouts(self):
        entry1 = 'Decreto del direttore n. 1. Contributi alle imprese. pag. 2'
        entry2 = 'Decreto del direttore n. 2. Assunzione personale. pag. 3'
        for separator in ['\n', ' ', '\n\n']:
            with self.subTest(separator=separator):
                text = entry1 + separator + entry2
                for mode in ['strict', 'broad']:
                    rows = list(e.candidates(text, mode=mode))
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0]['text'], text[rows[0]['start']:rows[0]['end']])
                    if mode == 'strict':
                        self.assertNotIn('Assunzione', rows[0]['text'])

if __name__ == '__main__': unittest.main()
