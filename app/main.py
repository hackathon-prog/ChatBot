import logging
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.agent import AnalyticsAgent
from app.auth import AuthError, RateLimiter, Verifier

log = logging.getLogger("chatbot")


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
) -> FastAPI:
    app = FastAPI(title="LMS Analytics Chatbot API", docs_url=None, redoc_url=None, openapi_url=None)
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
        try:
            return ChatResponse(reply=agent.chat([m.model_dump() for m in req.messages]))
        except Exception as exc:
            # Log the real cause server side; show the user a short safe message.
            log.exception("chat failed")
            status = getattr(exc, "status_code", None)
            if status in (401, 403):
                detail = "The AI service key is invalid. Ask the administrator to check it."
            elif status == 429 or "credit balance" in str(exc).lower():
                detail = "The AI service is out of quota or credits. Ask the administrator to check billing."
            else:
                detail = "The analytics assistant hit an error. Try again shortly."
            raise HTTPException(status_code=502, detail=detail) from None

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

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
    return create_app(agent, verifier, s.origins, s.requests_per_minute)
