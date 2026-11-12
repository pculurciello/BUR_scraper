import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import extract_bur_part_one as s

HEADER = 'SOMMARIO\nPARTE PRIMA\nLEGGI, REGOLAMENTI E ATTI DELLA REGIONE\n'
ENTRY = 'Decreto del direttore n. 1.\nContributi alle imprese.\npag. 20\n'

DATED_ENTRY = 'Decreto del direttore 17 febbraio 1999, n. 1.\nContributi alle imprese.\npag. 20\n'

class SectionTests(unittest.TestCase):
    def test_modern_summary_only(self):
        text = 'Bollettino ufficiale\n' + HEADER + ENTRY
        result = s.extract_section(text)
        self.assertEqual(result['stato'], 'ok')
        self.assertTrue(result['testo'].startswith('Decreto del direttore n. 1.'))
        self.assertNotIn('SOMMARIO', result['testo'])
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
            original = HEADER+DATED_ENTRY+'PARTE TERZA\nAvvisi. pag. 30'
            path.write_text(original)
            self.assertEqual(self.run_main([str(source), '--output', str(output)]), 0)
            extracted = output/path.relative_to(source).with_suffix('.xml')
            self.assertTrue(extracted.is_file())
            self.assertEqual(path.read_text(), original)
            root_xml = s.ET.parse(extracted).getroot()
            self.assertEqual(root_xml.tag, f'{{{s.FVG_NS}}}raccoltaAtti')
            ns = {'fvg': s.FVG_NS}
            self.assertEqual(root_xml.findtext('fvg:documento/fvg:metadati/fvg:data', namespaces=ns), '1999-02-17')
            self.assertEqual(root_xml.findtext('fvg:documento/fvg:metadati/fvg:titolo', namespaces=ns),
                             'Contributi alle imprese.')
            report = json.loads((output/'estrazione_sezioni.json').read_text())
            self.assertEqual(report[0]['stato'], 'ok')

    def test_nested_output_and_cache_are_not_rescanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            output = source/'filtered'
            (source/'a.txt').write_text(HEADER+DATED_ENTRY)
            (source/'cache').mkdir()
            (source/'cache/ignored.txt').write_text(HEADER+DATED_ENTRY)
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
                path.write_text(HEADER+DATED_ENTRY)
            self.assertEqual(self.run_main([str(source),'--year','2000','--output',str(output)]), 0)
            self.assertTrue((output/'2000/a.xml').is_file())
            self.assertFalse((output/'1999/a.xml').exists())
            self.assertEqual(self.run_main([str(source/'1999/a.txt'),'--output',str(root/'single')]), 0)
            self.assertTrue((root/'single/a.xml').is_file())

    def test_missing_section_does_not_create_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            path=root/'source.txt'
            path.write_text('Full legal document without a summary heading.')
            output=root/'out'
            self.assertEqual(self.run_main([str(path),'--output',str(output)]), 2)
            self.assertFalse((output/'source.xml').exists())
            self.assertTrue((output/'estrazione_sezioni.csv').exists())

    def test_undated_entry_is_written_with_blank_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, output = root/'source.txt', root/'out'
            source.write_text(HEADER + DATED_ENTRY + ENTRY, encoding='utf-8')
            self.assertEqual(self.run_main([str(source), '--output', str(output)]), 0)
            root_xml = s.ET.parse(output/'source.xml').getroot()
            self.assertEqual(len(root_xml), 2)
            undated = root_xml.find(f'{{{s.FVG_NS}}}voceSenzaData')
            self.assertIsNotNone(undated)
            self.assertIsNone(undated.find(f'{{{s.FVG_NS}}}metadati/{{{s.FVG_NS}}}data'))

    def test_office_and_cited_resolution_are_separate_from_act_date(self):
        text = ('Direzione centrale pianificazione territoriale, autonomie locali e sicurezza - '
                'Servizio pianificazione territoriale regionale LR 5/2007, art. 63, co. 2, '
                'LR 52/1991, art. 32, co. 9. Variante generale n. 24 al Piano regolatore generale '
                'comunale del Comune di Forni Avoltri: introduzione di modifiche e conferma di '
                'esecutività della deliberazione consiliare di approvazione n. 20 del 20 aprile 2009. pag. 20')
        ns = {'fvg': s.FVG_NS}
        entry = s.bulletin_xml([text]).getroot()[0]
        self.assertTrue(entry.findtext('fvg:metadati/fvg:organo', namespaces=ns).endswith('territoriale regionale'))
        self.assertTrue(entry.findtext('fvg:metadati/fvg:titolo', namespaces=ns).startswith('Variante generale'))
        self.assertIsNone(entry.find('fvg:metadati/fvg:data', ns))
        citations = entry.findall('fvg:citazioni/fvg:citazione/fvg:testoCitato', ns)
        self.assertEqual(len(citations), 3)
        self.assertIn('20 aprile 2009', citations[-1].text)

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

