# Changelog

All notable changes to galangal-orchestrate are documented here. This project
uses [semantic versioning](https://semver.org/) loosely (0.x, minor = features,
patch = fixes).

## 0.57.0 — Headless peer review

- **Peer review now runs in headless mode** (previously skipped entirely). With no
  interactive user, only the auto-accept path is available: on `REQUEST_CHANGES`
  the stage re-runs with the reviewer's feedback up to `max_auto_loops` times, then
  the workflow proceeds with the stage as-is rather than deadlocking. If the reviewer
  backend is unavailable it degrades to APPROVE (as before). Enabled by the engine
  consolidation in 0.56 (`accept_peer_review_feedback`).

## 0.56.0 — Peer-review state mutation moved onto the engine

Follow-up to the resolver consolidation. The peer-review "accept feedback and
re-run the stage" logic was stranded as a state-mutating helper inside the *TUI*
runner — invisible to the headless runner and untestable without the TUI.

- **`WorkflowEngine.accept_peer_review_feedback(review_notes, user_guidance=None)`**
  now owns archiving the review artifact to `{STAGE}_PEER_REVIEW_PREV.md` and
  queuing the feedback (`last_failure`) for the stage re-run — the peer-review
  counterpart to `plan_rollback_skips` (which the rollback path got in 0.55).
  The TUI runner delegates to it; the stranded `_accept_reviewer_feedback` helper
  is gone.
- Note on the broader "unify the two review concepts" idea: peer review and the
  REVIEW stage are intentionally *different* mechanisms — peer review re-runs the
  **same** producing stage with an independent second opinion, while REVIEW rolls
  back to an **earlier** stage. They are deliberately not merged; this change just
  removes the duplicated/stranded state logic and makes it testable. (Peer review is
  still skipped in headless mode — a known gap, left as-is to avoid a blind
  behavior change.)
- Tests: existing auto-accept tests now assert the delegation; added direct engine
  tests for `accept_peer_review_feedback`.

## 0.55.0 — Resolver consolidation + engine test harness

Internal refactor (behavior-preserving) plus its safety net.

- **Rollback skip planning consolidated:** the three-branch fast-track logic
  (REVIEW→DEV iteration loop / minor fast-track / full rollback) that was inlined
  in `handle_rollback` now lives in one `WorkflowState.plan_rollback_skips()`
  method, alongside the other fast-track helpers — the mirror of `get_next_stage`
  for the rollback path. The review-iteration *exit* logic is likewise extracted to
  `complete_review_iteration()`, so both sides of that state machine are named
  methods on the state object rather than scattered flag mutations.
- **AI-free engine simulation harness** (`tests/workflow_harness.py` +
  `tests/test_workflow_engine_sim.py`, 10 scenarios): drives the real engine through
  scripted per-stage outcomes by patching the single `_execute_stage` seam, pinning
  stage advancement, all three rollback branches, REDESIGN routing, task-type fast
  paths, and the rollback cap (and its REVIEW↔DEV exemption). This is the regression
  net that made the consolidation safe — every stage trace is identical before/after.

## 0.54.0 — Workflow & prompt design improvements

- **REVIEW prompt rewritten:** genericized (removed one project's AsyncPG/JSONB
  specifics that were shipped to everyone), and it now blocks (`REQUEST_CHANGES`)
  only on genuine correctness/security/maintainability defects — style, formatting,
  typos, unused imports, and missing type hints are recorded as non-blocking
  Suggestions instead of triggering an expensive DEV↔REVIEW loop.
- **REDESIGN rollback target:** REVIEW and SECURITY can now return `REDESIGN`, which
  rolls back to **DESIGN** (not DEV) for architectural problems, so a flawed approach
  is reconsidered rather than band-aided in DEV. DESIGN now receives `ROLLBACK.md` and
  the prior `DESIGN.md` so it revises instead of regenerating blind.
- **TEST_GATE runs inside the DEV↔REVIEW loop** (when enabled), so a regression
  introduced by a review fix is caught immediately rather than only after REVIEW
  approves and the full pipeline re-runs.
- **QA acceptance-criteria traceability:** the QA report now requires a per-criterion
  table (criterion verbatim → verdict → concrete evidence), and overall PASS requires
  every criterion to pass — replacing the loose holistic checkbox.
- **Configurable per-task-type fast path:** `task_type_settings.<type>.skip_stages`
  lets a project prune stages for a faster pipeline (on top of the built-in
  per-type defaults; PM/DEV/COMPLETE are never skippable).

## 0.53.0 — Hub hardening (round 2)

