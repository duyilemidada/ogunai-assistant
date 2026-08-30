# backend/app/services/agents/tools.py
import asyncio
import inspect
import json
import os
import re
import shlex
import subprocess
import threading
import time
import datetime as dt

import httpx
import numpy as np
from typing import Dict, Any, List, Callable, Optional
from sentence_transformers import SentenceTransformer

from ...config import settings
from ...database import SessionLocal
from ...models import (
    UserLike, DailyNutrition, WorkoutLog, PhysicalStatus,
    Document, DocumentChunk, LearningProgress
)


# ─── Tool Registry ────────────────────────────────────────────────────────────

_TOOL_REGISTRY: Dict[str, Callable] = {}


def register_tool(name: str):
    def decorator(func):
        _TOOL_REGISTRY[name] = func
        return func
    return decorator


def get_tool_schemas(tool_names: List[str]) -> List[Dict[str, Any]]:
    """Generates OpenAI-compatible tool schemas from registered function signatures."""
    schemas = []
    for name in tool_names:
        if name not in _TOOL_REGISTRY:
            continue
        func = _TOOL_REGISTRY[name]
        sig = inspect.signature(func)
        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            # user_id and db are injected at runtime — hide from the LLM
            if param_name in ('user_id', 'db'):
                continue
            py_type = param.annotation
            json_type = "string"
            if py_type in (int, float):
                json_type = "number"
            elif py_type is bool:
                json_type = "boolean"
            elif py_type in (Dict, dict):
                json_type = "object"

            properties[param_name] = {"type": json_type}
            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        doc = func.__doc__ or ""
        description = doc.split('\n')[0].strip()

        schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            }
        })
    return schemas


# ─── Singleton Embedder ───────────────────────────────────────────────────────

_embedder: Optional[SentenceTransformer] = None


def get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        # 384-dim, fast, good semantic similarity — ~80MB download on first run
        _embedder = SentenceTransformer('all-MiniLM-L6-v2')
    return _embedder


# ─── Async helper (Crawl4AI runs async; our tools are sync) ──────────────────

def _run_async(coro):
    """
    Runs an async coroutine from a sync context in a dedicated thread.
    The thread sets ProactorEventLoop on Windows because SelectorEventLoop
    (the Windows default) raises NotImplementedError on subprocess creation,
    which Playwright requires.
    """
    import sys
    result_box: list = [None]
    error_box: list = [None]

    def _runner():
        # Windows-specific: must use ProactorEventLoop for subprocess support.
        # SelectorEventLoop (the default) cannot call create_subprocess_exec.
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        try:
            result_box[0] = asyncio.run(coro)
        except Exception as e:
            error_box[0] = e

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout=60)

    if t.is_alive():
        return {"error": "Browser operation timed out (60s)."}
    if error_box[0]:
        raise error_box[0]
    return result_box[0]

# ─── API Constants ────────────────────────────────────────────────────────────

MONO_BASE = "https://api.withmono.com"
MONO_HEADERS = {
    "Accept": "application/json",
    "mono-sec-key": settings.MONO_SECRET_KEY
}

GITHUB_API_BASE = "https://api.github.com"
GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
    "X-GitHub-Api-Version": "2022-11-28"
}

# USDA nutrient IDs — stable identifiers that don't change between food types
USDA_NUTRIENT_IDS = {
    "calories": 1008,   # Energy (kcal)
    "protein":  1003,   # Protein (g)
    "carbs":    1005,   # Carbohydrate, by difference (g)
    "fat":      1004,   # Total lipid/fat (g)
    "fiber":    1079,   # Fiber, total dietary (g)
}

# run_terminal safety config
_BLOCKED_SUBSTRINGS = [
    'rm -rf /', 'rm -rf ~',
    ':(){:|:&};:',      # Fork bomb
    '/etc/shadow', '/etc/passwd',
    '> /dev/sda', 'dd if=/dev/',
]
_BLOCKED_COMMANDS = {
    'sudo', 'su', 'passwd', 'shutdown', 'reboot',
    'halt', 'poweroff', 'mkfs', 'fdisk',
}


# ─── Basic Tools ──────────────────────────────────────────────────────────────
@register_tool("web_search")
def web_search(query: str) -> Dict[str, Any]:
    """Searches the web for information. Use for facts, current events, and documentation."""
    if not settings.TAVILY_API_KEY:
        return {"error": "TAVILY_API_KEY is missing in settings/.env"}

    try:
        resp = httpx.post(
            "https://api.tavily.com/search",
            headers={
                "Authorization": f"Bearer {settings.TAVILY_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "query": query,
                "include_answer": True,
                "max_results": 5
            },
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "results": [
                {"title": r["title"], "url": r["url"], "snippet": r.get("content", "")}
                for r in data.get("results", [])
            ]
        }
    except Exception as e:
        return {"error": f"Tavily API Error: {str(e)}"}

@register_tool("read_file")
def read_file(file_path: str) -> Dict[str, Any]:
    """Reads the contents of a local file. Use absolute paths or paths relative to workspace."""
    try:
        # Try as-is first, then relative to workspace
        if not os.path.isabs(file_path):
            workspace_path = os.path.join(settings.WORKSPACE_DIR, file_path)
            if os.path.exists(workspace_path):
                file_path = workspace_path
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        return {"content": content[:8000], "truncated": len(content) > 8000, "path": file_path}
    except Exception as e:
        return {"error": str(e)}

# ─── Tutor Tools ──────────────────────────────────────────────────────────────
# All four call the existing web_search() function above — same Tavily backend,
# no duplicate search logic, no second provider to configure.

@register_tool("assess_prerequisite")
def assess_prerequisite(topic: str) -> Dict[str, Any]:
    """
    Finds the prerequisite concepts a learner needs before studying a topic.
    Searches for curriculum/roadmap information — never guesses from memory.
    Returns an ordered list of prerequisites and asks the learner which feel unfamiliar.
    """
    search_result = web_search(f"{topic} prerequisites what to know first learning roadmap")

    if "error" in search_result:
        return {"error": f"Search failed: {search_result['error']}"}

    return {
        "topic": topic,
        "sources": search_result.get("results", []),
        "instruction": (
            f"Using the search results above, list the 3–5 prerequisite concepts "
            f"a learner needs before studying '{topic}'. "
            "Order them from most fundamental to most advanced. "
            "For each, add one sentence explaining why it matters as a foundation. "
            "End with: 'Which of these feel unfamiliar to you?' to identify the gap."
        )
    }


