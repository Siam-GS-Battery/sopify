# Sopify Grafana Dashboards

Grafana dashboards that satisfy **REQ-7.3** from `DESIGN_ARCHITECTURE.md`. They
read Sopify OpenTelemetry events that are shipped by **Grafana Alloy** into a
**Loki** (logs / structured events) + **Prometheus** (metrics) stack.

This directory only contains the dashboard JSON artifacts. The Alloy pipeline
that produces the labels these dashboards rely on lives separately.

## Dashboards

| File | Title | Satisfies | What it covers |
| --- | --- | --- | --- |
| `sopify-it-overview.json` | Sopify - IT Overview | REQ-7.3.1 | Fleet-wide IT view: cost/day (30d), active sessions (1h), top-10 users by cost, error rate gauge, and a tool-decision pie chart. |
| `sopify-user-audit.json` | Sopify - User Audit | REQ-7.3.2 | Per-user drill-down driven by `$user_email` + optional `$session_id`. Shows the full event timeline, every tool decision, hard-deny events highlighted red, an API-requests-by-model stacked bar chart, and a `user_prompt` table that is only meaningful when `log_user_prompts=true`. |
| `sopify-promotion-candidates.json` | Sopify - Promotion Candidates | REQ-7.3.3 | Surfaces `vibe`-mode `app_fingerprint`s used more than 3 times in the last 7 days, ranks them by cost, and tracks how the candidate funnel grows over time. |

All three dashboards are tagged `sopify` and `audit` (the promotion dashboard
also carries the `promotion` tag) and target Grafana **schemaVersion 39**
(Grafana 11.x).

## How to import

1. Open Grafana as an IT admin (see RBAC note below).
2. Go to **Dashboards -> New -> Import**.
3. Click **Upload JSON file** and pick one of the files in this directory, or
   open the file in your editor and paste the JSON into the **Import via panel
   json** textarea.
4. When prompted, map:
   - `DS_LOKI` -> your Loki datasource
   - `DS_PROMETHEUS` -> your Prometheus datasource
5. Click **Import**. Repeat for each of the three files.

Once imported you can also provision them by dropping the JSON into your
Grafana provisioning directory (typically `/etc/grafana/provisioning/dashboards/`)
and adding a provider entry that points at this folder.

## Required Alloy / Loki / Prometheus configuration

These dashboards expect the following pipeline to already be in place:

- **Grafana Alloy** receives OTel events from the Sopify hooks (OTLP/HTTP),
  splits them by event type (`user_prompt`, `tool_decision`, `api_request`,
  `api_error`, etc.), promotes a fixed set of fields to Loki labels
  (`event_type`, `user_email`, `session_id`, `sopify_mode`, `app_fingerprint`,
  `model`, `decision`, `tool_name`), forwards the structured JSON line to
  Loki, and emits Prometheus counters such as
  `sopify_api_request_cost_usd_total` and
  `sopify_api_request_cost_usd{user_email=...}`.
- **Loki** stores the JSON lines; the dashboards use `| json` parsing.
- **Prometheus** stores the cost counters used by the IT Overview cost panels.

> **TODO:** the Alloy river config lives at `infra/alloy/config.river`
> (separate ticket). That file is the single source of truth for label
> promotion and metric derivation - if you add a panel here that needs a new
> label, add the label there first.

## `log_user_prompts` gating (REQ-7.4.1)

REQ-7.4.1 requires that the literal text of user prompts is only persisted
when the operator explicitly sets `log_user_prompts=true` in Sopify config.
The gating happens **at the hook layer in the agent**, *before* events leave
the machine - so when the flag is off, prompt bodies never reach Alloy /
Loki at all.

Panels that depend on prompt bodies therefore go dark when the flag is off:

- **Sopify - User Audit** -> *User prompts* panel: rows will either be empty
  or show only structural metadata (timestamp, session_id, length) with no
  `prompt_text` column.
- **Sopify - User Audit** -> *Session timeline* (logs panel): `user_prompt`
  lines still appear, but the `prompt` / `prompt_text` field will be absent
  from the parsed JSON.

The count-style queries (active sessions, promotion candidates, API
requests by model, tool decisions, cost panels) are **unaffected** because
they only look at counts and labels, not at prompt bodies. This is the
intended privacy posture.

If you need to verify the flag's current value at a glance, add a stat
panel that reads the `sopify_log_user_prompts` gauge once it is exposed
by the hooks (out of scope for the initial dashboards).

## Access control (REQ-7.4.3)

These dashboards expose **per-user** activity, cost, and (when
`log_user_prompts=true`) prompt content. They are **IT-admin-only**.

Enforcement is via Grafana RBAC, not via anything in the JSON:

1. Create (or reuse) a Grafana team named `sopify-it-admins`.
2. Put the three dashboards in a folder named `Sopify` (or similar).
3. In **Folder permissions**, remove the default `Viewer` role and grant
   `View` (or `Edit`) only to the `sopify-it-admins` team.
4. Confirm that anonymous access and `Viewer`-role inheritance are both
   disabled for that folder.

If you provision Grafana declaratively, encode the same rules in your
`provisioning/access-control/` config so the permissions survive restarts.
