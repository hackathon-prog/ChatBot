"""Vercel entrypoint: Vercel looks for a module-level FastAPI object named `app`."""

from app.main import build_default_app

app = build_default_app()
