# backend/app/main.py
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from .database import create_tables, engine
from .config import settings
from .core.exceptions import OgunAIException
from .routers import auth, chat
from .services.agents.tools import get_embedder


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[Ogun AI] Starting — {settings.APP_NAME} v{settings.APP_VERSION}")
    create_tables()
    for dir_path, label in [
        (settings.WORKSPACE_DIR,         "Workspace (run_terminal)"),
        (settings.PLAYWRIGHT_STORAGE_DIR, "Browser sessions (browse_authenticated)"),
        (settings.UPLOADS_DIR,           "Uploads (upload_pdf)"),
        (settings.ML_MODELS_DIR,         "ML models (XGBoost)"),
    ]:
        os.makedirs(dir_path, exist_ok=True)
        print(f"[Ogun AI] {label}: {os.path.abspath(dir_path)}/")

    print("[Ogun AI] Loading sentence-transformer (all-MiniLM-L6-v2)...")
    get_embedder()
    print("[Ogun AI] Embedder ready.")
    yield
    engine.dispose()
    print("[Ogun AI] Shutdown complete.")


app = FastAPI(
    title=settings.APP_NAME,
    lifespan=lifespan,
    docs_url="/docs" if settings.ENVIRONMENT == "development" else None
)


@app.exception_handler(OgunAIException)
async def ogunai_exception_handler(request: Request, exc: OgunAIException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.error_code, "message": exc.message}}
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Pydantic validation errors can contain raw bytes when a file upload is sent
    # to the wrong endpoint. json.dumps() raises TypeError on bytes, causing a 500.
    # Recursively convert any non-serializable types to safe strings first.
    def make_serializable(obj):
        if isinstance(obj, bytes):
            return f"<binary data, {len(obj)} bytes — did you mean to POST to /upload?>"
        if isinstance(obj, dict):
            return {k: make_serializable(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [make_serializable(i) for i in obj]
        return obj

    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "details": make_serializable(exc.errors())
            }
        }
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

PREFIX = "/api/v1"
app.include_router(auth.router, prefix=PREFIX)
app.include_router(chat.router, prefix=PREFIX)


@app.get("/health")
def health():
    return {"status": "ok", "version": settings.APP_VERSION}