@register_tool("build_learning_plan")
def build_learning_plan(goal: str, current_level: str = "complete beginner") -> Dict[str, Any]:
    """
    Builds a week-by-week study plan for a learning goal.
    current_level: what the learner already knows (e.g. 'knows Python basics', 'complete beginner').
    Searches for real curricula and roadmaps before planning.
    """
    search_result = web_search(f"learn {goal} roadmap curriculum step by step beginner")

    if "error" in search_result:
        return {"error": f"Search failed: {search_result['error']}"}

    return {
        "goal": goal,
        "current_level": current_level,
        "sources": search_result.get("results", []),
        "instruction": (
            f"Using the sources above, build a realistic learning plan to achieve: '{goal}'. "
            f"Starting level: {current_level}. "
            "Structure as weekly milestones (4–8 weeks). "
            "Each week: one main concept, one hands-on exercise, one free resource to use. "
            "Keep it achievable — 1–2 hours per day maximum. "
            "After the plan, ask: 'Which week would you like to start with?'"
        )
    }


@register_tool("explain_concept")
def explain_concept(concept: str, level: str = "beginner") -> Dict[str, Any]:
    """
    Teaches a concept grounded in real sources — never from memory alone.
    level: 'beginner', 'intermediate', or 'advanced'.
    Returns sources + a structured teaching instruction for the agent to follow.
    """
    search_result = web_search(f"{concept} explained simply example")

    if "error" in search_result:
        return {"error": f"Search failed: {search_result['error']}"}

    return {
        "concept": concept,
        "level": level,
        "sources": search_result.get("results", []),
        "instruction": (
            f"Using the sources above, teach '{concept}' at a {level} level. "
            "Structure: "
            "(1) One-sentence definition in plain language. "
            "(2) A familiar analogy — compare it to something in everyday life. "
            "(3) One concrete example showing it in action. "
            "(4) Why it matters — one real-world use case. "
            "(5) A short practice question to check understanding. "
            "Cite at least one source URL. "
            "Tone: warm and direct — like a brilliant friend explaining over coffee, not a textbook."
        )
    }


@register_tool("generate_practice")
def generate_practice(concept: str, difficulty: str = "easy") -> Dict[str, Any]:
    """
    Generates a practice question for a concept.
    difficulty: 'easy' (recall), 'medium' (apply), 'hard' (create or debug).
    For technical topics, prefers code exercises or scenario-based questions.
    """
    # No search needed here — this is pure generation, not fact lookup.
    return {
        "concept": concept,
        "difficulty": difficulty,
        "instruction": (
            f"Create a {difficulty} practice question about '{concept}'. "
            "Format exactly as: "
            "QUESTION: [the question] "
            "HINT: [one nudge without giving away the answer] "
            "GOOD ANSWER COVERS: [2–3 points a solid answer would include] "
            "For technical topics, prefer: code completion, debugging a broken snippet, "
            "or a scenario ('a user reports X — what do you check first?'). "
            "Post only the QUESTION first — wait for the learner's response before revealing "
            "the hint or the good answer."
        )
    }


@register_tool("record_mastery")
def record_mastery(topic: str, confidence: int, user_id: int) -> Dict[str, Any]:
    """
    Saves a learner's progress on a topic. Call after each teaching session.
    confidence: 1 (just heard of it) to 5 (can teach it to others).
    Builds the knowledge graph used to detect gaps and avoid re-teaching.
    """
    if not 1 <= confidence <= 5:
        return {"error": "confidence must be 1–5."}

    db = SessionLocal()
    try:
        topic_normalised = topic.lower().strip()
        existing = db.query(LearningProgress).filter(
            LearningProgress.user_id == user_id,
            LearningProgress.topic == topic_normalised
        ).first()

        if existing:
            existing.confidence = confidence
            existing.updated_at = dt.datetime.now(dt.timezone.utc)
            db.commit()
            return {
                "updated": True,
                "topic": topic,
                "confidence": confidence,
                "message": f"Updated: '{topic}' confidence is now {confidence}/5."
            }

        db.add(LearningProgress(
            user_id=user_id,
            topic=topic_normalised,
            confidence=confidence,
        ))
        db.commit()
        return {
            "recorded": True,
            "topic": topic,
            "confidence": confidence,
            "message": f"Saved: '{topic}' at {confidence}/5."
        }
    except Exception as e:
        db.rollback()
        return {"error": f"DB write failed: {e}"}
    finally:
        db.close()


@register_tool("daily_deep_read")
def daily_deep_read(topic_area: str = "auto") -> Dict[str, Any]:
    """
    Fetches and structures a rich beginner-friendly deep-dive on a topic.
    topic_area: 'technology', 'economics', 'finance', 'science', or 'auto'.
    Always web-grounded. Written like a brilliant friend explaining something fascinating,
    not a textbook. Assumes the reader is curious but completely new to the topic.
    """
    import random

    topic_pools = {
        "technology": [
            "how large language models actually work inside",
            "what happens in the milliseconds between pressing Enter and a webpage loading",
            "how GPS satellites know your exact location",
            "why CPUs have multiple cores and what that actually means",
            "how the internet routes a packet across the world",
            "what zero-knowledge proofs are and why they matter for privacy",
        ],
        "economics": [
            "why inflation happens and how central banks try to stop it",
            "how currency exchange rates are actually determined",
            "what GDP measures and what it completely misses",
            "why some countries stay poor despite having resources",
            "how microfinance changes local economies in practice",
            "what the informal economy is and how big it really is in Africa",
        ],
        "finance": [
            "how compound interest actually builds wealth over time",
            "what venture capital does and how it picks winners",
            "how stock markets set prices in real time",
            "how Nigeria's financial system works from CBN to your bank account",
            "what DeFi is and whether it solves a real problem",
            "how insurance companies price risk and make money",
        ],
        "science": [
            "how CRISPR edits genes and why that is both exciting and scary",
            "what dark matter is and why physicists are sure it exists",
            "how vaccines train your immune system at a molecular level",
            "what actually causes aging at the cellular level",
            "how the brain forms and retrieves memories",
            "why sleep deprivation is more dangerous than most people realise",
        ]
    }

    if topic_area == "auto" or topic_area not in topic_pools:
        area = random.choice(list(topic_pools.keys()))
    else:
        area = topic_area

    topic = random.choice(topic_pools[area])
    search_result = web_search(topic)

    if "error" in search_result:
        return {"error": f"Search failed: {search_result['error']}"}

    return {
        "topic": topic,
        "area": area,
        "sources": search_result.get("results", []),
        "instruction": (
            f"Using the sources above, write a rich, engaging deep-dive on: '{topic}'. "
            "Assume the reader is curious but completely new to this topic. "
            "Structure:\n"
            "1. HOOK — one surprising fact or question that makes them care immediately.\n"
            "2. THE BASICS — what it is, in plain language, with a simple everyday analogy.\n"
            "3. HOW IT WORKS — go one level deeper, still accessible, no jargon without explanation.\n"
            "4. WHY IT MATTERS — real-world implications, especially for Nigeria or Africa where relevant.\n"
            "5. THE FRONTIER — what is most exciting, contested, or unknown about this right now.\n"
            "6. ONE THING TO EXPLORE NEXT — a specific question, book, or rabbit hole to follow.\n"
            "Tone: warm, direct, intellectually alive — like a brilliant friend who happens to "
            "know a lot about this, explaining it over a meal. Not a Wikipedia article. "
            "End with source URLs."
        )
    }




