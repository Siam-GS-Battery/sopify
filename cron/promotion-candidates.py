#!/usr/bin/env python3
"""Nightly promotion-candidates detector (REQ-4.4.4).

Reads /vibe-mode session usage from Loki, finds app_fingerprints that
appear in > 3 sessions within the last 7 days, and posts an IT
notification (Slack webhook) per candidate (REQ-4.4.2 + REQ-4.4.3).

Designed to run at 03:00 server-time on the central Alloy box:

  # crontab -e (as the dedicated `sopify` service user)
  0 3 * * * /usr/local/bin/python3 /opt/sopify/cron/promotion-candidates.py

Env vars:
  SOPIFY_LOKI_URL              http://loki.gsbattery.local:3100
  SOPIFY_PROMOTION_WEBHOOK     Slack/Teams incoming-webhook URL
  SOPIFY_PROMOTION_LOOKBACK_D  default: 7
  SOPIFY_PROMOTION_MIN_COUNT   default: 3
  SOPIFY_GRAFANA_BASE          http://grafana.gsbattery.local (for deep link)
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from typing import Dict, List

logger = logging.getLogger("sopify.cron.promotion-candidates")
logging.basicConfig(
    level=os.environ.get("SOPIFY_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)

LOKI_URL    = os.environ.get("SOPIFY_LOKI_URL", "http://loki.gsbattery.local:3100")
WEBHOOK     = os.environ.get("SOPIFY_PROMOTION_WEBHOOK", "")
LOOKBACK_D  = int(os.environ.get("SOPIFY_PROMOTION_LOOKBACK_D", "7"))
MIN_COUNT   = int(os.environ.get("SOPIFY_PROMOTION_MIN_COUNT", "3"))
GRAFANA     = os.environ.get("SOPIFY_GRAFANA_BASE", "http://grafana.gsbattery.local")


def query_loki(query: str, since_seconds: int) -> Dict:
    """Run a LogQL query over the last N seconds. Returns the raw JSON."""
    end = int(time.time() * 1e9)
    start = end - since_seconds * 10**9
    params = {"query": query, "start": start, "end": end, "limit": "5000"}
    url = f"{LOKI_URL}/loki/api/v1/query_range?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.URLError as exc:
        logger.warning("Loki query failed: %s", exc)
        return {}


def find_candidates() -> List[Dict]:
    """Return list of dicts: {fingerprint, user_emails, session_count, cost_usd}."""
    raw = query_loki(
        '{event_type="user_prompt", sopify_mode="vibe"} | json',
        LOOKBACK_D * 86400,
    )
    streams = raw.get("data", {}).get("result", []) or []

    fingerprints: Dict[str, Dict] = defaultdict(
        lambda: {"users": set(), "sessions": set(), "cost": 0.0}
    )
    for stream in streams:
        for line in stream.get("values", []):
            if not isinstance(line, list) or len(line) < 2:
                continue
            try:
                evt = json.loads(line[1])
            except Exception:
                continue
            fp = evt.get("app_fingerprint") or stream.get("stream", {}).get("app_fingerprint")
            if not fp:
                continue
            fingerprints[fp]["users"].add(evt.get("user_email", "?"))
            fingerprints[fp]["sessions"].add(evt.get("session_id", "?"))

    # Aggregate cost from api_request stream (separate query).
    raw_cost = query_loki(
        '{event_type="api_request", sopify_mode="vibe"} | json',
        LOOKBACK_D * 86400,
    )
    for stream in raw_cost.get("data", {}).get("result", []) or []:
        for line in stream.get("values", []):
            try:
                evt = json.loads(line[1])
            except Exception:
                continue
            fp = evt.get("app_fingerprint")
            if not fp or fp not in fingerprints:
                continue
            fingerprints[fp]["cost"] += float(evt.get("cost_usd") or 0.0)

    candidates = []
    for fp, agg in fingerprints.items():
        if len(agg["sessions"]) > MIN_COUNT:
            candidates.append({
                "fingerprint": fp,
                "user_emails": sorted(agg["users"]),
                "session_count": len(agg["sessions"]),
                "cost_usd": round(agg["cost"], 2),
            })
    candidates.sort(key=lambda c: c["session_count"], reverse=True)
    return candidates


def post_notification(candidates: List[Dict]) -> bool:
    if not candidates:
        logger.info("No promotion candidates this run.")
        return True
    if not WEBHOOK:
        logger.warning("SOPIFY_PROMOTION_WEBHOOK unset — printing only.")
        for c in candidates:
            print(json.dumps(c))
        return True
    grafana_url = f"{GRAFANA}/d/sopify-promotion-candidates"
    lines = [f"*Sopify — {len(candidates)} promotion candidate(s) this week*"]
    for c in candidates[:20]:
        lines.append(
            f"• `{c['fingerprint'][:12]}…` — "
            f"{c['session_count']} sessions, "
            f"${c['cost_usd']:.2f}, "
            f"users: {', '.join(c['user_emails'][:5])}"
        )
    lines.append(f"\n<{grafana_url}|Open Grafana dashboard>")
    payload = {"text": "\n".join(lines)}
    try:
        req = urllib.request.Request(
            WEBHOOK, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10).read()
        logger.info("Posted notification for %d candidates", len(candidates))
        return True
    except Exception as exc:
        logger.warning("Webhook post failed: %s", exc)
        return False


def main() -> int:
    candidates = find_candidates()
    ok = post_notification(candidates)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
