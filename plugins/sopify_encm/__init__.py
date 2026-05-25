"""sopify-encm — External Network Control Module (Control Plane variant).

Manages outbound network policy by writing intent to YAML files under
``~/.sopify/encm/rules/`` and reconciling against the Docker Sandbox
(``sbx``) policy API. ENCM is the desired state; sbx is the actual state.

Entry points:
  - schema: ``sopify_encm.schema`` — Pydantic models (being reshaped to
    Kubernetes-style ``kind: NetworkRule`` YAML in the Control Plane rewrite)
  - audit: ``sopify_encm.audit`` — JSONL writer + retention (reused as the
    sink for the audit ingester that tails ``sbx policy log``)
  - rules: ``sopify_encm.rules`` — matcher + rate limiter + file-watched
    policy store (matcher/rate-limiter retained for the Custom Rule
    Engine — Week 4+ — for rules sbx can't express, e.g. time windows)

Out of scope (archived 2026-05-24 — see
``archive/2026-05-24-encm-mitm-attempt/``):
  - HTTPS MITM interception
  - Custom CA generation
  - Inline forward proxy

See ``SOPIFY_ENCM_SBX_INTEGRATION_PLAN.md`` for the design.
"""
from __future__ import annotations

__version__ = "0.1.0"

from . import schema, migration  # re-export for `from sopify_encm import schema`

__all__ = ["schema", "migration", "__version__"]
