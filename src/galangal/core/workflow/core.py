"""
Core workflow utilities - stage execution, rollback handling.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from galangal.ai import REVIEW_LIKE_STAGES, get_backend_for_stage, prepare_backend_for_stage
from galangal.ai.base import PauseCheck
from galangal.config.loader import get_config
from galangal.core.artifacts import artifact_exists, delete_artifact, read_artifact, write_artifact
from galangal.core.state import (
    STAGE_ORDER,
    Stage,
    WorkflowState,
    get_conditional_stages,
    save_state,
    should_skip_for_task_type,
)
from galangal.core.utils import now_iso
from galangal.prompts.builder import PromptBuilder
from galangal.results import StageResult, StageResultType
from galangal.ui.tui import TUIAdapter
from galangal.validation.runner import ValidationRunner

if TYPE_CHECKING:
    from galangal.ui.tui import WorkflowTUIApp


# Get conditional stages from metadata (cached at module load)
CONDITIONAL_STAGES: dict[Stage, str] = get_conditional_stages()


def get_task_dir(task_name: str):
    """Compatibility shim for tests patching this symbol."""
    from galangal.core.state import get_task_dir as _get_task_dir

    return _get_task_dir(task_name)


def _append_task_log(task_name: str, line: str, *, line_type: str = "system") -> None:
    """Best-effort DB task log append."""
    if not line:
        return
    try:
        from galangal.core.task_index import TaskIndex

        TaskIndex().append_task_log_line(
            task_name=task_name,
            line=line,
            line_type=line_type,
        )
    except Exception:
        pass


def _append_task_log_block(
    task_name: str,
    *,
    title: str,
    content: str,
    line_type: str = "system",
) -> None:
    """Append a titled multi-line block to task DB logs."""
    _append_task_log(task_name, title, line_type=line_type)
    if not content:
        return
    lines = content.splitlines()
    if not lines:
        return
    try:
        from galangal.core.task_index import TaskIndex

        TaskIndex().append_task_log_lines(
            task_name=task_name,
            lines=lines,
            line_type=line_type,
        )
    except Exception:
        for line in lines:
            _append_task_log(task_name, line, line_type=line_type)


def _format_issues(issues: list[dict[str, Any]]) -> str:
    """Format issues list into markdown."""
    if not issues:
        return ""

    formatted = "\n\n## Issues Found\n\n"
    for issue in issues:
        severity = issue.get("severity", "unknown")
        desc = issue.get("description", "")
        file_ref = issue.get("file", "")
        line = issue.get("line")
        loc = f" ({file_ref}:{line})" if file_ref and line else ""
        formatted += f"- **[{severity.upper()}]** {desc}{loc}\n"
    return formatted


def _write_artifacts_from_readonly_output(
    stage: Stage,
    output: str,
    task_name: str,
    tui_app: WorkflowTUIApp,
) -> None:
    """
    Write stage artifacts from read-only backend's structured JSON output.

    Read-only backends cannot write files directly. Instead, they return
    structured JSON which we post-process to create the expected artifacts
    based on STAGE_ARTIFACT_SCHEMA.

    Supports two modes:
    1. Schema-based: Uses STAGE_METADATA artifact_schema mapping
    2. Generic fallback: Looks for 'artifacts' array in JSON output

    Args:
        stage: The stage that was executed
        output: JSON string containing structured output
        task_name: Task name for artifact paths
        tui_app: TUI app for activity logging
    """
    from galangal.core.utils import extract_json_object

    # Tolerant parse: read-only backends sometimes wrap JSON in prose or code
    # fences; a strict json.loads would discard the whole stage result.
    data = extract_json_object(output)
    if data is None:
        tui_app.add_activity("Warning: Backend output is not valid JSON", "⚠️")
        return

    # Try schema-based artifact writing first
    schema = stage.metadata.artifact_schema
    if schema:
        _write_schema_artifacts(data, schema, stage, task_name, tui_app)
        return

    # Fall back to generic artifacts array
    artifacts = data.get("artifacts", [])
    if artifacts:
        _write_generic_artifacts(artifacts, task_name, tui_app)
    else:
        tui_app.add_activity(f"Warning: No artifact schema for {stage.value}", "⚠️")


def _write_schema_artifacts(
    data: dict[str, Any],
    schema: dict[str, str | None],
    stage: Stage,
    task_name: str,
    tui_app: WorkflowTUIApp,
) -> None:
    """Write artifacts based on stage schema mapping."""
    from galangal.core.state import get_decision_values

    notes_file = schema.get("notes_file")
    notes_field = schema.get("notes_field")
    decision_file = schema.get("decision_file")
    decision_field = schema.get("decision_field")
    issues_field = schema.get("issues_field")

    # Write notes file
    if notes_file and notes_field:
        notes = data.get(notes_field, "")
        if notes:
            # Append formatted issues if present
            if issues_field:
                issues = data.get(issues_field, [])
                notes += _format_issues(issues)

            write_artifact(notes_file, notes, task_name)
            tui_app.add_activity(f"Wrote {notes_file} from backend output", "📝")

    # Write decision file using stage-specific valid values
    if decision_file and decision_field:
        decision = data.get(decision_field, "")
        # Get valid decisions from STAGE_METADATA
        valid_decisions = get_decision_values(stage)
        if decision in valid_decisions:
            write_artifact(decision_file, decision, task_name)
            tui_app.add_activity(f"Wrote {decision_file}: {decision}", "📝")
        elif decision:
            tui_app.add_activity(
                f"Warning: Invalid decision '{decision}' for {stage.value} "
                f"(expected: {', '.join(valid_decisions)})",
                "⚠️",
            )


def _write_generic_artifacts(
    artifacts: list[dict[str, Any]],
    task_name: str,
    tui_app: WorkflowTUIApp,
) -> None:
    """Write artifacts from generic artifacts array in JSON output.

    Expected format:
    [
        {"name": "ARTIFACT_NAME.md", "content": "..."},
        ...
    ]
    """
    for artifact in artifacts:
        name = artifact.get("name")
        content = artifact.get("content")
        if name and content:
            write_artifact(name, content, task_name)
            tui_app.add_activity(f"Wrote {name} from backend output", "📝")


def get_next_stage(current: Stage, state: WorkflowState) -> Stage | None:
    """
    Determine the next stage in the workflow pipeline.

    Iterates through STAGE_ORDER starting after current stage, skipping
    stages that should be bypassed based on (in order):
    1. Config-level skipping (config.stages.skip)
    2. Task type skipping (e.g., DOCS tasks skip TEST, BENCHMARK)
    3. Fast-track skipping (minor rollback - skip stages that already passed)
    4. PM-driven stage plan (STAGE_PLAN.md recommendations)
    5. Manual skip artifacts (e.g., MIGRATION_SKIP.md from galangal skip-*)
    6. TEST_GATE: skip if not enabled or no tests configured
    7. skip_if conditions from validation config (glob-based skipping for all stages)

    This is the single source of truth for skip logic. All skip decisions
    happen here during planning, ensuring the progress bar accurately
    reflects which stages will run.

    Args:
        current: The stage that just completed.
        state: Current workflow state containing task_name and task_type.

    Returns:
        The next stage to execute, or None if current is the last stage.
    """
    config = get_config()
    task_name = state.task_name
    task_type = state.task_type
    start_idx = STAGE_ORDER.index(current) + 1
    config_skip_stages = [s.upper() for s in config.stages.skip]
    runner = ValidationRunner()  # Create once for all skip_if checks

    for next_stage in STAGE_ORDER[start_idx:]:
        # Check 1: config-level skipping
        if next_stage.value in config_skip_stages:
            continue

        # Check 2: task type skipping
        if should_skip_for_task_type(next_stage, task_type):
            continue

        # Check 3: fast-track skipping (minor rollback - skip stages that already passed)
        if state.should_fast_track_skip(next_stage):
            continue

        # Check 4: PM-driven stage plan (STAGE_PLAN.md recommendations)
        if state.stage_plan and next_stage.value in state.stage_plan:
            if state.stage_plan[next_stage.value].get("action") == "skip":
                continue

        # Check 5: manual skip artifacts (e.g., MIGRATION_SKIP.md from galangal skip-*)
        # Uses metadata as source of truth for which stages have skip artifacts
        stage_metadata = next_stage.metadata
        if stage_metadata.skip_artifact and artifact_exists(
            stage_metadata.skip_artifact, task_name
        ):
            continue

        # Check 6: TEST_GATE - skip if not enabled or no tests configured
        if next_stage == Stage.TEST_GATE:
            if not config.test_gate.enabled or not config.test_gate.tests:
                continue

        # Check 7: for conditional stages, if PM explicitly said "run", skip the glob check
        if next_stage in CONDITIONAL_STAGES:
            if state.stage_plan and next_stage.value in state.stage_plan:
                if state.stage_plan[next_stage.value].get("action") == "run":
                    return next_stage  # PM says run, skip the glob check

        # Check 8: skip_if conditions for ALL stages (glob-based skipping)
        # This is the single place where skip_if is evaluated
        if runner.should_skip_stage(next_stage.value.upper(), task_name):
            continue

        return next_stage

    return None


def _execute_test_gate(
    state: WorkflowState,
    tui_app: WorkflowTUIApp,
    config: Any,
) -> StageResult:
    """
    Execute the TEST_GATE stage - run configured test commands mechanically.

    This is a non-AI stage that runs shell commands to verify tests pass.
    All configured tests must pass for the stage to succeed.

    Output is streamed line-by-line to the TUI for real-time visibility.

    Args:
        state: Current workflow state.
        tui_app: TUI app for progress display.
        config: Galangal configuration with test_gate settings.

    Returns:
        StageResult indicating success or failure with rollback to DEV.
    """
    import os
    import signal
    import subprocess
    import threading
    from collections import deque
    from queue import Empty, Full, Queue

    def _kill_proc_group(p: subprocess.Popen) -> None:
        """Kill the whole process group so shell pipelines and grandchildren die.

        ``proc.kill()`` only signals the direct child (``/bin/sh -c ...``); test
        runners that spawn their own subprocesses would otherwise survive, keep
        the stdout pipe open, and hang the reader thread on EOF.
        """
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                p.kill()
            except OSError:
                pass

    from galangal.config.loader import get_project_root
    from galangal.logging import workflow_logger

    task_name = state.task_name
    test_config = config.test_gate
    project_root = get_project_root()

    max_output_chars = 200_000
    output_queue_size = 200

    tui_app.add_activity("Running test gate checks...", "🧪")
    _append_task_log(task_name, "=== TEST_GATE START ===", line_type="meta")

    # Track results for each test suite
    results: list[dict[str, Any]] = []
    all_passed = True
    failed_tests: list[str] = []

    def stream_output(
        proc: subprocess.Popen,
        output_tail: deque[str],
        queue: Queue,
        truncated_flag: list[bool],
    ) -> None:
        """Read process output, stream to queue, and keep a bounded tail."""
        output_chars = 0
        try:
            for line in iter(proc.stdout.readline, ""):
                if not line:
                    break

                output_tail.append(line)
                output_chars += len(line)
                while output_chars > max_output_chars and output_tail:
                    truncated_flag[0] = True
                    removed = output_tail.popleft()
                    output_chars -= len(removed)

                clean_line = line.rstrip("\n")
                try:
                    from galangal.hub.hooks import notify_output

                    notify_output(clean_line, "test_gate", task_name=task_name)
                except Exception:
                    _append_task_log(task_name, clean_line, line_type="test_gate")

                try:
                    queue.put(clean_line, timeout=1)
                except Full:
                    pass
        finally:
            try:
                queue.put_nowait(None)  # Signal completion
            except Full:
                pass

    for test in test_config.tests:
        tui_app.add_activity(f"Running: {test.name}", "▶")
        tui_app.show_message(f"Test Gate: {test.name}", "info")

        output_tail: deque[str] = deque()
        output_truncated = [False]
        exit_code = -1
        timed_out = False
        _append_task_log(
            task_name,
            f"[TEST_GATE] Running '{test.name}' command: {test.command}",
            line_type="meta",
        )

        proc: subprocess.Popen | None = None
        try:
            # Start process with stdout/stderr combined and piped.
            # start_new_session=True puts the shell pipeline in its own process
            # group so it can be killed as a unit on timeout.
            proc = subprocess.Popen(
                test.command,
                shell=True,
                cwd=project_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,  # Line buffered
                start_new_session=True,
            )

            # Stream output in background thread
            output_queue: Queue = Queue(maxsize=output_queue_size)
            reader_thread = threading.Thread(
                target=stream_output,
                args=(proc, output_tail, output_queue, output_truncated),
                daemon=True,
            )
            reader_thread.start()

            # Read from queue and display in TUI until process completes or timeout
            start_time = time.time()
            while True:
                try:
                    line = output_queue.get(timeout=0.1)
                    if line is None:
                        break  # Reader finished
                    # Stream each line to TUI (prefix with test name for context)
                    tui_app.add_activity(f"  {line[:200]}", "│")
                except Empty:
                    pass

                # Check timeout
                if time.time() - start_time > test.timeout:
                    _kill_proc_group(proc)
                    timed_out = True
                    break

                # Check if process finished
                if proc.poll() is not None and output_queue.empty():
                    break

            # Wait for reader thread to finish
            reader_thread.join(timeout=1.0)

            # Get exit code - must call wait() to ensure returncode is populated
            if timed_out:
                exit_code = -1
            else:
                try:
                    proc.wait(timeout=5)  # Ensure process fully terminated
                except subprocess.TimeoutExpired:
                    _kill_proc_group(proc)
                    proc.wait()
                exit_code = proc.returncode if proc.returncode is not None else -1

        except Exception as e:
            output_tail.append(f"Error running command: {e}")
            exit_code = -1
        finally:
            # Close the pipe so a still-blocked reader thread gets EOF, and reap
            # the process so a killed/abandoned pipeline never lingers as a zombie.
            if proc is not None:
                if proc.stdout is not None:
                    try:
                        proc.stdout.close()
                    except OSError:
                        pass
                if proc.poll() is None:
                    _kill_proc_group(proc)
                try:
                    proc.wait(timeout=5)
                except (subprocess.TimeoutExpired, OSError):
                    pass

        # Process results - include bounded tail for artifact
        output = "".join(output_tail)
        if output_truncated[0]:
            output = (
                f"[Output truncated to last {max_output_chars} characters. "
                "Full output is available in task_logs (.galangal/tasks.db).]\n\n"
                f"{output}"
            )

        if timed_out:
            results.append(
                {
                    "name": test.name,
                    "command": test.command,
                    "passed": False,
                    "exit_code": -1,
                    "output": f"Command timed out after {test.timeout} seconds\n\n{output}",
                }
            )
            tui_app.add_activity(f"✗ {test.name} timed out", "⏱️")
            all_passed = False
            failed_tests.append(test.name)

            if test_config.fail_fast:
                break
        else:
            passed = exit_code == 0
            results.append(
                {
                    "name": test.name,
                    "command": test.command,
                    "passed": passed,
                    "exit_code": exit_code,
                    "output": output,
                }
            )

            if passed:
                tui_app.add_activity(f"✓ {test.name} passed", "✅")
                _append_task_log(task_name, f"[TEST_GATE] '{test.name}' passed", line_type="meta")
            else:
                tui_app.add_activity(f"✗ {test.name} failed (exit code {exit_code})", "❌")
                all_passed = False
                failed_tests.append(test.name)
                _append_task_log(
                    task_name,
                    f"[TEST_GATE] '{test.name}' failed (exit code {exit_code})",
                    line_type="meta",
                )

                # Stop on first failure if fail_fast is enabled
                if test_config.fail_fast:
                    tui_app.add_activity("Stopping (fail_fast enabled)", "⚠")
                    break

    # Build TEST_GATE_RESULTS.md artifact
    passed_count = sum(1 for r in results if r["passed"])
    total_count = len(results)
    status = "PASS" if all_passed else "FAIL"

    artifact_lines = [
        "# Test Gate Results\n",
        f"\n**Status:** {status}",
        f"\n**Passed:** {passed_count}/{total_count}\n",
    ]

    if not all_passed:
        artifact_lines.append(f"\n**Failed Tests:** {', '.join(failed_tests)}\n")

    artifact_lines.append("\n## Test Results\n")

    for r in results:
        status_icon = "✅" if r["passed"] else "❌"
        artifact_lines.append(f"\n### {status_icon} {r['name']}\n")
        artifact_lines.append(f"\n**Command:** `{r['command']}`\n")
        artifact_lines.append(f"**Exit Code:** {r['exit_code']}\n")
        if r["output"]:
            artifact_lines.append(
                f"\n<details>\n<summary>Output</summary>\n\n```\n{r['output']}\n```\n\n</details>\n"
            )

    write_artifact("TEST_GATE_RESULTS.md", "".join(artifact_lines), task_name)
    tui_app.add_activity("Wrote TEST_GATE_RESULTS.md", "📝")

    # Write decision file
    decision = "PASS" if all_passed else "FAIL"
    write_artifact("TEST_GATE_DECISION", decision, task_name)

    # Log result
    workflow_logger.stage_completed(
        stage="TEST_GATE",
        task_name=task_name,
        success=all_passed,
        duration=0,  # Duration tracked by caller
    )

    if all_passed:
        message = f"All {total_count} test suite(s) passed"
        tui_app.show_message(f"Test Gate: {message}", "success")
        _append_task_log(task_name, f"=== TEST_GATE PASS: {message} ===", line_type="meta")
        return StageResult.create_success(message)
    else:
        message = f"Test gate failed: {len(failed_tests)} test suite(s) failed"
        tui_app.show_message(f"Test Gate: {message}", "error")
        _append_task_log(task_name, f"=== TEST_GATE FAIL: {message} ===", line_type="meta")
        return StageResult.rollback_required(
            message=message,
            rollback_to=Stage.DEV,
            output="\n".join(f"- {t}" for t in failed_tests),
        )


def execute_stage(
    state: WorkflowState,
    tui_app: WorkflowTUIApp,
    pause_check: PauseCheck | None = None,
) -> StageResult:
    """
    Execute a single workflow stage and validate its output.

    This function handles the full lifecycle of a stage execution:
    1. Check for pending clarifications (QUESTIONS.md without ANSWERS.md)
    2. For PREFLIGHT stage: run validation checks directly
    3. For other stages: build prompt, invoke AI backend, validate output

    The prompt is built using PromptBuilder which merges default prompts
    with project-specific overrides. Retry context is appended when
    state.attempt > 1.

    Stage metadata and output context are logged to task DB logs in `.galangal/tasks.db`.

    Args:
        state: Current workflow state containing stage, task_name, attempt count,
            and last_failure for retry context.
        tui_app: TUI application instance for displaying progress and messages.
        pause_check: Optional callback that returns True if a pause was requested
            (e.g., user pressed Ctrl+C). Passed to ClaudeBackend for graceful stop.

    Returns:
        StageResult with one of:
        - SUCCESS: Stage completed and validated successfully
        - PREFLIGHT_FAILED: Preflight checks failed
        - VALIDATION_FAILED: Stage output failed validation
        - ROLLBACK_REQUIRED: Validation indicated rollback needed
        - CLARIFICATION_NEEDED: Questions pending without answers
        - PAUSED/TIMEOUT/ERROR: AI execution issues
    """
    from galangal.logging import workflow_logger

    stage = state.stage
    task_name = state.task_name
    config = get_config()
    start_time = time.time()

    # Log stage start
    workflow_logger.stage_started(
        stage=stage.value,
        task_name=task_name,
        attempt=state.attempt,
        max_retries=config.stages.max_retries,
    )

    if stage == Stage.COMPLETE:
        return StageResult.create_success("Workflow complete")

    # NOTE: Skip conditions are checked in get_next_stage() which is the single
    # source of truth for skip logic. By the time we reach execute_stage(),
    # the stage has already been determined to not be skipped.

    # Check for clarification
    if artifact_exists("QUESTIONS.md", task_name) and not artifact_exists("ANSWERS.md", task_name):
        state.clarification_required = True
        save_state(state)
        return StageResult.clarification_needed()

    # PREFLIGHT runs validation directly
    if stage == Stage.PREFLIGHT:
        tui_app.add_activity("Running preflight checks...", "⚙")

        runner = ValidationRunner()
        result = runner.validate_stage("PREFLIGHT", task_name)

        if result.success:
            tui_app.show_message(f"Preflight: {result.message}", "success")
            return StageResult.create_success(result.message)
        else:
            return StageResult.preflight_failed(
                message=result.message,
                details=result.output or "",
            )

    # TEST_GATE runs configured test commands mechanically (no AI)
    if stage == Stage.TEST_GATE:
        return _execute_test_gate(state, tui_app, config)

    # Get backend first (needed for backend-specific prompts)
    backend = get_backend_for_stage(stage, config, use_fallback=True)

    # Force read-only mode for Codex on review-type stages so artifacts
    # are written via structured JSON post-processing instead of editable mode.
    if prepare_backend_for_stage(backend, stage):
        tui_app.add_activity(
            f"Forcing read-only mode for {backend.name} on {stage.value}", "🔒"
        )

    # Build prompt
    builder = PromptBuilder()
    # Backend-specific prompts like review_codex.md are intended for read-only
    # structured-output mode. Editable Codex should use the standard prompts.
    prompt_backend_name = backend.name
    if backend.name == "codex" and not backend.read_only:
        prompt_backend_name = None

    # For read-only backends on review-type stages, use minimal context
    # This gives an unbiased review without Claude's interpretations
    if backend.read_only and stage in REVIEW_LIKE_STAGES:
        prompt = builder.build_minimal_review_prompt(state, backend_name=backend.name)
        tui_app.add_activity("Using minimal context for independent review", "📋")
    else:
        prompt = builder.build_full_prompt(stage, state, backend_name=prompt_backend_name)

    # Add retry context
    if state.attempt > 1 and state.last_failure:
        retry_context = f"""
