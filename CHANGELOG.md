# Changelog

All notable changes to galangal-orchestrate are documented here. This project
uses [semantic versioning](https://semver.org/) loosely (0.x, minor = features,
patch = fixes).

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
