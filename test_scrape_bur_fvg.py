"""Retry tests: no live requests or real delays."""
import io
import logging
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch, call
from urllib.error import HTTPError, URLError
import scrape_bur_fvg as bur

class Response:
    def __init__(self, body=b'<html>ok</html>', headers=None):
        self.body, self.headers, self.url = body, headers or {}, bur.HOME
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return self.body

class RetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        sleep_patch = patch.object(bur.time, 'sleep')
        self.sleep = sleep_patch.start()
        self.addCleanup(sleep_patch.stop)
        jitter_patch = patch.object(bur.random, 'uniform', return_value=0)
        jitter_patch.start()
        self.addCleanup(jitter_patch.stop)
        self.client = bur.Client(self.root, 0, 30, 2)
        self.client.opener = Mock()

    def test_timeout_then_success_is_silent_and_cached(self):
        self.client.opener.open.side_effect = [TimeoutError('slow'), Response()]
        with self.assertNoLogs(bur.LOG, logging.DEBUG):
            self.assertEqual(self.client.get(bur.HOME), b'<html>ok</html>')
        self.assertEqual(self.client.opener.open.call_count, 2)
        self.assertEqual(self.client.opener.open.call_args.kwargs['timeout'], 30)
        self.assertIn(call(2.0), self.sleep.call_args_list)
        self.client.get(bur.HOME)
        self.assertEqual(self.client.opener.open.call_count, 2)

    def test_exhaustion(self):
        self.client.opener.open.side_effect = URLError('connection lost')
        with self.assertNoLogs(bur.LOG, logging.DEBUG):
            with self.assertRaises(URLError): self.client.get(bur.HOME)
        self.assertEqual(self.client.opener.open.call_count, 3)
        self.assertEqual(list((self.root/'cache').iterdir()), [])
        pauses = [c.args[0] for c in self.sleep.call_args_list if c.args[0] > 0]
        self.assertEqual(pauses, [2.0, 4.0])

    def test_retry_after_is_capped(self):
        error = HTTPError(bur.HOME, 503, 'busy', {'Retry-After': '120'}, io.BytesIO())
        self.client.opener.open.side_effect = [error, Response()]
        self.client.get(bur.HOME)
        self.assertIn(call(60.0), self.sleep.call_args_list)

    def test_404_is_not_retried(self):
        self.client.opener.open.side_effect = HTTPError(bur.HOME, 404, 'missing', {}, io.BytesIO())
        with self.assertRaises(HTTPError): self.client.get(bur.HOME)
        self.assertEqual(self.client.opener.open.call_count, 1)

    def test_certificate_error_is_not_retried(self):
        self.client.opener.open.side_effect = URLError(ssl.SSLCertVerificationError(1, 'failed'))
        with self.assertRaisesRegex(RuntimeError, 'Verifica TLS fallita'): self.client.get(bur.HOME)
        self.assertEqual(self.client.opener.open.call_count, 1)

    def test_incomplete_response_is_retried(self):
        self.client.opener.open.side_effect = [Response(b'<html>partial', {'Content-Length':'1000'}), Response()]
        self.assertEqual(self.client.get(bur.HOME), b'<html>ok</html>')
        self.assertEqual(self.client.opener.open.call_count, 2)

    def test_gateway_html_instead_of_pdf_is_retried(self):
        self.client.opener.open.side_effect = [Response(), Response(b'%PDF-test')]
        self.assertEqual(self.client.get(bur.HOME, pdf=True), b'%PDF-test')
        self.assertEqual(self.client.opener.open.call_count, 2)

    def test_zero_retries(self):
        self.client.retries = 0
        self.client.opener.open.side_effect = TimeoutError('slow')
        with self.assertRaises(TimeoutError): self.client.get(bur.HOME)
        self.assertEqual(self.client.opener.open.call_count, 1)

    def test_transient_http_statuses(self):
        for code in bur.RETRYABLE_HTTP:
            with self.subTest(code=code):
                self.client.refresh = True
                self.client.opener.open.reset_mock()
                self.client.opener.open.side_effect = [HTTPError(bur.HOME, code, 'busy', {}, io.BytesIO()), Response()]
                self.client.get(bur.HOME)
                self.assertEqual(self.client.opener.open.call_count, 2)

    def test_tls_verification_requires_explicit_opt_out(self):
        context = bur.tls_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        context = bur.tls_context(insecure=True)
        self.assertFalse(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_NONE)

    def test_retry_after_formats(self):
        self.assertIsNone(bur.retry_after_seconds({'Retry-After':'invalid'}))
        self.assertEqual(bur.retry_after_seconds({'Retry-After':'5'}), 5)
        self.assertEqual(bur.retry_after_seconds({'Retry-After':'Wed, 21 Oct 2015 07:28:00 GMT'}), 0)

