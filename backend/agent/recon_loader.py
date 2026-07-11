from __future__ import annotations

import json
from pathlib import Path

from agent.schema_context import update_from_recon


def load_recon_if_present() -> bool:
    """Load docs/schema_recon.json into SCHEMA if the recon script has been run."""
    candidates = [
        Path(__file__).resolve().parents[2] / "docs" / "schema_recon.json",
        Path(__file__).resolve().parents[1] / "docs" / "schema_recon.json",
        Path.cwd() / "docs" / "schema_recon.json",
        Path.cwd().parent / "docs" / "schema_recon.json",
    ]
    for path in candidates:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            update_from_recon(data)
            return True
    return False
