"""
Legacy console-based workflow runner (non-TUI mode).
"""

import signal

from rich.console import Console

from galangal.ai.claude import get_pause_requested
from galangal.config.loader import get_config
from galangal.core.artifacts import artifact_exists
from galangal.core.state import STAGE_ORDER, Stage, WorkflowState, save_state
from galangal.core.workflow.core import (
    archive_rollback_if_exists,
    execute_stage,
    get_next_stage,
    handle_rollback,
)
from galangal.core.workflow.pause import (
    _handle_pause,
    _signal_handler,
    set_current_state,
)

console = Console()


def _run_workflow_legacy(state: WorkflowState) -> None:
    """Run workflow without persistent TUI (legacy mode)."""
    from galangal.commands.approve import prompt_plan_approval
    from galangal.commands.complete import finalize_task

    config = get_config()
    max_retries = config.stages.max_retries

    set_current_state(state)
    original_handler = signal.signal(signal.SIGINT, _signal_handler)

    try:
        while True:
            # Run stages until COMPLETE
            while state.stage != Stage.COMPLETE:
                if get_pause_requested():
                    _handle_pause(state)
                    return

                success, message = execute_stage(state)

                if get_pause_requested() or message == "PAUSED: User requested pause":
                    _handle_pause(state)
                    return

                if not success:
                    # Handle preflight failures specially - don't auto-retry
                    if message.startswith("PREFLIGHT_FAILED:"):
                        detailed_error = message[len("PREFLIGHT_FAILED:") :]
                        console.print("\n[red]✗ Preflight checks failed[/red]\n")
                        console.print(detailed_error)
                        console.print()

                        # Prompt user to retry after fixing
                        while True:
                            console.print("[yellow]Fix environment issues and retry?[/yellow]")
                            console.print("  [bold]1[/bold] Retry")
                            console.print("  [bold]2[/bold] Quit")
                            choice = console.input("\n[bold]Choice:[/bold] ").strip()
                            if choice == "1":
                                console.print("\n[dim]Retrying preflight checks...[/dim]")
                                break  # Break out of while loop, continue outer loop
                            elif choice == "2":
                                save_state(state)
                                return
                            else:
                                console.print("[red]Invalid choice. Please enter 1 or 2.[/red]\n")
                        continue  # Retry without incrementing attempt

                    if state.awaiting_approval or state.clarification_required:
                        console.print(f"\n{message}")
                        save_state(state)
                        return

                    if handle_rollback(state, message):
                        continue

                    state.attempt += 1
                    state.last_failure = message

                    if state.attempt > max_retries:
                        console.print(
                            f"\n[red]Max retries ({max_retries}) exceeded for stage {state.stage.value}[/red]"
                        )
                        console.print("\n[bold]Last failure:[/bold]")
                        console.print(message[:2000])
                        console.print()

                        # Prompt user for what to do
                        while True:
                            console.print(
                                f"[yellow]Stage {state.stage.value} failed after {max_retries} attempts. "
                                "What would you like to do?[/yellow]"
                            )
                            console.print("  [bold]1[/bold] Retry (reset attempts)")
                            console.print("  [bold]2[/bold] Fix in DEV (add feedback and roll back)")
                            console.print("  [bold]3[/bold] Quit")
                            choice = console.input("\n[bold]Choice:[/bold] ").strip()

                            if choice == "1":
                                state.attempt = 1  # Reset attempts
                                console.print("\n[dim]Retrying stage...[/dim]")
                                save_state(state)
                                break
                            elif choice == "2":
                                feedback = console.input(
                                    "\n[bold]Describe what needs to be fixed:[/bold] "
                                ).strip()
                                if not feedback:
                                    feedback = "Fix the failing stage"
                                failing_stage = state.stage.value
                                state.stage = Stage.DEV
                                state.attempt = 1
                                state.last_failure = (
                                    f"Feedback from {failing_stage} failure: {feedback}\n\n"
                                    f"Original error:\n{message[:1500]}"
                                )
                                console.print("\n[yellow]Rolling back to DEV with feedback[/yellow]")
                                save_state(state)
                                break
                            elif choice == "3":
                                save_state(state)
                                return
                            else:
                                console.print("[red]Invalid choice. Please enter 1, 2, or 3.[/red]\n")
                        continue

                    console.print(
                        f"\n[yellow]Stage failed, retrying (attempt {state.attempt}/{max_retries})...[/yellow]"
                    )
                    console.print(f"Failure: {message[:500]}...")
                    save_state(state)
                    continue

                console.print(
                    f"\n[green]Stage {state.stage.value} completed successfully[/green]"
                )

                # Plan approval gate
                if state.stage == Stage.PM and not artifact_exists("APPROVAL.md", state.task_name):
                    result = prompt_plan_approval(state.task_name, state)
                    if result == "quit":
                        _handle_pause(state)
                        return
                    elif result == "rejected":
                        continue

                if state.stage == Stage.DEV:
                    archive_rollback_if_exists(state.task_name)

                next_stage = get_next_stage(state.stage, state)
                if next_stage:
                    expected_next_idx = STAGE_ORDER.index(state.stage) + 1
                    actual_next_idx = STAGE_ORDER.index(next_stage)
                    if actual_next_idx > expected_next_idx:
                        skipped = STAGE_ORDER[expected_next_idx:actual_next_idx]
                        for s in skipped:
                            console.print(
                                f"   [dim]⏭️  Skipped {s.value} (condition not met)[/dim]"
                            )

                    state.stage = next_stage
                    state.attempt = 1
                    state.last_failure = None
                    state.awaiting_approval = False
                    state.clarification_required = False
                    save_state(state)
                else:
                    state.stage = Stage.COMPLETE
                    save_state(state)

            # Workflow complete
            console.print("\n" + "=" * 60)
            console.print("[bold green]WORKFLOW COMPLETE[/bold green]")
            console.print("=" * 60)

            from rich.prompt import Prompt

            console.print("\n[bold]Options:[/bold]")
            console.print("  [green]y[/green] - Create PR and finalize")
            console.print("  [yellow]n[/yellow] - Review and make changes (go back to DEV)")
            console.print("  [yellow]q[/yellow] - Quit (finalize later with 'galangal complete')")

            while True:
                choice = Prompt.ask("Your choice", default="y").strip().lower()

                if choice in ["y", "yes"]:
                    finalize_task(state.task_name, state, force=False)
                    return
                elif choice in ["n", "no"]:
                    state.stage = Stage.DEV
                    state.attempt = 1
                    save_state(state)
                    console.print("\n[dim]Going back to DEV stage...[/dim]")
                    break
                elif choice in ["q", "quit"]:
                    _handle_pause(state)
                    return
                else:
                    console.print("[red]Invalid choice. Enter y/n/q[/red]")

    finally:
        signal.signal(signal.SIGINT, original_handler)
        set_current_state(None)
