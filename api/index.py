"""Vercel entry point: the one Python function every non-static path rewrites to
(vercel.json). It serves web/app.py in LITE mode; see docs/VERCEL.md."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web"))

from app import app  # noqa: E402,F401  (WSGI callable Vercel looks for)
