# backend/tests/test_search_providers.py
import httpx
import pytest

from app.services.agents import search_providers as sp


class FakeSettings:
    TAVILY_API_KEY = ""
    SEARXNG_URL = ""
    TAVILY_BASE_URL = ""
    SEARCH_PROVIDERS = ""


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    fake = FakeSettings()
    monkeypatch.setattr(sp, "settings", fake)
    sp.reset_state()
    yield fake
    sp.reset_state()


def resp(status, payload, url="http://x/"):
    return httpx.Response(status, json=payload, request=httpx.Request("GET", url))


R = [{"title": "T", "url": "https://a.example/1", "content": "snippet"}]


def test_searxng_parsed_and_tagged(clean, monkeypatch):
    clean.SEARXNG_URL = "http://box:8080/"
    seen = {}
    def fake_get(url, params=None, **kw):
        seen.update(url=url, params=params)
        return resp(200, {"results": R})
    monkeypatch.setattr(sp.httpx, "get", fake_get)
    out = sp.search("python")
    assert out == {"results": [{"title": "T", "url": "https://a.example/1", "snippet": "snippet"}], "provider": "searxng"}
    assert seen["url"] == "http://box:8080/search" and seen["params"]["format"] == "json"


def test_searxng_403_gives_actionable_hint_then_falls_back(clean, monkeypatch):
    clean.SEARXNG_URL = "http://box:8080"
    clean.TAVILY_API_KEY = "k"
    monkeypatch.setattr(sp.httpx, "get", lambda *a, **k: resp(403, {}))
    monkeypatch.setattr(sp.httpx, "post", lambda *a, **k: resp(200, {"results": R}))
    out = sp.search("q")
    assert out["provider"] == "tavily"


def test_tavily_only_default_matches_old_behaviour(clean, monkeypatch):
    clean.TAVILY_API_KEY = "k"
    captured = {}
    def fake_post(url, headers=None, json=None, **kw):
        captured.update(url=url, auth=headers["Authorization"], body=json)
        return resp(200, {"results": R})
    monkeypatch.setattr(sp.httpx, "post", fake_post)
    out = sp.search("q", max_results=3)
    assert out["provider"] == "tavily"
    assert captured["url"] == "https://api.tavily.com/search"
    assert captured["auth"] == "Bearer k" and captured["body"]["max_results"] == 3
    assert captured["body"]["include_answer"] is False


def test_siftdog_style_base_url_needs_no_real_key(clean, monkeypatch):
    clean.TAVILY_BASE_URL = "http://localhost:8000"
    captured = {}
    monkeypatch.setattr(sp.httpx, "post", lambda url, **k: (captured.setdefault("url", url), resp(200, {"results": R}))[1])
    assert sp.search("q")["provider"] == "tavily"
    assert captured["url"] == "http://localhost:8000/search"


def test_failed_provider_goes_on_cooldown_and_is_skipped(clean, monkeypatch):
    clean.TAVILY_API_KEY = "k"
    calls = {"tavily": 0}
    def boom(*a, **k):
        calls["tavily"] += 1
        raise httpx.ConnectError("down")
    monkeypatch.setattr(sp.httpx, "post", boom)
    monkeypatch.setitem(sp._PROVIDERS, "ddgs", lambda q, n: (_ for _ in ()).throw(sp.ProviderUnavailable("no")))
    first = sp.search("one")
    second = sp.search("two")
    assert "error" in first and "error" in second
    assert calls["tavily"] == 1                      # second search did not hit the dead provider
    assert "cooling down" in second["error"]


def test_empty_results_fall_through_to_next_provider(clean, monkeypatch):
    clean.TAVILY_API_KEY = "k"
    monkeypatch.setattr(sp.httpx, "post", lambda *a, **k: resp(200, {"results": []}))
    monkeypatch.setitem(sp._PROVIDERS, "ddgs", lambda q, n: [{"title": "D", "url": "https://d.example", "snippet": "s"}])
    out = sp.search("rare")
    assert out["provider"] == "ddgs"


def test_everything_empty_is_a_result_not_an_error(clean, monkeypatch):
    clean.TAVILY_API_KEY = "k"
    monkeypatch.setattr(sp.httpx, "post", lambda *a, **k: resp(200, {"results": []}))
    monkeypatch.setitem(sp._PROVIDERS, "ddgs", lambda q, n: [])
    out = sp.search("zzzz")
    assert out["results"] == [] and "error" not in out


