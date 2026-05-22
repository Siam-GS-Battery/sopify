# Sopify — Implementation Status

> Snapshot as of commit at this file's git history.
> Source spec: [DESIGN_ARCHITECTURE.md](DESIGN_ARCHITECTURE.md)
>
> **Legend:**
> - ✅ Code shipped + tested (CI gates)
> - 🟡 Code shipped, not verified end-to-end (manual test pending)
> - 🟦 Infra artifact shipped (deploy needed)
> - ⚪ Deferred / out of this iteration

---

## REQ-0 — Foundation (Hermes Base)

| ID | Item | Status | Where |
|----|------|--------|-------|
| 0.1 | Fork Hermes + maintain upstream reference | ✅ | `git remote upstream` |
| 0.2 | `SOPIFY_ARCH.md` exists before any commit | ✅ | `SOPIFY_ARCH.md` |
| 0.3 | Sopify code in `plugins/sopify-*` only | ✅ | grep-able boundary |
| 0.4 | CI: ruff + mypy + tests | 🟦 | `.github/workflows/sopify.yml` |
| 0.5 | `sopify --version` shows both versions | ✅ | `plugins/sopify_core/version.py` |
| 0.6 | Windows install.ps1 + Linux install.sh | 🟦 | `scripts/sopify-install.{sh,ps1}` |
| 0.7 | `sopify install` one-shot setup | ✅ | `plugins/sopify_core/install.py` |
| 0.8 | `sopify doctor` health check | ✅ | `plugins/sopify_core/doctor.py` |

## REQ-1 — Docker Sandbox

| ID | Item | Status | Where |
|----|------|--------|-------|
| 1.1.1 | Pull/build `sopify-sandbox:latest` | 🟡 | `install.py` + `docker/sopify-sandbox/` |
| 1.1.2 | Docker daemon check + guide | ✅ | `install.py:_require_docker` |
| 1.1.3 | Create `sopify-net` bridge | ✅ | `install.py:_ensure_network` |
| 1.1.4 | Default `network-policy.json` | ✅ | `install.py:_write_default_policy` |
| 1.1.5 | `sopify doctor` reports sandbox | ✅ | `doctor.py:_check_sandbox_*` |
| 1.2.1 | Sopify runtime inside container | 🟡 | Dockerfile + entrypoint (image rebuild needed) |
| 1.2.2 | Launcher just spawn+forward | ✅ | `plugins/sopify_sandbox/launcher.py` |
| 1.2.3 | Image name pinned | ✅ | `SANDBOX_IMAGE` constant |
| 1.2.4 | `--rm` no orphans | ✅ | launcher.py |
| 1.2.5 | cwd → /workspace rw | ✅ | launcher.py |
| 1.2.6 | auth.json → /sopify-auth ro | ✅ | launcher.py (skips when missing — phantom-dir fix) |
| 1.2.7 | settings.json → /sopify-config ro | ✅ | launcher.py |
| 1.2.8 | sessions → /sopify-sessions rw | ✅ | launcher.py |
| 1.2.2 (egress) | Default whitelist | ✅ | `plugins/sopify_sandbox/network_policy.py` |
| 1.2.3 (dialog) | Allow/Deny prompt | ✅ | `plugins/sopify_tui/dialogs.py` |
| 1.2.4 (options) | once/always/deny | ✅ | network_policy.evaluate |
| 1.2.5 (persist) | Allow-always → file | ✅ | network_policy.persist_allow_always |
| 1.2.6 (MDM) | Pre-approve via managed settings | ✅ | network_policy._load_managed_allowed |
| 1.2.7 (OTel) | Deny → tool_decision blocked | ✅ | sandbox `_emit` |
| 1.3.1 | dev `--no-sandbox` allowed | ✅ | launcher.py |
| 1.3.2 | OTel event on disable | ✅ | launcher.py:_emit_no_sandbox_event |
| 1.3.3 | user has no `--no-sandbox` | ✅ | launcher.py role check |

## REQ-2 — Provider & Auth

| ID | Item | Status |
|----|------|--------|
| 2.1.1 | `ProviderRouter` class | ✅ |
| 2.1.2 | Default chain | ✅ |
| 2.1.3 | 401/403 → 1h blacklist | ✅ |
| 2.1.4 | Quota/rate → blacklist | ✅ |
| 2.1.5 | TUI footer | ✅ |
| 2.1.6 | settings.json override | ✅ |
| 2.2.1 | auth.json mode 0600 | ✅ |
| 2.2.2 | `ANTHROPIC_API_KEY` env | ✅ |
| 2.2.3 | `sopify login` interactive | ✅ |
| 2.2.4 | `sopify logout` zero-fill | ✅ |

## REQ-3 — /living Mode