class NamingTests(unittest.TestCase):
    def test_url_paths(self):
        cases = [
            ('2020%2F04%2F08%2F17', 'ordinario', '2020/BUR_17_08_04_ordinario'),
            ('2026/10/19/30', 'supplemento', '2026/BUR_30_19_10_supplemento'),
            ('2026/01/02/1', 'supplemento_ordinario', '2026/BUR_1_02_01_supplemento_ordinario'),
            ('2020/4/8/017', 'straordinario', '2020/BUR_17_08_04_straordinario'),
            ('2020%2F01%2F02%2F1_1', 'supplemento', '2020/BUR_1_02_01_supplemento'),
        ]
        for bnum, kind, expected in cases:
            with self.subTest(bnum=bnum):
                url = bur.HOME + 'visionaBUR?bnum=' + bnum
                self.assertEqual(bur.document_basename(Path('out'), url, kind), Path('out')/expected)

    def test_invalid_url_metadata_is_rejected(self):
        for bnum in ['2020/02/30/17', '../../bad', '2020/04/08', '']:
            with self.subTest(bnum=bnum):
                with self.assertRaises(ValueError):
                    bur.document_basename(Path('out'), bur.HOME+'visionaBUR?bnum='+bnum, 'ordinario')
        with self.assertRaises(ValueError):
            bur.document_basename(Path('out'), bur.HOME, 'ordinario')

    def test_legacy_url_uses_url_ids(self):
        url = 'https://www.regione.fvg.it/asp/bur/ricerca/archivio2/archivioDettaglio.asp?num=5&nodo=73'
        self.assertEqual(bur.document_basename(Path('out'), url, 'supplemento', 1999),
                         Path('out/1999/BUR_legacy_5_73_supplemento'))

    def test_date_distinguishes_same_number_and_type(self):
        url = bur.HOME + 'visionaBUR?bnum='
        self.assertNotEqual(bur.document_basename(Path('out'), url+'2026/01/02/1', 'ordinario'),
                            bur.document_basename(Path('out'), url+'2026/01/07/1', 'ordinario'))

    def test_collision_suffixes_and_stable_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prefix = bur.HOME+'visionaBUR?bnum=2020/01/02/'
            urls = [prefix+'1', prefix+'1_1', prefix+'1_2']
            saved = []
            for i, url in enumerate(urls):
                base = bur.document_basename(root, url, 'supplemento')
                saved.append(bur.save_document_files(root, base, url,
                             f'pdf-{i}'.encode(), f'text-{i}'))
            self.assertEqual([p.name for p, _ in saved], [
                'BUR_1_02_01_supplemento.pdf', 'BUR_1_02_01_supplemento_2.pdf',
                'BUR_1_02_01_supplemento_3.pdf'])
            for i in reversed(range(3)):
                base = bur.document_basename(root, urls[i], 'supplemento')
                again = bur.save_document_files(root, base, urls[i],
                                               f'pdf-{i}'.encode(), f'text-{i}')
                self.assertEqual(again, saved[i])
                self.assertEqual(again[0].read_bytes(), f'pdf-{i}'.encode())
                self.assertEqual(again[1].stem, again[0].stem)

    def test_encoded_url_reuses_existing_assignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = bur.HOME+'visionaBUR?bnum=2020/01/02/1_1'
            encoded = bur.HOME+'visionaBUR?bnum=2020%2F01%2F02%2F1_1'
            base = bur.document_basename(root, raw, 'ordinario')
            first = bur.save_document_files(root, base, raw, b'pdf', 'text')
            second = bur.save_document_files(root, base, encoded, b'pdf', 'text')
            self.assertEqual(first, second)

    def test_untracked_files_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            url = bur.HOME+'visionaBUR?bnum=2020/01/02/1'
            base = bur.document_basename(root, url, 'ordinario')
            base.parent.mkdir()
            base.with_suffix('.txt').write_text('existing file')
            pdf, txt = bur.save_document_files(root, base, url, b'new-pdf', 'new-text')
            self.assertTrue(pdf.stem.endswith('_2'))
            self.assertEqual(base.with_suffix('.txt').read_text(), 'existing file')
            self.assertEqual(txt.read_text(), 'new-text')

    def test_fetch_summary_records_new_paths(self):
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        buf = io.BytesIO()
        writer.write(buf)
        title = 'NUMERO 42 - 21 OTTOBRE 2026'
        client = Mock()
        client.page.return_value = bur.Page(
            '<div class="box-titolo">' + title + '</div>'
            '<a href="/newbur/downloadPDF?doc=0&amp;name=test.pdf">Sommario</a>')
        client.get.return_value = buf.getvalue()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = bur.fetch_summary(client, 2026, bur.HOME+'visionaBUR?bnum=2020%2F04%2F08%2F17', title, root, 12)
            self.assertEqual(row['pdf'], '2020/BUR_17_08_04_ordinario.pdf')
            self.assertEqual(row['testo'], '2020/BUR_17_08_04_ordinario.txt')
            self.assertTrue((root/row['pdf']).is_file())
            self.assertTrue((root/row['testo']).is_file())

