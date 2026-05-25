"""mitmproxy addon — enforces HTTP/HTTPS rules + writes audit log.

Run inside the ENCM container as::

    mitmdump -s /opt/encm/sopify_encm/proxy/http_proxy.py \
        --listen-port 3128 \
        --set ssl_insecure=false \
        --set confdir=/etc/encm/mitm

This addon hooks two events:
  * ``request`` — match the rule, decide allow/deny, terminate with 403 if denied
  * ``response`` — capture status + size, optionally log payload (per-rule opt-in)

Per-flow state lives in ``flow.metadata["encm"]`` so the response handler
can find the matched rule without re-running the matcher.
"""
from __future__ import annotations

import base64
import logging
import os
import time
from pathlib import Path

# mitmproxy is loaded by the runtime, not as a regular dep — import lazily
# so static analysis (and unit tests of unrelated code) don't choke.
try:
    from mitmproxy import http  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover — only triggered outside the container
    http = None  # type: ignore[assignment]

# Absolute imports — mitmproxy loads this file via `--scripts <path>` which
# evaluates it as a standalone module (no enclosing package context), so
# relative `from ..audit` raises ImportError. PYTHONPATH=/opt/encm makes
# `sopify_encm` importable as a top-level package inside the container.
from sopify_encm.audit import AuditEvent, AuditWriter
from sopify_encm.rules import PolicyStore, RuleMatcher

log = logging.getLogger("sopify_encm.http_proxy")

# Headers that may carry credentials — never write them to the audit log.
# Match is case-insensitive on the header name.
REDACT_HEADERS = {
    "authorization", "cookie", "set-cookie",
    "x-api-key", "x-auth-token", "anthropic-api-key",
    "openai-api-key", "x-amz-security-token",
}

# Max payload bytes to capture per direction when log_payload=True.
MAX_PAYLOAD_BYTES = 64 * 1024


def _redact_headers(headers: dict) -> dict:
    """Return a copy of `headers` with sensitive values replaced by '<redacted>'."""
    out = {}
    for k, v in headers.items():
        out[k] = "<redacted>" if k.lower() in REDACT_HEADERS else v
    return out


def _truncate_body(body: bytes) -> str:
    """Encode + cap a payload. Returns base64 string so binary bodies are
    safe to JSON-serialize."""
    if not body:
        return ""
    capped = body[:MAX_PAYLOAD_BYTES]
    return base64.b64encode(capped).decode("ascii")


