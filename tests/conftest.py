"""Tests never touch the network.

SAPHES_OFFLINE is set before the application is imported so every verification
runs through the deterministic fallback. Live behaviour is covered separately by
tests/test_adapters.py, which mocks the HTTP layer.
"""

import os

os.environ.setdefault("SAPHES_OFFLINE", "1")