## ⚠️ RETRY ATTEMPT {state.attempt}

The previous attempt failed with the following error:

```
{state.last_failure[:1000]}
```

Please fix the issue above before proceeding. Do not repeat the same mistake.
"""
        prompt = f"{prompt}\n\n{retry_context}"

    _append_task_log(
        task_name,
        f"=== STAGE {stage.value} ATTEMPT {state.attempt} START (backend={backend.name}) ===",
        line_type="meta",
    )
    _append_task_log_block(
        task_name,
        title="=== Prompt ===",
        content=prompt,
        line_type="prompt",
    )

    tui_app.add_activity(f"Using {backend.name} backend", "🤖")

    ui = TUIAdapter(tui_app)
    max_turns = backend.config.max_turns if backend.config else 200
    invoke_result = backend.invoke(
        prompt=prompt,
        timeout=config.stages.timeout,
        max_turns=max_turns,
        ui=ui,
        pause_check=pause_check,
        stage=stage.value,
        log_file=None,
    )

    _append_task_log(
        task_name,
        f"=== STAGE RESULT: {invoke_result.type.value} ===",
        line_type="meta",
    )
    if invoke_result.message:
        _append_task_log(task_name, invoke_result.message, line_type="meta")

    # Return early if AI invocation failed
    if not invoke_result.success:
        _append_task_log(
            task_name,
            f"=== STAGE {stage.value} FAILED BEFORE VALIDATION ===",
            line_type="meta",
        )
        return invoke_result

    # Post-process for read-only backends (e.g., Codex with read_only=true)
    # These backends return structured JSON instead of writing files directly
    if backend.read_only and invoke_result.output:
        _write_artifacts_from_readonly_output(stage, invoke_result.output, task_name, tui_app)

    # Ingest any filesystem artifacts written by editable backends (e.g. Claude
    # Write tool) into canonical DB storage and delete the file copies.
    if not backend.read_only:
        from galangal.core.task_index import TaskIndex

        ingested = TaskIndex().ingest_task_artifacts(task_name=task_name)
        if ingested:
            tui_app.add_activity(f"Ingested {ingested} artifact(s) into DB", "📥")

    # Validate stage
    tui_app.add_activity("Validating stage outputs...", "⚙")

    runner = ValidationRunner()
    result = runner.validate_stage(stage.value, task_name)

    _append_task_log(task_name, "=== Validation ===", line_type="validation")
    _append_task_log(task_name, f"success: {result.success}", line_type="validation")
    _append_task_log(task_name, f"message: {result.message}", line_type="validation")
    _append_task_log(task_name, f"rollback_to: {result.rollback_to}", line_type="validation")
    _append_task_log(task_name, f"skipped: {result.skipped}", line_type="validation")
    if result.output:
        _append_task_log_block(
            task_name,
            title="=== Validation Output ===",
            content=result.output,
            line_type="validation",
        )

    duration = time.time() - start_time

    # Log validation result
    workflow_logger.validation_result(
        stage=stage.value,
        task_name=task_name,
        success=result.success,
        message=result.message,
        skipped=result.skipped,
    )

    if result.success:
        tui_app.show_message(result.message, "success")
        _append_task_log(task_name, f"=== STAGE {stage.value} SUCCESS ===", line_type="meta")
        workflow_logger.stage_completed(
            stage=stage.value,
            task_name=task_name,
            success=True,
            duration=duration,
        )
        return StageResult.create_success(result.message, output=invoke_result.output)
    else:
        # Check if user decision is needed (decision file missing)
        if result.needs_user_decision:
            tui_app.add_activity("Decision file missing - user confirmation required", "❓")
            return StageResult.user_decision_needed(
                message=result.message,
                artifact_content=result.output,
            )

        tui_app.show_message(result.message, "error")
        _append_task_log(
            task_name,
            f"=== STAGE {stage.value} VALIDATION FAILED ===",
            line_type="meta",
        )
        workflow_logger.stage_failed(
            stage=stage.value,
            task_name=task_name,
            error=result.message,
            attempt=state.attempt,
        )
        # Check if rollback is required
        if result.rollback_to:
            rollback_type = "fast-track rollback" if result.is_fast_track else "rollback"
            tui_app.add_activity(f"Triggering {rollback_type} to {result.rollback_to}", "🔄")
            return StageResult.rollback_required(
                message=result.message,
                rollback_to=Stage.from_str(result.rollback_to),
                output=invoke_result.output,
                is_fast_track=result.is_fast_track,
            )
        # Log when rollback_to is not set (helps debug missing rollback)
        tui_app.add_activity("Validation failed without rollback target", "⚠")
        return StageResult.validation_failed(result.message)


def append_rollback_entry(
    task_name: str,
    source: str,
    from_stage: str,
    target_stage: str,
    reason: str,
) -> None:
    """
    Append a rollback entry to ROLLBACK.md, preserving history.

    Creates a structured entry documenting the rollback event and appends it
    to existing ROLLBACK.md content (or creates new file if none exists).

    Args:
        task_name: Name of the task.
        source: Description of what triggered the rollback
            (e.g., "User interrupt (Ctrl+I)", "Validation failure", "Manual review").
        from_stage: Stage where the rollback was triggered.
        target_stage: Stage to roll back to.
        reason: Description of issues to fix.
    """
    rollback_entry = f"""
