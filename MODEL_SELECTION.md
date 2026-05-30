# Sopify — Model Selection Policy

**Status:** Proposed (rev 0.1, 2026-05-30). Companion to [§15 of SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md#15-model-selection-strategy). Reviewer-ready, not yet implemented in code.

> **TL;DR** — Default to OSS where the task is "code + tool-calling" or "Thai-language chat", keep Anthropic where visual taste, security liability, or 1 M context matters. Estimated cost reduction vs the current "Opus-first" default: **70–80%** on Vibe Code workloads, **60%** overall.

---

## Table of contents

1. [Why the current default is wrong](#1-why-the-current-default-is-wrong)
2. [Decision criteria](#2-decision-criteria)
3. [Use-case → model mapping](#3-use-case--model-mapping)
4. [Cost model](#4-cost-model)
5. [Failover & resilience](#5-failover--resilience)
6. [Migration plan](#6-migration-plan)
7. [Risks & where OSS still loses](#7-risks--where-oss-still-loses)
8. [Monitoring & review cadence](#8-monitoring--review-cadence)

---

## 1. Why the current default is wrong

The first entry in `_PROVIDER_MODELS["nous"]` ([models.py:165](sopify-harness/hermes_cli/models.py#L165)) is `anthropic/claude-opus-4.7`. This becomes the default in the model picker UI and — for users who never open the picker — the model that drives every conversation.

That's correct for a research lab where the user is a model expert and tokens are subsidised. It is **wrong** for Sopify because:

- **Audience.** The flagship flow (Vibe Code) is explicitly aimed at non-engineers ([vibe-app-builder skill bundle](sopify-harness/sopify_skill_bundles/vibe-app-builder/SKILL.md)). They will accept the default and never change it.
- **Workload character.** SDLC tasks (form scaffolds, Express CRUD, Supabase wiring) are not at the frontier of model capability. OSS models from 2025–2026 handle them with no measurable quality gap.
- **Token volume.** Vibe Code is multi-phase + dev-server iterating. A single project can churn 500K–2M tokens. Opus-rate on that volume burns budget the org can spend on more seats instead.
- **Egress governance.** ENCM ([sopify_daemon/](sopify-harness/sopify_daemon/)) already mediates which providers traffic can reach. The platform is *built* to switch primaries.

## 2. Decision criteria

Pick the cheapest model in the tier above the task's actual bar — not the most-capable model the picker offers. The bars that matter:

| Criterion | Where it matters | Anthropic edge? |
|---|---|---|
| **Tool-calling reliability** | Every agent loop in Hermes | Marginal — Kimi K2.6 / Qwen3.6-plus / DeepSeek V3.2 all pass `_openrouter_model_supports_tools` and complete agent turns reliably in practice |
| **Visual taste / frontend aesthetics** | Vibe Design phase, `/panel` Canvas previews | **Yes** — measurable. `frontend-design` skill is Anthropic-tuned; OSS output skews "generic AI slop" (Inter / Roboto / purple gradients) |
| **Long context (>200 K)** | `/gs-mad` reading full SOP-SDLC docs; cross-phase Vibe runs | **Yes** — 1 M context unique to Claude family |
| **Thai-language fluency** | `company-sop`, `living-employee`, end-user-facing chat | OSS edge — Qwen3.6-plus is materially better than Haiku on Thai colloquial register |
| **Security review depth** | Vibe Security phase, `claude-code-security-review` skill | **Yes** — Opus has more public eval data on adversarial code review |
| **Refusal pattern compatibility** | Any user-facing turn | OSS edge — GLM family refuses some Thai SDLC phrasings; Anthropic and Qwen handle them cleanly |
| **Cost** | Everywhere | Strong OSS edge (5–50× cheaper) |

## 3. Use-case → model mapping

### 3.1 Vibe Code phases

Phase machine: [web_server.py:5484](sopify-harness/hermes_cli/web_server.py#L5484) + `_VIBE_BUILDING_PHASES`. Today single-model; proposal pins per-phase.

| Phase | Prompt file | Primary | Fallback | Why |
|---|---|---|---|---|
| brainstorm | [brainstorm.md](sopify-harness/prompts/vibe/phases/brainstorm.md) | `claude-haiku-4-5` | `qwen/qwen3.6-plus` | Short turns, low stakes |
| design | [design.md](sopify-harness/prompts/vibe/phases/design.md) | `claude-sonnet-4-6` | `claude-opus-4-7` | `frontend-design` skill demands Anthropic family |
| backend | [backend.md](sopify-harness/prompts/vibe/phases/backend.md) | `moonshotai/kimi-k2.6` | `claude-sonnet-4-6` | Express + Supabase + SQL — coding-strong OSS handles cleanly |
| improvement | [improvement.md](sopify-harness/prompts/vibe/phases/improvement.md) | `claude-sonnet-4-6` | `moonshotai/kimi-k2.6` | Diff-aware refactor benefits from Anthropic tool-call discipline |
| security | [security.md](sopify-harness/prompts/vibe/phases/security.md) | `claude-opus-4-7` | `claude-sonnet-4-6` | Liability bar — do not compromise |
| approve | [approve.md](sopify-harness/prompts/vibe/phases/approve.md) | `claude-haiku-4-5` | `qwen/qwen3.6-plus` | Handoff doc generation |

### 3.2 Sopify modes

| Mode | Source | Primary | Fallback |
|---|---|---|---|
| `code-with-you` | [code_with_you.py](sopify-harness/plugins/sopify_modes/code_with_you.py) | `moonshotai/kimi-k2.6` | `claude-sonnet-4-6` |
| `company-sop` | [config.py](sopify-harness/plugins/sopify_modes/config.py) | `qwen/qwen3.6-plus` | `claude-haiku-4-5` |
| `living-employee` | [living.py](sopify-harness/plugins/sopify_modes/living.py) | `qwen/qwen3.6-plus` | `claude-haiku-4-5` |
| `vibe` | [vibe.py](sopify-harness/plugins/sopify_modes/vibe.py) | per §3.1 above | per §3.1 above |

### 3.3 Auxiliary slots

These slots ([web_server.py:996](sopify-harness/hermes_cli/web_server.py#L996)) currently inherit the primary model. They run constantly and rarely need top-tier quality. Pin them to Haiku:

| Slot | Pin to | Why |
|---|---|---|
| `title_generation` | `claude-haiku-4-5` | One-line output, latency-sensitive |
| `compression` | `claude-haiku-4-5` | Summarise transcripts; quality bar low |
| `session_search` | `claude-haiku-4-5` | Keyword + intent, not deep reasoning |
| `curator` | `claude-haiku-4-5` | Tag / category extraction |
| `mcp` | inherit primary | Tool-routing — keep on primary |
| `approval` | inherit primary | User-facing — keep on primary |
| `vision` | `claude-sonnet-4-6` | Multimodal needed; Sonnet cheaper than Opus, better than Haiku-vision |
| `web_extract` | `qwen/qwen3.6-plus` | Long page → structured; cheap |
| `skills_hub` | inherit primary | Stays in lockstep with main turn |

## 4. Cost model

Pricing snapshot **2026-05** (USD per 1 M tokens, input / output). Treat as ±20% — refresh quarterly.

| Model | Input | Output | Tier role |
|---|--:|--:|---|
| `claude-opus-4-7` | $15.00 | $75.00 | Premium |
| `claude-sonnet-4-6` | $3.00 | $15.00 | Workhorse |
| `claude-haiku-4-5` | $0.80 | $4.00 | Routine |
| `moonshotai/kimi-k2.6` (Moonshot direct) | $0.60 | $2.50 | OSS-coding |
| `deepseek/deepseek-v4-pro` (DeepSeek direct) | $0.27 | $1.10 | OSS-cheap |
| `qwen/qwen3.6-plus` (DashScope intl) | $0.40 | $1.20 | OSS-multilingual |
| `z-ai/glm-5.1` (Zhipu direct) | $0.50 | $1.50 | OSS-agentic |

### Projected per-Vibe-project spend

Assume a "median" Vibe project: 200 K input / 60 K output across all phases (rough from `/api/analytics/usage` historical ranges — verify against your tenant before publishing).

| Configuration | Cost per project | Notes |
|---|--:|---|
| **Today** — Opus 4.7 throughout | **$7.50** | Current default if user never changes picker |
| Sonnet 4.6 throughout | $1.50 | Drop-Opus-only quick win |
| **Proposed hybrid (§3.1)** | **$1.10** | Phase-aware; security stays on Opus |
| All-OSS (Kimi backend + Qwen elsewhere) | $0.22 | Aggressive; loses design taste + security liability cover |

Hybrid retains the Opus-where-it-matters insurance for ~15% the Opus-everywhere cost.

## 5. Failover & resilience

`ProviderRouter` ([router.py](sopify-harness/plugins/sopify_providers/router.py)) handles cascade + 1 h blacklist on 401/403/429. Adapting it for an OSS-heavy world:

1. **Tier-aware fallback** — define each model assignment as `(primary, equivalent_fallback, anthropic_safety_net)`. Falling from `kimi-k2.6` to "any Hermes default" can land on a model that can't reliably tool-call; falling to `claude-sonnet-4-6` keeps capability constant.
2. **Provider-route diversification** — `kimi-k2.6` is reachable via Moonshot direct, OpenRouter, and Novita. Set Moonshot direct as primary, OpenRouter as fallback. ENCM already permits all three.
3. **Capability probe on first failure** — if primary throws a tool-call schema error (not 4xx), upgrade to Anthropic immediately for that session rather than waiting on the 1 h blacklist.
4. **Per-mode chain override** — settings.json gains `mode_chains: { "vibe.backend": ["moonshot", "openrouter", "anthropic"], ... }`. Honour at `ProviderRouter.from_settings`.

## 6. Migration plan

Atomic PRs against `main`, in order. Each is independently shippable and reversible.

### PR 1 — Reorder picker default (smallest blast radius)
Move `claude-sonnet-4-6` to the top of `_PROVIDER_MODELS["nous"]` ([models.py:165](sopify-harness/hermes_cli/models.py#L165)). Users who care about Opus still see it one row down. Effect: new users default to 1/5th cost.

### PR 2 — Pin auxiliary slots to Haiku
Add hard-coded defaults in [web_server.py:996](sopify-harness/hermes_cli/web_server.py#L996) (`title_generation`, `compression`, `session_search`, `curator`). Effect: ~30% of background spend drops to noise.

### PR 3 — Per-phase model in Vibe phase machine
Extend `_VIBE_BUILDING_PHASES` with a `model` field; thread through `_vibe_compose_system_prompt` and `pre_api_request`. Add 6 unit tests (one per phase). Effect: Vibe spend drops 70–80% per §4.

### PR 4 — Mode-specific defaults
`plugins/sopify_modes/{config,living,code_with_you}.py` declare their own primary model. Effect: mode-level cost predictable.

### PR 5 — Tier-aware fallback
Extend `ProviderRouter` with `(primary, fallback, safety_net)` tuples and `mode_chains` from settings.json. Migrate existing call sites to use the new API. Effect: OSS primary safe to ship to non-engineers without quality cliffs on outages.

### PR 6 — Picker UX
Add a "Recommended" badge for the proposed primary per use case. Dashboard `/api/model/options` endpoint already returns descriptions ([web_server.py:1009](sopify-harness/hermes_cli/web_server.py#L1009)) — extend the schema to include `recommended_for: ["vibe.backend", "code-with-you"]`.

## 7. Risks & where OSS still loses

| Risk | Severity | Mitigation |
|---|---|---|
| **Generic frontend output** ("AI slop" aesthetics) when downgrading design phase | Medium — user-perceptible | Keep design on Anthropic (Sonnet 4.6 minimum); enforce `frontend-design` skill |
| **Tool-call schema drift** on edge cases (deeply-nested JSON-schema tool defs) | Low–medium | Capability probe → auto-upgrade per §5.3 |
| **Provider downtime** (Moonshot, DeepSeek occasionally) | Low | Multi-route per §5.2 — three independent paths to Kimi K2.6 |
| **Refusal pattern surprises** (GLM family on certain Thai phrasings) | Low | GLM is fallback only, not primary, in proposed config |
| **OSS model deprecation faster than Anthropic** | Medium | Quarterly review (§8) + pin in `_PROVIDER_MODELS` makes deprecation visible at PR time |
| **Security review false negatives if downgraded** | High — liability | **Do not downgrade security phase**. Hard rule in §3.1. |
| **Pricing volatility** (OSS providers shift pricing more aggressively) | Low–medium | §4 numbers re-checked quarterly; migration PR template includes a current-pricing checkbox |

## 8. Monitoring & review cadence

- **Daily** — `/api/analytics/models` ([web_server.py:3315-3384](sopify-harness/hermes_cli/web_server.py#L3315)) shows per-model token volume. Watch for spend creeping back to Anthropic via fallbacks (signals an OSS primary is unreliable).
- **Per Vibe project completion** — attribute total spend by phase once PR 3 lands. Verify hybrid actually achieves the projected per-project cost in §4.
- **Quarterly** — refresh pricing in §4, re-evaluate new models. The OSS frontier moved twice in 2025 alone; this doc rots without a refresh cadence.
- **Per outage** — note in §5 fallback table which provider failed, for how long, and whether the safety-net Anthropic path activated cleanly.

---

## Appendix — Related code & docs

| File | Role |
|---|---|
| [hermes_cli/models.py](sopify-harness/hermes_cli/models.py) | `_PROVIDER_MODELS` curated lists + tool-call filter |
| [plugins/sopify_providers/router.py](sopify-harness/plugins/sopify_providers/router.py) | Cascade + blacklist |
| [plugins/sopify_providers/providers_registry.py](sopify-harness/plugins/sopify_providers/providers_registry.py) | UI-facing provider list + env-var mapping |
| [plugins/sopify_providers/auth.py](sopify-harness/plugins/sopify_providers/auth.py) | Per-provider API key storage (`~/.hermes/.env`, 0600) |
| [hermes_cli/web_server.py § /api/model/*](sopify-harness/hermes_cli/web_server.py#L911) | Model info / options / set endpoints |
| [hermes_cli/web_server.py § /api/analytics/*](sopify-harness/hermes_cli/web_server.py#L3315) | Per-model token analytics |
| [hermes_cli/web_server.py § Vibe phase machine](sopify-harness/hermes_cli/web_server.py#L5484) | Where per-phase model override lands |
| [prompts/vibe/base.md](sopify-harness/prompts/vibe/base.md) + [prompts/vibe/phases/](sopify-harness/prompts/vibe/phases/) | Per-phase system prompts |
| [website/static/api/model-catalog.json](sopify-harness/website/static/api/model-catalog.json) | Picker manifest (out-of-tree on `development`, lives on `main`) |
| [SYSTEM_ARCHITECTURE.md §15](SYSTEM_ARCHITECTURE.md#15-model-selection-strategy) | Architecture-level summary of this doc |