class EntriesOnlyCleanupTests(unittest.TestCase):
    publication = 'BOLLETTINO UFFICIALE DELLA REGIONE AUTONOMA FRIULI-VENEZIA GIULIA'
    next_entry = 'Decreto n. 2 del 5 maggio 1999.\nContributi alle famiglie.\npag. 21'

    def extract(self, header):
        result = s.extract_section(HEADER + ENTRY + header + self.next_entry)
        self.assertEqual(result['stato'], 'ok')
        self.assertIn('Contributi alle imprese', result['testo'])
        self.assertIn('Contributi alle famiglie', result['testo'])
        self.assertIn('5 maggio 1999', result['testo'])
        self.assertNotIn('SOMMARIO', result['testo'])
        self.assertNotIn('LEGGI, REGOLAMENTI E ATTI DELLA REGIONE', result['testo'])
        return result['testo']

    def test_legacy_page_date_publication_issue_header(self):
        text = self.extract('2690 - 17/3/1999 ' + self.publication + ' N. 11\n')
        self.assertNotIn('2690', text)
        self.assertNotIn('17/3/1999', text)
        self.assertNotIn('N. 11', text)
        self.assertNotIn(self.publication, text)

    def test_legacy_issue_publication_date_page_header(self):
        text = self.extract('N. 11 ' + self.publication + ' 17/3/1999 - 2691\n')
        self.assertNotIn('2691', text)
        self.assertNotIn('17/3/1999', text)
        self.assertNotIn('N. 11', text)
        self.assertNotIn(self.publication, text)

    def test_modern_multiline_masthead_and_repeated_section(self):
        text = self.extract(self.publication + ' 1\nso3019 ottobre 2026\n' + HEADER)
        self.assertNotIn('ottobre 2026', text)
        self.assertNotIn('so30', text)
        self.assertNotIn(self.publication, text)

    def test_reflowed_headers_do_not_drop_neighboring_entries(self):
        source = ' '.join((HEADER + ENTRY + '2690 - 17/3/1999 ' + self.publication + ' N. 11 ' + self.next_entry).split())
        result = s.extract_section(source)
        self.assertEqual(result['stato'], 'ok')
        self.assertIn('Contributi alle imprese', result['testo'])
        self.assertIn('Contributi alle famiglie', result['testo'])
        self.assertNotIn(self.publication, result['testo'])
        self.assertNotIn('2690', result['testo'])
        self.assertNotIn('N. 11', result['testo'])

    def test_standalone_bur_number_date_title(self):
        text = self.extract('NUMERO 42 - 21 OTTOBRE 2026\n')
        self.assertNotIn('NUMERO 42', text)
        self.assertNotIn('OTTOBRE 2026', text)

    def test_inline_bur_title_after_page_locator(self):
        source = ' '.join((HEADER + ENTRY + 'NUMERO 42 - 21 OTTOBRE 2026 ' + self.next_entry).split())
        result = s.extract_section(source)
        self.assertEqual(result['stato'], 'ok')
        self.assertNotIn('NUMERO 42', result['testo'])
        self.assertIn('Contributi alle famiglie', result['testo'])

    def test_publication_reference_inside_entry_is_not_a_header(self):
        entry = 'Decreto n. 3. Pubblicazione nel ' + self.publication + ' prevista dalla legge. pag. 22'
        result = s.extract_section(HEADER + entry)
        self.assertEqual(result['stato'], 'ok')
        self.assertIn('Pubblicazione nel ' + self.publication, result['testo'])

    def test_bounded_historical_cover_block_is_removed(self):
        cover = ('Spedizione in abbonamento postale\nAnno XXXVI - N. 11\n' + self.publication +
                 '\nTRIESTE, 17 marzo 1999 Lire 2.500\nDIREZIONE E REDAZIONE: TRIESTE\n'
                 'Per quanto in esse non previsto si applicano le norme statali in materia di pubblicità degli atti.\n')
        text = self.extract(cover)
        self.assertNotIn('Spedizione', text)
        self.assertNotIn('XXXVI', text)
        self.assertNotIn('REDAZIONE', text)
        self.assertNotIn(self.publication, text)

