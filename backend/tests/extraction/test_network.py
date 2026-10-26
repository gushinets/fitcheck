import io
import socket
import subprocess
import ssl
import threading

import pytest

from fitcheck_backend.extraction import network
from fitcheck_backend.extraction.errors import ExtractionError
from fitcheck_backend.extraction.network import RawPageResponse, fetch_public_page


def page(body=b"Role", status=200, **headers):
    return RawPageResponse(status, {"content-type": "text/html; charset=utf-8", **headers}, body)


def fetch(url="https://jobs.example/role", *, resolve=lambda host: ["93.184.216.34"], request=lambda *args: page()):
    return fetch_public_page(url, resolve=resolve, request=request)


@pytest.mark.parametrize("address", [
    "0.0.0.0", "10.0.0.1", "100.64.0.1", "127.0.0.1", "169.254.169.254",
    "172.16.0.1", "192.0.2.1", "192.168.1.1", "198.51.100.1", "203.0.113.1",
    "224.0.0.1", "::", "::1", "::ffff:8.8.8.8", "::ffff:7f00:1", "2001:db8::1",
    "fc00::1", "fe80::1", "ff00::1", "2002:7f00:1::", "fe80::1%en0", "not-an-ip",
    "fec0::1", "::8.8.8.8", "3fff::1", "2001:20::1", "168.63.129.16",
])
def test_blocks_non_public_addresses(address):
    with pytest.raises(ExtractionError, match="manual") as error:
        fetch(resolve=lambda host: [address])
    assert error.value.code == "blocked_address"


@pytest.mark.parametrize("address", ["8.8.8.8", "93.184.216.34", "2001:4860:4860::8888"])
def test_allows_public_addresses(address):
    assert fetch(resolve=lambda host: [address]).body == "Role"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "https://user:secret@jobs.example/", "https://jobs.example:0/", "http://jobs.example:65536/", "https://jobs.example:abc/", "https://jobs.example/a\n", "http://", "https://jobs.example\\@127.0.0.1/", "https://jobs.example%00/", "https://jobs.example:/"])
def test_rejects_invalid_urls_before_network(url):
    def forbidden(*args):
        pytest.fail("invalid input reached network")
    with pytest.raises(ExtractionError) as error:
        fetch(url, resolve=forbidden, request=forbidden)
    assert error.value.code == "invalid_url"


def test_rejects_dns_answer_if_any_address_is_blocked():
    with pytest.raises(ExtractionError) as error:
        fetch(resolve=lambda host: ["93.184.216.34", "127.0.0.1"])
    assert error.value.code == "blocked_address"


def test_pins_all_validated_addresses_and_supports_ipv6_literals():
    def request(url, addresses, max_bytes, timeout_seconds):
        assert addresses == ["2001:4860:4860::8888"]
        assert 0 < timeout_seconds <= 8
        return page()
    assert fetch("https://[2001:4860:4860::8888]/", request=request).final_url == "https://[2001:4860:4860::8888]/"


def test_redirect_revalidation_and_limit():
    with pytest.raises(ExtractionError) as error:
        fetch(request=lambda *args: page(status=302, location="http://127.0.0.1/"))
    assert error.value.code == "blocked_address"
    calls = []
    def redirect(url, *args):
        calls.append(url)
        return page(status=302, location="/next")
    with pytest.raises(ExtractionError) as error:
        fetch(request=redirect)
    assert error.value.code == "redirect_limit"
    assert len(calls) == 4


def test_input_and_redirect_urls_are_length_bounded():
    with pytest.raises(ExtractionError) as error:
        fetch("https://jobs.example/" + "x" * 2000)
    assert error.value.code == "invalid_url"
    with pytest.raises(ExtractionError) as error:
        fetch(request=lambda *args: page(status=302, location="https://jobs.example/" + "x" * 2000))
    assert error.value.code == "invalid_url"


@pytest.mark.parametrize("url,limit", [
    ("https://www.freelancer.com/projects/n8n/role", 3_000_000),
    ("https://freelancer.com/projects/n8n/role", 3_000_000),
    ("https://freelancer.com.evil.example/projects/n8n/role", 1_000_000),
    ("https://www.freelancer.com/users/profile", 1_000_000),
    ("https://www.freelancer.com/projects/n8n/role/extra", 1_000_000),
])
def test_byte_limits_are_specific_to_exact_project_paths(url, limit):
    def oversized(url, addresses, max_bytes, timeout_seconds):
        assert max_bytes == limit
        return page(b"x" * (limit + 1))
    with pytest.raises(ExtractionError) as error:
        fetch(url, request=oversized)
    assert error.value.code == "response_too_large"


def test_limit_resets_after_redirect():
    def request(url, addresses, max_bytes, timeout_seconds):
        if "freelancer.com" in url:
            return page(status=302, location="https://jobs.example/role")
        assert max_bytes == 1_000_000
        return page(b"x" * 1_000_001)
    with pytest.raises(ExtractionError) as error:
        fetch("https://www.freelancer.com/projects/n8n/role", request=request)
    assert error.value.code == "response_too_large"


@pytest.mark.parametrize("response,code", [
    (page(status=500), "fetch_failed"), (page(status=302), "fetch_failed"),
    (page(**{"content-type": "application/json"}), "unsupported_content"),
])
def test_safe_response_errors(response, code):
    with pytest.raises(ExtractionError) as error:
        fetch(request=lambda *args: response)
    assert error.value.code == code
    assert "jobs.example" not in str(error.value)


