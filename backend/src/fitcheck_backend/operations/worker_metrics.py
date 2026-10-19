from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from ..worker.health import healthy


def start_worker_metrics(host, port, path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in {'/metrics', '/health'}:
                self.send_error(404); return
            up = healthy(path)
            body = f'# TYPE fitcheck_worker_healthy gauge\nfitcheck_worker_healthy {int(up)}\n'.encode()
            self.send_response(200 if self.path=='/metrics' or up else 503)
            self.send_header('Content-Type','text/plain; version=0.0.4')
            self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
        def log_message(self, *_args): pass
    server = ThreadingHTTPServer((host,port),Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever,daemon=True,name='worker-metrics').start()
    return server
