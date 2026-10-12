"""Bounded public-page fetches with DNS validation and pinned connections.

DNS runs in a disposable subprocess: blocking system resolver calls cannot be
cancelled safely in a Python thread. subprocess.run kills and reaps the child
on timeout, so stalled DNS cannot leave an unbounded collection of workers.
"""

from dataclasses import dataclass
import http.client
import ipaddress
import json
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

from .errors import ExtractionError

MAX_REDIRECTS = 3
MAX_BYTES = 1_000_000
FREELANCER_MAX_BYTES = 3_000_000
TIMEOUT_SECONDS = 8.0
MAX_URL_LENGTH = 2_000
MAX_HEADER_BYTES = 65_536


@dataclass(frozen=True)
class RawPageResponse:
    status: int
    headers: dict[str, str]
    body: bytes


@dataclass(frozen=True)
class PublicPageResponse:
    final_url: str
    content_type: str
    body: str


_BLOCKED_V4 = tuple(ipaddress.ip_network(cidr) for cidr in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
    "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24",
    "192.88.99.0/24", "192.168.0.0/16", "198.18.0.0/15", "198.51.100.0/24",
    "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4", "168.63.129.16/32",
))
_BLOCKED_V6 = tuple(ipaddress.ip_network(cidr) for cidr in (
    "64:ff9b::/96", "64:ff9b:1::/48", "2001:20::/28", "3fff::/20",
))


def is_public_address(address: str) -> bool:
    try:
        if "%" in address:
            return False
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    if parsed.version == 4:
        return parsed.is_global and not any(parsed in block for block in _BLOCKED_V4)
    # Translation/tunnelling ranges can encode a private IPv4 destination.
    return (
        parsed.is_global
        and not parsed.is_reserved
        and not parsed.is_site_local
        and not parsed.is_multicast
        and parsed.ipv4_mapped is None
        and parsed.sixtofour is None
        and parsed.teredo is None
        and not any(parsed in block for block in _BLOCKED_V6)
    )