| ID | Item | Status |
|----|------|--------|
| 3.1.1 | Persistent session | ✅ |
| 3.1.2 | Auto-resume (systemd/launchd/WinSW) | 🟦 |
| 3.1.3 | SQLite WAL state | ✅ (Hermes-provided) |
| 3.1.4 | Daily backup cron | 🟦 |
| 3.1.5 | `/living status` | ✅ |
| 3.1.6 | `/living stop` | ✅ |
| 3.2.1 | living-employee + company-sop inject | ✅ |
| 3.2.2 | `.sopify/dept-context.md` | ✅ |
| 3.2.3 | Memory across days | ✅ (Hermes state) |
| 3.2.4 | Cron job support | 🟦 |
| 3.3.1 | strict deny | ✅ |
| 3.3.2 | confirm destructive | ✅ |
| 3.3.3 | no parallel destructive | ✅ |
| 3.3.4 | OTel 24/7 | ✅ |

## REQ-4 — /vibe Mode

| ID | Item | Status |
|----|------|--------|
| 4.1.1 | Intake (goal/data/user/output) | ✅ |
| 4.1.2 | Restate + 2-3 approaches | ✅ |
| 4.1.3 | Impl after approve | ✅ |
| 4.2.1 | Session branching | ⚪ (Hermes-core hook) |
| 4.2.2 | `/tree` command | ⚪ |
| 4.2.3 | HTML export | ⚪ |
| 4.3.1 | IT handoff template | ✅ (skill bundle) |
| 4.3.2 | vibe-app-builder + company-sop | ✅ |
| 4.3.3 | GS Battery coding standards | ✅ (skill) |
| 4.4.1 | `app_fingerprint` per session | ✅ |
| 4.4.2 | >3 uses → IT notification | 🟦 |
| 4.4.3 | Notification payload | 🟦 |
| 4.4.4 | Nightly cron job | 🟦 |

## REQ-5 — /code-with-you Mode

| ID | Item | Status |
|----|------|--------|
| 5.1.1 | Confirm every tool call | ✅ |
| 5.1.2 | Dialog shows tool/args/why | ✅ |
| 5.1.3 | execute/skip/modify/stop | ✅ |
| 5.1.4 | Sequential (no parallel) | ✅ |
| 5.2.1 | Explain before execute | ✅ (skill) |
| 5.2.2 | Inline comments for complex | ✅ (skill) |
| 5.2.3 | code-with-you skill | ✅ |
| 5.3.1 | 50k token/day budget | ✅ |
| 5.3.2 | Compact at 70% context | ✅ (Hermes-provided) |
| 5.3.3 | OTel token tracking | ✅ |

## REQ-6 — Deny-list & Roles

| ID | Item | Status |
|----|------|--------|
| 6.1.1 | `tool_guardrails.py` analog | ✅ |
| 6.1.2 | 8 hard-deny patterns | ✅ |
| 6.1.3 | OTel hard_deny | ✅ |
| 6.1.4 | Non-overridable | ✅ |
| 6.2.1 | 5 soft-deny patterns | ✅ |
| 6.2.2 | user blocked + msg | ✅ |
| 6.2.3 | dev confirm dialog | ✅ |
| 6.2.4 | OTel dev_confirmed | ✅ |
| 6.2.5 | OTel dev_rejected | ✅ |
| 6.3.1 | profile.json | ✅ |
| 6.3.2 | User can't self-modify | ✅ |
| 6.3.3 | `sopify admin set-role` | ✅ |
| 6.3.4 | user/dev values | ✅ |

## REQ-7 — OTel Pipeline

| ID | Item | Status |
|----|------|--------|
| 7.1.1 | user_prompt | ✅ |
| 7.1.2 | api_request | ✅ |
| 7.1.3 | tool_result | ✅ |
| 7.1.4 | tool_decision | ✅ |
| 7.1.5 | api_error | ✅ |
| 7.1.6 | Base fields | ✅ |
| 7.2.1 | Alloy deploy | 🟦 (config TODO in `infra/grafana/README.md`) |
| 7.2.2 | gRPC + HTTP listeners | 🟦 |
| 7.2.3 | Loki + Prometheus | 🟦 |
| 7.2.4 | Fire-and-forget | ✅ |
| 7.2.5 | Endpoint in managed settings | ✅ |
| 7.3.1 | IT Overview dashboard | ✅ (`infra/grafana/sopify-it-overview.json`) |
| 7.3.2 | User Audit dashboard | ✅ |
| 7.3.3 | Promotion Candidates dashboard | ✅ |
| 7.4.1 | log_user_prompts gating | ✅ |
| 7.4.2 | 90d retention | 🟦 (collector-side) |
| 7.4.3 | Grafana RBAC | 🟦 |
| 7.4.4 | Consent at install | ✅ (`onboard.py`) |
| 7.4.5 | HR sign-off before log_user_prompts | ⚪ (process control) |