- **Agent-identity protection:** the connection manager no longer lets a
  registration silently displace a *live* connection under the same `agent_id`
  (a key-holder can't hijack another agent's control channel, and two
  mis-configured agents can't clobber each other). A dead/stale connection is
  still taken over, so legitimate reconnects work. The server rejects the
  duplicate registration with a clear error.
- **Process manager:** start operations are serialized with a lock (the
  check-then-spawn was racy and could orphan duplicate processes), a concurrent
  process cap bounds resource use, and dead port-allocation code was removed.

## 0.52.0 — Hub security hardening

**Security release for the Galangal Hub.** A default-config hub was an
unauthenticated, internet-exposed control plane with remote-code-execution paths.

> ⚠️ **Behavior change:** `galangal-hub serve` now binds `127.0.0.1` by default and
> **refuses to bind a non-loopback interface unless authentication is configured**
> (`HUB_API_KEY` and/or `HUB_USERNAME`+`HUB_PASSWORD`), or you set
> `HUB_ALLOW_INSECURE=1` (only behind a trusted proxy/firewall/Tailscale).

Critical:
- **API auth is now actually enforced.** Every `/api` router (actions, tasks,
  agents, environments) requires auth — accepting an API key (agents) or a session
  cookie (dashboard). Previously the auth helpers existed but were never wired up.
- **The interactive terminal WebSocket** (`/ws/claude-accounts/{id}/terminal`, which
  forks a host shell) now authenticates before accepting.
- **Session tokens are HMAC-signed with an expiry** and verified; the old check
  accepted any 64-char string. Secret is stable via `HUB_SECRET_KEY`/`HUB_SESSION_SECRET`.
- **The dashboard WebSocket** now authenticates (session cookie / key) before accept.

High:
- All secret comparisons use `hmac.compare_digest`; the query-param API-key fallback
  (which leaks into logs) was removed; dashboard passwords use salted scrypt.
- Git clone/checkout validate the URL (block `file://`/`ext::`/local paths → SSRF /
  file exfiltration) and branch name (block option injection), with `--` separators
  and `protocol.ext/file` disabled.
- The auto-generated credential key is written `0600` with a warning; arbitrary
  `HUB_SECRET_KEY` is stretched with scrypt instead of a single SHA-256.

Medium:
- WebSocket message-size and dashboard-connection caps; the dashboard connection list
  is now lock-guarded; the prompt-context broadcast no longer assumes a dict.
- Secret-bearing process commands are no longer logged in full; credential redaction
  never shows a prefix and only reveals the last 4 chars of long values.
- Multi-statement artifact writes in hub storage are serialized with a lock.
- The hub client keeps a reference to its reconnect task (was GC-able), uses capped
  exponential backoff + jitter, cancels stale loops on reconnect, and reconnects on
  send failure (not just receive).
- Environment names are validated to a safe path segment (no traversal into `rmtree`).

## 0.51.0

Artifact and git data-integrity hardening (follow-up to the disk↔DB fix in 0.50):

- **Name-reuse bleed:** deleting a task now clears its artifacts (`is_present=0`),
  so a new task reusing the name no longer inherits the old task's SPEC/PLAN.
- **Deleted-artifact resurrection:** `record_artifact_delete` now always removes
  the on-disk copy, so the next ingest can't flip a "deleted" artifact back to present.
- **Done-task divergence:** ingest and rehydrate now resolve the task dir the same
  way as mirroring (done dir takes precedence), so re-entering a finalized task
  doesn't diverge.
- **Encoding:** all artifact reads/writes in the task index are UTF-8 with
  `errors="replace"`; a non-UTF-8 file no longer aborts the whole post-stage ingest.
- **Squash safety:** `squash_to_base` now verifies the base is an ancestor of HEAD
  before the soft reset (a stale base after a rebase/branch-switch would otherwise
  collapse unrelated commits), and `_squash_stage_commits` actually falls back to a
  plain commit instead of leaving work uncommitted.
- **Finalize:** a failed commit/squash now aborts and restores the task (even in
  TUI/headless/force mode) instead of pushing and opening a PR against an
  empty/wrong branch.
- **Archive restore:** path-traversal-safe tar extraction and a guard against
  clobbering an existing task in `done/`.
- **WIP commits:** per-stage commit tracking is deduped by stage, so REVIEW→DEV
  iterations no longer pile up duplicate entries.

## 0.50.0

- **Artifact rehydration (disk↔DB consistency):** before each stage runs, the
  canonical DB artifacts are now materialized back to the task's working directory.
  Previously, non-mirrored artifacts (everything except `PLAN.md`/`SUMMARY.md`) were
  deleted from disk after each stage's ingest and never restored, so on a re-run the
  agent saw only a partial subset on disk and could regenerate artifacts that already
  existed in the DB — e.g. an agent re-authoring `SPEC.md` because it "couldn't find
  it on disk," even though it was safe in `.galangal/tasks.db`. The agent's filesystem
  view now matches canonical storage.

## 0.49.0

- **doctor:** now checks the CLI for the *active* backend(s) (default + per-stage),
  not just hardcoded `claude` — a gemini/codex profile no longer passes while its
  binary is missing.
- **init --quick:** truly non-interactive — defaults the project name to the
  directory name when there's no TTY (for CI/automation) instead of prompting.
- **Config errors:** invalid `config.yaml` now reports field-by-field issues
  instead of dumping the raw pydantic error.
- **Mistake tracking:** the table is now pruned (stale single-occurrence entries
  age out; a hard cap bounds total rows).
- **Tests:** added CLI parser/dispatch tests (`test_cli.py`) via an extracted
  `build_parser()`, and made the `status` command tests hermetic.
- **Docs:** documented the full config/CLI surface and added this changelog
  (see also the `docs/guide/` updates).

## 0.48.0

- **Prompt efficiency:** per-attempt content (attempt number, previous failure)
  moved to a trailer at the end of the stage prompt so the large artifact/context
  prefix is stable across retries (cache-friendly) and no longer duplicated. Any
  single artifact block is capped at ~4k tokens in the prompt (full version stays
  on disk).

## 0.47.0

- **Lineage:** validator and lineage tracker now share one robust section-name
  normalizer, so decorated/numbered headers (`## 1. File Changes`) no longer make
  staleness detection silently fail open. Staleness rollbacks feed the section-level
  change reasons into the re-running stage's prompt.
- **Mistake tracking:** fixed the stage-filtered vector query, added recency-decayed
  ranking, wired file-pattern context end-to-end, reuse a process-wide tracker
  (model loads once), and log once when falling back from `sqlite-vss`.

## 0.46.0

- **Rollback loops:** added an absolute per-stage rollback cap over the whole task
  in addition to the 1-hour window (the window alone missed slow loops).
- **Model tiers:** new opt-in `ai.auto_model_tiers` routes mechanical stages
  (TEST/QA/DOCS/SUMMARY) to cheaper models; explicit `stage_models` / pinned model win.

## 0.45.0

- **Schema in prompts:** stage prompts now include the required artifact structure
  up front, so deterministic schema-validation failures don't cost a full retry.
- **Robust section matching:** validation tolerates numbered/decorated/bold headers,
  eliminating false "missing required section" failures.

## 0.44.0

- **Lean install:** `sentence-transformers`/`sqlite-vss` moved out of core deps into
  a `[full]` extra. `pip install "galangal-orchestrate[full]"` for mistake tracking.
- **Non-interactive start:** `--type` now works (skips the picker); new `--headless`
  flag creates and runs a task without the TUI (CI/scripts).
- **Fail-closed peer review:** a reviewer that ran but produced unparseable output is
  treated as `REQUEST_CHANGES`, not a silent approval. Tolerant JSON parsing for
  read-only backend output (code fences / prose no longer discard the result).
- **Exit codes:** `complete` exits `2` when finalized without a PR; `reset` exits `0`
  when the confirmation is declined.

## 0.43.0

- Added a **"Provide guidance & retry"** option to the stage-failure modals
  (`MAX_RETRIES_EXCEEDED`, `ROLLBACK_BLOCKED`): free-text guidance is fed into the
  next same-stage attempt.

## 0.42.0

- **REVIEW→DEV check-in:** new `stages.review_iteration_ask_after` (default 3)
  surfaces the outstanding review notes and asks for guidance after that many
  round-trips, instead of looping indefinitely.

## 0.41.0

- **Peer-review escape hatch:** new `peer_review.ask_user_after_loops` (default 2)
  surfaces the disagreement early; a "Provide guidance & continue" option feeds your
  steer into the re-run.

## 0.40.0

- Hardening: atomic `state.json` writes; staleness rollback clears fast-track skip;
  REVIEW pass/fail markers anchored to decision lines; codex/gemini status scanning
  scoped to the output tail; process-group kills for TEST_GATE and `generate_text`;
  honest `squash_to_base` failure reporting; SSRF guard on issue-image downloads.

## 0.39.0

- **Per-stage Claude model selection:** `backends.<name>.model` (passed via `--model`)
  and per-stage `ai.stage_models`; `galangal doctor` now reports the active model.
  Fixed dropped text-only assistant output and made max-turns detection structural.
