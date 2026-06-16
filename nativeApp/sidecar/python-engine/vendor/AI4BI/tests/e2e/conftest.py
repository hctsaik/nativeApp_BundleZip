"""Playwright E2E fixtures for AI4BI Streamlit app."""

from __future__ import annotations

import subprocess
import sys
import time
import socket
from pathlib import Path

import pytest
import requests

_APP_PATH = Path(__file__).parents[2] / "ai4bi" / "ui" / "app.py"


def _free_port() -> int:
    """Pick an OS-assigned free port so e2e never clashes with a running dev
    server (e.g. a developer's GUI on 8502)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def streamlit_server():
    """Start a Streamlit server for the session and yield the base URL."""
    port = _free_port()
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run",
            str(_APP_PATH),
            "--server.port", str(port),
            "--server.headless", "true",
            "--server.runOnSave", "false",
            "--browser.gatherUsageStats", "false",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    base_url = f"http://localhost:{port}"
    # Wait up to 30s for the server to be ready
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            resp = requests.get(base_url, timeout=2)
            if resp.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(1)
    else:
        proc.terminate()
        raise RuntimeError(f"Streamlit server did not start on port {port} within 30s")

    yield base_url

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="session")
def app_url(streamlit_server) -> str:
    return streamlit_server