# ─── Developer Tools ──────────────────────────────────────────────────────────

@register_tool("run_terminal")
def run_terminal(command: str) -> Dict[str, Any]:
    """
    Runs a shell command in the sandboxed workspace directory.
    Good for: writing files, running Python, pytest, pip install, git operations.
    Timeout: 30 seconds. CWD is always reset to WORKSPACE_DIR.
    """
    workspace = os.path.abspath(settings.WORKSPACE_DIR)
    os.makedirs(workspace, exist_ok=True)

    # Safety: block dangerous substrings before shell execution
    for blocked in _BLOCKED_SUBSTRINGS:
        if blocked in command:
            return {"error": f"Blocked for safety — command contains '{blocked}'."}

    # Safety: block dangerous root commands
    try:
        parts = shlex.split(command)
        base_cmd = os.path.basename(parts[0]) if parts else ""
        if base_cmd in _BLOCKED_COMMANDS:
            return {"error": f"Command '{base_cmd}' is not permitted."}
    except ValueError:
        pass  # shlex can't parse it — let subprocess handle the error

    try:
        proc = subprocess.run(
            command,
            shell=True,          # Shell needed for pipes, &&, redirects
            capture_output=True,
            text=True,
            timeout=30,
            cwd=workspace        # Always starts in workspace — relative paths stay sandboxed
        )
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout[:5000],
            "stderr": proc.stderr[:2000],
            "success": proc.returncode == 0,
            "cwd": workspace
        }
    except subprocess.TimeoutExpired:
        return {"error": "Command timed out (30s limit). Use background processes for long tasks."}
    except Exception as e:
        return {"error": str(e)}


@register_tool("github_api")
def github_api(endpoint: str, method: str = "GET", data: Dict = None) -> Dict[str, Any]:
    """
    Calls the GitHub REST API v3. endpoint is the path after api.github.com
    (e.g. '/user/repos', '/repos/owner/repo/pulls').
    method: GET, POST, PATCH, PUT, DELETE. data: JSON body for write operations.
    """
    if not settings.GITHUB_TOKEN:
        return {
            "error": (
                "GITHUB_TOKEN not set. Add to .env: GITHUB_TOKEN=ghp_... "
                "Create one at github.com/settings/tokens → Tokens (classic) → "
                "Generate new token → check 'repo' scope."
            )
        }

    try:
        resp = httpx.request(
            method=method.upper(),
            url=f"{GITHUB_API_BASE}{endpoint}",
            headers=GITHUB_HEADERS,
            json=data if data else None,
            timeout=15
        )
        resp.raise_for_status()

        if resp.status_code == 204:
            return {"status": "success", "message": "Done."}

        raw = resp.json()

        # GitHub list endpoints (repos, issues, PRs, etc.) return a full object
        # per item — 50–100 fields each. For a user with many repos this is
        # 40k+ tokens in one response. Compress lists to essential fields only.
        if isinstance(raw, list):
            compressed = _compress_github_list(endpoint, raw)
            return {
                "total": len(raw),
                "items": compressed,
                "note": "Fields compressed to stay within context limits."
            }

        return {"data": raw, "status": resp.status_code}

    except httpx.HTTPStatusError as e:
        return {"error": f"GitHub API {e.response.status_code}: {e.response.text[:500]}"}
    except Exception as e:
        return {"error": str(e)}


def _compress_github_list(endpoint: str, items: list) -> list:
    """
    Extracts only the fields an LLM needs from GitHub list responses.
    Reduces a 40k-token repo list to ~200 tokens.
    """
    def _repo(r):
        return {
            "name":        r.get("name"),
            "full_name":   r.get("full_name"),
            "description": r.get("description"),
            "language":    r.get("language"),
            "url":         r.get("html_url"),
            "private":     r.get("private"),
            "stars":       r.get("stargazers_count"),
            "updated":     r.get("updated_at", "")[:10],
        }

    def _issue_or_pr(i):
        return {
            "number":  i.get("number"),
            "title":   i.get("title"),
            "state":   i.get("state"),
            "url":     i.get("html_url"),
            "created": i.get("created_at", "")[:10],
        }

    def _commit(c):
        return {
            "sha":     c.get("sha", "")[:8],
            "message": c.get("commit", {}).get("message", "")[:80],
            "author":  c.get("commit", {}).get("author", {}).get("name"),
            "date":    c.get("commit", {}).get("author", {}).get("date", "")[:10],
        }

    # Pick compressor based on endpoint
    ep = endpoint.lower()
    if "repos" in ep and ("pulls" in ep or "issues" in ep):
        fn = _issue_or_pr
    elif "commits" in ep:
        fn = _commit
    elif "repos" in ep or ep in ("/user/repos", "/user/starred"):
        fn = _repo
    else:
        # Unknown list type — take first 5 items, each trimmed to 300 chars
        return [str(item)[:300] for item in items[:5]]

    return [fn(item) for item in items[:30]]  # cap at 30 items

@register_tool("fetch_url")
def fetch_url(url: str) -> Dict[str, Any]:
    """
    Fetches a URL and returns its content as clean text.
    Use for static pages, documentation, and APIs. For JS-heavy pages, use browse_js instead.
    """
    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; OgunAI/1.0)"},
            follow_redirects=True,
            timeout=15
        )
        resp.raise_for_status()

        try:
            import html2text
            h = html2text.HTML2Text()
            h.ignore_links = False
            h.ignore_images = True
            h.body_width = 0    # No line wrapping
            text = h.handle(resp.text)
        except ImportError:
            # Fallback: strip HTML tags with regex
            text = re.sub(r'<[^>]+>', ' ', resp.text)
            text = re.sub(r'\s+', ' ', text).strip()

        return {
            "url": str(resp.url),
            "status_code": resp.status_code,
            "content": text[:10000],
            "truncated": len(text) > 10000
        }
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code} fetching {url}"}
    except Exception as e:
        return {"error": str(e)}


