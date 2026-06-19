# Changelog

All notable changes to galangal-orchestrate are documented here. This project
uses [semantic versioning](https://semver.org/) loosely (0.x, minor = features,
patch = fixes).

## 0.65.2 — Keep intentional styling while escaping untrusted activity content

Follow-up to 0.65.1, which escaped *every* activity message and so broke the few
that use intentional Rich markup (the WORKFLOW COMPLETE banner, "Task completed",
the PR link rendered as raw `[bold ...]` tags).

- `ActivityEntry` / `add_activity` gain a `markup` flag. Default `False` escapes the
  message (arbitrary AI/review content still can't crash the markup parser);
  `markup=True` opts trusted, intentionally-styled messages through as-is.
- Flipped the intentional-markup callers (completion banner, "Task completed
  successfully!", PR link, "Starting new task…") to `markup=True`.

## 0.65.1 — Fix TUI crash on '[...]' content in prompts and the activity log

A REVIEW_NOTES.md note containing `[/{id}]` (a markup-like closing tag) crashed the
TUI with `MarkupError` when shown in a prompt on resume, because Textual's `Static`
parses Rich markup by default.

- **PromptModal** now renders its message as a literal `Text` (markup off) — the
  exact crash. Text-input / multiline labels and Q&A question text hardened the
  same way.
- **Activity log** (`format_display`) and the verbose log write now `escape()` the
  message, so a stray `[...]` in any log line can't crash the RichLog.
- The error panel was already safe (uses `Text.append`).

## 0.65.0 — Force exhaustive REVIEW: per-file coverage + completeness self-check

Targets codex reporting only 3-4 issues per round and trickling the rest across
many DEV↔REVIEW round-trips.

- **Required per-file coverage.** The codex read-only output schema for REVIEW now
  requires a `files_reviewed` array — one entry per changed file with a one-line
  verdict. Because it's required, codex must walk the whole diff and account for
  every file instead of stopping after the first few findings. The coverage list is
  appended to `REVIEW_NOTES.md`. Only REVIEW is affected; QA/SECURITY schemas are
  unchanged.
- **Completeness self-check.** Both review prompts now enumerate the full diff
  first (`git diff --name-only`), review every file end to end, run a pre-decision
  self-check ("did I actually trace each file, or just skim it?"), and are told a
  short issue list on a large feature usually means they stopped early.

## 0.64.0 — Autonomous arbiter, stage caching, spec anchoring, regression tests

A batch of REVIEW-loop and efficiency improvements, plus a fix to "Fix in DEV".

- **Autonomous arbiter.** When a REVIEW issue has been re-raised
  `stages.arbiter_after_rounds` (default 3) times — DEV and REVIEW deadlocked — a
  second backend adjudicates. If it rules the reviewer is overreaching, REVIEW is
  auto-approved; otherwise the rollback proceeds with the arbiter's reasoning
  appended to `REVIEW_NOTES.md`. Off by default (`stages.arbiter_enabled`); set
  `ai.stage_backends['ARBITER']` for an independent backend (defaults to
  `ai.default`). Fails safe to "uphold".
- **Recurring issues → mistake DB.** Confirmed recurring REVIEW issues are now
  logged to the cross-task mistake DB, so future tasks' DEV prompts are warned.
- **Regression tests for fixed defects.** The TEST prompt now requires a
  regression test for each defect listed in `ROLLBACK.md`/`REVIEW_NOTES.md`
  (especially recurring ones) — turning detection into prevention.
- **Content-hash stage caching** (opt-in). With `stages.cache_unchanged_stages`
  on, a validation stage is skipped on re-run when the files it depends on (new
  per-stage `validation.<stage>.inputs` globs) are byte-identical to when it last
  passed. Only stages that declare `inputs` are ever cached — broad-scan and
  code-modifying stages never auto-skip.
- **Definition-of-Done anchoring.** PM marks the Acceptance Criteria as the
  contract; both REVIEW prompts now block only on acceptance-criteria violations
  and real defects, not on Non-Goals or gold-plating.
- **Fix: "Fix in DEV" now resets the REVIEW→DEV iteration counter.** Previously it
  only reset the generic rollback cap, so after one more round the review-loop cap
  re-blocked immediately. It now clears both, giving the loop a fresh budget.

## 0.63.0 — Smarter REVIEW: severity-gated auto-approve + recurring-issue tracking

Reduces REVIEW↔DEV churn by not bouncing on trivia and by helping DEV fix
root causes instead of getting bounced for the same issue repeatedly.

- **Severity-gated auto-approve.** New `stages.review_block_min_severity`
  (default `major`). If the reviewer returns `REQUEST_CHANGES` but every issue is
  below the threshold (e.g. only `minor`/`suggestion`), the decision is upgraded
  to `APPROVE` and the issues are recorded in `REVIEW_NOTES.md` without a DEV
  round-trip. `REDESIGN` is never downgraded; unknown severities rank as
  `critical` (fail-safe). Set the threshold to `suggestion` to disable.
- **Recurring-issue tracking → DEV.** Each blocking REVIEW round's issues are
  persisted (`review_issue_rounds`) and fingerprinted on `file:line` (robust to
  reworded descriptions). On a REVIEW→DEV rollback, issues raised in more than
  one round are surfaced in a prominent "⚠️ RECURRING ISSUES — fix the root
  cause" section of `ROLLBACK.md` (which DEV reads), tagged `raised Nx`. Reset
  when the iteration loop completes.
- **Reviewer prompt** updated so severity labels are used accurately now that
  they drive blocking.

## 0.62.0 — Break the endless REVIEW↔DEV loop; configurable rollback caps

Targets a real task that ran 69+ hours because codex REVIEW kept trickle-feeding a
few issues per pass, and every approval rewound to re-run the whole validation
pipeline *and re-review*, giving the reviewer a fresh chance to find new issues and
restart the loop.

- **Validate once after approval, no re-review.** When REVIEW approves during the
  DEV↔REVIEW iteration loop, the full validation pipeline (TEST/QA/SECURITY/…) now
  runs **once** and then advances to DOCS — REVIEW is no longer re-run, so codex can
  no longer surface fresh issues and restart the loop. A genuine validation failure
  still rolls back to DEV as a full rollback (which re-reviews, since code changed).
- **Tight DEV↔REVIEW loop.** The iteration loop now skips *every* stage between DEV
  and REVIEW (including TEST_GATE) so a review fix goes straight back to the
  reviewer; the regression check moves to the post-approval validation pass.
- **Exhaustive single-pass review.** `review_codex.md` / `review.md` now require the
  reviewer to report **every** blocking issue in one pass rather than trickling a
  few out at a time (each omitted issue costs a full extra round-trip).
- **Accurate block messages.** A blocked rollback now names the limiter that
  actually fired — the REVIEW→DEV iteration cap vs the generic burst/total cap —
  with the real counter and the config key to raise, instead of always showing
  generic rollback-history counts.
- **Configurable rollback caps.** New `stages` config keys: `max_rollbacks_per_stage`
  (default 5), `rollback_time_window_hours` (default 1), `max_total_rollbacks_per_stage`
  (default 12). 0 disables either cap. (Previously hard-coded at 3/1/6.)

## 0.58.0 — Catch hallucinated APIs: baseline-diffed validation + grounding prompts

Targets the dominant AI-coding failure mode (seen in a real task: a hallucinated
Twilio attribute `phone_number_sid` that mocked tests passed but crashed at runtime,
and which the type checker *did* flag but got dismissed as "pre-existing").

- **Baseline-diffed validation (`baseline_diff: true`).** A validation command can
  now fail **only on errors NEW since the task's base commit**. The command is run
  against the base commit (via a cached transient `git worktree`) and its error
  output is diffed, so pre-existing repo lint/type errors no longer force you to
  disable the gate — and a genuinely new error is caught instead of lost in the
  noise. Reuses the `base_commit_sha` already captured at task start. Ideal for
  `pyright`/`mypy`/`ruff`/`tsc`.
- **Import-smoke + baseline examples** added (commented) to the default config so
  they're discoverable.
- **DEV prompt:** must verify external library symbols exist in the *installed*
  package before calling them (don't guess attribute/method names), and fix new
  type/lint errors rather than dismissing them as pre-existing.
- **TEST prompt:** don't mock the library you're verifying — exercise the real SDK
  surface on at least one path so a hallucinated API fails in tests, not prod.
- **QA prompt:** don't re-dismiss a previously-raised finding without verified
  justification; a lint/type error on a file the task changed is in scope.

## 0.57.2 — Dashboard: render "Last Failure" as markdown with a reveal toggle

- The task detail page's **Last Failure** block now renders as **markdown**
  (GFM: tables, code, lists) instead of a raw paragraph, and shows a **clamped
  snippet with a "Show all" / "Show less"** toggle so a long QA/rollback report no
  longer floods the page. The description block also gains GFM rendering.

## 0.57.1 — Fix hub login page 500 on modern Starlette

- **`/login` returned 500** (`TypeError: unhashable type: 'dict'`) on current
  Starlette: `views.py` used the deprecated `TemplateResponse(name, context)`
  signature, which modern Starlette interprets as `(request, name, …)` — passing
  the context dict as the template name. Switched both call sites to the
  request-first signature. Added a `GET /login` rendering regression test.

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
