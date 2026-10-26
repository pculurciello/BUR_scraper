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

if __name__ == '__main__': unittest.main()
