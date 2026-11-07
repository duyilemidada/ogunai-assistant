# backend/app/services/agents/formatting.py
"""
Fixes the "Python shown as text" annoyance.

The model often opens a code block with a bare ``` or with ```text, and the
chat UI then labels (and fails to highlight) real code as "text". Prompts only
ask the model to tag its blocks; this module makes sure of it in code, on the
way into the database, so every saved message is already correct.

Rules, in order of importance:
  1. Never touch a block that already has a real language tag.
  2. Only relabel blocks that are untagged or tagged text/txt/plain.
  3. Only relabel when detection is confident. When unsure, leave the block
     exactly as it was: a wrong label is worse than no label.
  4. Everything outside the opening fence line is preserved byte for byte
     (line endings included).
"""
import json
import re
from typing import Optional

# Tags that mean "no real language was given".
_GENERIC_TAGS = frozenset({"", "text", "txt", "plain", "plaintext", "none", "code"})

# Harmless spelling normalisation for tags the UI may not recognise.
_ALIASES = {"py": "python", "python3": "python", "py3": "python"}

# ```lang   (optionally indented)   -- anything extra on the line (title="x") means: leave alone.
_OPEN = re.compile(
    r"^(?P<indent>[ \t]*)(?P<fence>`{3,}|~{3,})[ \t]*(?P<info>[^\s`~]*)[ \t]*(?P<rest>[^\r\n]*?)(?P<eol>\r?\n?)$"
)


