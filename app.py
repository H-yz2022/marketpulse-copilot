"""Vercel entrypoint: Vercel loads the ASGI `app` from this file.

The package lives under src/ (setuptools "src layout"), so put that on the path
before importing. Locally and in Docker the app runs as
`uvicorn marketpulse.api.main:app` instead.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from marketpulse.api.main import app  # noqa: E402

__all__ = ["app"]