---

## {source}

**Date:** {now_iso()}
**From Stage:** {from_stage}
**Target Stage:** {target_stage}

### Issues to Fix
{reason}
"""

    existing = read_artifact("ROLLBACK.md", task_name)
    if existing:
        new_content = existing + rollback_entry
    else:
        new_content = f"# Rollback Log\n\nThis file tracks issues that required rolling back to earlier stages.\n{rollback_entry}"

    write_artifact("ROLLBACK.md", new_content, task_name)


def archive_rollback_if_exists(task_name: str, tui_app: WorkflowTUIApp) -> None:
    """
    Archive ROLLBACK.md to ROLLBACK_RESOLVED.md after DEV stage succeeds.

    When validation failures or manual review trigger a rollback to DEV,
    the issues are recorded in ROLLBACK.md. Once DEV completes successfully,
    this function moves the rollback content to ROLLBACK_RESOLVED.md with
    a resolution timestamp.

    Multiple rollbacks are accumulated in ROLLBACK_RESOLVED.md, separated
    by horizontal rules, providing a history of issues encountered.

    Args:
        task_name: Name of the task to archive rollback for.
        tui_app: TUI app for displaying archive notification.
    """
    if not artifact_exists("ROLLBACK.md", task_name):
        return

    rollback_content = read_artifact("ROLLBACK.md", task_name) or ""

    resolution_note = f"\n\n## Resolved: {now_iso()}\n\nIssues fixed by DEV stage.\n"
    existing = read_artifact("ROLLBACK_RESOLVED.md", task_name)
    if existing:
        resolved_content = existing + "\n---\n" + rollback_content + resolution_note
    else:
        resolved_content = rollback_content + resolution_note

    write_artifact("ROLLBACK_RESOLVED.md", resolved_content, task_name)
    delete_artifact("ROLLBACK.md", task_name)

    tui_app.add_activity("Archived ROLLBACK.md → ROLLBACK_RESOLVED.md", "📋")


def handle_rollback(state: WorkflowState, result: StageResult) -> bool:
    """
    Process a rollback from validation failure.

    When validation indicates a rollback is needed (e.g., QA fails and needs
    to go back to DEV), this function:
    1. Checks if rollback is allowed (prevents infinite loops)
    2. Records the rollback in state history
    3. Appends the rollback details to ROLLBACK.md
    4. Updates the workflow state to target stage
    5. Resets attempt counter and records failure reason

    The ROLLBACK.md file serves as context for the target stage, describing
    what issues need to be fixed.

    Rollback loop prevention: If too many rollbacks to the same stage occur
    within the time window (default: 3 within 1 hour), the rollback is blocked
    and returns False.

    Args:
        state: Current workflow state to update. Modified in place.
        result: StageResult with type=ROLLBACK_REQUIRED and rollback_to set.
            The message field describes what needs to be fixed.

    Returns:
        True if rollback was processed (result was ROLLBACK_REQUIRED type).
        False if result was not a rollback or rollback was blocked due to
        too many recent rollbacks to the same stage.
    """
    if result.type != StageResultType.ROLLBACK_REQUIRED or result.rollback_to is None:
        return False

    task_name = state.task_name
    from_stage = state.stage
    target_stage = result.rollback_to
    reason = result.message

    # Enrich rollback reason with review-stage artifact content so the
    # target stage (usually DEV) has the full feedback without needing
    # to read the artifact from the DB.
    if from_stage in REVIEW_LIKE_STAGES:
        metadata = from_stage.metadata
        if metadata and metadata.produces_artifacts:
            notes_artifact = metadata.produces_artifacts[0]
            notes_content = read_artifact(notes_artifact, task_name)
            if notes_content:
                reason = f"{reason}\n\n## {notes_artifact}\n\n{notes_content}"

    # Check for rollback loops (exempt REVIEW→DEV iteration since the
    # whole point of the iteration loop is repeated back-and-forth)
    is_review_iteration = from_stage == Stage.REVIEW and target_stage == Stage.DEV
    if not is_review_iteration and not state.should_allow_rollback(target_stage):
        from galangal.logging import workflow_logger

        rollback_count = state.get_rollback_count(target_stage)
        loop_msg = (
            f"Rollback loop detected: {rollback_count} rollbacks to {target_stage.value} "
            f"in the last hour. Manual intervention required."
        )
        workflow_logger.rollback(
            from_stage=from_stage.value,
            to_stage=target_stage.value,
            task_name=task_name,
            reason=f"BLOCKED: {loop_msg}",
        )
        return False

    # Record rollback in state history
    state.record_rollback(from_stage, target_stage, reason)

    # Append to ROLLBACK.md
    append_rollback_entry(
        task_name=task_name,
        source=f"Validation failure in {from_stage.value}",
        from_stage=from_stage.value,
        target_stage=target_stage.value,
        reason=reason,
    )

    # Review iteration: when REVIEW rolls back to DEV, enter direct DEV↔REVIEW
    # loop by skipping all stages between DEV and REVIEW. The full validation
    # pipeline runs once REVIEW approves.
    if from_stage == Stage.REVIEW and target_stage == Stage.DEV:
        state.review_iteration = True
        dev_idx = STAGE_ORDER.index(Stage.DEV)
        review_idx = STAGE_ORDER.index(Stage.REVIEW)
        state.fast_track_skip = {s.value for s in STAGE_ORDER[dev_idx + 1 : review_idx]}
        fast_track_skip_list = sorted(state.fast_track_skip)
    elif result.is_fast_track:
        # Minor rollback from other stages: skip stages that already passed
        state.setup_fast_track()
        fast_track_skip_list = sorted(state.fast_track_skip)
    else:
        # Full rollback: re-run all stages (but preserve stages marked preserve_on_rollback)
        state.clear_fast_track()
        state.clear_passed_stages(preserve_marked=True)
        # Skip preserved stages (e.g., TEST doesn't need re-running if tests already written)
        if state.passed_stages:
            state.fast_track_skip = state.passed_stages.copy()
        fast_track_skip_list = sorted(state.fast_track_skip)

    # Log rollback event with fast-track info
    from galangal.logging import workflow_logger

    workflow_logger.rollback(
        from_stage=from_stage.value,
        to_stage=target_stage.value,
        task_name=task_name,
        reason=reason,
        fast_track=result.is_fast_track,
        fast_track_skip=fast_track_skip_list,
    )

    state.stage = target_stage
    state.last_failure = f"Rollback from {from_stage.value}: {reason}"
    state.reset_attempts(clear_failure=False)
    save_state(state)

    # Log mistake for future reference (if tracking is available)
    _log_mistake_from_rollback(
        task_name=task_name,
        stage=from_stage.value,
        reason=reason,
    )

    return True


def _log_mistake_from_rollback(task_name: str, stage: str, reason: str) -> None:
    """Log a mistake from a rollback for future reference."""
    from galangal.mistakes import log_mistake
    log_mistake(reason, stage=stage, task_name=task_name)