class MetadataTypeTests(unittest.TestCase):
    def test_pdfinfo_title(self):
        reader = Mock()
        result = Mock(returncode=0, stdout=b'Title: Supplemento straordinario n. 4\n')
        with patch.object(bur.shutil, 'which', return_value='/usr/bin/pdfinfo'), \
             patch.object(bur.subprocess, 'run', return_value=result) as run:
            title, source = bur.pdf_document_title(b'pdf-data', reader)
        self.assertEqual(source, 'pdfinfo')
        self.assertEqual(bur.infer_document_type(title), 'supplemento_straordinario')
        self.assertEqual(run.call_args.kwargs['input'], b'pdf-data')

    def test_pypdf_fallback(self):
        reader = Mock()
        reader.metadata.title = 'Sommario relativo al BUR n. 42 del 21 ottobre 2026'
        with patch.object(bur.shutil, 'which', return_value=None):
            title, source = bur.pdf_document_title(b'pdf-data', reader)
        self.assertEqual(source, 'pdf_metadata')
        self.assertEqual(bur.infer_document_type(title), 'ordinario')

    def test_failed_pdfinfo_falls_back(self):
        reader = Mock()
        reader.metadata.title = 'Supplemento n. 30'
        with patch.object(bur.shutil, 'which', return_value='pdfinfo'), \
             patch.object(bur.subprocess, 'run', side_effect=bur.subprocess.TimeoutExpired('pdfinfo', 30)):
            title, source = bur.pdf_document_title(b'pdf-data', reader)
        self.assertEqual(source, 'pdf_metadata')
        self.assertEqual(bur.infer_document_type(title), 'supplemento')

    def test_generic_pdf_title_is_not_classified(self):
        self.assertIsNone(bur.infer_document_type('bur-99.PDF'))

    def test_metadata_overrides_webpage_type(self):
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        writer.add_metadata({'/Title': 'Sommario relativo al 1° Supplemento n. 30 del 19 ottobre 2026 relativo al BUR n. 41'})
        buf = io.BytesIO()
        writer.write(buf)
        title = 'I SUPPLEMENTO ORDINARIO N. 30 DEL 19 OTTOBRE 2026 AL BUR N. 41'
        client = Mock()
        client.page.return_value = bur.Page('<div class="box-titolo">'+title+'</div>'
            '<a href="/newbur/downloadPDF?doc=0&amp;name=test.pdf">Sommario</a>')
        client.get.return_value = buf.getvalue()
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(bur.shutil, 'which', return_value=None):
            row = bur.fetch_summary(client, 2026, bur.HOME+'visionaBUR?bnum=2026/10/19/30', title, Path(tmp), 12)
            self.assertEqual(row['pdf'], '2026/BUR_30_19_10_supplemento.pdf')
            self.assertEqual(row['tipo_fascicolo'], 'supplemento')
            self.assertEqual(row['fonte_tipo'], 'pdf_metadata')