def _is_closing(line: str, fence: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and set(stripped) == {fence[0]} and len(stripped) >= len(fence)


# ── Language detection ────────────────────────────────────────────────────────

_PY_LINE = [
    re.compile(r"^\s*(async\s+)?def\s+\w+\s*\(.*\)\s*(->\s*[^:]+)?:\s*(#.*)?$"),
    re.compile(r"^\s*class\s+\w+(\(.*\))?\s*:\s*(#.*)?$"),
    re.compile(r"^\s*from\s+[\w.]+\s+import\s+[\w*, ()]+$"),
    re.compile(r"^\s*import\s+[\w.]+(\s+as\s+\w+)?(\s*,\s*[\w.]+(\s+as\s+\w+)?)*\s*$"),
    re.compile(r"^\s*@[\w.]+(\(.*\))?\s*$"),
    re.compile(r"^\s*(if|elif|else|try|except|finally|with|for|while)\b[^\n]*:\s*(#.*)?$"),
    re.compile(r"^\s*if\s+__name__\s*==\s*['\"]__main__['\"]\s*:"),
    re.compile(r"^\s*print\(.*\)\s*$"),
    re.compile(r"^\s*(return|raise|yield|assert|pass|break|continue)\b"),
    re.compile(r"^\s*\w+(\.\w+)*\s*=\s*.+$"),
    re.compile(r"\bself\.\w+"),
    re.compile(r"^\s*(await\s+)?\w+(\.\w+)*\(.*\)\s*$"),
]
# Lines that make Python much more likely than the generic ones above.
_PY_STRONG = [0, 1, 2, 3, 4, 6]   # indexes into _PY_LINE

_SHELL_CMDS = (
    "pip", "pip3", "python", "python3", "py", "npm", "npx", "yarn", "pnpm", "git", "cd", "ls", "mkdir",
    "curl", "wget", "export", "uvicorn", "pytest", "docker", "echo", "cat", "sudo", "apt", "apt-get",
    "brew", "set", "copy", "dir", "type", "del", "taskkill", "venv", "source", "chmod", "rm", "mv", "cp",
    "touch", "grep", "ssh", "node", "cargo", "uv", "alembic", "wsl",
)
_SHELL_LINE = re.compile(r"^\s*(\$\s+|>\s+|PS [^>]*>\s*)?(?P<cmd>[\w.\-]+)(\s|$)")
_PS_HINT = re.compile(r"\$env:|\b(Get|Set|New|Remove|Invoke|Start|Stop)-[A-Z]\w+|\.\\[\w\\]+\.ps1|^\s*PS [^>]*>", re.M)

_SQL_START = re.compile(r"^\s*(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|CREATE\s+(TABLE|INDEX|VIEW)|ALTER\s+TABLE|DROP\s+TABLE|WITH)\b", re.I | re.M)
_SQL_BODY = re.compile(r"\b(FROM|VALUES|SET|WHERE|JOIN|COLUMN|PRIMARY\s+KEY)\b", re.I)

_TS_SIGNALS = [
    re.compile(r"^\s*import\s+.+\s+from\s+['\"].+['\"]", re.M),
    re.compile(r"^\s*(export\s+)?(default\s+)?(const|let|function|async function)\s+\w+", re.M),
    re.compile(r"=>"),
    re.compile(r"^\s*(export\s+)?(interface|type)\s+\w+", re.M),
    re.compile(r"\buse(State|Effect|Ref|Memo|Callback)\("),
    re.compile(r"\brequire\(['\"]"),
    re.compile(r"\bconsole\.(log|error)\("),
]
_JSX = re.compile(r"<[A-Z]\w*[\s/>]|className=|</\w+>")
_TS_ONLY = re.compile(r"^\s*(export\s+)?(interface|type)\s+\w+|:\s*(string|number|boolean|void)\b|\bReact\.FC\b|<\w+>\(", re.M)


def _non_empty(body: str):
    return [ln for ln in body.splitlines() if ln.strip()]


def detect_language(body: str) -> Optional[str]:
    """Best-guess language of a code block, or None if not confident."""
    lines = _non_empty(body)
    if not lines:
        return None
    text = "\n".join(lines)
    stripped = text.strip()

    # JSON: strict parse, so prose can never match.
    if stripped[0] in "{[":
        try:
            json.loads(stripped)
            return "json"
        except ValueError:
            pass

    # Unified diff.
    if re.search(r"^@@ .+ @@", text, re.M) or (re.search(r"^--- ", text, re.M) and re.search(r"^\+\+\+ ", text, re.M)):
        return "diff"

    # SQL.
    if _SQL_START.search(text) and _SQL_BODY.search(text):
        return "sql"

    # PowerShell (before bash: shares command-ish lines).
    if _PS_HINT.search(text):
        return "powershell"

    # Python: score each line; strong lines (def/class/import/decorator/__main__) count extra.
    py_hits = 0
    py_strong = 0
    for ln in lines:
        for i, pat in enumerate(_PY_LINE):
            if pat.search(ln):
                py_hits += 1
                if i in _PY_STRONG:
                    py_strong += 1
                break
    py_ratio = py_hits / len(lines)
    if py_strong >= 1 and py_hits >= 2 and py_ratio >= 0.6:
        return "python"
    if py_strong == 0 and py_hits >= 3 and py_ratio >= 0.8 and "{" not in text and ";" not in text \
            and re.search(r"\bprint\(|\bself\.|\bdef\b|:\s*$", text, re.M):
        return "python"

    # JS / TS / TSX: need at least two distinct signals.
    ts_hits = sum(1 for pat in _TS_SIGNALS if pat.search(text))
    if ts_hits >= 2:
        if _JSX.search(text):
            return "tsx"
        if _TS_ONLY.search(text):
            return "typescript"
        return "javascript"

    # Shell: most lines look like commands, at least one is a well-known one.
    cmd_lines = 0
    known = 0
    for ln in lines:
        if ln.lstrip().startswith("#"):
            cmd_lines += 1
            continue
        m = _SHELL_LINE.match(ln)
        if m and (ln.lstrip().startswith(("$", ">")) or m.group("cmd") in _SHELL_CMDS or ln.rstrip().endswith("\\")):
            cmd_lines += 1
            if m.group("cmd") in _SHELL_CMDS or ln.lstrip().startswith("$"):
                known += 1
    if known >= 1 and cmd_lines / len(lines) >= 0.8:
        # `set X=Y` / `copy` / `dir` are cmd.exe, not bash: don't guess a label for those.
        if re.search(r"^\s*(set\s+\w+=|copy\s|dir\b|del\s|type\s)", text, re.M | re.I):
            return None
        return "bash"

    return None


# ── Public API ────────────────────────────────────────────────────────────────

def normalize_code_fences(text: str) -> str:
    """
    Return `text` with untagged / ```text fences relabelled to the detected
    language. Safe to call on any string; non-strings and fence-free text are
    returned untouched.
    """
    if not isinstance(text, str) or "```" not in text and "~~~" not in text:
        return text

    lines = text.splitlines(keepends=True)
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _OPEN.match(line)
        if not m:
            out.append(line)
            i += 1
            continue

        fence = m.group("fence")
        # Find the closing fence (or the end of the text if the block is unclosed).
        j = i + 1
        while j < len(lines) and not _is_closing(lines[j], fence):
            j += 1
        body = "".join(lines[i + 1:j])
        closing = lines[j] if j < len(lines) else None

        info = m.group("info")
        tag = info.lower()
        new_tag = info
        if m.group("rest"):
            pass                                   # title="..." etc: leave the whole line alone
        elif tag in _ALIASES:
            new_tag = _ALIASES[tag]
        elif tag in _GENERIC_TAGS:
            detected = detect_language(body)
            if detected:
                new_tag = detected

        if new_tag != info and not m.group("rest"):
            out.append(f"{m.group('indent')}{fence}{new_tag}{m.group('eol')}")
        else:
            out.append(line)
        out.append(body)
        if closing is not None:
            out.append(closing)
        i = j + 1 if closing is not None else j
    return "".join(out)