class EmbeddedPageDateTests(unittest.TestCase):
    example = ('Bando per la realizzazione di opere cinematografiche originali di rievocazione '
               'e rappresen4526 - 9/6/1999 tazione di fiabe e leggende appartenenti alla '
               'tradizione popolare della Comunità del Friuli.')
    expected = ('Bando per la realizzazione di opere cinematografiche originali di rievocazione '
                'e rappresentazione di fiabe e leggende appartenenti alla '
                'tradizione popolare della Comunità del Friuli.')
    publication = EntriesOnlyCleanupTests.publication

    def test_exact_user_example_is_repaired(self):
        self.assertEqual(s.entries_only(self.example), self.expected)

    def test_embedded_numeric_header_in_full_extraction(self):
        result = s.extract_section(HEADER + self.example + ' pag. 4553')
        self.assertEqual(result['stato'], 'ok')
        self.assertEqual(result['testo'].strip(), self.expected + ' pag. 4553')

    def test_full_masthead_attached_to_word_is_repaired(self):
        text = 'rappresen4526 - 9/6/1999 ' + self.publication + ' N. 23 tazione di fiabe.'
        self.assertEqual(s.entries_only(text), 'rappresentazione di fiabe.')

    def test_raw_word_wrap_across_full_masthead_is_repaired(self):
        text = 'rappresen-\n\n4526 - 9/6/1999 ' + self.publication + ' N. 23\ntazione di fiabe.'
        self.assertEqual(s.entries_only(text), 'rappresentazione di fiabe.')

    def test_masthead_between_whole_words_keeps_a_separator(self):
        text = 'Contributi 4526 - 9/6/1999 ' + self.publication + ' N. 23 alle imprese.'
        self.assertEqual(s.entries_only(text), 'Contributi alle imprese.')

    def test_normal_legal_citations_are_preserved(self):
        text = 'Decreto n. 4526 - 9/6/1999. Legge regionale 9/6/1999, n. 23.'
        self.assertEqual(s.entries_only(text), text)

    def test_invalid_date_is_not_treated_as_header(self):
        text = 'rappresen4526 - 31/2/1999 tazione'
        self.assertEqual(s.entries_only(text), text)

    def test_uppercase_word_fragments_are_joined(self):
        self.assertEqual(s.entries_only('RAPPRESEN4526 - 9/6/1999 TAZIONE'), 'RAPPRESENTAZIONE')

class CoverNoteVariantTests(unittest.TestCase):
    old_end = ('Per quanto in esse non previsto si applicano le norme statali '
               'in materia di pubblicità degli atti.')
    new_paragraph = ('La versione integrale dei testi è consultabile online. '
                     'La riproduzione del Bollettino sul sito Internet è pertanto priva di valore giuridico.')
    cover_start = 'Spedizione in abbonamento postale. DIREZIONE E REDAZIONE: TRIESTE. '
    next_entry = 'DECRETO DEL DIRETTORE n. 2. Contributi alle famiglie. pag. 21'

    def test_disclaimer_after_old_clause_is_also_removed(self):
        cover = self.cover_start + self.old_end + '\n' + self.new_paragraph + '\n'
        result = s.extract_section(HEADER+ENTRY+cover+self.next_entry)
        self.assertEqual(result['stato'], 'ok')
        self.assertNotIn('Spedizione', result['testo'])
        self.assertNotIn('consultabile online', result['testo'])
        self.assertNotIn('valore giuridico', result['testo'])
        self.assertIn('Contributi alle famiglie', result['testo'])
        self.assertIn('Contributi alle imprese', result['testo'])

    def test_privo_variant_without_old_clause(self):
        cover = 'Spedizione in abbonamento\nNota editoriale.\nDocumento privo di\nvalore giuridico.\n'
        self.assertEqual(s.entries_only(cover+self.next_entry), self.next_entry)

    def test_value_legale_variant(self):
        cover = self.cover_start + 'Documento privo di valore legale. '
        self.assertEqual(s.entries_only(cover+self.next_entry), self.next_entry)

    def test_note_attached_inside_word_is_removed_without_leaving_a_gap(self):
        source = 'Piano parti' + self.cover_start + self.old_end + ' ' + self.new_paragraph + ' colareggiato.'
        self.assertEqual(s.entries_only(source), 'Piano particolareggiato.')

    def test_old_note_does_not_consume_a_later_act_mentioning_legal_value(self):
        for entry in ['DECRETO DEL DIRETTORE n. 2.', 'Decreto del direttore n. 2.']:
            with self.subTest(entry=entry):
                following = entry + ' Documento privo di valore giuridico. Contributi alle famiglie. pag. 21'
                source = self.cover_start + self.old_end + ' ' + following
                self.assertEqual(s.entries_only(source), following)

    def test_repeated_notes_are_removed_independently(self):
        source = (self.cover_start + self.old_end + ' ' + self.next_entry + ' '
                  + self.cover_start + self.new_paragraph + ' DECRETO n. 3. Altro atto. pag. 22')
        result = s.entries_only(source)
        self.assertNotIn('Spedizione', result)
        self.assertNotIn('valore giuridico', result)
        self.assertIn(self.next_entry, result)
        self.assertIn('Altro atto', result)

    def test_unterminated_note_is_not_deleted_blindly(self):
        source = 'Spedizione in abbonamento postale. Nota con una chiusura sconosciuta.'
        self.assertEqual(s.entries_only(source), source)

