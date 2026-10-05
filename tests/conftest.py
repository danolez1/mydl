import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def mod(tmp_path_factory):
    """app-web.py has a hyphen, so it is loaded by path, with its cache and proxy files in a temp dir."""
    work = tmp_path_factory.mktemp("mydl")
    import os

    os.environ["CACHE_DIR"] = str(work / "cache")
    os.environ["PROXY_FILE"] = str(work / "proxies.txt")
    os.environ["COOKIES_FILE"] = str(work / "no-cookies.txt")
    os.environ["PUBLIC_BASE"] = ""
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("app_web", ROOT / "app-web.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["app_web"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def clean_state(mod):
    mod.CACHE.clear()
    mod.PROXIES.clear()
    mod.PROXY_HEALTH.clear()
    for fp in mod.CACHE_DIR.iterdir():
        fp.unlink()
    yield


@pytest.fixture
def client(mod):
    from fastapi.testclient import TestClient

    # No context manager, so the lifespan's background loops never start.
    return TestClient(mod.app)
