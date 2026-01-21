
import pytest
from galangal.ui.tui.app import WorkflowTUIApp, ActivityLevel, ActivityCategory
from galangal.ui.tui.widgets import FilesPanelWidget
from galangal.core.state import WorkflowState, Stage, RollbackEvent

def test_tui_activity_log_truncation():
    """Verify that activity log is truncated at ACTIVITY_LOG_MAX_ENTRIES."""
    app = WorkflowTUIApp("test-task", "PM")

    # Add entries beyond the limit
    limit = app.ACTIVITY_LOG_MAX_ENTRIES
    excess = 100
    total = limit + excess
    
    for i in range(total):
        app.add_activity(f"Message {i}")
        
    # Check size
    assert len(app._activity_entries) == limit
    
    # Verify we kept the *latest* entries
    assert app._activity_entries[0].message == f"Message {excess}"
    assert app._activity_entries[-1].message == f"Message {total - 1}"

def test_tui_files_panel_truncation():
    """Verify that files panel is truncated at MAX_FILES_HISTORY."""
    widget = FilesPanelWidget()
    
    # Add entries beyond the limit
    limit = widget.MAX_FILES_HISTORY
    excess = 20
    total = limit + excess
    
    for i in range(total):
        widget.add_file("read", f"file_{i}.py")
        
    # Check size
    assert len(widget._files) == limit
    
    # Verify we kept the *latest* entries
    assert widget._files[0] == ("read", f"file_{excess}.py")
    assert widget._files[-1] == ("read", f"file_{total - 1}.py")

def test_state_rollback_history_truncation():
    """Verify that rollback history is truncated at 50."""
    state = WorkflowState.new("desc", "task")
    
    # Add entries beyond the limit
    limit = 50
    excess = 10
    total = limit + excess
    
    for i in range(total):
        state.record_rollback(Stage.DEV, Stage.PM, f"Reason {i}")
        
    # Check size
    assert len(state.rollback_history) == limit
    
    # Verify we kept the *latest* entries
    assert state.rollback_history[0].reason == f"Reason {excess}"
    assert state.rollback_history[-1].reason == f"Reason {total - 1}"
