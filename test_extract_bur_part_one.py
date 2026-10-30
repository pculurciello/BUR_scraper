import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import extract_bur_part_one as s

HEADER = 'SOMMARIO\nPARTE PRIMA\nLEGGI, REGOLAMENTI E ATTI DELLA REGIONE\n'
ENTRY = 'Decreto del direttore n. 1.\nContributi alle imprese.\npag. 20\n'

class SectionTests(unittest.TestCase):
    def test_modern_summary_only(self):
        text = 'Bollettino ufficiale\n' + HEADER + ENTRY
        result = s.extract_section(text)
        self.assertEqual(result['stato'], 'ok')
        self.assertTrue(result['testo'].startswith(s.HEADING))
        self.assertNotIn('Bollettino ufficiale', result['testo'])
        self.assertIn('Contributi alle imprese', result['testo'])

    def test_1999_excludes_other_parts_and_later_full_text(self):
        text = HEADER+ENTRY+'PARTE TERZA\nCONCORSI E AVVISI\nContributi comunali. pag. 30\n'
        text += 'PARTE PRIMA\nLEGGI, REGOLAMENTI E ATTI DELLA REGIONE\nTESTO INTEGRALE DEL DECRETO'
        result = s.extract_section(text)
        self.assertEqual(result['stato'], 'ok')
        self.assertNotIn('comunali', result['testo'])
        self.assertNotIn('TESTO INTEGRALE', result['testo'])

    def test_2000_repeated_part_one_starts_full_acts(self):
        text = HEADER+ENTRY+'PARTE PRIMA\nLEGGI, REGOLAMENTI E ATTI DELLA REGIONE\n'
        text += 'Legge regionale n. 1.\nIL PRESIDENTE DELLA REGIONE PROMULGA\nArticolo 1. TESTO INTEGRALE.'
        result = s.extract_section(text)
        self.assertEqual(result['stato'], 'ok')
        self.assertEqual(result['confine'], 'full_text_part_one')
        self.assertNotIn('PROMULGA', result['testo'])
        self.assertNotIn('Articolo', result['testo'])

    def test_body_formula_cuts_even_without_repeated_part_header(self):
        text = HEADER+ENTRY+'Legge regionale n. 1.\nIL CONSIGLIO REGIONALE HA APPROVATO\nTESTO INTEGRALE pag. 500'
        result = s.extract_section(text)
        self.assertEqual(result['stato'], 'ok')
        self.assertEqual(result['confine'], 'full_text_formula')
        self.assertNotIn('Legge regionale n. 1', result['testo'])
        self.assertNotIn('500', result['testo'])

    def test_repeated_summary_header_is_continuation(self):
        text = HEADER+ENTRY+HEADER+'Legge regionale n. 2.\nAltri contributi. pag. 21'
        result = s.extract_section(text)
        self.assertEqual(result['stato'], 'ok')
        self.assertEqual(result['voci'], 2)
        self.assertIn('Altri contributi', result['testo'])

    def test_missing_summary_or_locators_is_rejected(self):
        self.assertEqual(s.extract_section('PARTE PRIMA LEGGI, REGOLAMENTI E ATTI DELLA REGIONE '+ENTRY)['stato'],
                         'section_not_found')
        self.assertEqual(s.extract_section(HEADER+'Testo senza riferimenti di pagina')['stato'], 'no_summary_entries')

    def test_unknown_trailing_body_is_not_copied(self):
        result = s.extract_section(HEADER+ENTRY+'Testo integrale privo di intestazioni riconoscibili.')
        self.assertEqual(result['stato'], 'ambiguous_end')
        self.assertEqual(result['testo'], '')

    def test_final_publisher_footer_is_excluded(self):
        result = s.extract_section(HEADER+ENTRY+'2690 - 17/3/1999 BOLLETTINO UFFICIALE DELLA REGIONE AUTONOMA FRIULI VENEZIA GIULIA N. 11')
        self.assertEqual(result['stato'], 'ok')
        self.assertNotIn('2690', result['testo'])

    def test_original_and_reflowed_repository_layout_fixtures(self):
        path = Path(__file__).parent/'tests/fixtures/section_layouts.json'
        for case in json.loads(path.read_text(encoding='utf-8')):
            for text in [case['text'], ' '.join(case['text'].split())]:
                with self.subTest(case=case['name'], flat='\n' not in text):
                    result = s.extract_section(text)
                    self.assertEqual(result['stato']=='ok', case['section_found'])
                    self.assertNotIn('ripetuti nel testo integrale', result['testo'])
                    self.assertNotIn('Contributi comunali', result['testo'])

class CliTests(unittest.TestCase):
    def run_main(self, argv):
        with contextlib.redirect_stdout(io.StringIO()):
            return s.main(argv)

    def test_directory_preserves_paths_and_originals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, output = root/'input', root/'output'
            path = source/'1999'/'BUR_11_17_03_ordinario.txt'
            path.parent.mkdir(parents=True)
            original = HEADER+ENTRY+'PARTE TERZA\nAvvisi. pag. 30'
            path.write_text(original)
            self.assertEqual(self.run_main([str(source), '--output', str(output)]), 0)
            extracted = output/path.relative_to(source)
            self.assertTrue(extracted.is_file())
            self.assertEqual(path.read_text(), original)
            self.assertNotIn('PARTE TERZA', extracted.read_text())
            report = json.loads((output/'estrazione_sezioni.json').read_text())
            self.assertEqual(report[0]['stato'], 'ok')

    def test_nested_output_and_cache_are_not_rescanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            output = source/'filtered'
            (source/'a.txt').write_text(HEADER+ENTRY)
            (source/'cache').mkdir()
            (source/'cache/ignored.txt').write_text(HEADER+ENTRY)
            argv = [str(source),'--output',str(output)]
            self.assertEqual(self.run_main(argv), 0)
            self.assertEqual(self.run_main(argv), 0)
            self.assertEqual(len(json.loads((output/'estrazione_sezioni.json').read_text())), 1)

    def test_year_filter_and_single_file_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, output = root/'input', root/'output'
            for year in [1999, 2000]:
                path = source/str(year)/'a.txt'
                path.parent.mkdir(parents=True)
                path.write_text(HEADER+ENTRY)
            self.assertEqual(self.run_main([str(source),'--year','2000','--output',str(output)]), 0)
            self.assertTrue((output/'2000/a.txt').is_file())
            self.assertFalse((output/'1999/a.txt').exists())
            self.assertEqual(self.run_main([str(source/'1999/a.txt'),'--output',str(root/'single')]), 0)
            self.assertTrue((root/'single/a.txt').is_file())

    def test_missing_section_does_not_create_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            path=root/'source.txt'
            path.write_text('Full legal document without a summary heading.')
            output=root/'out'
            self.assertEqual(self.run_main([str(path),'--output',str(output)]), 2)
            self.assertFalse((output/'source.txt').exists())
            self.assertTrue((output/'estrazione_sezioni.csv').exists())

    def test_rejects_same_input_output(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.run_main([tmp,'--output',tmp])

class OutputProtectionTests(unittest.TestCase):
    def test_rejects_output_ancestor_of_input(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            source = Path(tmp)/'input'
            source.mkdir()
            with self.assertRaises(SystemExit):
                s.main([str(source), '--output', tmp])

if __name__ == '__main__':
    unittest.main()
