"""Vercel entrypoint: Vercel looks for a module-level FastAPI object named `app`.

If configuration is wrong the import must not crash (that shows an opaque FUNCTION_INVOCATION_FAILED).
Instead every route answers 503 with the names of the settings that need fixing. No values are shown.
"""

import logging

from fastapi import FastAPI, HTTPException

log = logging.getLogger("chatbot")


def _problem(exc: Exception) -> str:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            names = sorted({str(e["loc"][0]).upper() for e in errors() if e.get("loc")})
            if names:
                return "Missing or invalid settings: " + ", ".join(names) + ". Set them in the Vercel project environment variables."
            return "Invalid settings. Check REQUIRE_AUTH, SUPABASE_URL and SUPABASE_ANON_KEY."
        except Exception:
            pass
    return f"Startup failed ({type(exc).__name__}). Check DATABASE_URL and the Vercel logs."


# Vercel finds the entrypoint by scanning for a top-level `app = FastAPI(...)`, so it is declared here.
app = FastAPI(title="LMS Analytics Chatbot API", docs_url=None, redoc_url=None, openapi_url=None)

try:
    from app.main import build_default_app

    app.mount("/", build_default_app())
except Exception as exc:
    log.exception("startup failed")
    message = _problem(exc)

    @app.api_route("/{path:path}", methods=["GET", "POST", "OPTIONS"])
    def unavailable(path: str) -> None:
        raise HTTPException(status_code=503, detail=message)