@register_tool("browse_js")
def browse_js(url: str) -> Dict[str, Any]:
    """
    Fetches a URL using a real headless Chromium browser (via Crawl4AI).
    Use when fetch_url returns empty or broken content due to JavaScript rendering.
    Requires: pip install crawl4ai && crawl4ai-setup && playwright install chromium
    """
    async def _crawl():
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
        except ImportError:
            return {
                "error": (
                    "crawl4ai not installed. "
                    "Run: pip install crawl4ai && crawl4ai-setup && playwright install chromium"
                )
            }

        browser_cfg = BrowserConfig(headless=True, verbose=False)
        run_cfg = CrawlerRunConfig(
            word_count_threshold=10,
            remove_overlay_elements=True,   # Dismiss cookie banners, popups
            exclude_external_links=True,
        )
        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            result = await crawler.arun(url=url, config=run_cfg)
            if result.success:
                md = result.markdown or ""
                return {
                    "url": url,
                    "content": md[:10000],
                    "truncated": len(md) > 10000
                }
            return {"error": result.error_message or "Crawl4AI returned no content."}

    try:
        return _run_async(_crawl())
    except Exception as e:
        return {"error": str(e)}


@register_tool("browse_authenticated")
def browse_authenticated(url: str, login_url: str, username: str, password: str) -> Dict[str, Any]:
    """
    Fetches a URL that requires login. Fills the login form automatically.
    Sessions are cached in PLAYWRIGHT_STORAGE_DIR — repeat calls skip the login step.
    Requires: playwright install chromium
    """
    storage_dir = os.path.abspath(settings.PLAYWRIGHT_STORAGE_DIR)
    os.makedirs(storage_dir, exist_ok=True)

    # Cache session by hostname so the same site reuses credentials
    from urllib.parse import urlparse
    hostname = urlparse(login_url).netloc.replace('.', '_')
    session_file = os.path.join(storage_dir, f"{hostname}.json")

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        return {
            "error": (
                "playwright not installed. "
                "Run: pip install playwright && playwright install chromium"
            )
        }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            # Restore cached session if available
            ctx = (
                browser.new_context(storage_state=session_file)
                if os.path.exists(session_file)
                else browser.new_context()
            )
            page = ctx.new_page()

            # Try the target URL first — cached session may still be valid
            page.goto(url, wait_until="networkidle", timeout=15000)

            # Detect if we landed on a login page
            current = page.url.lower()
            needs_login = any(k in current for k in ("login", "signin", "sign-in", "auth"))
            if not needs_login:
                needs_login = (urlparse(page.url).netloc == urlparse(login_url).netloc
                               and page.url.rstrip('/') == login_url.rstrip('/'))

            if needs_login:
                page.goto(login_url, wait_until="networkidle", timeout=15000)

                # Try common username/email selectors in order of specificity
                for sel in ['input[type="email"]', 'input[name="username"]',
                             'input[name="email"]', '#username', '#email', '#user']:
                    if page.locator(sel).count() > 0:
                        page.fill(sel, username)
                        break

                # Try common password selectors
                for sel in ['input[type="password"]', 'input[name="password"]',
                             '#password', '#pass']:
                    if page.locator(sel).count() > 0:
                        page.fill(sel, password)
                        break

                page.keyboard.press("Enter")
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except PWTimeout:
                    pass  # Some sites don't fully settle — continue anyway

                # Persist the session cookies for next time
                ctx.storage_state(path=session_file)

                # Now navigate to the actual target URL
                page.goto(url, wait_until="networkidle", timeout=15000)

            content = page.inner_text("body")
            final_url = page.url
            browser.close()

            return {
                "url": final_url,
                "content": content[:8000],
                "truncated": len(content) > 8000,
                "session_cached": os.path.exists(session_file)
            }

    except Exception as e:
        return {"error": str(e)}


# ─── Recommender ─────────────────────────────────────────────────────────────

@register_tool("predict_affinity")
def predict_affinity(item_type: str, metadata: Dict[str, Any], user_id: int) -> Dict[str, Any]:
    """Predicts how much the user will like an item. Uses XGBoost model if trained, else cosine similarity."""
    title = metadata.get("title", "")
    desc = metadata.get("description", "")
    cand_emb = get_embedder().encode(f"{title} {desc}").astype(np.float32)

    # Feature vector: embedding (384) + 3 scalar metadata fields = 387 dims.
    # Must match what train_affinity_model.py produces at training time.
    features = np.hstack([
        cand_emb,
        [
            float(metadata.get("price", 0)),
            float(metadata.get("rating", 0)),
            float(metadata.get("year", 2000))
        ]
    ]).reshape(1, -1)

    model_path = os.path.join(settings.ML_MODELS_DIR, "affinity_model.pkl")
    if os.path.exists(model_path):
        try:
            import joblib
            pipeline = joblib.load(model_path)
            prob = float(pipeline.predict_proba(features)[0][1])
            return {
                "affinity_score": round(prob, 2),
                "confidence": "high" if prob > 0.7 else "medium" if prob > 0.4 else "low",
                "reason": "XGBoost model prediction based on past likes and feedback.",
                "model": "xgboost"
            }
        except Exception as e:
            print(f"[predict_affinity] XGBoost load failed ({e}). Falling back to cosine.")

    # Fallback: cosine similarity against liked items in DB
    db = SessionLocal()
    try:
        liked = db.query(UserLike).filter(
            UserLike.user_id == user_id,
            UserLike.item_type == item_type
        ).all()

        if not liked:
            return {
                "affinity_score": 0.5,
                "confidence": "low",
                "reason": "No past likes yet. Rate items so the system can learn.",
                "model": "no_data"
            }

        similarities = []
        for item in liked:
            item_emb = np.frombuffer(item.embedding, dtype=np.float32)
            norm = np.linalg.norm(cand_emb) * np.linalg.norm(item_emb)
            sim = float(np.dot(cand_emb, item_emb) / norm) if norm > 0 else 0.0
            similarities.append((sim, item.title))

        max_sim, best_match = max(similarities, key=lambda x: x[0])
        return {
            "affinity_score": round(max_sim, 2),
            "confidence": "high" if max_sim > 0.7 else "medium" if max_sim > 0.5 else "low",
            "reason": f"Similar to '{best_match}' which you liked.",
            "model": "cosine_similarity"
        }
    finally:
        db.close()


# ─── Finance Tools ────────────────────────────────────────────────────────────

