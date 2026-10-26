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

    def test_collision_does_not_overwrite_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = bur.document_basename(root, bur.HOME+'visionaBUR?bnum=2026/10/21/42', 'ordinario')
            pdf, txt = bur.save_document_files(root, base, 'source-a', b'pdf-a', 'text-a')
            with self.assertRaisesRegex(ValueError, 'Collisione'):
                bur.save_document_files(root, base, 'source-b', b'pdf-b', 'text-b')
            self.assertEqual(pdf.read_bytes(), b'pdf-a')
            self.assertEqual(txt.read_text(), 'text-a')
            bur.save_document_files(root, base, 'source-a', b'pdf-a', 'text-a')

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

if __name__ == '__main__': unittest.main()