def test_cache_answers_repeat_without_network(clean, monkeypatch):
    clean.TAVILY_API_KEY = "k"
    n = {"c": 0}
    def fake_post(*a, **k):
        n["c"] += 1
        return resp(200, {"results": R})
    monkeypatch.setattr(sp.httpx, "post", fake_post)
    sp.search("Same Query"); out = sp.search("same query")
    assert n["c"] == 1 and out.get("cached") is True


def test_nothing_configured_says_how_to_fix(clean, monkeypatch):
    monkeypatch.setitem(sp._PROVIDERS, "ddgs", lambda q, n: (_ for _ in ()).throw(sp.ProviderUnavailable("x")))
    out = sp.search("q")
    assert "TAVILY_API_KEY" in out["error"] and "SEARXNG_URL" in out["error"]


def test_provider_order_setting_and_junk_names(clean):
    clean.SEARCH_PROVIDERS = "ddgs, tavily, bogus, ddgs"
    assert sp.provider_order() == ["ddgs", "tavily"]


def test_results_without_http_urls_are_dropped(clean, monkeypatch):
    clean.TAVILY_API_KEY = "k"
    bad = [{"title": "x", "url": "javascript:alert(1)", "content": "c"}, *R]
    monkeypatch.setattr(sp.httpx, "post", lambda *a, **k: resp(200, {"results": bad}))
    assert [r["url"] for r in sp.search("q")["results"]] == ["https://a.example/1"]


def test_empty_query():
    assert "error" in sp.search("   ")



# ── Query scrubbing (privacy) ─────────────────────────────────────────────────

def test_ordinary_queries_pass_through_untouched():
    for q in ["FastAPI JWT authentication tutorial 2026", "ISBN 9780134685991 clean code",
              "python 3.12 release notes", "stackoverflow.com/questions/12345678/how-to-parse-json-in-python",
              "git commit a94a8fe5ccb19ba61c4c0873d391e987982fbbd3 regression", "primary key vs foreign key"]:
        assert sp.scrub_query(q) == (q, [])


def test_secrets_and_personal_numbers_are_redacted():
    cases = {
        "why does gsk_abcdefghijklmnop1234 fail": "api_key",
        "AKIAIOSFODNN7EXAMPLE leaked": "aws_key",
        "Authorization: Bearer abcdefghijklmnopqrstuvwx": "bearer_token",
        "TAVILY_API_KEY=abc123xyz789 not working": "secret_assignment",
        "contact me@example.com about it": "email",
        "customer 08012345678 called": "phone_number",
        "NUBAN 0123456789 failed": "account_number",
        "BVN 12345678901 mismatch": "account_number",
        "charge 4111 1111 1111 1111 declined": "card_number",
        "token 9fA3kLmQ8vXz2RtYb6NcHd4WePs1JuGo7": "token",
    }
    for query, kind in cases.items():
        clean, kinds = sp.scrub_query(query)
        assert kind in kinds and f"[REDACTED:{kind}]" in clean, (query, clean, kinds)


def test_a_number_that_fails_the_card_check_is_left_alone():
    assert sp.scrub_query("order 4111 1111 1111 1112")[1] == []


def test_search_sends_only_the_scrubbed_query(clean, monkeypatch):
    seen = {}
    def fake_ddgs(q, n):
        seen["q"] = q
        return [{"title": "T", "url": "https://a.example", "snippet": "s"}]
    monkeypatch.setitem(sp._PROVIDERS, "ddgs", fake_ddgs)
    out = sp.search("how to fix gsk_abcdefghijklmnop1234 error")
    assert "gsk_" not in seen["q"] and "[REDACTED:api_key]" in seen["q"]
    assert out["redacted"] == ["api_key"]


def test_query_that_is_only_a_secret_is_not_sent_at_all(clean, monkeypatch):
    monkeypatch.setitem(sp._PROVIDERS, "ddgs", lambda q, n: pytest.fail("must not be called"))
    assert "only sensitive data" in sp.search("gsk_abcdefghijklmnop1234")["error"]