class OneLinePerEntryTests(unittest.TestCase):
    def assert_entry_lines(self, result, expected):
        self.assertEqual(result['stato'], 'ok')
        lines = result['testo'].splitlines()
        self.assertEqual(lines, expected)
        self.assertEqual(result['voci'], len(lines))
        for line in lines:
            locators = list(s.PAGE.finditer(line))
            self.assertEqual(len(locators), 1)
            self.assertEqual(locators[0].end(), len(line))

    def test_legacy_wrapped_entries_become_separate_single_lines(self):
        source = HEADER + ENTRY + 'Legge regionale n. 2.\nAltri contributi.\npag. 21'
        self.assert_entry_lines(s.extract_section(source), [
            'Decreto del direttore n. 1. Contributi alle imprese. pag. 20',
            'Legge regionale n. 2. Altri contributi. pag. 21'])

    def test_reflowed_entries_are_split_after_page_number(self):
        source = ' '.join((HEADER+ENTRY+'Decreto n. 2. Contributi alle famiglie. pag. 21').split())
        self.assert_entry_lines(s.extract_section(source), [
            'Decreto del direttore n. 1. Contributi alle imprese. pag. 20',
            'Decreto n. 2. Contributi alle famiglie. pag. 21'])

    def test_sentence_periods_do_not_split_an_entry(self):
        source = HEADER + 'Legge regionale 1 giugno 2026, n. 1.\nArt. 1. Risorse.\nModalità di domanda.\npag. 20'
        self.assert_entry_lines(s.extract_section(source), [
            'Legge regionale 1 giugno 2026, n. 1. Art. 1. Risorse. Modalità di domanda. pag. 20'])

    def test_same_page_number_still_separates_entries(self):
        source = HEADER + ENTRY + 'Decreto n. 2. Seconda voce. pag. 20'
        self.assertEqual(len(s.extract_section(source)['testo'].splitlines()), 2)

    def test_wrapped_page_reference_case_and_ranges(self):
        source = HEADER + 'Decreto n. 1. Contributi. PAG.\n20-21\nLegge n. 2. Risorse. pag. 22, 23'
        self.assert_entry_lines(s.extract_section(source), [
            'Decreto n. 1. Contributi. PAG. 20-21', 'Legge n. 2. Risorse. pag. 22, 23'])

    def test_word_wraps_rejoin_but_spaced_dashes_remain(self):
        source = HEADER+'Decreto n. 1. Contri-\nbuti -\nper le imprese. pag. 20'
        self.assert_entry_lines(s.extract_section(source), [
            'Decreto n. 1. Contributi - per le imprese. pag. 20'])

    def test_headers_removed_before_entry_formatting(self):
        source = (HEADER+ENTRY+'2690 - 17/3/1999 '+EntriesOnlyCleanupTests.publication+' N. 11\n'
                  +'Decreto n. 2. Contributi alle famiglie. pag. 21')
        self.assert_entry_lines(s.extract_section(source), [
            'Decreto del direttore n. 1. Contributi alle imprese. pag. 20',
            'Decreto n. 2. Contributi alle famiglie. pag. 21'])

    def test_unterminated_remainder_is_not_silently_discarded(self):
        with self.assertRaisesRegex(ValueError, 'Testo residuo'):
            s.summary_entry_lines('Prima voce. pag. 20 Seconda voce priva di pagina')

if __name__ == '__main__':
    unittest.main()




