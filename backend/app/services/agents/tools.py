# backend/app/services/agents/tools.py
import asyncio
import inspect
import json
import os
import re
import json
import re
import shlex
import signal
import types as _types
import typing
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
from .events import emit_event
from .guards import (
    get_turn_context, create_pending_action, is_cancelled,
    is_sensitive_path, command_touches_secrets, build_specialist_task
)
from .search_providers import search as _search_web
from .fitness_logic import (
    injury_features, window_bounds, heuristic_injury_risk, combine_risk, risk_label,
    model_is_trusted, injury_model_paths,
)
from .rec_logic import (
    normalize_item_type, item_text, score_against_history, affinity_model_paths, affinity_model_is_trusted,
)
from ...models import Episode as _Episode
from ...models import (
    UserLike, DailyNutrition, WorkoutLog, PhysicalStatus,
    Document, DocumentChunk, LearningProgress, ConversationMemory
)


# ─── Tool Registry ────────────────────────────────────────────────────────────

_TOOL_REGISTRY: Dict[str, Callable] = {}


def register_tool(name: str):
    def decorator(func):
        _TOOL_REGISTRY[name] = func
        return func
    return decorator


_UnionType = getattr(_types, "UnionType", None)   # X | None syntax (Python 3.10+)


def _json_schema_for(annotation) -> Dict[str, Any]:
    """
    Maps a Python annotation to a JSON-schema fragment.
    The old check (`py_type in (Dict, dict)`) never matched Dict[str, Any] or
    Optional[int], so those were advertised to the model as plain strings and
    the model then sent strings (a metadata *string* where the tool calls
    metadata.get(...), "7" where it compares energy_level <= 10).
    """
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is typing.Union or (_UnionType is not None and origin is _UnionType):
        non_none = [a for a in args if a is not type(None)]
        return _json_schema_for(non_none[0]) if len(non_none) == 1 else {"type": "string"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation in (int, float):
        return {"type": "number"}
    if annotation is dict or origin is dict:
        return {"type": "object"}
    if annotation is list or origin is list:
        return {"type": "array", "items": _json_schema_for(args[0]) if args else {"type": "object"}}
    return {"type": "string"}


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
            properties[param_name] = _json_schema_for(param.annotation)
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

def generate_conversation_title(user_message: str, agent_response: str) -> str:
    """
    Generates a short, descriptive conversation title from the first exchange.
    Uses a separate, tool-free LLM call — cheap and fast since there's no
    tool schema overhead and the prompt is tiny. Falls back to a truncated
    user message if the LLM call fails for any reason, so a title is always
    produced even if this optional step breaks.
    """
    from ..llm_adapter import llm_adapter

    prompt = (
        "Generate a short title (4-6 words max) for this conversation. "
        "No quotes, no punctuation at the end, no prefix like 'Title:'. "
        "Just the title text itself.\n\n"
        f"User: {user_message[:300]}\n"
        f"Assistant: {agent_response[:300]}"
    )

    try:
        response = llm_adapter.invoke_with_tools(
            messages=[{"role": "user", "content": prompt}],
            tools=[],              # no tools — forces a plain text answer
            temperature=0.3,       # low temperature — titles should be consistent, not creative
            tool_choice="auto"
        )
        title = response.get("text", "").strip().strip('"').strip("'")
        if title and len(title) <= 80:
            return title
    except Exception as e:
        print(f"[Title Generation] Failed: {e}")

    # Fallback — the old behaviour, only used if the LLM call above fails
    return user_message[:50]

# ─── Cross-Conversation Memory ─────────────────────────────────────────────────

def store_conversation_memory(user_id: int, conversation_id: int, user_message: str, agent_response: str) -> None:
    """
    Embeds and stores one completed exchange for future recall via recall_memory.
    Called automatically by chat.py after every turn — never called by the LLM
    itself. Store everything; recall_memory decides what's relevant later.
    """
    db = SessionLocal()
    try:
        combined = f"User: {user_message}\nOgun: {agent_response}"
        emb = get_embedder().encode(combined[:2000]).astype(np.float32)

        db.add(ConversationMemory(
            user_id=user_id,
            conversation_id=conversation_id,
            summary=combined[:1500],
            embedding=emb.tobytes()
        ))
        db.commit()
    except Exception as e:
        print(f"[Memory] Failed to store conversation memory: {e}")
        db.rollback()
    finally:
        db.close()


@register_tool("recall_memory")
def recall_memory(query: str, user_id: int) -> Dict[str, Any]:
    """
    Searches every past conversation (across all sessions, not just this one)
    for exchanges related to the query. Use when the user references something
    from an earlier conversation not visible in the current context —
    'do you remember...', 'what did we discuss last week', 'have I mentioned...'.
    """
    db = SessionLocal()
    try:
        entries = db.query(ConversationMemory).filter(
            ConversationMemory.user_id == user_id
        ).all()

        if not entries:
            return {"found": False, "message": "No past conversation history has been recorded yet."}

        q_emb = get_embedder().encode(query).astype(np.float32)
        scored = []
        for entry in entries:
            e_emb = np.frombuffer(entry.embedding, dtype=np.float32)
            norm = np.linalg.norm(q_emb) * np.linalg.norm(e_emb)
            sim = float(np.dot(q_emb, e_emb) / norm) if norm > 0 else 0.0
            scored.append((sim, entry))

        # A note on scale: this is a plain Python loop over every stored
        # exchange, same pattern as ask_document. Fine for years of
        # personal-scale use (thousands of rows). If this ever grows past
        # tens of thousands of entries, sqlite-vec would speed the scan up —
        # not needed at anything close to current scale.
        top = sorted(scored, key=lambda x: x[0], reverse=True)[:5]
        relevant = [
            {
                "date": entry.created_at.strftime("%Y-%m-%d"),
                "similarity": round(sim, 3),
                "exchange": entry.summary[:400],
            }
            for sim, entry in top
            if sim > 0.25
        ]

        if not relevant:
            return {"found": False, "message": "Nothing in past conversations closely matches this."}

        return {
            "found": True,
            "matches": relevant,
            "instruction": (
                "These are real excerpts from past conversations with this user. "
                "Answer naturally, e.g. 'Yes, on [date] we discussed...'. "
                "Do not add details beyond what's shown here."
            )
        }
    finally:
        db.close()

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
    # Tries SearXNG, Tavily and DuckDuckGo in turn (see search_providers.py),
    # so one blocked or exhausted back-end no longer means "no search".
    return _search_web(query, max_results=5)

@register_tool("read_file")
def read_file(file_path: str) -> Dict[str, Any]:
    """Reads the contents of a local file. Use absolute paths or paths relative to workspace."""
    try:
        # Try as-is first, then relative to workspace
        if not os.path.isabs(file_path):
            workspace_path = os.path.join(settings.WORKSPACE_DIR, file_path)
            if os.path.exists(workspace_path):
                    file_path = workspace_path
        # Agents must never read credentials: an injected instruction could
        # otherwise read .env and smuggle the keys out inside a search query.
        if is_sensitive_path(file_path):
            return {"error": "Access denied: that file may contain credentials or private data and cannot be read by agents."}
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        return {"content": content[:8000], "truncated": len(content) > 8000, "path": file_path}
    except Exception as e:
        return {"error": str(e)}

# ─── Tutor Tools ──────────────────────────────────────────────────────────────
# All four call the existing web_search() function above — same search chain
# (search_providers.py), no duplicate search logic, no second provider to configure.

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

def _kill_process_tree(proc: "subprocess.Popen") -> None:
    """Kill the shell AND anything it started (a plain proc.kill() leaves children running)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=5)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _run_shell_cancellable(command: str, cwd: str, timeout: float):
    """
    Like subprocess.run(..., shell=True, capture_output=True, timeout=...), but
    it wakes every 0.25s to check whether the user pressed Stop.
    Returns (returncode, stdout, stderr, aborted) where aborted is None,
    "timeout" or "cancelled".
    """
    kwargs: Dict[str, Any] = {}
    if os.name != "nt":
        kwargs["start_new_session"] = True      # own process group, so the whole tree can be killed
    proc = subprocess.Popen(
        command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=cwd, **kwargs,
    )
    deadline = time.monotonic() + timeout
    while True:
        try:
            stdout, stderr = proc.communicate(timeout=0.25)
            return proc.returncode, stdout, stderr, None
        except subprocess.TimeoutExpired:
            reason = "cancelled" if is_cancelled() else ("timeout" if time.monotonic() >= deadline else None)
            if reason is None:
                continue
            _kill_process_tree(proc)
            try:
                proc.communicate(timeout=2)
            except Exception:
                pass
            return None, "", "", reason


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
    # Safety: keep the shell away from credentials (.env, databases, SSH keys,
    # saved browser sessions). A speed bump against the lazy injection payload
    # ("type ..\\.env"), not a sandbox; the approval gate in guards.py is the
    # real protection once a request has touched external content.
    if command_touches_secrets(command):
        return {"error": "Blocked for safety — the command references a credentials or secrets file."}

    # Safety: block dangerous root commands
    try:
        parts = shlex.split(command)
        base_cmd = os.path.basename(parts[0]) if parts else ""
        if base_cmd in _BLOCKED_COMMANDS:
            return {"error": f"Command '{base_cmd}' is not permitted."}
    except ValueError:
        pass  # shlex can't parse it — let subprocess handle the error

    try:
        # shell=True is needed for pipes, && and redirects. cwd is always the
        # workspace, so relative paths stay sandboxed. Polls for the Stop button.
        returncode, stdout, stderr, aborted = _run_shell_cancellable(command, workspace, timeout=30)
        if aborted == "timeout":
            return {"error": "Command timed out (30s limit). Use background processes for long tasks."}
        if aborted == "cancelled":
            return {"error": "Command stopped by the user."}
        return {
            "returncode": returncode,
            "stdout": stdout[:5000],
            "stderr": stderr[:2000],
            "success": returncode == 0,
            "cwd": workspace
        }
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

def _as_candidate(meta: Any) -> Dict[str, Any]:
    """Tolerate the model sending a JSON string or a bare title instead of an object."""
    if isinstance(meta, str):
        try:
            parsed = json.loads(meta)
            meta = parsed if isinstance(parsed, dict) else {"title": meta}
        except ValueError:
            meta = {"title": meta}
    return meta if isinstance(meta, dict) else {}


def _is_false(v: Any) -> bool:
    return v is False or str(v).strip().lower() in ("false", "no", "0", "dislike", "disliked")


def _affinity_history(db, user_id: int, wanted_type: str):
    """(liked, disliked) as lists of (title, embedding) for this user and item type."""
    liked = []
    for row in db.query(UserLike).filter(UserLike.user_id == user_id).all():
        if normalize_item_type(row.item_type) == wanted_type and row.embedding is not None:
            liked.append((row.title, np.frombuffer(row.embedding, dtype=np.float32)))
    # Rejections live in the audit log: every record_preference call is stored as an
    # Episode with its arguments (including the injected user_id).
    rejected = []
    for ep in db.query(_Episode).filter(_Episode.action == "record_preference").all():
        m = ep.meta_data or {}
        if m.get("user_id") == user_id and _is_false(m.get("liked")) \
                and normalize_item_type(m.get("item_type")) == wanted_type and item_text(m):
            rejected.append((m.get("title", ""), item_text(m)))
    disliked = []
    if rejected:
        embs = get_embedder().encode([t for _, t in rejected])
        disliked = [(title, np.asarray(e, dtype=np.float32)) for (title, _), e in zip(rejected, embs)]
    return liked, disliked


def _trusted_affinity_model(user_id: int, wanted_type: str):
    pkl, meta_path = affinity_model_paths(settings.ML_MODELS_DIR, user_id)
    if not (os.path.exists(pkl) and os.path.exists(meta_path)):
        return None
    try:
        with open(meta_path) as f:
            meta = json.load(f)
        if not affinity_model_is_trusted(meta, wanted_type):
            return None
        import joblib
        return joblib.load(pkl)
    except Exception as e:
        print(f"[affinity] model unusable ({e}); using similarity.")
        return None


def _score_items(item_type: str, metas: List[Dict[str, Any]], user_id: int):
    wanted = normalize_item_type(item_type)
    embs = np.asarray(get_embedder().encode([item_text(m) for m in metas]), dtype=np.float32)
    model = _trusted_affinity_model(user_id, wanted)
    db = SessionLocal()
    try:
        liked, disliked = _affinity_history(db, user_id, wanted)
    finally:
        db.close()
    out = []
    for meta, emb in zip(metas, embs):
        if model is not None:
            prob = float(model.predict_proba(emb.reshape(1, -1))[0][1])
            res = {"affinity_score": round(prob, 2), "confidence": "high" if prob > 0.7 else "medium" if prob > 0.4 else "low",
                   "reason": "Trained model, built from your likes and rejections.", "model": "xgboost"}
        else:
            res = score_against_history(emb, liked, disliked)
        res["title"] = meta.get("title", "")
        out.append(res)
    return out, len(liked), len(disliked)


@register_tool("predict_affinity")
def predict_affinity(item_type: str, metadata: Dict[str, Any], user_id: int) -> Dict[str, Any]:
    """Scores ONE item (0 to 1) from the user's past likes and rejections. Use score_candidates for several items."""
    meta = _as_candidate(metadata)
    if not item_text(meta):
        return {"error": "metadata needs at least a title (and ideally a description)."}
    results, n_liked, n_disliked = _score_items(item_type, [meta], user_id)
    return {**results[0], "based_on": {"liked": n_liked, "rejected": n_disliked}}


@register_tool("score_candidates")
def score_candidates(item_type: str, candidates: List[Dict[str, Any]], user_id: int) -> Dict[str, Any]:
    """Scores several candidate items at once (each with title and description) and returns them ranked best first."""
    if not isinstance(candidates, list) or not candidates:
        return {"error": "candidates must be a non-empty list of {title, description} objects."}
    metas = [m for m in (_as_candidate(c) for c in candidates[:10]) if item_text(m)]
    if not metas:
        return {"error": "Each candidate needs at least a title."}
    results, n_liked, n_disliked = _score_items(item_type, metas, user_id)
    ranked = sorted(results, key=lambda r: r["affinity_score"], reverse=True)
    return {"item_type": item_type, "ranked": ranked, "based_on": {"liked": n_liked, "rejected": n_disliked},
            "note": "Low confidence means little history yet, not a bad item."}


@register_tool("record_preference")
def record_preference(item_type: str, title: str, liked: bool, user_id: int, description: Optional[str] = None) -> Dict[str, Any]:
    """Records that the user liked or rejected an item, so future recommendations improve."""
    title = (title or "").strip()
    if not title:
        return {"error": "title is required."}
    is_like = not _is_false(liked)
    wanted = normalize_item_type(item_type)
    text = f"{title} {description or ''}".strip()
    emb = np.asarray(get_embedder().encode(text), dtype=np.float32)

    db = SessionLocal()
    try:
        existing = [r for r in db.query(UserLike).filter(UserLike.user_id == user_id).all()
                    if normalize_item_type(r.item_type) == wanted and (r.title or "").strip().lower() == title.lower()]
        if is_like:
            if existing:
                return {"recorded": "like", "title": title, "message": "Already in your likes."}
            cols = UserLike.__table__.columns.keys()
            kwargs = {"user_id": user_id, "item_type": wanted, "title": title, "embedding": emb.tobytes()}
            if "description" in cols and description:
                kwargs["description"] = description
            db.add(UserLike(**kwargs))
            db.commit()
            return {"recorded": "like", "title": title, "message": "Saved. I will weight similar items higher."}
        for r in existing:                                  # changed their mind: a rejection removes the like
            db.delete(r)
        db.commit()
        # The rejection itself is stored by the audit log (Episode) when this call finishes.
        return {"recorded": "rejection", "title": title, "message": "Noted. I will steer away from similar items."}
    except Exception as e:
        db.rollback()
        return {"error": f"Could not save preference: {e}"}
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
    if amount <= 0:
        return {"error": "amount must be greater than 0."}

    # Save the draft in the approval ledger. execute_transfer is blocked in
    # code (guards.py) until the USER replies with a confirmation to this
    # exact draft, so the model cannot skip this step or invent a confirmation.
    draft_id = create_pending_action(
        tool_name="execute_transfer",
        args={"amount": amount, "recipient": recipient, "description": description},
        summary=f"Transfer {amount:,.2f} NGN to {recipient} ({description})",
    )
    if draft_id is None:
        return {"error": "Could not save the draft: transfers can only be drafted inside a chat conversation."}

    return {
        "status": "pending_approval",
        "draft_id": draft_id,
        "amount_ngn": amount,
        "amount_kobo": int(amount * 100),
        "recipient": recipient,
        "description": description,
        "currency": "NGN",
        "message": (
            "Draft saved. Show this draft to the user and STOP. Do not call execute_transfer in this turn: "
            "it only works after the user replies with an explicit confirmation such as 'yes, confirm'."
        ),
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
    Call this ONCE per question — the result is deterministic and calling it
    again with the same question returns the same chunks.
    document_id: from upload_pdf response. question: what you want to know.
    """
    db = SessionLocal()
    try:
        document = db.query(Document).filter(
            Document.id == document_id,
            Document.user_id == user_id
        ).first()

        if not document:
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

        # Top 3 (was 5) — fewer chunks per call keeps token cost predictable
        # and reduces the chance of hitting free-tier ITPM limits.
        top = sorted(scored, key=lambda x: x[0], reverse=True)[:3]
        relevant = [
            {
                "page": c.page_number,
                "similarity": round(sim, 3),
                # Capped at 500 chars (was full chunk, ~800 chars) — enough
                # context to answer general questions without ballooning
                # the request size.
                "text": c.text[:500]
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
                "This is enough context to answer. Answer ONLY using the text in "
                "relevant_chunks above. For every claim, cite the page number in "
                "parentheses e.g. (p.3). Do not call ask_document again for this question — "
                "if these chunks don't fully cover it, say what's missing rather than "
                "re-querying with the same question."
            )
        }
    finally:
        db.close()
# ─── Fitness: Private Helpers ─────────────────────────────────────────────────

def _build_injury_features(user_id: int):
    """
    8-feature vector over the last 7 days (today inclusive). The maths lives in
    fitness_logic.injury_features, which the trainer also uses, so training and
    serving can no longer drift apart.
    """
    db = SessionLocal()
    try:
        today = dt.date.today()
        start, _ = window_bounds(today)
        workouts = db.query(WorkoutLog).filter(WorkoutLog.user_id == user_id, WorkoutLog.date >= start).all()
        statuses = db.query(PhysicalStatus).filter(PhysicalStatus.user_id == user_id, PhysicalStatus.date >= start).all()
        return injury_features(workouts, statuses, today)
    finally:
        db.close()


def _heuristic_injury_risk(summary: dict) -> float:
    """Rule engine used when there is no trusted model (see fitness_logic.heuristic_injury_risk)."""
    return heuristic_injury_risk(summary)


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

def _usda_per_100g(food: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """
    Nutrient values from /foods/search are ALWAYS per 100 g, for every data
    type including Branded (servingSize is a separate field). Returns None if
    the entry has no usable energy value or the numbers are not physically
    plausible (USDA branded data contains a few absurd rows).
    """
    by_id = {n.get("nutrientId"): n.get("value") for n in food.get("foodNutrients", []) if n.get("value") is not None}
    calories = by_id.get(USDA_NUTRIENT_IDS["calories"])
    if calories is None:                                   # Foundation Foods report Atwater energy instead
        calories = by_id.get(2047, by_id.get(2048))
    if calories is None:
        return None
    per = {
        "calories": float(calories),
        "protein": float(by_id.get(USDA_NUTRIENT_IDS["protein"], 0)),
        "carbs":   float(by_id.get(USDA_NUTRIENT_IDS["carbs"], 0)),
        "fat":     float(by_id.get(USDA_NUTRIENT_IDS["fat"], 0)),
        "fiber":   float(by_id.get(USDA_NUTRIENT_IDS["fiber"], 0)),
    }
    if not 0 <= per["calories"] <= 900:                    # pure fat is about 884 kcal per 100 g
        return None
    if per["protein"] + per["carbs"] + per["fat"] > 105:   # cannot exceed 100 g of food per 100 g
        return None
    return per


@register_tool("log_nutrition")
def log_nutrition(food_name: str, portion_grams: float, user_id: int) -> Dict[str, Any]:
    """
    Logs a food item's macros from USDA FoodData Central. Use generic names like
    'chicken breast cooked', 'white rice cooked', or 'oats dry' for best matches.
    """
    try:
        portion_grams = float(portion_grams)
    except (TypeError, ValueError):
        return {"error": "portion_grams must be a number of grams, e.g. 150."}
    if not 0 < portion_grams <= 3000:
        return {"error": "portion_grams must be between 1 and 3000. Convert pieces to grams first (1 large egg is about 50 g)."}

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
        # Foundation Foods and SR Legacy are lab-analysed generic foods — prefer these
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

        food, per100 = None, None
        for candidate in foods:                            # first entry with sane numbers, not blindly foods[0]
            per100 = _usda_per_100g(candidate)
            if per100:
                food = candidate
                break
        if food is None:
            return {"error": f"USDA results for '{food_name}' had no usable nutrition data. Try a more specific name."}

        scale = portion_grams / 100.0                      # values are per 100 g, always
        calories = round(per100["calories"] * scale, 1)
        protein  = round(per100["protein"] * scale, 1)
        carbs    = round(per100["carbs"] * scale, 1)
        fat      = round(per100["fat"] * scale, 1)
        fiber    = round(per100["fiber"] * scale, 1)

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
            "matched_data_type": food.get("dataType"),
            "portion_grams": portion_grams,
            "calories": calories, "protein_grams": protein,
            "carb_grams": carbs, "fat_grams": fat, "fiber_grams": fiber,
            "per_100g": {k: round(v, 1) for k, v in per100.items()},
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
    Logging again on the same day updates today's entry (worst pain of the day is kept).
    """
    try:
        pain_level = int(pain_level)
        sleep_hours = float(sleep_hours)
        energy_level = None if energy_level is None or energy_level == "" else int(energy_level)
    except (TypeError, ValueError):
        return {"error": "pain_level, sleep_hours and energy_level must be numbers."}
    if not 0 <= pain_level <= 10:
        return {"error": "pain_level must be 0–10."}
    if not 0 < sleep_hours <= 24:
        return {"error": "sleep_hours must be between 0 and 24."}
    if energy_level is not None and not 1 <= energy_level <= 10:
        return {"error": "energy_level must be 1–10."}

    db = SessionLocal()
    try:
        today = dt.date.today()
        row = db.query(PhysicalStatus).filter(
            PhysicalStatus.user_id == user_id, PhysicalStatus.date == today
        ).first()
        updated = row is not None
        if row:
            row.pain_level = max(row.pain_level or 0, pain_level)   # keep the worst pain of the day
            row.sleep_hours = sleep_hours
            if injury_site:
                row.injury_site = injury_site
            if energy_level is not None:
                row.energy_level = energy_level
            if notes:
                row.notes = f"{row.notes} | {notes}" if row.notes else notes
            pain_level = row.pain_level
        else:
            db.add(PhysicalStatus(
                user_id=user_id, date=today,
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
            "logged": True, "updated_existing_entry": updated, "pain_level": pain_level,
            "sleep_hours": sleep_hours, "energy_level": energy_level,
            "message": f"Physical status logged.{warning}"
        }
    except Exception as e:
        db.rollback()
        return {"error": f"DB write failed: {e}"}
    finally:
        db.close()

# Movements available with a barbell and bench only (no rack, cables or machines).
_SAFE_BY_SITE = {
    "shoulder": ["Romanian deadlift", "conventional deadlift", "Zercher squat"],
    "knee":     ["Romanian deadlift", "bench press", "overhead press (seated)", "barbell curl",
                 "single-arm behind-the-neck tricep extension"],
    "back":     ["bench press", "barbell curl", "single-arm behind-the-neck tricep extension"],
    "wrist":    ["Romanian deadlift", "conventional deadlift", "Zercher squat"],
    "elbow":    ["Romanian deadlift", "conventional deadlift"],
    "hip":      ["bench press", "overhead press (seated)", "barbell curl",
                 "single-arm behind-the-neck tricep extension"],
    "ankle":    ["bench press", "overhead press (seated)", "barbell curl",
                 "single-arm behind-the-neck tricep extension"],
}
_SITE_WORDS = {
    "shoulder": ["shoulder", "rotator", "deltoid"], "knee": ["knee", "patella"],
    "back": ["back", "spine", "lumbar"], "wrist": ["wrist"], "elbow": ["elbow"],
    "hip": ["hip", "glute"], "ankle": ["ankle"],
}
_SITE_CAUTION = {
    "shoulder": "Skip the split squat: cleaning the bar to the front rack loads the shoulder. Keep pulls light until pain is below 3.",
    "back": "Do pressing seated or lying; no standing overhead work.",
    "wrist": "Use straps on pulls; Zercher keeps the wrists out of the lift.",
    "elbow": "Zercher puts the bar in the elbow crook, so it is excluded. Keep deadlifts light and use straps.",
}


@register_tool("adjust_program")
def adjust_program(injury_site: str, current_exercise: str) -> Dict[str, Any]:
    """
    Finds safe barbell-and-bench alternatives for an injured body part.
    injury_site examples: 'shoulder', 'knee', 'lower back', 'wrist', 'elbow'. Several sites can be named.
    """
    text = (injury_site or "").lower()
    sites = [s for s, words in _SITE_WORDS.items() if any(re.search(rf"\b{w}", text) for w in words)]
    base = {"injury_site": injury_site, "replaced_exercise": current_exercise,
            "equipment_constraint": "Barbell + bench only. No rack, cables, or machines.",
            "source": "Vetted offline list (no external lookup)"}

    if not sites:
        return {**base, "alternatives": [],
                "note": f"I do not recognise '{injury_site}'. Ask the user exactly where it hurts. Until then keep to rest or very light "
                        "movement, and see a physio if it persists. Known sites: " + ", ".join(_SAFE_BY_SITE) + "."}

    # With several injured sites, only movements safe for ALL of them qualify.
    safe = [m for m in _SAFE_BY_SITE[sites[0]] if all(m in _SAFE_BY_SITE[s] for s in sites[1:])]
    cautions = [_SITE_CAUTION[s] for s in sites if s in _SITE_CAUTION]
    note = ("Conservative defaults, not medical advice. See a physio if pain persists. " + " ".join(cautions)).strip()
    if not safe:
        note = f"No vetted barbell movement avoids all of: {', '.join(sites)}. Rest or physio advice is the safe call. " + note
    return {**base, "injury_sites_matched": sites, "alternatives": safe, "note": note}


@register_tool("predict_injury_risk")
def predict_injury_risk(user_id: int) -> Dict[str, Any]:
    """Predicts injury risk from the last 7 days of training and recovery. Uses a trained model only if it is trustworthy, else rules."""
    features, summary = _build_injury_features(user_id)

    if features is None:
        return {
            "risk": "unknown",
            "message": "Log at least a few workouts and physical status entries, then call again.",
            "days_logged": summary.get("days_logged", 0)
        }

    model_prob = None
    model_note = None
    pkl, meta_path = injury_model_paths(settings.ML_MODELS_DIR, user_id)
    if os.path.exists(pkl) and os.path.exists(meta_path):
        try:
            with open(meta_path) as f:
                meta = json.load(f)
            if model_is_trusted(meta):
                import joblib
                model_prob = float(joblib.load(pkl).predict_proba([features])[0][1])
            else:
                model_note = "A trained model exists but was judged too weak to use yet (too little data or low accuracy)."
        except Exception as e:
            print(f"[predict_injury_risk] model unusable ({e}). Using rules.")

    # The model may raise risk but never push it below the hard pain rule.
    risk, source = combine_risk(model_prob, summary)
    out = {
        "risk_probability": round(risk, 2),
        "risk": risk_label(risk),
        "recommendation": _get_injury_recommendation(risk),
        "model": source,
        "training_summary": summary,
    }
    if summary.get("data_notes"):
        out["data_notes"] = summary["data_notes"]
    if model_note:
        out["note"] = model_note
    elif model_prob is None:
        out["note"] = "Rule-based estimate. Run `python -m ml.train_injury_model --user-id N` after 30+ logged days."
    return out


# ─── Orchestration ────────────────────────────────────────────────────────────
@register_tool("delegate_to")
def delegate_to(specialist_name: str, instruction: str, user_id: int) -> Dict[str, Any]:
    """
    Delegates a sub-task to a specialist agent.
    Available: 'DeveloperAgent', 'ResearchAgent', 'FinanceAgent', 'FitnessAgent',
    'LifestyleAgent', 'CyberSecurityAgent', 'TutorAgent'.
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

    # Powers the 'Supervisor -> Specialist' cards in the activity panel.
    emit_event("specialist_start", {
        "specialist": specialist_name,
        "instruction_preview": instruction[:120],
    })

    # Pass the conversation id down so the specialist's tool calls are logged
    # to the episodes table too (before, only the Supervisor's were).
    ctx = get_turn_context()
    specialist = OgunAIAgent(
        role_config=config,
        user_id=user_id,
        conversation_id=ctx.conversation_id if ctx else None,
    )
    # build_specialist_task attaches the user's original message (and recent
    # context) so the specialist sees what the user actually pasted.
    result = specialist.run(build_specialist_task(instruction))

    emit_event("specialist_done", {"specialist": specialist_name})
    return {"specialist_result": result}



