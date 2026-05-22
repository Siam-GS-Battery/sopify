"""PII / secret redaction before any OTel emit.

REQ-11.2 — no API keys in logs/OTel.
REQ-11.3 — Hermes has `agent/redact.py`; this layer is a Sopify-side belt-and-
braces sweep targeting the patterns most likely to appear in tool args.
"""
from __future__ import annotations

import re
from typing import Any, Dict

API_KEY_RE = re.compile(
    r"\b(sk-[a-zA-Z0-9_-]{20,}|ant-[a-zA-Z0-9_-]{20,}|"
    r"AIza[0-9A-Za-z_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,})\b"
)
BEARER_RE = re.compile(r"(?i)bearer\s+[a-z0-9._-]{20,}")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
PHONE_RE = re.compile(r"\b\+?\d[\d\s().-]{8,}\b")


def redact_string(s: str) -> str:
    s = API_KEY_RE.sub("[REDACTED_KEY]", s)
    s = BEARER_RE.sub("Bearer [REDACTED]", s)
    return s


def redact_with_email(s: str, *, scrub_email: bool = False) -> str:
    s = redact_string(s)
    if scrub_email:
        s = EMAIL_RE.sub("[REDACTED_EMAIL]", s)
        s = PHONE_RE.sub("[REDACTED_PHONE]", s)
    return s


def redact_payload(payload: Dict[str, Any], *, scrub_email: bool = False) -> Dict[str, Any]:
    """Walk dict/list values and redact string leaves in place (returns copy)."""
    def walk(v):
        if isinstance(v, str):
            return redact_with_email(v, scrub_email=scrub_email)
        if isinstance(v, list):
            return [walk(i) for i in v]
        if isinstance(v, dict):
            return {k: walk(val) for k, val in v.items()}
        return v
    return walk(payload)