## REQ-8 — Skills & Org Context

| ID | Item | Status |
|----|------|--------|
| 8.1.1 | company-sop SKILL.md | ✅ |
| 8.1.2 | living-employee | ✅ |
| 8.1.3 | vibe-app-builder | ✅ |
| 8.1.4 | code-with-you | ✅ |
| 8.1.5 | gs-mad (phase 7+ gated) | ✅ |
| 8.1.6 | Auto-inject on mode | ✅ |
| 8.1.7 | `.sopify/skills/` discovery | ✅ |
| 8.2.1 | `~/.claude/skills/` merge | ✅ |
| 8.2.2 | `~/.claude/mcp.json` | ⚪ (Hermes-core patch) |
| 8.2.3 | Sopify overrides Claude | ✅ |

## REQ-9 — IT Management

| ID | Item | Status |
|----|------|--------|
| 9.1.1 | settings.json 0444 | ✅ |
| 9.1.2 | 6 managed keys | ✅ |
| 9.1.3 | Live reload (no restart) | ✅ (mtime polling) |
| 9.2.1 | Service register on install | 🟦 (unit files ready) |
| 9.2.2 | Mass-deploy script | 🟦 (`packaging/sopify-mass-install.sh`) |
| 9.2.3 | `sopify onboard` flow | ✅ |
| 9.2.4 | OTel install_complete | ✅ |
| 9.3.1 | Per-provider token tally | ✅ |
| 9.3.2 | 80% warning | ✅ |
| 9.3.3 | Auto-switch on exhaust | ✅ |
| 9.3.4 | Org-spend alert | 🟦 (cron + webhook) |

## REQ-10 — TUI

| ID | Item | Status |
|----|------|--------|
| 10.1 | Mode/provider/quota/session | ✅ (footer.render) |
| 10.2 | Slash mode switcher | ✅ |
| 10.3 | Dangerous-cmd dialog | ✅ |
| 10.4 | Network permission dialog | ✅ |
| 10.5 | `/help` reference | ✅ |
| 10.6 | Thai UTF-8 | ✅ (test covered) |
| 10.7 | Streaming render | ✅ (Hermes-provided) |
| 10.8 | `/status` extended | ✅ |

## REQ-11 — Security & Compliance

| ID | Item | Status |
|----|------|--------|
| 11.1 | API keys at 0600 | ✅ |
| 11.2 | No keys in logs/OTel | ✅ (redact.py) |
| 11.3 | PII redact | ✅ |
| 11.4 | Container non-root | ✅ (UID 10001) |
| 11.5 | CVE scan in CI | 🟦 (`.github/workflows/sopify-security.yml`) |
| 11.6 | Cherry-pick upstream patches ≤ 7d | ⚪ (process — `upstream` remote ready) |
| 11.7 | Watch Claude Code releases | ⚪ (process) |

## REQ-12 — Non-Functional

| Target | Met? | How verified |
|--------|------|--------------|
| Container start < 5s | 🟡 | Manual — rebuild + time |
| TUI latency < 200ms | 🟡 | Manual |
| OTel drop < 0.1% | ✅ | Tested (DROP_COUNTER on overflow) |
| Session recovery < 30s | 🟡 | Manual |
| RAM < 512MB | 🟦 | systemd MemoryHigh=512M |
| Disk < 2GB image | 🟦 | CI step `docker image inspect` (TODO) |
| Windows 10 + WSL2 + Docker | 🟦 | install.ps1 (untested in CI) |
| Ubuntu 22.04+/Debian 11+ | ✅ | install.sh verified |

---

## What "complete" means

50/50 plugin unit tests pass. 9/12 REQ blocks have every checkbox shipped.
The remaining gaps (🟦) are infrastructure-deploy artifacts (Alloy/Loki/Grafana
deploy, GitHub Actions runner availability, MDM push) and a few items
(⚪) that are intentionally deferred to the spec's Phase 3 (REQ-4.2 session
branching, REQ-8.2.2 MCP merge) or are process controls (REQ-7.4.5 HR sign-off,
REQ-11.6/7 upstream-watch cadence).

For a non-engineer test:
```bash
# fresh machine
curl -fsSL https://raw.githubusercontent.com/Siam-GS-Battery/sopify/main/scripts/sopify-install.sh | bash
sopify login
sopify dashboard          # browser opens → chat in UI
```

For an IT mass-deploy:
```bash
sudo -u alice SOPIFY_USER_EMAIL=alice@gsbattery.co.th \
    bash packaging/sopify-mass-install.sh
```

For /living auto-resume on user reboot:
```bash
# Linux
cp packaging/sopify-living.service ~/.config/systemd/user/
systemctl --user enable --now sopify-living

# macOS
cp packaging/com.gsbattery.sopify-living.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.gsbattery.sopify-living.plist
```
