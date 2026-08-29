"""Load the small, approved set of local runtime environment values."""

from __future__ import annotations

import os
import re
from pathlib import Path


APPROVED_ENV_KEYS = frozenset(
    {
        "SHOPPING_COPILOT_LLM_ENABLED",
        "SHOPPING_COPILOT_LLM_MAX_CALLS",
        "SHOPPING_COPILOT_LLM_MODEL",
        "SOCLAAS_BASE_URL",
        "SOCLAAS_API_KEY",
    }
)
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DEFAULT_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def load_runtime_environment(path: str | Path | None = None) -> Path | None:
    """Load approved values without replacing variables supplied by the OS.

    ``SHOPPING_COPILOT_ENV_FILE`` may point to a secret file outside the
    repository. When it is set, the local ``.env`` file is not inspected.
    """

    selected = Path(path).expanduser() if path is not None else _selected_env_file()
    if not selected.is_file():
        return None
    for raw_line in selected.read_text(encoding="utf-8-sig").splitlines():
        parsed = _parse_env_line(raw_line)
        if parsed is None:
            continue
        key, value = parsed
        if key in APPROVED_ENV_KEYS:
            os.environ.setdefault(key, value)
    return selected


def _selected_env_file() -> Path:
    configured = os.environ.get("SHOPPING_COPILOT_ENV_FILE", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_ENV_FILE


def _parse_env_line(raw_line: str) -> tuple[str, str] | None:
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[7:].lstrip()
    if "=" not in line:
        return None
    key, value = line.split("=", 1)
    key = key.strip()
    if not ENV_KEY_RE.fullmatch(key):
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value