class ArchivePaginationTests(unittest.TestCase):
    def test_discovery_starts_on_explicit_page_one(self):
        seed = bur.HOME + 'archivioBollettini?anno=2021'
        first = bur.canonical(seed, num_pag=1)
        second = bur.canonical(seed, num_pag=2)
        pages = {
            first: bur.Page('<a href="./visionaBUR?bnum=2021/01/07/1">NUMERO 1</a>'
                '<a href="?anno=2021&amp;num_pag=1">1</a>'
                '<a href="?anno=2021&amp;num_pag=2">2</a>'),
            second: bur.Page('<a href="./visionaBUR?bnum=2021/01/14/2">NUMERO 2</a>'
                '<a href="?anno=2021&amp;num_pag=1">1</a>'),
        }
        client = Mock()
        client.page.side_effect = lambda url, **kwargs: pages[url]
        errors = []
        found, visited = bur.discover(client, 2021, seed, errors)
        self.assertEqual(client.page.call_args_list, [call(first, require_issues=True), call(second, require_issues=True)])
        self.assertEqual(len(found), 2)
        self.assertEqual(visited, 2)
        self.assertEqual(errors, [])

    def test_real_duplicate_pages_still_reported(self):
        seed = bur.HOME+'archivioBollettini?anno=2021'
        page = bur.Page('<a href="./visionaBUR?bnum=2021/01/07/1">NUMERO 1</a>'
                        '<a href="?anno=2021&amp;num_pag=2">2</a>')
        client = Mock()
        client.page.return_value = page
        errors = []
        bur.discover(client, 2021, seed, errors)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['fase'], 'paginazione')

    def test_preserves_numbered_pages_and_legacy_urls(self):
        numbered = bur.HOME+'archivioBollettini?anno=2021&num_pag=3'
        self.assertEqual(bur.archive_page_url(numbered, 2021), bur.canonical(numbered))
        legacy = 'https://www.regione.fvg.it/asp/bur/ricerca/archivio2/archivio.asp?anno=1999'
        self.assertEqual(bur.archive_page_url(legacy, 1999), bur.canonical(legacy))

