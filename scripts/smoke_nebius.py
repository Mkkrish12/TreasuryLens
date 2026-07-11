#!/usr/bin/env python3
"""Smoke-test Nebius Token Factory with the TreasuryLens synthesis prompt."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from agent.synthesis import synthesize_report  # noqa: E402
from agent.treasury_agent import demo_lens_results  # noqa: E402
from app.settings import get_settings  # noqa: E402


def main() -> int:
    settings = get_settings()
    if not settings.nebius_configured:
        print("NEBIUS_API_KEY not set — skipping live call; heuristic only.")
        report = synthesize_report(settings, demo_lens_results())
        print(json.dumps(report.model_dump(), indent=2))
        return 0
    print(f"Calling {settings.nebius_model} at {settings.nebius_base_url}")
    report = synthesize_report(settings, demo_lens_results())
    print(json.dumps(report.model_dump(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
