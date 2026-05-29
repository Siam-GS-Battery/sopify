## Phase: Verify (user-testing pass)

The app is wired end-to-end.  This phase is for the user to exercise it
in the dev-server preview while you stay on standby to fix what they hit.

### What you produce in this phase

1. **A short test plan** at the project root as `VERIFY_NOTES.md`
   (you can write this proactively, then update as the user reports):
   - The 5–10 user-flow happy paths the design phase implied
     (create order, view dashboard, submit form, …)
   - The 3–5 edge cases the mockup's error states cover (empty list,
     invalid input, network failure)
   - Known limitations / out-of-scope items (so the user does not
     report them as bugs)
2. **Fix patches** for whatever the user reports during testing —
   small, targeted, no scope creep.  Each fix should:
   - Reference the test step that failed
   - Keep changes scoped to one layer (frontend OR service OR DB)
   - Note any SOP-DEV-001 rule that the fix relies on

### What you DO NOT do in this phase

- Do not redesign anything — UI changes here are bug fixes, not
  improvements.  If the user wants a new feature, push back: "let's
  loop back to design after approval".
- Do not introduce new tables / endpoints / dependencies.
- Do not "polish" what works.  The `improvement` phase that follows is
  the right place for that.

### Done definition

The user has clicked through the test plan, every step passes (or has
been knowingly waived in `VERIFY_NOTES.md`), and they click **Looks
good**.  That advances the phase to `improvement` and the automated
review pipeline begins.
