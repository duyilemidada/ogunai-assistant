Ogun AI

A private, multi-agent personal assistant. FastAPI backend running a ReAct Supervisor + specialist agents, React/TypeScript frontend with live streaming of agent activity. Named after the Yoruba deity of iron, fire, and craft.

What it does

Ogun AI is not a chatbot — it's a Supervisor that delegates to specialist agents, each with its own tools:

ResearchAgent — web search (Tavily), page fetching, JS-rendered pages (headless Chromium via Crawl4AI), grounded PDF Q&A, cross-conversation memory recall
DeveloperAgent — sandboxed terminal access, GitHub API, file I/O
FinanceAgent — bank balance/transactions via Mono, draft-then-confirm transfers via Mono DirectPay (never executes without explicit approval)
FitnessAgent — nutrition logging against USDA FoodData Central, workout logging, XGBoost-based injury risk prediction, exercise substitution via the wger database
TutorAgent — prerequisite-gap detection, grounded concept explanations, practice question generation, mastery tracking, daily deep-dive readings
LifestyleAgent — preference-based recommendations (cosine similarity, upgrading to XGBoost once enough feedback accumulates)
CyberSecurityAgent — log/config analysis, web asset inspection

Every specialist call, tool call, and result streams to the frontend in real time over Server-Sent Events — the UI shows exactly what the agent is doing, not a spinner.

Architecture
frontend/   Vite + React 19 + TypeScript + Tailwind v4
            Zustand (UI/streaming state) + TanStack Query (server state)
            SSE via @microsoft/fetch-event-source

backend/    FastAPI + SQLAlchemy + SQLite
            ReAct agent loop with tool-calling via Groq (OpenAI-compatible API)
            sentence-transformers + numpy cosine similarity for all embeddings
            (no vector database — avoids compiled-dependency issues on Windows)

Full technical documentation lives in /docs (backend deep-dive and frontend spec, both generated as part of this project's build process).

Setup
Backend
bash
cd backend
python -m venv venv
source venv/Scripts/activate      # Windows Git Bash
pip install -r requirements.txt
playwright install chromium

Copy .env.example to .env (at the project root, one level above backend/) and fill in your keys:

SECRET_KEY=
DATABASE_URL=sqlite:///./ogun.db
LLM_PROVIDER=openai_compatible
LLM_MODEL=llama-3.1-8b-instant
LLM_MAX_TOKENS=800
LLM_API_KEY=
LLM_BASE_URL=https://api.groq.com/openai/v1
TAVILY_API_KEY=
MONO_SECRET_KEY=
MONO_ACCOUNT_ID=
USDA_API_KEY=
GITHUB_TOKEN=

Run it:

bash
uvicorn backend.app.main:app --reload --port 8000

API docs at http://localhost:8000/docs.

Frontend
bash
cd frontend
npm install

Create frontend/.env.local:

VITE_API_BASE_URL=http://localhost:8000

Run it:

bash
npm run dev

App at http://localhost:5173.

Status

Backend and frontend are both functional end-to-end — auth, streaming chat, all seven specialists, PDF upload and grounded Q&A, conversation history persistence, and a memory browser are wired up. This has not yet had a full systematic test pass across every feature; treat it as working-but-unaudited rather than production-hardened. See /docs for the test plan being used to work through this.

License

