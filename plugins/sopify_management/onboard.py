"""sopify onboard — welcome + audit consent + auth setup.

REQ-9.2.3 — welcome flow that explains the three modes and gets audit consent.
REQ-7.4.4 — user must be told their session will be audited.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import settings as managed

CONSENT_PROMPT = """\
Welcome to Sopify.

By using Sopify, your AI session activity (tool calls, prompts when enabled by
IT, errors) is sent to GS Battery's audit pipeline. The audit log is reviewed
by IT and HR per company policy.

You can:
- Continue (you consent to audit)
- Cancel (no audit, no Sopify)

Three modes are available:
  /vibe          — guided app builder (with IT handoff at end)
  /living        — 24/7 AI employee for the department
  /code-with-you — pair programming for engineers

Press ENTER to consent and continue, or Ctrl-C to cancel.
"""


def consent_file() -> Path:
    home = managed.settings_path().parent
    return home / "consent.json"


def already_consented() -> bool:
    return consent_file().exists()


def record_consent(user: str) -> None:
    """Write consent.json with timestamp + user."""
    import time
    consent_file().parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    consent_file().write_text(
        json.dumps({"user": user, "ts": time.time(), "version": 1}, indent=2)
    )
    consent_file().chmod(0o644)


def run_interactive(user: str = "") -> int:
    if already_consented():
        print("sopify onboard: consent already on record.")
        return 0
    try:
        print(CONSENT_PROMPT)
        input()
    except KeyboardInterrupt:
        print("Cancelled.")
        return 1
    record_consent(user or "unknown")
    print("Consent recorded. Run `sopify login` next.")
    return 0
