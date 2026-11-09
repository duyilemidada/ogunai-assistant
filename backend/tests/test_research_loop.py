"""The research loop: readable pages, results the model can actually see, and an answer at the step limit."""
import httpx
import pytest

from app.services.agents import base, tools


# ── fetch_url ─────────────────────────────────────────────────────────────────

class Resp:
    def __init__(self, text="", status=200, ctype="text/html", url="https://news.test/a", data=None):
        self.text, self.status_code, self.url, self._data = text, status, url, data
        self.headers = {"content-type": ctype}
    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("GET", self.url)
            raise httpx.HTTPStatusError("x", request=req, response=httpx.Response(self.status_code, request=req))
    def json(self):
        return self._data


NEWS_PAGE = ("<html><body><nav>" + "Home News Sport Weather " * 200 + "</nav><article><h1>Exchange hacked</h1>"
             "<p>On 29 October attackers drained funds from hot wallets.</p></article><footer>Copyright 2026</footer></body></html>")


def test_fetch_returns_the_article_not_the_navigation(monkeypatch):
    monkeypatch.setattr(tools.httpx, "get", lambda *a, **k: Resp(NEWS_PAGE))
    out = tools.fetch_url("https://news.test/a")
    assert "Exchange hacked" in out["content"] and "drained funds" in out["content"]
    assert "Home News Sport" not in out["content"] and "Copyright" not in out["content"]


def test_blocked_site_error_tells_the_agent_not_to_retry(monkeypatch):
    monkeypatch.setattr(tools.httpx, "get", lambda *a, **k: Resp(status=403))
    out = tools.fetch_url("https://news.test/a")
    assert "HTTP 403" in out["error"] and "Do NOT retry" in out["error"]


def test_a_404_is_a_plain_error_without_the_blocked_hint(monkeypatch):
    monkeypatch.setattr(tools.httpx, "get", lambda *a, **k: Resp(status=404))
    assert "Do NOT retry" not in tools.fetch_url("https://news.test/a")["error"]


def test_wikipedia_is_read_through_its_api(monkeypatch):
    seen = {}
    def fake(url, params=None, **kw):
        seen["url"], seen["params"] = url, params
        return Resp(ctype="application/json", data={"query": {"pages": {"1": {"extract": "The 2026 Binance hack was a theft."}}}})
    monkeypatch.setattr(tools.httpx, "get", fake)
    out = tools.fetch_url("https://en.wikipedia.org/wiki/2026_Binance_hack")
    assert "api.php" in seen["url"] and seen["params"]["titles"] == "2026_Binance_hack"
    assert out["source"] == "Wikipedia API" and "Binance hack" in out["content"]


def test_json_and_plain_text_pass_through_unchanged(monkeypatch):
    monkeypatch.setattr(tools.httpx, "get", lambda *a, **k: Resp('{"a": 1}', ctype="application/json"))
    assert tools.fetch_url("https://api.test/x")["content"] == '{"a": 1}'


# ── the agent loop ────────────────────────────────────────────────────────────

class ScriptLLM:
    """Always asks for another tool while tools are available; answers when they are not."""
    def __init__(self):
        self.calls = []
    def invoke_with_tools(self, messages, tools_, temperature=0.4, tool_choice="auto"):
        self.calls.append({"tools": list(tools_), "messages": [dict(m) for m in messages]})
        if tools_:
            return {"text": "", "tool_calls": [{"id": f"c{len(self.calls)}", "name": "research_probe",
                                                "arguments": {"q": f"query {len(self.calls)}"}}]}
        return {"text": "FINAL SYNTHESIS from the gathered facts", "tool_calls": []}


@pytest.fixture
def probe(monkeypatch):
    monkeypatch.setitem(tools._TOOL_REGISTRY, "research_probe", lambda q: {"blob": "x" * 3000, "q": q})


def agent(llm, tool="research_probe", iterations=5):
    cfg = {"name": "R", "system_prompt": "x", "tools": [tool], "max_iterations": iterations}
    return base.OgunAIAgent(role_config=cfg, llm_adapter=llm, user_id=1, conversation_id=None)


def test_hitting_the_step_limit_still_produces_an_answer(probe):
    llm = ScriptLLM()
    out = agent(llm).run("research it")
    assert out == "FINAL SYNTHESIS from the gathered facts"        # used to be the generic failure message
    assert len(llm.calls) == 5
    assert llm.calls[-1]["tools"] == [] and all(c["tools"] for c in llm.calls[:-1])
    assert any(base.FINAL_ANSWER_NUDGE == m.get("content") for m in llm.calls[-1]["messages"])


def test_old_tool_results_are_shortened_but_the_newest_stay_full(probe):
    llm = ScriptLLM()
    agent(llm).run("research it")
    tool_msgs = [m for m in llm.calls[-1]["messages"] if m["role"] == "tool"]
    assert len(tool_msgs) == 4
    assert "[older result shortened]" in tool_msgs[0]["content"]
    assert len(tool_msgs[0]["content"]) < len(tool_msgs[-1]["content"])
    assert "[older result shortened]" not in tool_msgs[-1]["content"]


def test_search_results_are_not_cut_at_two_thousand_characters(monkeypatch):
    results = {"results": [{"title": f"T{i}", "url": f"https://s{i}.test", "snippet": "word " * 120 + f"END{i}"} for i in range(5)]}
    monkeypatch.setattr(tools, "_search_web", lambda q, max_results=5: results)
    class OneSearch(ScriptLLM):
        def invoke_with_tools(self, messages, tools_, **k):
            self.calls.append({"messages": [dict(m) for m in messages]})
            if len(self.calls) == 1:
                return {"text": "", "tool_calls": [{"id": "c1", "name": "web_search", "arguments": {"query": "q"}}]}
            return {"text": "done", "tool_calls": []}
    llm = OneSearch()
    agent(llm, tool="web_search").run("q")
    seen = [m for m in llm.calls[-1]["messages"] if m["role"] == "tool"][0]["content"]
    assert "END4" in seen and "truncated" not in seen              # the fifth result is visible
