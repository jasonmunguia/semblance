"""Vercel's Python entrypoint; local dev also supports the package factory."""
from backend.semblance.api import create_app

app = create_app()
