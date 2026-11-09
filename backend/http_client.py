"""Shared HTTP GET session with bounded retries for transient public-feed failures.

Only idempotent GET/HEAD calls are retried. Local Ollama POSTs and any future side-effecting
requests intentionally remain outside this helper.
"""
from __future__ import annotations

from requests import Session, Response
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .version import VERSION


def build_get_session() -> Session:
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=0.2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        respect_retry_after_header=True,
        raise_on_status=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=16)
    session = Session()
    session.headers.update({
        "User-Agent": f"curl/8.0 (compatible; Windows; RupeePredictionResearch/{VERSION})",
        "Accept": "text/html,text/csv,application/json,application/vnd.ms-excel,*/*",
    })
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


GET_SESSION = build_get_session()


def get(url: str, **kwargs) -> Response:
    """Perform a GET with explicit caller timeout and bounded transient retries."""
    if "timeout" not in kwargs:
        kwargs["timeout"] = 25
    return GET_SESSION.get(url, **kwargs)
