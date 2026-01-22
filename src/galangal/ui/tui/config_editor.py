"""
Interactive configuration editor TUI.

Provides a terminal UI for editing .galangal/config.yaml with:
- Tree navigation of config sections
- Field documentation and type hints
- Real-time validation via Pydantic
- Preview changes before saving
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError as PydanticValidationError
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Input, Static, Tree
from textual.widgets.tree import TreeNode

from galangal.config.loader import get_project_root
from galangal.config.schema import GalangalConfig


@dataclass
class ConfigField:
    """Represents a single config field."""

    path: list[str]  # e.g., ["project", "name"]
    value: Any
    field_type: str
    description: str
    default: Any = None
    is_modified: bool = False


@dataclass
class EditorState:
    """Tracks editor state and modifications."""

    original_data: dict[str, Any] = field(default_factory=dict)
    modified_data: dict[str, Any] = field(default_factory=dict)
    selected_path: list[str] = field(default_factory=list)
    has_unsaved_changes: bool = False


def get_nested_value(data: dict[str, Any], path: list[str]) -> Any:
    """Get a nested value from a dictionary by path."""
    current = data
    for key in path:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None
    return current


def set_nested_value(data: dict[str, Any], path: list[str], value: Any) -> None:
    """Set a nested value in a dictionary by path."""
    current = data
    for key in path[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]
    current[path[-1]] = value


def get_field_info(model_class: type, field_name: str) -> tuple[str, str, Any]:
    """Get field type, description, and default from a Pydantic model."""
    if hasattr(model_class, "model_fields"):
        fields = model_class.model_fields
        if field_name in fields:
            field_info = fields[field_name]
            # Get type annotation
            annotation = field_info.annotation
            type_str = getattr(annotation, "__name__", str(annotation))
            # Get description
            desc = field_info.description or ""
            # Get default
            default = field_info.default
            return type_str, desc, default
    return "unknown", "", None


def build_field_tree(
    config: GalangalConfig, prefix: list[str] | None = None
) -> list[ConfigField]:
    """Build a flat list of all config fields with their metadata."""
    if prefix is None:
        prefix = []

    fields: list[ConfigField] = []
    data = config.model_dump()

    def traverse(obj: Any, path: list[str], model_class: type | None) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                new_path = path + [key]
                # Try to get nested model class
                nested_model = None
                if model_class and hasattr(model_class, "model_fields"):
                    field_info = model_class.model_fields.get(key)
                    if field_info and hasattr(field_info.annotation, "model_fields"):
                        nested_model = field_info.annotation

                if isinstance(value, dict) and value:
                    # Recurse into nested objects
                    traverse(value, new_path, nested_model)
                else:
                    # Leaf field
                    type_str, desc, default = "", "", None
                    if model_class:
                        type_str, desc, default = get_field_info(model_class, key)

                    fields.append(
                        ConfigField(
                            path=new_path,
                            value=value,
                            field_type=type_str,
                            description=desc,
                            default=default,
                        )
                    )

    traverse(data, prefix, GalangalConfig)
    return fields


class ConfigEditorApp(App[bool]):
    """
    Interactive configuration editor.

    Returns True if changes were saved, False otherwise.
    """

    TITLE = "Galangal Config Editor"
    CSS_PATH = "styles/config_editor.tcss"

    BINDINGS = [
        Binding("ctrl+s", "save", "Save", show=True),
        Binding("ctrl+q", "quit_editor", "Quit", show=True),
        Binding("escape", "quit_editor", "Quit", show=False),
        Binding("enter", "edit_field", "Edit", show=True),
        Binding("r", "reset_field", "Reset", show=True),
    ]

    def __init__(self, config_path: Path | None = None) -> None:
        super().__init__()
        self.config_path = config_path or (get_project_root() / ".galangal" / "config.yaml")
        self.state = EditorState()
        self._load_config()
        self._editing = False

    def _load_config(self) -> None:
        """Load config from file."""
        if self.config_path.exists():
            try:
                self.state.original_data = yaml.safe_load(self.config_path.read_text()) or {}
            except yaml.YAMLError:
                self.state.original_data = {}
        else:
            self.state.original_data = {}

        # Deep copy for modifications
        import copy

        self.state.modified_data = copy.deepcopy(self.state.original_data)

    def compose(self) -> ComposeResult:
        with Container(id="editor-root"):
            yield Static("Galangal Configuration Editor", id="editor-title")
            with Horizontal(id="editor-content"):
                with Vertical(id="tree-panel"):
                    yield Static("Sections", id="tree-title")
                    yield Tree("config", id="config-tree")
                with Vertical(id="detail-panel"):
                    yield Static("Field Details", id="detail-title")
                    with VerticalScroll(id="detail-content"):
                        yield Static("", id="field-path")
                        yield Static("", id="field-type")
                        yield Static("", id="field-description")
                        yield Static("", id="field-default")
                        yield Static("Current Value:", id="value-label")
                        yield Static("", id="field-value")
                    yield Static("", id="validation-status")
            yield Static("", id="status-bar")
            yield Footer()

    def on_mount(self) -> None:
        """Build the config tree on mount."""
        tree = self.query_one("#config-tree", Tree)
        tree.show_root = False

        # Build tree from schema, not just current data
        self._build_tree(tree.root, GalangalConfig, self.state.modified_data, [])
        tree.root.expand_all()

        self._update_status_bar()

    def _build_tree(
        self,
        node: TreeNode[str],
        model_class: type | None,
        data: dict[str, Any],
        path: list[str],
    ) -> None:
        """Recursively build tree from Pydantic model schema."""
        if model_class is None or not hasattr(model_class, "model_fields"):
            return

        for field_name, field_info in model_class.model_fields.items():
            new_path = path + [field_name]
            path_str = ".".join(new_path)

            # Get current value
            current_value = get_nested_value(data, [field_name]) if data else None

            # Check if this is a nested model
            annotation = field_info.annotation
            is_nested = hasattr(annotation, "model_fields")

            if is_nested:
                # Add as expandable node
                child = node.add(f"[#83a598]{field_name}[/]", data=path_str)
                child_data = current_value if isinstance(current_value, dict) else {}
                self._build_tree(child, annotation, child_data, new_path)
            else:
                # Add as leaf with value preview
                value_preview = self._format_value_preview(current_value)
                label = f"[#ebdbb2]{field_name}[/] [#7c6f64]= {value_preview}[/]"
                node.add_leaf(label, data=path_str)

    def _format_value_preview(self, value: Any, max_len: int = 30) -> str:
        """Format a value for preview in the tree."""
        if value is None:
            return "[dim]not set[/]"
        if isinstance(value, bool):
            return "[#b8bb26]true[/]" if value else "[#fb4934]false[/]"
        if isinstance(value, (int, float)):
            return f"[#d3869b]{value}[/]"
        if isinstance(value, str):
            if len(value) > max_len:
                return f'[#b8bb26]"{value[:max_len]}..."[/]'
            return f'[#b8bb26]"{value}"[/]'
        if isinstance(value, list):
            return f"[#fe8019][{len(value)} items][/]"
        if isinstance(value, dict):
            return f"[#fe8019]{{{len(value)} keys}}[/]"
        return str(value)[:max_len]

    def on_tree_node_selected(self, event: Tree.NodeSelected[str]) -> None:
        """Handle tree node selection."""
        if event.node.data:
            path = event.node.data.split(".")
            self.state.selected_path = path
            self._update_detail_panel(path)

    def _update_detail_panel(self, path: list[str]) -> None:
        """Update the detail panel for the selected field."""
        # Navigate to the field's model class
        model_class = GalangalConfig
        for i, key in enumerate(path[:-1]):
            if hasattr(model_class, "model_fields"):
                field_info = model_class.model_fields.get(key)
                if field_info and hasattr(field_info.annotation, "model_fields"):
                    model_class = field_info.annotation

        field_name = path[-1]
        type_str, description, default = "", "", None

        if hasattr(model_class, "model_fields") and field_name in model_class.model_fields:
            type_str, description, default = get_field_info(model_class, field_name)

        # Get current value
        current_value = get_nested_value(self.state.modified_data, path)

        # Update UI
        self.query_one("#field-path", Static).update(
            f"[#83a598]Path:[/] [#ebdbb2]{'.'.join(path)}[/]"
        )
        self.query_one("#field-type", Static).update(f"[#83a598]Type:[/] [#d3869b]{type_str}[/]")
        self.query_one("#field-description", Static).update(
            f"[#83a598]Description:[/]\n[#a89984]{description or 'No description'}[/]"
        )
        self.query_one("#field-default", Static).update(
            f"[#83a598]Default:[/] {self._format_value_preview(default)}"
        )

        # Format current value
        if isinstance(current_value, (list, dict)):
            value_display = yaml.dump(current_value, default_flow_style=False).strip()
            self.query_one("#field-value", Static).update(f"[#ebdbb2]{value_display}[/]")
        else:
            self.query_one("#field-value", Static).update(
                f"{self._format_value_preview(current_value)}"
            )

    def _update_status_bar(self) -> None:
        """Update the status bar."""
        status = self.query_one("#status-bar", Static)
        if self.state.has_unsaved_changes:
            status.update("[#fabd2f]● Unsaved changes[/] | Ctrl+S to save, Ctrl+Q to quit")
        else:
            status.update("[#7c6f64]No changes[/] | Enter to edit, Ctrl+Q to quit")

    def action_edit_field(self) -> None:
        """Edit the selected field."""
        if not self.state.selected_path or self._editing:
            return

        path = self.state.selected_path
        current_value = get_nested_value(self.state.modified_data, path)

        # Don't edit complex types directly
        if isinstance(current_value, (dict,)) and current_value:
            self.notify("Navigate to child fields to edit", severity="warning")
            return

        self._editing = True
        self._show_edit_modal(path, current_value)

    def _show_edit_modal(self, path: list[str], current_value: Any) -> None:
        """Show edit modal for a field."""
        from galangal.ui.tui.modals import TextInputModal

        # Format current value for editing
        if isinstance(current_value, list):
            default = ", ".join(str(v) for v in current_value)
        elif current_value is None:
            default = ""
        else:
            default = str(current_value)

        label = f"Edit {'.'.join(path)}:"

        def handle_result(result: str | None) -> None:
            self._editing = False
            if result is not None:
                self._apply_edit(path, result)

        screen = TextInputModal(label, default)
        self.push_screen(screen, handle_result)

    def _apply_edit(self, path: list[str], new_value_str: str) -> None:
        """Apply an edit and validate."""
        # Get expected type
        model_class = GalangalConfig
        for key in path[:-1]:
            if hasattr(model_class, "model_fields"):
                field_info = model_class.model_fields.get(key)
                if field_info and hasattr(field_info.annotation, "model_fields"):
                    model_class = field_info.annotation

        field_name = path[-1]
        annotation = None
        if hasattr(model_class, "model_fields") and field_name in model_class.model_fields:
            annotation = model_class.model_fields[field_name].annotation

        # Convert string to appropriate type
        try:
            new_value = self._parse_value(new_value_str, annotation)
        except ValueError as e:
            self._show_validation_error(str(e))
            return

        # Apply change
        set_nested_value(self.state.modified_data, path, new_value)

        # Validate entire config
        try:
            GalangalConfig.model_validate(self.state.modified_data)
            self.state.has_unsaved_changes = True
            self._update_status_bar()
            self._update_detail_panel(path)
            self._refresh_tree()
            self._show_validation_success()
        except PydanticValidationError as e:
            # Revert change
            original_value = get_nested_value(self.state.original_data, path)
            set_nested_value(self.state.modified_data, path, original_value)
            self._show_validation_error(str(e.errors()[0]["msg"]))

    def _parse_value(self, value_str: str, annotation: type | None) -> Any:
        """Parse a string value to the appropriate type."""
        value_str = value_str.strip()

        if not value_str:
            return None

        # Handle common types
        if annotation is bool or str(annotation) == "bool":
            return value_str.lower() in ("true", "yes", "1", "on")
        if annotation is int or str(annotation) == "int":
            return int(value_str)
        if annotation is float or str(annotation) == "float":
            return float(value_str)
        if "list" in str(annotation).lower():
            # Parse comma-separated list
            if not value_str:
                return []
            return [v.strip() for v in value_str.split(",") if v.strip()]

        # Default to string
        return value_str

    def _show_validation_error(self, message: str) -> None:
        """Show validation error."""
        status = self.query_one("#validation-status", Static)
        status.update(f"[#fb4934]✗ {message}[/]")

    def _show_validation_success(self) -> None:
        """Show validation success."""
        status = self.query_one("#validation-status", Static)
        status.update("[#b8bb26]✓ Valid[/]")

    def _refresh_tree(self) -> None:
        """Refresh the tree to show updated values."""
        tree = self.query_one("#config-tree", Tree)
        tree.clear()
        self._build_tree(tree.root, GalangalConfig, self.state.modified_data, [])
        tree.root.expand_all()

    def action_reset_field(self) -> None:
        """Reset the selected field to its default value."""
        if not self.state.selected_path:
            return

        path = self.state.selected_path
        original_value = get_nested_value(self.state.original_data, path)
        set_nested_value(self.state.modified_data, path, original_value)

        self._update_detail_panel(path)
        self._refresh_tree()
        self.notify(f"Reset {'.'.join(path)} to original value")

        # Check if there are still unsaved changes
        import copy

        self.state.has_unsaved_changes = self.state.modified_data != copy.deepcopy(
            self.state.original_data
        )
        self._update_status_bar()

    def action_save(self) -> None:
        """Save changes to config file."""
        if not self.state.has_unsaved_changes:
            self.notify("No changes to save", severity="information")
            return

        # Final validation
        try:
            GalangalConfig.model_validate(self.state.modified_data)
        except PydanticValidationError as e:
            self.notify(f"Validation failed: {e.errors()[0]['msg']}", severity="error")
            return

        # Ensure directory exists
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        # Write config
        try:
            with open(self.config_path, "w") as f:
                yaml.dump(
                    self.state.modified_data,
                    f,
                    default_flow_style=False,
                    sort_keys=False,
                    allow_unicode=True,
                )
            self.state.has_unsaved_changes = False
            self.state.original_data = self.state.modified_data.copy()
            self._update_status_bar()
            self.notify("Configuration saved!", severity="information")
        except OSError as e:
            self.notify(f"Failed to save: {e}", severity="error")

    def action_quit_editor(self) -> None:
        """Quit the editor."""
        if self.state.has_unsaved_changes:
            self.notify("Unsaved changes! Press Ctrl+S to save or Ctrl+Q again to discard.")
            self.state.has_unsaved_changes = False  # Allow quit on second press
            return
        self.exit(False)


def run_config_editor(config_path: Path | None = None) -> bool:
    """Run the config editor and return True if changes were saved."""
    app = ConfigEditorApp(config_path)
    return app.run() or False
