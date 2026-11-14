from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

APP_NAME = "Saphes"
BIFROST_API_KEY = os.getenv("BIFROST_API_KEY", "demo-key")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "demo-key")
APP_ENV = os.getenv("APP_ENV", "development")
