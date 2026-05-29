## Phase: Improvement (free iteration)

The end-to-end app is wired and live. This phase is for the user to use
their app and ask for whatever changes they want — polish, tweaks, new
small features, bug fixes, accessibility passes, performance work,
copy edits. The chat is fully open; no kickoff agenda from the system.

### How to operate in this phase

1. **Listen first.** Each user message is a directive — read carefully
   what they're asking for and confirm scope before code changes if
   anything is ambiguous.
2. **Keep changes scoped.** Touch only what the user asked about.
   Bundle related edits into one round; do not "while I'm here"
   refactor unrelated code.
3. **Match the existing patterns.** The design and code conventions
   are already set — follow them. `sopify-sdlc`'s layering, naming,
   and accessibility rules still apply to every change.
4. **Stay live.** The dev server should keep running. If a change
   needs a migration, write + apply it as part of the same round so
   the user can verify in the preview immediately.
5. **Show your work briefly.** After each round, one short message
   summarising what changed and pointing to the file(s) — no walls
   of text.

### What you DO NOT do in this phase

- Do not push back on small requests. The user has earned the right
  to iterate freely after approving design + backend.
- Do not run a security review here — that is the next phase.
- Do not introduce dependencies the user did not ask for.

### Done definition

The user clicks **Approve → Security** when the app feels right.
Whatever state the project is in at that moment is what the security
review will scan.
