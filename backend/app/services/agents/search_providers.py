# backend/app/services/agents/search_providers.py
"""
Web search with automatic fallback.

Why this exists
---------------
web_search used to call Tavily and nothing else, so a missing key, an
exhausted quota or a network hiccup meant no search at all. This module tries
several back-ends in order and returns the first that gives results, always
in the same shape the agents already expect:

    {"results": [{"title", "url", "snippet"}, ...], "provider": "<name>"}

Back-ends
---------
searxng : a SearXNG instance's JSON API (SEARXNG_URL). Needs no API key.
          Point it at SearXNG itself or at a machine you control.
tavily  : the Tavily API (TAVILY_API_KEY). Also speaks to any Tavily-compatible
          server such as siftdog: set TAVILY_BASE_URL to its address and the
          key can be any non-empty string.
ddgs    : DuckDuckGo via the `ddgs` package. Zero setup, but it is scraping and
          gets rate-limited, so it is the last resort.

Settings (all optional, read from config.py / .env)
---------------------------------------------------
SEARCH_PROVIDERS  comma list, tried in order      default "searxng,tavily,ddgs"
SEARXNG_URL       e.g. http://192.168.1.20:8080   default "" (searxng skipped)
TAVILY_API_KEY    existing setting
TAVILY_BASE_URL   default https://api.tavily.com
SEARCH_TIMEOUT    seconds per provider            default 8
A provider with no configuration is skipped silently, so the default chain
works with only a Tavily key (tavily, then ddgs) exactly as before.

Two protections for a flaky or metered connection:
- cooldown: a provider that just failed is skipped for COOLDOWN_SECONDS, so one
  agent loop cannot hammer a blocked back-end.
- cache: identical queries within CACHE_TTL_SECONDS are answered locally,
  which saves quota and survives a retry after a connection drop.
"""
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from ...config import settings

DEFAULT_PROVIDERS = "searxng,tavily,ddgs"
DEFAULT_TAVILY_BASE = "https://api.tavily.com"
COOLDOWN_SECONDS = 60
CACHE_TTL_SECONDS = 600
CACHE_MAX_ENTRIES = 128
MAX_SNIPPET_CHARS = 500

_lock = threading.Lock()
_cooldown_until: Dict[str, float] = {}
_cache: Dict[Tuple[str, int], Tuple[float, Dict[str, Any]]] = {}


class ProviderUnavailable(Exception):
    """Provider is not configured; skip it without counting it as a failure."""


def _cfg(name: str, default: Any = "") -> Any:
    return getattr(settings, name, default) or default


def _timeout() -> float:
    try:
        return float(_cfg("SEARCH_TIMEOUT", 8))
    except (TypeError, ValueError):
        return 8.0