def test_dns_errors_and_empty_answers():
    def broken(host):
        raise OSError("secret DNS details")
    with pytest.raises(ExtractionError) as error:
        fetch(resolve=broken)
    assert error.value.code == "fetch_failed"
    with pytest.raises(ExtractionError) as error:
        fetch(resolve=lambda host: [])
    assert error.value.code == "blocked_address"


def test_global_deadline_covers_dns_and_redirects(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(network.time, "monotonic", lambda: now[0])
    def resolve(host):
        now[0] += 3
        return ["93.184.216.34"]
    def request(url, addresses, max_bytes, timeout_seconds):
        assert timeout_seconds <= 5
        now[0] += 3
        return page(status=302, location="/next")
    with pytest.raises(ExtractionError) as error:
        fetch(resolve=resolve, request=request)
    assert error.value.code == "timeout"


def test_default_dns_process_is_bounded_and_reports_timeout(monkeypatch):
    def timed_out(command, **kwargs):
        assert 0 < kwargs["timeout"] <= 0.1
        assert kwargs["shell"] is False
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])
    monkeypatch.setattr(network.subprocess, "run", timed_out)
    with pytest.raises(ExtractionError) as error:
        network._resolve_addresses("jobs.example", 0.1)
    assert error.value.code == "timeout"


class FakeSocket:
    def __init__(self, wire):
        self.wire = io.BytesIO(wire)
        self.sent = b""
        self.closed = False
        self.connected = None
    def settimeout(self, timeout):
        assert timeout > 0
    def connect(self, address):
        self.connected = address
    def sendall(self, data):
        self.sent += data
    def makefile(self, *args):
        return self.wire
    def close(self):
        self.closed = True
    def shutdown(self, how):
        self.close()


def test_runtime_transport_pins_socket_and_preserves_tls_identity_and_host(monkeypatch):
    sock = FakeSocket(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 4\r\n\r\nRole")
    monkeypatch.setattr(network.socket, "socket", lambda *args: sock)
    class Context:
        def wrap_socket(self, raw, *, server_hostname):
            assert server_hostname == "jobs.example"
            return raw
    original_context = network.ssl.create_default_context
    def verified_context():
        context = original_context()
        assert context.check_hostname
        assert context.verify_mode == ssl.CERT_REQUIRED
        return Context()
    monkeypatch.setattr(network.ssl, "create_default_context", verified_context)
    def no_dns(*args, **kwargs):
        pytest.fail("transport performed a second DNS lookup")
    monkeypatch.setattr(network.socket, "getaddrinfo", no_dns)
    assert fetch(request=None).body == "Role"
    assert sock.connected == ("93.184.216.34", 443)
    assert b"Host: jobs.example\r\n" in sock.sent
    assert sock.closed


def test_stream_byte_limit_closes_connection(monkeypatch):
    sock = FakeSocket(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\n" + b"x" * 101)
    monkeypatch.setattr(network.socket, "socket", lambda *args: sock)
    with pytest.raises(ExtractionError) as error:
        network._request_page("http://jobs.example/", ["93.184.216.34"], 100, 1)
    assert error.value.code == "response_too_large"
    assert sock.closed
    assert sock.wire.closed


def test_aggregate_response_headers_are_bounded(monkeypatch):
    sock = FakeSocket(b"HTTP/1.1 200 OK\r\n" + (b"X-Large: " + b"x" * 40_000 + b"\r\n") * 2 + b"\r\n")
    monkeypatch.setattr(network.socket, "socket", lambda *args: sock)
    with pytest.raises(ExtractionError) as error:
        network._request_page("http://jobs.example/", ["93.184.216.34"], 1_000_000, 1)
    assert error.value.code == "response_too_large"
    assert sock.closed


def test_deadline_interrupts_slow_response_and_joins_timer(monkeypatch):
    client, peer = socket.socketpair()
    class ConnectedSocket:
        def settimeout(self, timeout):
            client.settimeout(timeout)
        def connect(self, address):
            assert address == ("93.184.216.34", 80)
        def sendall(self, data):
            client.sendall(data)
        def makefile(self, *args):
            return client.makefile(*args)
        def shutdown(self, how):
            client.shutdown(how)
        def close(self):
            client.close()
    monkeypatch.setattr(network.socket, "socket", lambda *args: ConnectedSocket())
    peer.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 100\r\n\r\nx")
    threads_before = set(threading.enumerate())
    try:
        with pytest.raises(ExtractionError) as error:
            network._request_page("http://jobs.example/", ["93.184.216.34"], 100, 0.05)
        assert error.value.code == "timeout"
        assert client.fileno() == -1
        assert set(threading.enumerate()) == threads_before
    finally:
        peer.close()


def test_tls_verification_failure_is_safe_and_closes_socket(monkeypatch):
    sock = FakeSocket(b"")
    monkeypatch.setattr(network.socket, "socket", lambda *args: sock)
    class RejectingContext:
        def wrap_socket(self, raw, *, server_hostname):
            raise ssl.SSLCertVerificationError("secret certificate details")
    monkeypatch.setattr(network.ssl, "create_default_context", lambda: RejectingContext())
    with pytest.raises(ExtractionError) as error:
        fetch(request=None)
    assert error.value.code == "fetch_failed"
    assert "secret" not in error.value.message
    assert sock.closed
