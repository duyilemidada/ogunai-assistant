#!/usr/bin/env python3
"""
Live check of every search back-end, from YOUR machine (run it with internet on).

    cd backend
    python scripts/check_search.py "latest CBN circular on fintech"

For each provider it prints: configured or not, latency, result count, the first
title, and WHO receives your query. Then it runs the real chain and shows which
provider answered. Nothing is written anywhere.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.agents import search_providers as sp

WHO = {
    "searxng": "your SearXNG instance, which forwards the query to Google/Bing/etc. (they see the text, not your IP)",
    "tavily": "Tavily (third party: sees the query text and your API key)",
    "ddgs": "DuckDuckGo (third party: sees the query text and your IP)",
}


def main():
    query = " ".join(sys.argv[1:]) or "python fastapi streaming response"
    clean, redacted = sp.scrub_query(query)
    print(f"Query sent    : {clean!r}" + (f"   (redacted: {sorted(set(redacted))})" if redacted else ""))
    print(f"Chain order   : {sp.provider_order()}\n")
    for name in ("searxng", "tavily", "ddgs"):
        start = time.monotonic()
        try:
            results = sp._PROVIDERS[name](clean, 3)
            ms = int((time.monotonic() - start) * 1000)
            first = results[0]["title"][:60] if results else "-"
            print(f"[ OK   ] {name:8} {ms:5} ms  {len(results)} results  first: {first}")
            print(f"           goes to: {WHO[name]}")
        except sp.ProviderUnavailable as e:
            print(f"[ skip ] {name:8} not configured ({e})")
        except Exception as e:
            print(f"[ FAIL ] {name:8} {str(e)[:100]}")
    sp.reset_state()
    out = sp.search(query)
    print("\nReal chain result:", out.get("provider") or out.get("error"))


if __name__ == "__main__":
    main()