def _parse_url(raw_url: str) -> str:
    try:
        if not isinstance(raw_url, str) or len(raw_url) > MAX_URL_LENGTH or re.search(r"[\x00-\x20\x7f\\]", raw_url):
            raise ValueError
        parts = urlsplit(raw_url)
        if parts.scheme not in ("http", "https") or not parts.hostname or "@" in parts.netloc:
            raise ValueError
        port = parts.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        if parts.netloc.endswith(":") or "%" in parts.hostname:
            raise ValueError
        hostname = parts.hostname.encode("idna").decode("ascii").lower()
        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError:
            if len(hostname) > 253 or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in hostname.rstrip(".").split(".")
            ):
                raise ValueError
            netloc = hostname
        else:
            netloc = f"[{ip}]" if ip.version == 6 else str(ip)
        if port is not None:
            netloc += f":{port}"
        # Percent-encode Unicode paths while preserving existing escapes.
        from urllib.parse import quote
        normalized = urlunsplit((parts.scheme, netloc, quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~"), quote(parts.query, safe="/%?:@!$&'()*+,;=-._~"), ""))
        if len(normalized) > MAX_URL_LENGTH:
            raise ValueError
        return normalized
    except (ValueError, UnicodeError):
        raise ExtractionError("invalid_url") from None


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ExtractionError("timeout")
    return remaining


def _resolve_addresses(hostname: str, timeout_seconds: float) -> list[str]:
    script = (
        "import json,socket,sys; "
        "print(json.dumps(list(dict.fromkeys(row[4][0] for row in "
        "socket.getaddrinfo(sys.argv[1],None,type=socket.SOCK_STREAM)))))"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-c", script, hostname],
            capture_output=True, text=True, timeout=timeout_seconds,
            check=True, shell=False,
        )
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        raise ExtractionError("timeout") from None
    except (OSError, subprocess.CalledProcessError, ValueError):
        raise ExtractionError("fetch_failed") from None


def _validated_addresses(url: str, resolve, deadline: float) -> list[str]:
    hostname = urlsplit(url).hostname
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        try:
            addresses = resolve(hostname) if resolve is not None else _resolve_addresses(hostname, _remaining(deadline))
        except ExtractionError:
            raise
        except TimeoutError:
            raise ExtractionError("timeout") from None
        except Exception:
            raise ExtractionError("fetch_failed") from None
    else:
        addresses = [hostname]
    _remaining(deadline)
    if not addresses or any(not is_public_address(address) for address in addresses):
        raise ExtractionError("blocked_address")
    return addresses


def _page_limit(url: str) -> int:
    parts = urlsplit(url)
    if parts.hostname in ("freelancer.com", "www.freelancer.com") and re.fullmatch(r"/projects/[^/]+/[^/]+/?", parts.path):
        return FREELANCER_MAX_BYTES
    return MAX_BYTES


class _HeaderReader:
    def __init__(self, reader):
        self.reader = reader
        self.remaining = MAX_HEADER_BYTES

    def readline(self, limit=-1):
        size = self.remaining + 1
        if limit >= 0:
            size = min(size, limit)
        line = self.reader.readline(size)
        self.remaining -= len(line)
        if self.remaining < 0:
            raise ExtractionError("response_too_large")
        return line


class _BoundedHTTPResponse(http.client.HTTPResponse):
    def begin(self):
        reader = self.fp
        self.fp = _HeaderReader(reader)
        try:
            super().begin()
        finally:
            self.fp = reader


def _request_page(url: str, addresses: list[str], max_bytes: int, timeout_seconds: float) -> RawPageResponse:
    """Connect directly to one numeric address; HTTP never resolves the host.

    The default SSL context verifies the original hostname and CA chain. The
    deadline timer shuts down the socket even if a peer dribbles response
    headers or body bytes slowly enough to avoid a socket idle timeout.
    """
    parts = urlsplit(url)
    deadline = time.monotonic() + timeout_seconds
    port = parts.port or (443 if parts.scheme == "https" else 80)
    address = addresses[0]
    family = socket.AF_INET6 if ipaddress.ip_address(address).version == 6 else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    connection = http.client.HTTPConnection(parts.hostname, port, timeout=timeout_seconds)
    connection.response_class = _BoundedHTTPResponse
    response = None
    timer = None
    expired = threading.Event()
    try:
        sock.settimeout(_remaining(deadline))
        sock.connect((address, port))
        if parts.scheme == "https":
            sock.settimeout(_remaining(deadline))
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parts.hostname)
        connection.sock = sock

        def cancel():
            expired.set()
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

        timer = threading.Timer(_remaining(deadline), cancel)
        timer.daemon = True
        timer.start()
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        connection.request("GET", path, headers={
            "Host": parts.netloc,
            "Accept": "text/html,text/plain;q=0.9",
            "User-Agent": "FitCheck Vacancy Extractor/1.0",
            "Accept-Encoding": "identity",
        })
        response = connection.getresponse()
        headers = {key.lower(): value for key, value in response.getheaders()}
        declared_size = headers.get("content-length")
        if declared_size and declared_size.isdigit() and int(declared_size) > max_bytes:
            raise ExtractionError("response_too_large")
        chunks = []
        size = 0
        while True:
            _remaining(deadline)
            chunk = response.read(min(65_536, max_bytes - size + 1))
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                raise ExtractionError("response_too_large")
            chunks.append(chunk)
        _remaining(deadline)
        return RawPageResponse(response.status, headers, b"".join(chunks))
    except ExtractionError:
        raise
    except (TimeoutError, socket.timeout):
        raise ExtractionError("timeout") from None
    except Exception:
        if expired.is_set() or time.monotonic() >= deadline:
            raise ExtractionError("timeout") from None
        raise ExtractionError("fetch_failed") from None
    finally:
        if timer is not None:
            timer.cancel()
            timer.join()
        if response is not None:
            response.close()
        connection.close()
        sock.close()


def fetch_public_page(raw_url: str, *, resolve=None, request=None) -> PublicPageResponse:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    url = _parse_url(raw_url)
    transport = request if request is not None else _request_page
    for redirects in range(MAX_REDIRECTS + 1):
        addresses = _validated_addresses(url, resolve, deadline)
        max_bytes = _page_limit(url)
        try:
            response = transport(url, addresses, max_bytes, _remaining(deadline))
        except ExtractionError:
            raise
        except TimeoutError:
            raise ExtractionError("timeout") from None
        except Exception:
            raise ExtractionError("fetch_failed") from None
        _remaining(deadline)
        headers = {key.lower(): value for key, value in response.headers.items()}
        if 300 <= response.status < 400:
            location = headers.get("location")
            if not location:
                raise ExtractionError("fetch_failed")
            if redirects == MAX_REDIRECTS:
                raise ExtractionError("redirect_limit")
            # Validate before urljoin can silently strip control characters.
            if len(location) > MAX_URL_LENGTH or re.search(r"[\x00-\x20\x7f\\]", location):
                raise ExtractionError("invalid_url")
            try:
                url = _parse_url(urljoin(url, location))
            except ValueError:
                raise ExtractionError("invalid_url") from None
            continue
        if not 200 <= response.status < 300:
            raise ExtractionError("fetch_failed")
        if len(response.body) > max_bytes:
            raise ExtractionError("response_too_large")
        content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type not in ("text/html", "text/plain"):
            raise ExtractionError("unsupported_content")
        return PublicPageResponse(url, content_type, response.body.decode("utf-8", errors="replace"))
    raise ExtractionError("redirect_limit")
