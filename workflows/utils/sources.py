from __future__ import annotations

from urllib.parse import urlparse


def is_valid_http_url(url: str) -> bool:
    if not isinstance(url, str):
        return False
    stripped = url.strip().lower()
    return stripped.startswith("http://") or stripped.startswith("https://")


def domain_to_organization(url: str) -> str:
    try:
        # Use .hostname so that ports (e.g. "example.com:8080") are stripped.
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host or "source-inconnue"


def normalized_host(url: str) -> str:
    try:
        # Use .hostname so that ports (e.g. "example.com:8080") are stripped.
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host
