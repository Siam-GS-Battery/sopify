# Vibe Code & Panel — Spec

> Authoritative spec for the Vibe Code flow and the free-form Panel chat: state
> machine, model assignment, port routing, compute separation, and per-state
> output artifacts. PR-001 promotes this from a draft note (`spec.md` outside
> the repo) into the canonical reference inside `sopify-harness/`.

Linked from [SYSTEM_ARCHITECTURE.md §8 — Vibe Code feature](../SYSTEM_ARCHITECTURE.md#8-vibe-code-feature).

---

## 1. Source intent (verbatim)

The user-provided draft, preserved here so future readers can trace decisions
back to the original wording.

```text
ส่วน Vibe Code จะมีแสดงดังนี้

1. State = Brainstorm
   Outcome : Markdown File Spec Driven Development / System Architecture
   (Frontend + Backend) / Task
   Set Model = Anthropic Sonnet

2. State = Design — เขียน Frontend; เมื่อเสร็จแล้ว Running Server (Vite) ->
   localhost:5174 จะต้องเปิด Panel ที่เป็นหน้า Frontend ที่เปิดจาก Server จริง
   บน Panel ด้านขวา
   What to show : Left = Chat (agent thinking + coding) / Right = Frontend
   Outcome : Vite Frontend Server -> Show Panel right hand side
   Set Model = Anthropic Sonnet

3. State = Backend — สร้าง Database บน Supabase บน Docker + Backend
   What to show : Left = Chat / Right = Frontend
   Outcome : Backend เชื่อมต่อ Supabase ได้ + Backend เปิด Server ได้ +
   Backend เชื่อมต่อ Frontend ได้ + Frontend Server ทำงานได้
   Set Model = Qwen

4. State = Improvement — Free form
   What to show : Left = Chat / Right = Frontend
   Outcome : (same as Backend)
   Set Model = Qwen

5. State = Security Review
   What to show : Left = security checklist / Right = Frontend
   Set Model = Anthropic Sonnet

6. State = Ready — Free Form (when User returns to Project)
   Set Model = Qwen

บนหน้า Vibe Code เขียนด้วยว่ามี Model ไหนใช้ตรงไหนบ้าง สามารถเปลี่ยนได้
จากบนหน้า Vertical ได้เลย

ส่วนหน้า Panel ให้ขึ้น Free Form Chat แต่ถ้ามีการเปิด Server ผ่าน Panel นี้เอง
ให้เปิด Panel ด้านขวา โดยจะต้องมีการ Code บอกว่าเปิดแบบ Static หรือ
Localhost:5173 แต่จะไม่เปิดตั้งแต่แรก แต่ถ้า Session ยังค้างก็ต้องเปิดอยู่

ทั้งคู่ควรมีการ Compute ที่แยกกัน ตัวอย่างเช่นกำลังรอให้ Agent Vibe Code
ก็สามารถไปคุย Chat บน Panel ได้

ดังนั้น
Panel จะแสดง Localhost:5173 (Fixed Port) และ Static  เป็น Panel ขวามือ
Vibe Coding จะแสดง Localhost:5174 (Port Run On) เป็น Panel ขวามือ

ส่วนการ Vibe Code เมื่อมีการ Change จาก project นี้ ไป Project ใหม่
จะถือว่าคนละ State กัน แต่ Background จะยังคงต้องมี Runtime Task Background
ได้อยู่ หากมีการ Running Server จะต้อง Running Port 517x ไปเรื่อย ๆ

ส่วนการ Panel ถ้ามีการเข้า State ใหม่จะต้อง Kill Port 5173 เพื่อเปิด 5173
```

---

## 2. State machine (Vibe Code)

Six lifecycle states. Phase keys must stay in sync with
[`VIBE_STEP_KEYS`](../web/src/components/vibe/VerticalStepper.tsx#L104) and the
backend `VibePhase` enum.

| # | State          | Default model        | Driving skill(s)                                                                                                                         | Left pane                         | Right pane                        | Output artifact                                                          |
|---|----------------|----------------------|------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------|-----------------------------------|--------------------------------------------------------------------------|
| 1 | `brainstorm`   | `anthropic/sonnet`   | (none — agent reasons from `brief.md`)                                                                                                   | Chat                              | (none — chat-only)                | `REQUIREMENTS.md` ¹                                                      |
| 2 | `design`       | `anthropic/sonnet`   | [`sopify-sdlc-design`](../skills/sopify-sdlc-design/SKILL.md)                                                                            | Chat                              | **Frontend @ `localhost:5174`**   | `DESIGN.md` + static frontend on Vite port 5174                          |
| 3 | `backend`      | `qwen`               | [`sopify-sdlc-database`](../skills/sopify-sdlc-database/SKILL.md) → [`sopify-sdlc-backend`](../skills/sopify-sdlc-backend/SKILL.md)        | Chat                              | Frontend                          | `DATABASE.md`, `API.md`, Supabase on Docker, backend ↔ frontend wired up |
| 4 | `improvement`  | `qwen`               | [`sopify-sdlc-design`](../skills/sopify-sdlc-design/SKILL.md) + [`sopify-sdlc-backend`](../skills/sopify-sdlc-backend/SKILL.md)            | Chat                              | Frontend                          | Updates to any of the above; free-form iteration                         |
| 5 | `security`     | `anthropic/sonnet`   | (security review prompt; see `prompts/vibe/phases/security.md`)                                                                          | **Security checklist (not chat)** | Frontend                          | `SECURITY_REVIEW.md` + checklist marks                                   |
| 6 | `ready` / done | `qwen`               | (free-form — any of the above on demand)                                                                                                 | Free-form chat                    | Frontend                          | Whatever the user iterates on after final approval                       |

¹ The user's source draft (§1) names brainstorm outputs as *Spec / System
Architecture / Task* (three files). The current implementation produces a
single curated `REQUIREMENTS.md`. PR-011 will reconcile this — either by
splitting into three files or by having `REQUIREMENTS.md` contain all three
sections explicitly.

**Transition rules.**
- Forward-only by default. Backward jumps are allowed but warn.
- Switching to a different project does **not** advance the source project's
  state — see §5 on background runtime.
- Skill auto-load: the phase prompt names the skill(s) above; the
  `claude-code` host loads them at phase entry. The split into per-phase
  skills was introduced in commit `066d23157` (PR #24) — older prompts that
  reference the bundled `sopify-sdlc` will be updated alongside PR-004.

---

## 3. Model assignment

- Each phase has a **default model** (table §2).
- Defaults can be overridden **per project, per phase** via the Vertical
  stepper UI (model badge next to each step → dropdown → save).
- Persisted as `model_per_phase` map on the project marker. Missing keys fall
  back to the table defaults.
- API contract (PR-002): `GET/PUT /api/vibe/projects/{name}/models`.
- The selected model is applied when starting/resuming the agent for that
  phase — `chat_start` parameter, not a post-hoc switch.

---

## 4. Port routing

Two separate right-pane preview surfaces with **fixed ports**:

| Surface            | Port                    | Lifecycle                                         |
|--------------------|-------------------------|---------------------------------------------------|
| **Vibe Code page** | `localhost:5174`        | Started by the project (e.g. `vite --port 5174`). Stays up while the project's runtime is alive. |
| **Panel page**     | `localhost:5173`        | Fixed. **Kill-then-respawn** on every Panel state transition.                                    |

Other 517x ports remain published by the sandbox
([sbx_launcher.py:298](../plugins/sopify_sandbox/sbx_launcher.py#L298)) so
ad-hoc dev servers still work; the right-pane filter just hardcodes 5174
(Vibe) / 5173 (Panel).

**Panel preview is NOT auto-opened.** First Panel load → chat only. The user
must invoke "Open Preview" which prompts: **Static** (served file tree) vs
**Localhost:5173**. If the session is resumed and the preview was previously
open, restore it.

---

## 5. Background runtime

Switching between Vibe Code projects is a **state change in the UI**, but
**does not kill** the project's runtime processes. A project that has a server
running on a 517x port keeps running in the background; coming back to it
re-attaches.

- Runtime registry: tracked by project name → process IDs + ports.
- Endpoint (PR-007): `GET /api/vibe/runtimes` returns the live list.
- Cleanup: explicit user action ("Stop server") or sandbox teardown only.

The Panel page is the exception: entering a new Panel state **kills 5173**
before reopening it (PR-008).

---

## 6. Compute separation

The Panel chat and the Vibe Code agent run on **independent sessions**. The
user can chat in the Panel while the Vibe Code agent is mid-turn.

- Vibe Code session IDs: keyed by project name
  (`localStorage["sopify:vibeSessionId:" + projectName]`).
- Panel session ID: single, global (`localStorage["sopify:panelSessionId"]`).
- Backend already supports concurrent agent sessions
  ([tui_gateway/server.py](../tui_gateway/server.py)); PR-009 wires the
  frontend to actually use separate IDs.

---

## 7. UI surfacing of model assignment

- Each step in the [Vertical
  stepper](../web/src/components/vibe/VerticalStepper.tsx) shows the active
  model as a small badge next to the title.
- Click the badge → dropdown listing available models (from `/api/models`).
- Change applies immediately and is persisted via PUT
  `/api/vibe/projects/{name}/models`.

---

## 8. Non-goals (out of scope for this spec)

- Choosing the *exact* model SKU (e.g. `claude-sonnet-4-7` vs `4-6`). Phase
  defaults reference the provider/family; the active SKU is set globally in
  `MODEL_SELECTION.md`.
- Adding new states beyond the six listed. The state machine is closed for
  this spec.
- Cross-project chat history sharing. Each project is isolated.

---

## 9. PR slicing (implementation roadmap)

This spec is delivered across atomic PRs against `main`. Each merges before
the next starts.

| PR    | Slice                                                          |
|-------|----------------------------------------------------------------|
| 001   | **This file** — spec lands in repo, no behavior change         |
| 002   | Backend: per-phase model config + GET/PUT endpoint             |
| 003   | Frontend: model badge in VerticalStepper, click-to-change      |
| 004   | Wire selected model into chat start per phase                  |
| 005   | Vibe Code right pane → fixed `localhost:5174`                  |
| 006   | Panel right pane → fixed `localhost:5173` + default-closed     |
| 007   | Background runtime registry + `/api/vibe/runtimes`             |
| 008   | Panel state change → kill 5173 + reopen                        |
| 009   | Separate session pools (Vibe vs Panel)                         |
| 010   | Security phase: checklist UI on the left                       |
| 011   | Brainstorm output: reconcile REQUIREMENTS.md vs Spec/Arch/Tasks |
