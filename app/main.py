from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent import AnalyticsAgent
from app.auth import AuthError, RateLimiter, Verifier

STATIC = Path(__file__).parent / "static"


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=30)


class ChatResponse(BaseModel):
    reply: str


def create_app(
    agent: AnalyticsAgent,
    verifier: Verifier | None = None,
    cors_origins: list[str] | None = None,
    requests_per_minute: int = 12,
    public_config: dict[str, str] | None = None,
) -> FastAPI:
    app = FastAPI(title="LMS Analytics Chatbot")
    limiter = RateLimiter(requests_per_minute, 60.0)

    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["POST", "GET"],
            allow_headers=["Authorization", "Content-Type"],
        )

    def caller(authorization: str | None) -> str:
        """Return the caller id. Without a verifier (local sample) everyone is one anonymous caller."""
        if verifier is None:
            return "local"
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Sign in to use analytics.")
        try:
            return verifier.verify(authorization[7:].strip())
        except AuthError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.message) from None

    @app.post("/api/chat", response_model=ChatResponse)
    def chat(req: ChatRequest, authorization: str | None = Header(default=None)) -> ChatResponse:
        who = caller(authorization)
        if not limiter.allow(who):
            raise HTTPException(status_code=429, detail="Too many questions. Wait a minute and try again.")
        if req.messages[-1].role != "user":
            return ChatResponse(reply="Ask a question to continue.")
        return ChatResponse(reply=agent.chat([m.model_dump() for m in req.messages]))

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/config")
    def config() -> dict[str, object]:
        """Public sign-in settings for the page. Only the Supabase URL and anon key, never a secret."""
        cfg = public_config or {}
        return {
            "auth_required": verifier is not None,
            "supabase_url": cfg.get("supabase_url", ""),
            "supabase_anon_key": cfg.get("supabase_anon_key", ""),
        }

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def build_default_app() -> FastAPI:
    import anthropic

    from app.auth import SupabaseAdminVerifier
    from app.config import Settings
    from app.db import AnalyticsDb

    s = Settings()
    db = AnalyticsDb(s.database_url, s.blocked_set, s.max_rows, schema=s.db_schema or None)
    agent = AnalyticsAgent(anthropic.Anthropic(api_key=s.anthropic_api_key), db, s.anthropic_model)
    verifier = SupabaseAdminVerifier(s.supabase_url, s.supabase_anon_key) if s.require_auth else None
    public = {"supabase_url": s.supabase_url, "supabase_anon_key": s.supabase_anon_key}
    return create_app(agent, verifier, s.origins, s.requests_per_minute, public)