@register_tool("check_balance")
def check_balance(account_id: str = settings.MONO_ACCOUNT_ID) -> Dict[str, Any]:
    """Returns the current balance of a linked Mono bank account."""
    try:
        resp = httpx.get(
            f"{MONO_BASE}/accounts/{account_id}",
            headers=MONO_HEADERS,
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "balance_ngn": data.get("balance", 0) / 100,
            "currency": "NGN",
            "account_id": account_id
        }
    except httpx.HTTPStatusError as e:
        return {"error": f"Mono API {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


@register_tool("fetch_transactions")
def fetch_transactions(
    account_id: str = settings.MONO_ACCOUNT_ID,
    limit: int = 10
) -> Dict[str, Any]:
    """Fetches recent transactions from a linked Mono bank account."""
    try:
        resp = httpx.get(
            f"{MONO_BASE}/accounts/{account_id}/transactions",
            headers=MONO_HEADERS,
            params={"limit": limit},
            timeout=10
        )
        resp.raise_for_status()
        return {"transactions": resp.json().get("transactions", [])}
    except httpx.HTTPStatusError as e:
        return {"error": f"Mono API {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


@register_tool("draft_transfer")
def draft_transfer(amount: float, recipient: str, description: str) -> Dict[str, Any]:
    """Prepares a transfer for user review. Does NOT move money. Always call before execute_transfer."""
    return {
        "status": "pending_approval",
        "amount_ngn": amount,
        "amount_kobo": int(amount * 100),
        "recipient": recipient,
        "description": description,
        "currency": "NGN",
        "message": "Draft ready. Awaiting user confirmation before execution."
    }


@register_tool("execute_transfer")
def execute_transfer(amount: float, recipient: str, description: str) -> Dict[str, Any]:
    """
    Executes a one-time debit via Mono DirectPay v2 (POST /v2/payments/initiate).
    ONLY call after the user has explicitly approved a draft_transfer.
    recipient: Mono account ID of the source account to debit.
    """
    payload = {
        "amount": int(amount * 100),    # Mono uses kobo
        "type": "onetime-debit",        # Required by Mono DirectPay v2
        "method": "account",            # Debit via linked Mono account
        "account": recipient,
        "description": description,
        "reference": f"ogun_{int(time.time())}"  # Idempotency key
    }
    try:
        resp = httpx.post(
            f"{MONO_BASE}/v2/payments/initiate",
            headers=MONO_HEADERS,
            json=payload,
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "status": "completed",
            "amount_ngn": amount,
            "recipient": recipient,
            "reference": data.get("reference", payload["reference"]),
            "mono_response": data
        }
    except httpx.HTTPStatusError as e:
        return {"error": f"Mono DirectPay {e.response.status_code}: {e.response.text}"}
    except httpx.TimeoutException:
        return {
            "error": (
                "Mono API timed out. The transfer may or may not have processed. "
                "Check your balance before retrying."
            )
        }
    except Exception as e:
        return {"error": str(e)}


# ─── Document RAG Tools ───────────────────────────────────────────────────────

def _chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> List[str]:
    """
    Splits document text into overlapping chunks, breaking at paragraph boundaries.
    chunk_size: target chars per chunk (~200 tokens for LLaMA). overlap: chars of shared context.
    """
    # Prefer paragraph breaks; fall back to line breaks for dense text
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    if len(paragraphs) <= 1:
        paragraphs = [p.strip() for p in text.split('\n') if p.strip()]

    chunks: List[str] = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 <= chunk_size:
            current += para + "\n\n"
        else:
            if current.strip():
                chunks.append(current.strip())
            if len(para) > chunk_size:
                # Very long paragraph — split by words with overlap
                words = para.split()
                word_buf = ""
                for word in words:
                    if len(word_buf) + len(word) + 1 <= chunk_size:
                        word_buf += word + " "
                    else:
                        if word_buf.strip():
                            chunks.append(word_buf.strip())
                        # Start next chunk with overlap
                        tail_words = word_buf.split()[-max(1, overlap // 6):]
                        word_buf = " ".join(tail_words) + " " + word + " "
                if word_buf.strip():
                    current = word_buf
                else:
                    current = ""
            else:
                current = para + "\n\n"

    if current.strip():
        chunks.append(current.strip())

    # Filter out noise (very short fragments that aren't meaningful)
    return [c for c in chunks if len(c.strip()) > 40]


def _process_pdf(file_path: str, user_id: int) -> Dict[str, Any]:
    """
    Core PDF processing logic used by both the upload_pdf tool and the REST upload endpoint.
    Extracts text with PyMuPDF, chunks it, embeds each chunk, writes to DB.
    Returns the document_id on success.
    """
    try:
        import pymupdf
    except ImportError:
        return {"error": "pymupdf not installed. Run: pip install pymupdf"}

    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        return {"error": f"File not found: {abs_path}"}
    if not abs_path.lower().endswith('.pdf'):
        return {"error": "Only PDF files are currently supported."}

    filename = os.path.basename(abs_path)

    try:
        doc = pymupdf.open(abs_path)
        total_pages = doc.page_count

        # Extract text page by page; keep page number for citations
        pages_text: List[tuple] = []  # (page_num_1based, text)
        for page_num in range(total_pages):
            page = doc.load_page(page_num)
            text = page.get_text("text")
            if text.strip():
                pages_text.append((page_num + 1, text))

        doc.close()
    except Exception as e:
        return {"error": f"PyMuPDF failed to open PDF: {e}"}

    if not pages_text:
        return {
            "error": (
                "No extractable text found. The PDF may be a scanned image. "
                "OCR support requires tesseract — install it separately."
            )
        }

    db = SessionLocal()
    try:
        document = Document(
            user_id=user_id,
            filename=filename,
            file_path=abs_path,
            total_pages=total_pages
        )
        db.add(document)
        db.commit()
        db.refresh(document)

        embedder = get_embedder()
        chunk_index = 0

        for page_num, page_text in pages_text:
            chunks = _chunk_text(page_text, chunk_size=800, overlap=100)
            for chunk in chunks:
                emb = embedder.encode(chunk).astype(np.float32)
                db.add(DocumentChunk(
                    document_id=document.id,
                    chunk_index=chunk_index,
                    page_number=page_num,
                    text=chunk,
                    embedding=emb.tobytes()
                ))
                chunk_index += 1

        document.total_chunks = chunk_index
        db.commit()

        return {
            "document_id": document.id,
            "filename": filename,
            "total_pages": total_pages,
            "total_chunks": chunk_index,
            "message": (
                f"PDF ingested. Use ask_document(document_id={document.id}, question='...') "
                "to query it with grounded citations."
            )
        }
    except Exception as e:
        db.rollback()
        return {"error": f"DB write failed: {e}"}
    finally:
        db.close()


@register_tool("upload_pdf")
def upload_pdf(file_path: str, user_id: int) -> Dict[str, Any]:
    """
    Ingests a PDF file for grounded document Q&A. Chunks the text and stores embeddings.
    file_path: filename within UPLOADS_DIR, or absolute path. Returns document_id for ask_document.
    """
    uploads_dir = os.path.abspath(settings.UPLOADS_DIR)

    # Resolve relative paths against the uploads directory
    if not os.path.isabs(file_path):
        resolved = os.path.join(uploads_dir, file_path)
        if os.path.exists(resolved):
            file_path = resolved
        else:
            return {
                "error": (
                    f"File '{file_path}' not found in {uploads_dir}/. "
                    "Upload it via POST /api/v1/chat/upload or copy it there manually."
                )
            }

    return _process_pdf(file_path, user_id)


@register_tool("ask_document")
def ask_document(document_id: int, question: str, user_id: int) -> Dict[str, Any]:
    """
    Answers a question using ONLY content from an uploaded document (grounded RAG).
    Use after upload_pdf. Always cite the page number in your answer.
    document_id: from upload_pdf response. question: what you want to know.
    """
    db = SessionLocal()
    try:
        document = db.query(Document).filter(
            Document.id == document_id,
            Document.user_id == user_id
        ).first()

        if not document:
            # Use STOP_AND_REPORT so the agent prompt can match this signal
            # and return immediately without attempting workarounds.
            return {
                "STOP_AND_REPORT": True,
                "error": (
                    f"Document {document_id} does not exist. "
                    "Do not search the web. Do not try to upload anything. "
                    "Tell the user: 'Document {document_id} was not found. "
                    "Please upload a PDF first using the upload endpoint, "
                    "then use the returned document_id.'"
                )
            }

        chunks = db.query(DocumentChunk).filter(
            DocumentChunk.document_id == document_id
        ).all()

        if not chunks:
            return {
                "STOP_AND_REPORT": True,
                "error": f"Document {document_id} exists but has no indexed content. Re-upload the PDF."
            }

        q_emb = get_embedder().encode(question).astype(np.float32)
        scored: List[tuple] = []
        for chunk in chunks:
            c_emb = np.frombuffer(chunk.embedding, dtype=np.float32)
            norm = np.linalg.norm(q_emb) * np.linalg.norm(c_emb)
            sim = float(np.dot(q_emb, c_emb) / norm) if norm > 0 else 0.0
            scored.append((sim, chunk))

        top = sorted(scored, key=lambda x: x[0], reverse=True)[:5]
        relevant = [
            {
                "page": c.page_number,
                "chunk_index": c.chunk_index,
                "similarity": round(sim, 3),
                "text": c.text
            }
            for sim, c in top
            if sim > 0.1
        ]

        if not relevant:
            return {
                "document": document.filename,
                "question": question,
                "error": (
                    "No relevant content found for this question. "
                    "Try rephrasing or check whether the topic is covered in this document."
                )
            }

        return {
            "document": document.filename,
            "question": question,
            "relevant_chunks": relevant,
            "instruction": (
                "Answer ONLY using the text in relevant_chunks above. "
                "For every claim, cite the page number in parentheses e.g. (p.3). "
                "If the chunks don't contain enough information to answer fully, say so explicitly."
            )
        }
    finally:
        db.close()

# ─── Fitness: Private Helpers ─────────────────────────────────────────────────

def _build_injury_features(user_id: int):
    """
    8-feature vector over the past 7 days. Must match train_injury_model.py exactly.
    Returns (features_list, summary_dict) or (None, summary_dict) if data is insufficient.
    """
    db = SessionLocal()
    try:
        today = dt.date.today()
        week_ago = today - dt.timedelta(days=7)

        workouts = db.query(WorkoutLog).filter(
            WorkoutLog.user_id == user_id,
            WorkoutLog.date >= week_ago
        ).all()

        statuses = db.query(PhysicalStatus).filter(
            PhysicalStatus.user_id == user_id,
            PhysicalStatus.date >= week_ago
        ).all()

        if not workouts and not statuses:
            return None, {"days_logged": 0}

        training_days = len(set(w.date for w in workouts))
        total_volume = sum(w.sets * w.reps * w.load_kg for w in workouts)
        rpe_values = [w.rpe for w in workouts if w.rpe is not None]
        avg_rpe = float(np.mean(rpe_values)) if rpe_values else 5.0
        max_rpe = float(max(rpe_values)) if rpe_values else 5.0
        avg_sleep = float(np.mean([s.sleep_hours for s in statuses])) if statuses else 7.0
        pain_values = [s.pain_level for s in statuses]
        avg_pain = float(np.mean(pain_values)) if pain_values else 0.0
        max_pain = float(max(pain_values)) if pain_values else 0.0
        low_sleep_days = float(sum(1 for s in statuses if s.sleep_hours < 6.0))

        features = [training_days, total_volume, avg_rpe, max_rpe,
                    avg_sleep, avg_pain, max_pain, low_sleep_days]
        summary = {
            "training_days_last_7": training_days,
            "total_volume_kg": round(total_volume, 1),
            "avg_rpe": round(avg_rpe, 1),
            "avg_sleep_hours": round(avg_sleep, 1),
            "avg_pain_level": round(avg_pain, 1),
            "max_pain_level": round(max_pain, 1),
            "status_days_logged": len(statuses)
        }
        return features, summary
    finally:
        db.close()


def _heuristic_injury_risk(summary: dict) -> float:
    """Evidence-based rule engine used before the XGBoost model has enough data."""
    risk = 0.0
    if summary.get("training_days_last_7", 0) >= 6:
        risk += 0.30
    elif summary.get("training_days_last_7", 0) >= 5:
        risk += 0.10
    avg_rpe = summary.get("avg_rpe", 0)
    if avg_rpe >= 8.5:
        risk += 0.25
    elif avg_rpe >= 7.0:
        risk += 0.10
    avg_sleep = summary.get("avg_sleep_hours", 8)
    if avg_sleep < 6.0:
        risk += 0.25
    elif avg_sleep < 7.0:
        risk += 0.10
    avg_pain = summary.get("avg_pain_level", 0)
    if avg_pain >= 5.0:
        risk += 0.30
    elif avg_pain >= 3.0:
        risk += 0.15
    return min(risk, 1.0)


def _get_injury_recommendation(risk: float) -> str:
    if risk > 0.7:
        return (
            "High risk. Implement a deload week: reduce volume 40–50%, "
            "cap intensity at RPE 7, prioritise 8h sleep and 1.6–2g protein/kg."
        )
    elif risk > 0.4:
        return "Moderate risk. Drop today's session by one RPE point and log any soreness."
    return "Training load looks sustainable. Maintain recovery habits."


# ─── Fitness Tools ────────────────────────────────────────────────────────────

@register_tool("log_nutrition")
def log_nutrition(food_name: str, portion_grams: float, user_id: int) -> Dict[str, Any]:
    """
    Logs a food item's macros from USDA FoodData Central. Use generic names like
    'chicken breast cooked', 'white rice cooked', or 'oats dry' for best matches.
    """
    def _usda_search(data_types: Optional[str] = None) -> list:
        params: Dict[str, Any] = {
            "query": food_name,
            "pageSize": 5,
            "api_key": settings.USDA_API_KEY
        }
        if data_types:
            params["dataType"] = data_types
        resp = httpx.get(f"{settings.USDA_BASE_URL}/foods/search", params=params, timeout=10)
        resp.raise_for_status()
        return resp.json().get("foods", [])

    try:
        # Foundation Foods and SR Legacy are standardised per 100g — prefer these
        foods = _usda_search("Foundation Foods,SR Legacy")
        if not foods:
            foods = _usda_search()  # Fall back to branded foods
        if not foods:
            return {
                "error": (
                    f"No USDA data found for '{food_name}'. "
                    "Try a more generic description, e.g. 'egg whole cooked', 'oats dry'."
                )
            }

        food = foods[0]
        nutrients_by_id = {
            n["nutrientId"]: n.get("value", 0)
            for n in food.get("foodNutrients", [])
        }

        base_size_g = food.get("servingSize", 100)
        serving_unit = food.get("servingSizeUnit", "g").lower()
        if serving_unit not in ("g", "gram", "grams"):
            base_size_g = 100  # Fall back to 100g if unit is unexpected
        scale = portion_grams / base_size_g

        calories = round(nutrients_by_id.get(USDA_NUTRIENT_IDS["calories"], 0) * scale, 1)
        protein  = round(nutrients_by_id.get(USDA_NUTRIENT_IDS["protein"],  0) * scale, 1)
        carbs    = round(nutrients_by_id.get(USDA_NUTRIENT_IDS["carbs"],    0) * scale, 1)
        fat      = round(nutrients_by_id.get(USDA_NUTRIENT_IDS["fat"],      0) * scale, 1)
        fiber    = round(nutrients_by_id.get(USDA_NUTRIENT_IDS["fiber"],    0) * scale, 1)

    except httpx.HTTPStatusError as e:
        return {"error": f"USDA API {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": f"Nutrition lookup failed: {e}"}

    db = SessionLocal()
    try:
        db.add(DailyNutrition(
            user_id=user_id,
            date=dt.date.today(),
            food_name=food.get("description", food_name),
            portion_grams=portion_grams,
            calories=calories, protein_grams=protein,
            carb_grams=carbs, fat_grams=fat, fiber_grams=fiber
        ))
        db.commit()
        return {
            "logged": food.get("description", food_name),
            "portion_grams": portion_grams,
            "calories": calories, "protein_grams": protein,
            "carb_grams": carbs, "fat_grams": fat, "fiber_grams": fiber,
            "source": "USDA FoodData Central"
        }
    except Exception as e:
        db.rollback()
        return {"error": f"DB write failed: {e}"}
    finally:
        db.close()


@register_tool("fetch_macros")
def fetch_macros(user_id: int, date_str: Optional[str] = None) -> Dict[str, Any]:
    """Returns total macronutrient intake for a given date (defaults to today). Format: YYYY-MM-DD."""
    if date_str:
        try:
            target_date = dt.date.fromisoformat(date_str)
        except ValueError:
            return {"error": "Invalid date. Use YYYY-MM-DD, e.g. '2025-03-15'."}
    else:
        target_date = dt.date.today()

    db = SessionLocal()
    try:
        entries = db.query(DailyNutrition).filter(
            DailyNutrition.user_id == user_id,
            DailyNutrition.date == target_date
        ).all()

        if not entries:
            return {"date": str(target_date), "message": "No food logged for this date.", "totals": {}}

        totals = {
            "calories":      round(sum(e.calories      for e in entries), 1),
            "protein_grams": round(sum(e.protein_grams for e in entries), 1),
            "carb_grams":    round(sum(e.carb_grams    for e in entries), 1),
            "fat_grams":     round(sum(e.fat_grams     for e in entries), 1),
            "fiber_grams":   round(sum(e.fiber_grams   for e in entries), 1),
        }
        items = [{"food": e.food_name, "portion_grams": e.portion_grams, "calories": e.calories} for e in entries]
        return {"date": str(target_date), "totals": totals, "items": items}
    finally:
        db.close()


@register_tool("log_workout")
def log_workout(
    exercise_name: str, sets: int, reps: int, load_kg: float,
    rpe: int, user_id: int, notes: Optional[str] = None
) -> Dict[str, Any]:
    """
    Logs a completed exercise set. Use load_kg=0 for bodyweight movements.
    rpe: Rate of Perceived Exertion 1–10 (6=moderate, 8=hard, 10=max).
    """
    if sets <= 0 or reps <= 0:
        return {"error": "sets and reps must be > 0."}
    if load_kg < 0:
        return {"error": "load_kg cannot be negative. Use 0 for bodyweight."}
    if not 1 <= rpe <= 10:
        return {"error": "rpe must be 1–10."}

    db = SessionLocal()
    try:
        db.add(WorkoutLog(
            user_id=user_id, date=dt.date.today(),
            exercise_name=exercise_name, sets=sets,
            reps=reps, load_kg=load_kg, rpe=rpe, notes=notes
        ))
        db.commit()
        volume = sets * reps * load_kg
        return {
            "logged": exercise_name, "sets": sets, "reps": reps,
            "load_kg": load_kg, "rpe": rpe,
            "total_volume_kg": round(volume, 1),
            "message": f"Logged. Total volume this movement today: {round(volume, 1)} kg."
        }
    except Exception as e:
        db.rollback()
        return {"error": f"DB write failed: {e}"}
    finally:
        db.close()


@register_tool("log_physical_status")
def log_physical_status(
    pain_level: int, sleep_hours: float, user_id: int,
    injury_site: Optional[str] = None,
    energy_level: Optional[int] = None,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """
    Logs today's physical status. This data trains the injury prediction model.
    pain_level: 0 (none) to 10 (severe). sleep_hours: hours slept last night.
    """
    if not 0 <= pain_level <= 10:
        return {"error": "pain_level must be 0–10."}
    if not 0 < sleep_hours <= 24:
        return {"error": "sleep_hours must be between 0 and 24."}
    if energy_level is not None and not 1 <= energy_level <= 10:
        return {"error": "energy_level must be 1–10."}

    db = SessionLocal()
    try:
        db.add(PhysicalStatus(
            user_id=user_id, date=dt.date.today(),
            pain_level=pain_level, injury_site=injury_site,
            sleep_hours=sleep_hours, energy_level=energy_level, notes=notes
        ))
        db.commit()
        warning = ""
        if pain_level >= 7:
            warning = " ⚠️ High pain — consider rest and consult a professional if it persists."
        elif pain_level >= 4:
            warning = " Consider reducing today's intensity."
        if sleep_hours < 6:
            warning += " 🔴 Sub-6h sleep significantly elevates injury risk."
        return {
            "logged": True, "pain_level": pain_level,
            "sleep_hours": sleep_hours, "energy_level": energy_level,
            "message": f"Physical status logged.{warning}"
        }
    except Exception as e:
        db.rollback()
        return {"error": f"DB write failed: {e}"}
    finally:
        db.close()

@register_tool("adjust_program")
def adjust_program(injury_site: str, current_exercise: str) -> Dict[str, Any]:
    """
    Finds safe exercise alternatives for an injured body part.
    Alternatives are constrained to barbell-only home gym equipment
    (bench, barbell, cement plates — no rack, cables, or machines).
    injury_site examples: 'shoulder', 'knee', 'lower back', 'wrist', 'elbow'.
    """
    # Each entry maps an injury to movements that avoid loading that structure.
    # All alternatives are drawable from: Zercher squat, barbell split squat,
    # Romanian deadlift, conventional deadlift, bench press, overhead press,
    # barbell curl, single-arm behind-neck tricep extension.
    safe_search_map = {
        "shoulder": [
            # Shoulder injured → all lower body, no pressing
            "romanian deadlift",
            "barbell deadlift",
            "barbell lunge",        # wger approximates split squat
            "zercher squat"
        ],
        "knee": [
            # Knee injured → hip hinges + upper body, no knee-dominant squat patterns
            "romanian deadlift",
            "bench press",
            "overhead press",
            "barbell curl"
        ],
        "back": [
            # Lower back → upper body only, avoid spinal loading
            "bench press",
            "overhead press",
            "barbell curl"
        ],
        "wrist": [
            # Wrist injured → movements where wrist is neutral or not loaded
            # Zercher uses the crook of the elbows so wrist-friendly
            "romanian deadlift",
            "barbell deadlift",
            "zercher squat"
        ],
        "elbow": [
            # Elbow injured → no curl or tricep extension, lower body focus
            "romanian deadlift",
            "barbell deadlift",
            "barbell lunge",
            "zercher squat"
        ],
        "hip": [
            # Hip injured → upper body + exercises with minimal hip load
            "bench press",
            "overhead press",
            "barbell curl"
        ],
        "ankle": [
            # Ankle injured → seated/lying upper body + hip hinge (minimal ankle stress)
            "bench press",
            "overhead press",
            "romanian deadlift",
            "barbell curl"
        ],
    }

    injury_lower = injury_site.lower()
    search_terms = None
    for keyword, terms in safe_search_map.items():
        if keyword in injury_lower:
            search_terms = terms
            break

    # If injury site not in map, default to upper body only (conservative)
    if not search_terms:
        search_terms = ["bench press", "barbell curl", "romanian deadlift"]

    alternatives: List[str] = []

    # Query wger for exercise descriptions and cues — useful context even if
    # names differ slightly from what we call them
    for term in search_terms[:3]:
        try:
            resp = httpx.get(
                f"{settings.WGER_BASE_URL}/exercise/search/",
                params={"term": term, "language": "english", "format": "json"},
                timeout=8
            )
            if resp.status_code == 200:
                for suggestion in resp.json().get("suggestions", [])[:2]:
                    name = suggestion.get("value", "")
                    if name and name not in alternatives:
                        alternatives.append(name)
        except Exception:
            pass

    # Fallback: use the actual exercise names from Israel's available list.
    # These are always valid regardless of wger availability.
    if not alternatives:
        alternatives = search_terms

    return {
        "injury_site": injury_site,
        "replaced_exercise": current_exercise,
        "alternatives": alternatives[:6],
        "equipment_constraint": "Barbell + bench only. No rack, cables, or machines.",
        "source": "wger Exercise Database (with equipment constraints applied)",
        "note": (
            f"All alternatives avoid loading {injury_site} and are executable "
            "with a barbell and bench. "
            "For the shoulder specifically: stick to lower body until pain_level < 3. "
            "Consult a physio for persistent shoulder issues."
        )
    }


@register_tool("predict_injury_risk")
def predict_injury_risk(user_id: int) -> Dict[str, Any]:
    """Predicts injury risk from last 7 days of training and recovery. Uses XGBoost if trained, else heuristics."""
    features, summary = _build_injury_features(user_id)

    if features is None:
        return {
            "risk": "unknown",
            "message": "Log at least a few workouts and physical status entries, then call again.",
            "days_logged": summary.get("days_logged", 0)
        }

    model_path = os.path.join(settings.ML_MODELS_DIR, "injury_model.pkl")
    if os.path.exists(model_path):
        try:
            import joblib
            pipeline = joblib.load(model_path)
            prob = float(pipeline.predict_proba([features])[0][1])
            return {
                "risk_probability": round(prob, 2),
                "risk": "high" if prob > 0.7 else "moderate" if prob > 0.4 else "low",
                "recommendation": _get_injury_recommendation(prob),
                "model": "xgboost",
                "training_summary": summary
            }
        except Exception as e:
            print(f"[predict_injury_risk] XGBoost failed ({e}). Using heuristic.")

    risk_score = _heuristic_injury_risk(summary)
    return {
        "risk_probability": round(risk_score, 2),
        "risk": "high" if risk_score > 0.7 else "moderate" if risk_score > 0.4 else "low",
        "recommendation": _get_injury_recommendation(risk_score),
        "model": "heuristic",
        "training_summary": summary,
        "note": "Run `python -m ml.train_injury_model` after 30+ days of logs to activate XGBoost."
    }


# ─── Orchestration ────────────────────────────────────────────────────────────

@register_tool("delegate_to")
def delegate_to(specialist_name: str, instruction: str, user_id: int) -> Dict[str, Any]:
    """
    Delegates a sub-task to a specialist agent.
    Available: 'DeveloperAgent', 'LifestyleAgent', 'CyberSecurityAgent',
    'ResearchAgent', 'FinanceAgent', 'FitnessAgent'.
    """
    from .base import OgunAIAgent
    from .configs import SPECIALIST_CONFIGS

    if specialist_name not in SPECIALIST_CONFIGS:
        return {
            "error": (
                f"Unknown specialist '{specialist_name}'. "
                f"Available: {list(SPECIALIST_CONFIGS.keys())}"
            )
        }

    config = SPECIALIST_CONFIGS[specialist_name]
    specialist = OgunAIAgent(role_config=config, user_id=user_id)
    result = specialist.run(instruction)
    return {"specialist_result": result}