class TitleMismatchTests(unittest.TestCase):
    expected = 'NUMERO 49 - 9 DICEMBRE 2021'
    wrong = 'NUMERO 31 - 2 AGOSTO 2023'
    url = bur.HOME + 'visionaBUR?bnum=2021%2F12%2F09%2F49'

    def page(self, title):
        return bur.Page('<div class="box-titolo">'+title+'</div>'
                        '<a href="/newbur/downloadPDF?doc=0&amp;name=test.pdf">Sommario</a>')

    def fetch(self, root, refreshed):
        client = Mock()
        client.page.side_effect = [self.page(self.wrong), refreshed]
        client.get.return_value = b'%PDF-test'
        reader = Mock()
        page = Mock()
        page.extract_text.return_value = 'summary text'
        reader.pages = [page]
        with patch.object(bur, 'PdfReader', return_value=reader), \
             patch.object(bur, 'pdf_document_title', return_value=('BUR n. 49', 'pdf_metadata')):
            row = bur.fetch_summary(client, 2021, self.url, self.expected, root, 12)
        self.assertEqual(client.page.call_args_list, [call(self.url), call(self.url, refresh=True)])
        self.assertTrue((root/row['pdf']).is_file())
        self.assertTrue((root/row['testo']).is_file())
        self.assertEqual(row['pdf'], '2021/BUR_49_09_12_ordinario.pdf')
        self.assertEqual(row['errore'], '')
        return row

    def test_persistent_mismatch_downloads_and_flags_for_review(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertLogs(bur.LOG, 'WARNING'):
            row = self.fetch(Path(tmp), self.page(self.wrong))
        self.assertEqual(row['stato'], 'da_verificare')
        self.assertTrue(row['titolo_discordante'])
        self.assertEqual(row['titolo_dettaglio'], self.wrong)
        self.assertIn('Download proseguito', row['avviso'])

    def test_fresh_page_resolves_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = self.fetch(Path(tmp), self.page(self.expected))
        self.assertEqual(row['stato'], 'ok')
        self.assertFalse(row['titolo_discordante'])
        self.assertEqual(row['titolo_dettaglio'], self.expected)

    def test_failed_refresh_uses_original_page(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertLogs(bur.LOG, 'WARNING'):
            row = self.fetch(Path(tmp), TimeoutError('slow refresh'))
        self.assertEqual(row['stato'], 'da_verificare')
        self.assertIn('Rilettura fresca', row['avviso'])

    def test_refresh_bypasses_cache_and_sends_headers(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(bur.time, 'sleep'):
            client = bur.Client(Path(tmp), 0, 30, 0)
            client.opener = Mock()
            client.opener.open.side_effect = [Response(b'<html>old</html>'), Response(b'<html>new</html>')]
            self.assertEqual(client.get(self.url), b'<html>old</html>')
            self.assertEqual(client.get(self.url), b'<html>old</html>')
            self.assertEqual(client.get(self.url, refresh=True), b'<html>new</html>')
            self.assertEqual(client.opener.open.call_count, 2)
            request = client.opener.open.call_args.args[0]
            self.assertEqual(request.get_header('Cache-control'), 'no-cache')
            self.assertEqual(request.get_header('Pragma'), 'no-cache')
            self.assertEqual(client.get(self.url), b'<html>new</html>')

class ManualArchivePageTests(unittest.TestCase):
    def test_modern_selected_page_does_not_follow_links(self):
        client = Mock()
        client.page.return_value = bur.Page(
            '<a href="./visionaBUR?bnum=2021/01/14/2">NUMERO 2</a>'
            '<a href="?anno=2021&amp;num_pag=1">1</a>'
            '<a href="?anno=2021&amp;num_pag=4">4</a>')
        seed = bur.HOME+'archivioBollettini?anno=2021'
        errors = []
        found, count = bur.discover(client, 2021, seed, errors, page_number=3)
        client.page.assert_called_once_with(bur.canonical(seed, num_pag=3), require_issues=True)
        self.assertEqual(count, 1)
        self.assertEqual(len(found), 1)
        self.assertEqual(errors, [])

    def test_legacy_uses_pag_parameter(self):
        client = Mock()
        client.page.return_value = bur.Page(
            '<a href="archivioDettaglio.asp?num=5&amp;nodo=73">SUPPLEMENTO</a>'
            '<a href="?pag=4">4</a>')
        seed = 'https://www.regione.fvg.it/asp/bur/ricerca/archivio2/archivio.asp?anno=1999'
        errors = []
        found, _ = bur.discover(client, 1999, seed, errors, page_number=3)
        client.page.assert_called_once_with(bur.canonical(seed, pag=3), require_issues=True)
        self.assertEqual(len(found), 1)
        self.assertEqual(errors, [])

    def test_invalid_manual_page_arguments_fail_before_network(self):
        for options in [['--year', '2021', '--page', '0'], ['--page', '3']]:
            with self.subTest(options=options), patch('sys.argv', ['scraper']+options), \
                 patch.object(bur, 'Client') as client, patch('sys.stderr', new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as exc:
                    bur.main()
                self.assertEqual(exc.exception.code, 2)
                client.assert_not_called()

    def test_cli_passes_year_and_page_to_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ['scraper', '--year', '2021', '--page', '3', '--output', tmp, '--solo-indice']
            client = Mock()
            client.page.return_value = bur.Page(
                '<select><option value="/newbur/archivioBollettini?anno=2021">2021</option></select>')
            url = bur.HOME+'visionaBUR?bnum=2021/01/14/2'
            with patch('sys.argv', argv), patch.object(bur, 'Client', return_value=client), \
                 patch.object(bur, 'discover', return_value=({url: 'NUMERO 2'}, 1)) as discover, \
                 patch.object(bur.logging, 'basicConfig'), \
                 patch.object(bur.logging, 'FileHandler', return_value=logging.NullHandler()):
                self.assertEqual(bur.main(), 0)
            self.assertEqual(discover.call_count, 1)
            self.assertEqual(discover.call_args.args[1], 2021)
            self.assertEqual(discover.call_args.kwargs['page_number'], 3)
            self.assertTrue((Path(tmp)/'fascicoli.csv').is_file())

class EmptyArchiveResponseTests(unittest.TestCase):
    url = bur.HOME + 'archivioBollettini?anno=2022&num_pag=5'
    empty = b'<html><body>Servizio temporaneamente non disponibile</body></html>'
    valid = b'<html><a href="./visionaBUR?bnum=2022/07/06/27">NUMERO 27</a></html>'

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        sleep = patch.object(bur.time, 'sleep')
        sleep.start()
        self.addCleanup(sleep.stop)
        self.client = bur.Client(self.root, 0, 30, 2)
        self.client.opener = Mock()

    def test_empty_then_valid_is_retried_silently(self):
        self.client.opener.open.side_effect = [Response(self.empty), Response(self.valid)]
        with self.assertNoLogs(bur.LOG, logging.DEBUG):
            page = self.client.page(self.url, require_issues=True)
        self.assertEqual(len(bur.issue_links(page, self.url)), 1)
        self.assertEqual(self.client.opener.open.call_count, 2)
        self.assertEqual(self.client.opener.open.call_args.args[0].get_header('Cache-control'), 'no-cache')
        self.assertEqual(next((self.root/'cache').glob('*.html')).read_bytes(), self.valid)

    def test_old_empty_cache_is_discarded(self):
        key = bur.hashlib.sha256(bur.canonical(self.url).encode()).hexdigest()
        cached = self.root/'cache'/(key+'.html')
        cached.write_bytes(self.empty)
        self.client.opener.open.return_value = Response(self.valid)
        page = self.client.page(self.url, require_issues=True)
        self.assertEqual(len(bur.issue_links(page, self.url)), 1)
        self.client.opener.open.assert_called_once()
        self.assertEqual(cached.read_bytes(), self.valid)
        self.assertEqual(self.client.opener.open.call_args.args[0].get_header('Cache-control'), 'no-cache')

    def test_exhausted_empty_responses_preserve_diagnostic_not_cache(self):
        self.client.opener.open.return_value = Response(self.empty)
        with self.assertRaisesRegex(bur.InvalidResponseError, 'Risposta HTML:'):
            self.client.page(self.url, require_issues=True)
        self.assertEqual(self.client.opener.open.call_count, 3)
        self.assertEqual(list((self.root/'cache').glob('*.html')), [])
        diagnostic = list((self.root/'diagnostics').glob('*.html'))
        self.assertEqual(len(diagnostic), 1)
        self.assertEqual(diagnostic[0].read_bytes(), self.empty)

    def test_valid_cache_is_reused(self):
        self.client.opener.open.return_value = Response(self.valid)
        self.client.page(self.url, require_issues=True)
        self.client.page(self.url, require_issues=True)
        self.client.opener.open.assert_called_once()

    def test_non_archive_html_does_not_require_issue_links(self):
        self.client.opener.open.return_value = Response(self.empty)
        self.client.page(bur.HOME)
        self.client.opener.open.assert_called_once()

class PdfTextReflowTests(unittest.TestCase):
    def test_sentence_has_no_layout_or_page_breaks(self):
        text = bur.reflow_pdf_text(['La Regione\nconcede contributi',
                                   'alle imprese.\n\nLa domanda\tva inviata.'])
        self.assertEqual(text, 'La Regione concede contributi alle imprese. La domanda va inviata.')
        self.assertNotIn('\n', text)
        self.assertNotIn('Pagina', text)

    def test_wrapped_words_are_rejoined(self):
        cases = [
            ('contri-\nbuti', 'contributi'),
            ('contri-  \n  buti', 'contributi'),
            ('mo -\ndificata', 'modificata'),
            ('le -\ngislatura', 'legislatura'),
            ('suben-\ntrato', 'subentrato'),
            ('con-\ntri-\nbuti', 'contributi'),
            ('contribu\u2010\nzioni', 'contribuzioni'),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(bur.reflow_pdf_text([raw]), expected)

    def test_word_across_pages_is_rejoined(self):
        self.assertEqual(bur.reflow_pdf_text(['contribu-', 'zioni alle imprese.']), 'contribuzioni alle imprese.')

    def test_soft_hyphens_and_unicode_spaces(self):
        self.assertEqual(bur.reflow_pdf_text(['contri\u00ad\nbuti e risorse\u00a0regionali.']),
                         'contributi e risorse regionali.')
        self.assertEqual(bur.reflow_pdf_text(['con\u00adtributi']), 'contributi')

    def test_real_hyphens_ranges_and_spaced_dashes_survive(self):
        text = bur.reflow_pdf_text(['socio-\neconomico e tecnico-scientifico. '
                                   'FRIULI-\nVENEZIA. COVID-\n19. 1998-\n2003. '
                                   'Titolo -\n nota.'])
        self.assertEqual(text, 'socio-economico e tecnico-scientifico. FRIULI-VENEZIA. '
                              'COVID-19. 1998-2003. Titolo - nota.')

    def test_empty_pages_remain_empty(self):
        self.assertEqual(bur.reflow_pdf_text(['', '  \n\t', '']), '')

    def test_fetch_writes_continuous_text_and_extracts_each_page_once(self):
        url = bur.HOME+'visionaBUR?bnum=2020/04/08/17'
        title = 'NUMERO 17 - 8 APRILE 2020'
        client = Mock()
        client.page.return_value = bur.Page('<div class="box-titolo">'+title+'</div>'
            '<a href="/newbur/downloadPDF?doc=0&amp;name=test.pdf">Sommario</a>')
        client.get.return_value = b'%PDF-test'
        reader = Mock()
        reader.pages = [Mock(), Mock()]
        reader.pages[0].extract_text.return_value = 'La Regione concede contri-'
        reader.pages[1].extract_text.return_value = 'buti alle\nimprese.'
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(bur, 'PdfReader', return_value=reader), \
             patch.object(bur, 'pdf_document_title', return_value=('BUR n. 17', 'pdf_metadata')):
            row = bur.fetch_summary(client, 2020, url, title, Path(tmp), 12)
            self.assertEqual(row['stato'], 'ok')
            self.assertEqual((Path(tmp)/row['testo']).read_text(), 'La Regione concede contributi alle imprese.')
            for page in reader.pages:
                page.extract_text.assert_called_once_with()

class ConversionOnlyTests(unittest.TestCase):
    def reader(self, texts):
        reader = Mock()
        reader.pages = []
        for text in texts:
            page = Mock()
            page.extract_text.return_value = text
            reader.pages.append(page)
        return reader

    def test_cli_conversion_never_constructs_network_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root/'2021'
            folder.mkdir()
            pdf = folder/'BUR_49_09_12_ordinario.pdf'
            pdf.write_bytes(b'pdf fixture')
            txt = pdf.with_suffix('.txt')
            txt.write_text('old text')
            index = root/'fascicoli.json'
            index.write_text('original index')
            registry = root/'file_sources.json'
            registry.write_text('original registry')
            argv = ['scraper', '--convert-only', '--output', str(root)]
            reader = self.reader(['La Regione concede contri-', 'buti alle\nimprese.'])
            with patch('sys.argv', argv), patch.object(bur, 'Client') as network, \
                 patch.object(bur, 'PdfReader', return_value=reader), \
                 patch.object(bur.logging, 'basicConfig'), \
                 patch.object(bur.logging, 'FileHandler', return_value=logging.NullHandler()):
                self.assertEqual(bur.main(), 0)
            network.assert_not_called()
            self.assertEqual(txt.read_text(), 'La Regione concede contributi alle imprese.')
            self.assertEqual(index.read_text(), 'original index')
            self.assertEqual(registry.read_text(), 'original registry')
            with (root/'conversione.csv').open(encoding='utf-8-sig', newline='') as f:
                row = next(bur.csv.DictReader(f))
            self.assertEqual(row['stato'], 'ok')
            self.assertEqual(row['pagine_estratte'], '2')

    def test_year_filter_uppercase_extension_and_cache_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ['2021/a.PDF', '2022/b.pdf', 'cache/2021/c.pdf', 'diagnostics/2021/d.pdf']:
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'pdf fixture')
            with patch.object(bur, 'PdfReader', return_value=self.reader(['some text'])) as read:
                self.assertEqual(bur.convert_existing_pdfs(root, year=2021), 0)
            read.assert_called_once_with(root/'2021/a.PDF')
            self.assertTrue((root/'2021/a.txt').is_file())
            self.assertFalse((root/'cache/2021/c.txt').exists())
            self.assertFalse((root/'2022/b.txt').exists())

    def test_corrupt_pdf_preserves_txt_and_continues(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'a.pdf').write_bytes(b'bad pdf')
            (root/'a.txt').write_text('keep this text')
            (root/'b.pdf').write_bytes(b'good pdf')
            with patch.object(bur, 'PdfReader', side_effect=[ValueError('bad PDF'), self.reader(['new text'])]), \
                 self.assertLogs(bur.LOG, 'WARNING'):
                self.assertEqual(bur.convert_existing_pdfs(root), 2)
            self.assertEqual((root/'a.txt').read_text(), 'keep this text')
            self.assertEqual((root/'b.txt').read_text(), 'new text')

    def test_no_text_preserves_existing_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'a.pdf').write_bytes(b'image PDF')
            (root/'a.txt').write_text('existing OCR result')
            with patch.object(bur, 'PdfReader', return_value=self.reader(['', '   '])), \
                 self.assertLogs(bur.LOG, 'WARNING'):
                self.assertEqual(bur.convert_existing_pdfs(root), 2)
            self.assertEqual((root/'a.txt').read_text(), 'existing OCR result')

    def test_empty_selection_reports_failure(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertLogs(bur.LOG, 'WARNING'):
            root = Path(tmp)
            self.assertEqual(bur.convert_existing_pdfs(root), 2)
            self.assertTrue((root/'conversione.csv').is_file())

    def test_limit_applies_to_sorted_local_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ['b.pdf', 'a.pdf']:
                (root/name).write_bytes(b'pdf fixture')
            with patch.object(bur, 'PdfReader', return_value=self.reader(['text'])) as read:
                self.assertEqual(bur.convert_existing_pdfs(root, limit=1), 0)
            read.assert_called_once_with(root/'a.pdf')
            self.assertFalse((root/'b.txt').exists())

    def test_invalid_conversion_arguments_fail_before_network(self):
        for options in [['--convert-only', '--page', '2'],
                        ['--convert-only', '--solo-indice']]:
            with patch('sys.argv', ['scraper']+options), patch.object(bur, 'Client') as client, \
                 patch('sys.stderr', new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as result:
                    bur.main()
                self.assertEqual(result.exception.code, 2)
                client.assert_not_called()

if __name__ == '__main__': unittest.main()