def _clean(items: List[Dict[str, Any]], title_k: str, url_k: str, text_k: str, limit: int) -> List[Dict[str, str]]:
    out = []
    for it in items:
        url = str(it.get(url_k) or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        out.append({
            "title": str(it.get(title_k) or url).strip()[:200],
            "url": url,
            "snippet": str(it.get(text_k) or "").strip()[:MAX_SNIPPET_CHARS],
        })
        if len(out) >= limit:
            break
    return out


# ── Providers ─────────────────────────────────────────────────────────────────

def _searxng(query: str, limit: int) -> List[Dict[str, str]]:
    base = str(_cfg("SEARXNG_URL")).rstrip("/")
    if not base:
        raise ProviderUnavailable("SEARXNG_URL not set")
    resp = httpx.get(
        f"{base}/search",
        params={"q": query, "format": "json"},
        headers={"User-Agent": "OgunAI/1.0", "Accept": "application/json"},
        timeout=_timeout(),
    )
    if resp.status_code == 403:
        raise RuntimeError("SearXNG refused the request: enable 'json' under search.formats in its settings.yml")
    resp.raise_for_status()
    return _clean(resp.json().get("results", []), "title", "url", "content", limit)


def _tavily(query: str, limit: int) -> List[Dict[str, str]]:
    base = str(_cfg("TAVILY_BASE_URL", DEFAULT_TAVILY_BASE)).rstrip("/")
    key = _cfg("TAVILY_API_KEY")
    custom_base = base != DEFAULT_TAVILY_BASE
    if not key and not custom_base:
        raise ProviderUnavailable("TAVILY_API_KEY not set")
    resp = httpx.post(
        f"{base}/search",
        headers={"Authorization": f"Bearer {key or 'unused'}", "Content-Type": "application/json"},
        # include_answer stays off: the agents never used it, and a
        # Tavily-compatible server may need an extra key to produce one.
        json={"query": query, "include_answer": False, "max_results": limit},
        timeout=_timeout(),
    )
    resp.raise_for_status()
    return _clean(resp.json().get("results", []), "title", "url", "content", limit)


def _ddgs(query: str, limit: int) -> List[Dict[str, str]]:
    try:
        from ddgs import DDGS                      # current package name
    except ImportError:
        try:
            from duckduckgo_search import DDGS     # older name of the same project
        except ImportError:
            raise ProviderUnavailable("ddgs not installed (pip install ddgs)")
    raw = DDGS(timeout=int(_timeout())).text(query, max_results=limit)
    return _clean(list(raw or []), "title", "href", "body", limit)


_PROVIDERS: Dict[str, Callable[[str, int], List[Dict[str, str]]]] = {
    "searxng": _searxng,
    "tavily": _tavily,
    "ddgs": _ddgs,
}


# ── Public entry point ────────────────────────────────────────────────────────

def provider_order() -> List[str]:
    raw = str(_cfg("SEARCH_PROVIDERS", DEFAULT_PROVIDERS))
    names = [n.strip().lower() for n in raw.split(",") if n.strip()]
    return [n for n in dict.fromkeys(names) if n in _PROVIDERS]


def reset_state() -> None:
    """Clear cooldowns and cache (used by tests, and handy after fixing a config)."""
    with _lock:
        _cooldown_until.clear()
        _cache.clear()


def search(query: str, max_results: int = 5) -> Dict[str, Any]:
    query = (query or "").strip()
    if not query:
        return {"error": "Empty search query."}

    cache_key = (query.lower(), max_results)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(cache_key)
        if hit and now - hit[0] < CACHE_TTL_SECONDS:
            return dict(hit[1], cached=True)

    problems: List[str] = []
    empty_from: Optional[str] = None

    for name in provider_order():
        with _lock:
            wait = _cooldown_until.get(name, 0) - time.monotonic()
        if wait > 0:
            problems.append(f"{name}: cooling down after a recent failure ({int(wait)}s left)")
            continue
        try:
            results = _PROVIDERS[name](query, max_results)
        except ProviderUnavailable:
            continue
        except Exception as e:
            with _lock:
                _cooldown_until[name] = time.monotonic() + COOLDOWN_SECONDS
            problems.append(f"{name}: {str(e)[:160]}")
            print(f"  [SEARCH] {name} failed: {str(e)[:160]}")
            continue

        if results:
            payload = {"results": results, "provider": name}
            with _lock:
                if len(_cache) >= CACHE_MAX_ENTRIES:
                    _cache.pop(next(iter(_cache)))
                _cache[cache_key] = (time.monotonic(), payload)
            return payload
        # Answered but found nothing: an empty answer is often a soft block,
        # so try the next provider before believing it.
        empty_from = empty_from or name
        problems.append(f"{name}: no results")

    if empty_from:
        failures = [p for p in problems if not p.endswith("no results")]
        note = "No results found for this query."
        if failures:
            note += " Other providers failed: " + "; ".join(failures)
        return {"results": [], "provider": empty_from, "note": note}
    if not problems:
        return {"error": "No search provider is configured. Set TAVILY_API_KEY or SEARXNG_URL in .env, or pip install ddgs."}
    return {"error": "Search failed on every provider. " + "; ".join(problems)}
