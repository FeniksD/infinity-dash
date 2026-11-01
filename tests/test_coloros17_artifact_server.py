import hashlib
import http.client
from pathlib import Path
import tempfile
import threading
import unittest

from ports.coloros17.serve_artifact import Artifact, make_server


class ArtifactServerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'image.gz'
        self.data = b'0123456789abcdef'
        self.path.write_bytes(self.data)
        self.artifact = Artifact(self.path, len(self.data), hashlib.sha256(self.data).hexdigest())
        self.server = make_server(('127.0.0.1', 0), self.artifact, 'test-token')
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()
        self.directory.cleanup()

    def request(self, path='/coloros17.img.gz', method='GET', token='test-token', **headers):
        if token is not None:
            headers['Authorization'] = 'Bearer ' + token
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=2)
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_authentication_and_exact_path(self):
        for token in (None, 'wrong', 'test-token-extra'):
            self.assertEqual(self.request(token=token)[0], 401)
        for path in ('/', '/image.gz', '/../image.gz', '/coloros17.img.gz?token=x'):
            self.assertEqual(self.request(path=path)[0], 404)
        status, headers, body = self.request()
        self.assertEqual((status, body), (200, self.data))
        self.assertEqual(headers['Content-Length'], str(len(self.data)))

    def test_head_and_single_range(self):
        status, headers, body = self.request(method='HEAD')
        self.assertEqual((status, body), (200, b''))
        self.assertEqual(headers['Content-Length'], '16')
        for range_header, expected in [('bytes=4-', self.data[4:]), ('bytes=4-7', self.data[4:8])]:
            status, headers, body = self.request(Range=range_header)
            self.assertEqual((status, body), (206, expected))
            self.assertEqual(headers['Content-Length'], str(len(expected)))
        for invalid in ('bytes=-4', 'bytes=16-', 'bytes=8-3', 'bytes=0-1,4-5', 'garbage'):
            self.assertEqual(self.request(Range=invalid)[0], 416)

    def test_changed_or_replaced_file_is_refused(self):
        self.path.write_bytes(b'x' * len(self.data))
        self.assertEqual(self.request()[0], 409)

    def test_symlink_or_bad_hash_is_refused_at_start(self):
        with self.assertRaises(ValueError):
            Artifact(self.path, len(self.data), '0' * 64)
        link = self.path.with_name('link')
        link.symlink_to(self.path)
        with self.assertRaises((ValueError, OSError)):
            Artifact(link, len(self.data), hashlib.sha256(self.data).hexdigest())


if __name__ == '__main__':
    unittest.main()