class HttpProxy:
    """The mitmproxy addon. One instance lives for the lifetime of the proxy."""

    def __init__(
        self,
        policy_path: str | os.PathLike | None = None,
        audit_dir: str | os.PathLike | None = None,
        sandbox_label: str = "sandbox-unknown",
    ) -> None:
        # Container deployment passes paths via env vars (ENCM_POLICY_PATH +
        # ENCM_AUDIT_DIR). Constructor args are for unit tests / dev runs.
        policy_path = policy_path or os.environ.get(
            "ENCM_POLICY_PATH", "~/.sopify/network-policy.json"
        )
        audit_dir = audit_dir or os.environ.get(
            "ENCM_AUDIT_DIR", "~/.sopify/audit-log"
        )
        self._policy_path = Path(policy_path).expanduser()
        self._audit = AuditWriter(audit_dir)
        self._store = PolicyStore(self._policy_path)
        self._matcher = RuleMatcher(self._store.policy)
        self._store.on_change(self._matcher.update_policy)
        self._store.start()
        # The sandbox label tags audit events. Provided via env var when the
        # ENCM container is wired to a specific sandbox; falls back to "unknown"
        # in dev mode.
        self._src = os.environ.get("ENCM_SANDBOX_LABEL", sandbox_label)

    # ── mitmproxy hooks ────────────────────────────────────────────────

    def http_connect(self, flow: "http.HTTPFlow") -> None:  # type: ignore[name-defined]
        """Called for the initial CONNECT request that establishes an HTTPS
        tunnel. We must enforce destination here — by the time the inner
        request handler runs, upstream is already connected (or, when DNS
        fails, mitmproxy has already returned 502 to the client without
        ever consulting us).

        Policy check is host+port only; method/path are evaluated again on
        the inner request once the TLS tunnel is up."""
        host = flow.request.host
        port = flow.request.port
        # Look for ANY https rule matching this destination — we don't know
        # method/path yet, so just match domain + port.
        matched = None
        for rule in self._matcher.policy.rules:
            # Avoid importing HttpRule here — duck-type on .protocol/.domain/.ports
            if getattr(rule, "protocol", None) != "https":
                continue
            if port not in getattr(rule, "ports", []):
                continue
            from sopify_encm.rules.matcher import _domain_matches  # local import
            if _domain_matches(rule.domain, host):
                matched = rule
                break

        if matched is None:
            # Pre-tunnel deny. Returning a response from http_connect short-
            # circuits the tunnel and sends the response back to the client.
            self._audit.write(AuditEvent(
                decision="deny", protocol="https",
                src=self._src, dst=f"{host}:{port}",
                rule_id=None, reason="no matching rule (default-deny)",
                method="CONNECT", path="",
            ))
            flow.response = http.Response.make(
                403,
                f'{{"error":"Sopify policy: domain {host} not whitelisted","rule_id":null}}',
                {"Content-Type": "application/json"},
            )

    def request(self, flow: "http.HTTPFlow") -> None:  # type: ignore[name-defined]
        """Called once per request, before it leaves the proxy."""
        start = time.monotonic()
        host = flow.request.host
        port = flow.request.port
        method = flow.request.method.upper()
        path = flow.request.path
        scheme = flow.request.scheme.lower()  # "http" or "https"

        if scheme not in ("http", "https"):
            # mitmproxy can intercept connect-tunnels for non-HTTP traffic;
            # let those flow through unmatched (the underlying TCP forward
            # addon would handle them in M1.9).
            return

        decision = self._matcher.evaluate_http(
            protocol=scheme, host=host, port=port,
            method=method, path=path, src=self._src,
        )

        # Stash everything the response handler needs into flow.metadata so
        # we don't re-evaluate the rule on the way back.
        flow.metadata["encm.start"] = start
        flow.metadata["encm.decision"] = decision
        # Look up the rule object so we can read log_payload later. Matcher
        # only stored the id.
        rule = self._matcher.policy.find_rule(decision.rule_id) if decision.rule_id else None
        flow.metadata["encm.rule"] = rule

        if not decision.allow:
            self._audit.write(AuditEvent(
                decision="deny",
                protocol=scheme,
                src=self._src,
                dst=f"{host}:{port}",
                rule_id=decision.rule_id,
                reason=decision.reason,
                method=method,
                path=path,
            ))
            # Hard-deny: return a 403 to the sandbox, never contact upstream.
            flow.response = http.Response.make(
                403,
                f'{{"error":"Sopify policy: {decision.reason}","rule_id":{decision.rule_id!r}}}',
                {"Content-Type": "application/json"},
            )
            return

        # Allow path — request continues to upstream. Optional payload log.
        if rule is not None and getattr(rule, "log_payload", False):
            flow.metadata["encm.req_body"] = bytes(flow.request.raw_content or b"")
            flow.metadata["encm.req_headers"] = _redact_headers(dict(flow.request.headers))

    def response(self, flow: "http.HTTPFlow") -> None:  # type: ignore[name-defined]
        """Called once per response, after upstream replies."""
        start = flow.metadata.get("encm.start")
        decision = flow.metadata.get("encm.decision")
        rule = flow.metadata.get("encm.rule")
        if decision is None or not decision.allow:
            # Either the request was denied (already logged) or this is a
            # connect-tunnel without a paired decision.
            return

        duration_ms = int((time.monotonic() - start) * 1000) if start else None
        host = flow.request.host
        port = flow.request.port

        extras: dict = {}
        if rule is not None and getattr(rule, "log_payload", False):
            req_body = flow.metadata.get("encm.req_body")
            if req_body:
                extras["req_body_b64"] = _truncate_body(req_body)
            req_headers = flow.metadata.get("encm.req_headers")
            if req_headers:
                extras["req_headers"] = req_headers
            resp_body = bytes(flow.response.raw_content or b"") if flow.response else b""
            if resp_body:
                extras["resp_body_b64"] = _truncate_body(resp_body)
            if flow.response:
                extras["resp_headers"] = _redact_headers(dict(flow.response.headers))

        self._audit.write(AuditEvent(
            decision="allow",
            protocol=flow.request.scheme.lower(),
            src=self._src,
            dst=f"{host}:{port}",
            rule_id=decision.rule_id,
            method=flow.request.method.upper(),
            path=flow.request.path,
            status=flow.response.status_code if flow.response else None,
            duration_ms=duration_ms,
            bytes_sent=len(flow.request.raw_content or b""),
            bytes_recv=len(flow.response.raw_content or b"") if flow.response else 0,
            extras=extras,
        ))

    def done(self) -> None:
        """mitmproxy lifecycle hook — proxy shutting down."""
        self._store.stop()
        self._audit.close()


# mitmproxy convention: ``addons`` list at module level is auto-registered.
addons = [HttpProxy()]
