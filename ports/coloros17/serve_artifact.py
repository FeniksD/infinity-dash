"""Serve one verified artifact with bearer authentication and optional TLS.

For temporary, source-IP-restricted transfers. No directory browsing, uploads,
redirects, or arbitrary file paths. Token and TLS key come from private files.
"""
import argparse
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import socket
import ssl
import stat


def identity(st):
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


class Artifact:
    def __init__(self, path, size, sha256):
        self.path = Path(path)
        with self.open() as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size != size:
                raise ValueError('Artifact size/type differs')
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            after = os.fstat(stream.fileno())
        if identity(before) != identity(after) or digest != sha256:
            raise ValueError('Artifact hash/identity differs')
        self.expected_identity = identity(after)
        self.size = size

    def open(self):
        return os.fdopen(os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW), 'rb')


def make_server(address, artifact, token, tls_context=None, tcp_congestion=None):
    if not token or '\n' in token or '\r' in token:
        raise ValueError('Invalid token')
    if tcp_congestion not in (None, 'reno', 'cubic', 'bbr'):
        raise ValueError('Unreviewed TCP congestion algorithm')
    expected_auth = ('Bearer ' + token).encode()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        server_version = 'ArtifactTransfer'
        sys_version = ''

        def log_message(self, *_args):
            pass  # Never log request headers, tokens, or URL query strings.

        def empty(self, status, **headers):
            self.send_response(status)
            self.send_header('Content-Length', '0')
            self.send_header('Connection', 'close')
            for key, value in headers.items():
                self.send_header(key.replace('_', '-'), value)
            self.end_headers()
            self.close_connection = True

        def do_HEAD(self):
            self.transfer(False)

        def do_GET(self):
            self.transfer(True)

        def transfer(self, body):
            auth = self.headers.get('Authorization', '').encode()
            if not hmac.compare_digest(auth, expected_auth):
                return self.empty(401, WWW_Authenticate='Bearer')
            if self.path != '/coloros17.img.gz':
                return self.empty(404)
            start, end = 0, artifact.size - 1
            partial = self.headers.get('Range')
            if partial:
                match = re.fullmatch(r'bytes=(\d+)-(\d*)', partial)
                if match:
                    start = int(match[1])
                    end = min(int(match[2]), end) if match[2] else end
                if not match or not 0 <= start <= end < artifact.size:
                    return self.empty(416, Content_Range=f'bytes */{artifact.size}')
            try:
                stream = artifact.open()
            except OSError:
                return self.empty(409)
            with stream:
                if identity(os.fstat(stream.fileno())) != artifact.expected_identity:
                    return self.empty(409)
                self.send_response(206 if partial else 200)
                self.send_header('Content-Type', 'application/gzip')
                self.send_header('Content-Length', str(end - start + 1))
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Connection', 'close')
                if partial:
                    self.send_header('Content-Range', f'bytes {start}-{end}/{artifact.size}')
                self.end_headers()
                self.close_connection = True
                if body:
                    stream.seek(start)
                    remaining = end - start + 1
                    try:
                        while remaining:
                            chunk = stream.read(min(1024 * 1024, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                    except (BrokenPipeError, ConnectionResetError, TimeoutError):
                        pass

    class Server(ThreadingHTTPServer):
        daemon_threads = True

        def get_request(self):
            connection, peer = super().get_request()
            connection.settimeout(60)
            if tls_context is not None:
                try:
                    connection = tls_context.wrap_socket(connection, server_side=True)
                except BaseException:
                    connection.close()
                    raise
            return connection, peer

    server = Server(address, Handler, bind_and_activate=False)
    try:
        if tcp_congestion:
            server.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_CONGESTION,
                                     tcp_congestion.encode('ascii'))
        server.server_bind()
        server.server_activate()
    except BaseException:
        server.server_close()
        raise
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', type=Path, required=True)
    parser.add_argument('--size', type=int, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--token-file', type=Path, required=True)
    parser.add_argument('--cert', type=Path, required=True)
    parser.add_argument('--key', type=Path, required=True)
    parser.add_argument('--bind', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=9443)
    parser.add_argument('--tcp-congestion', choices=['reno', 'cubic', 'bbr'])
    args = parser.parse_args()
    if args.size <= 0 or not re.fullmatch('[0-9a-f]{64}', args.sha256):
        parser.error('Expected positive size and SHA256')
    artifact = Artifact(args.file, args.size, args.sha256)
    token = args.token_file.read_text().strip()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(args.cert, args.key)
    server = make_server((args.bind, args.port), artifact, token, context, args.tcp_congestion)
    print(json.dumps({'ready': True, 'bind': args.bind, 'port': args.port,
                      'verified_bytes': args.size, 'sha256': args.sha256}), flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
