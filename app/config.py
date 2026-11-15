from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

APP_NAME = "Saphes"

# Optional. Saphes works without any key by using Tavily's keyless access mode.
BIFROST_API_KEY = os.getenv("BIFROST_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

APP_ENV = os.getenv("APP_ENV", "development")

# Force deterministic, cache-backed behaviour (used by tests and by the
# offline demo path so a dead conference network cannot kill a live demo).
OFFLINE_MODE = os.getenv("SAPHES_OFFLINE", "").strip().lower() in {"1", "true", "yes", "on"}

TAVILY_SEARCH_URL = os.getenv("TAVILY_SEARCH_URL", "https://api.tavily.com/search")
TAVILY_TIMEOUT_SECONDS = float(os.getenv("TAVILY_TIMEOUT_SECONDS", "8"))
TAVILY_MAX_RESULTS = int(os.getenv("TAVILY_MAX_RESULTS", "3"))

# Search results are cached on disk so a repeat claim costs nothing and the
# demo still works with the network unplugged.
CACHE_DIR = os.getenv("SAPHES_CACHE_DIR", ".saphes_cache")
BUNDLED_EVIDENCE = os.path.join(os.path.dirname(__file__), "data", "cached_evidence.json")

SAPHES_HOST = os.getenv("SAPHES_HOST", os.getenv("TRUTHLAYER_HOST", "127.0.0.1"))
SAPHES_PORT = int(os.getenv("SAPHES_PORT", os.getenv("TRUTHLAYER_PORT", "8000")))
