# Local Development Guide

This guide covers setting up and testing galangal-orchestrate locally without affecting any globally installed version (e.g., via pipx).

## Prerequisites

- Python 3.12+
- A clone of the repository

## Setup

### 1. Create the virtual environment

```bash
cd galangal-orchestrate
python -m venv venv
source venv/bin/activate
```

### 2. Install in editable mode

```bash
pip install -e .
```

This installs the package in "editable" (development) mode. Any changes you make to the source code are immediately available without reinstalling.

### 3. Verify the installation

```bash
galangal --help
pip show galangal-orchestrate
```

## Running Local Commands

You have two options for running commands against your local development version:

### Option A: Activate the venv

```bash
source venv/bin/activate
galangal status
galangal start "my test task" --type bug_fix
```

### Option B: Use the full path (no activation needed)

```bash
./venv/bin/galangal status
./venv/bin/galangal start "my test task" --type bug_fix
```

This is useful when you want to quickly run a command without activating the environment, or when you have a global install and want to explicitly use the local version.

## Testing Changes

### Using a sandbox directory

Create a sandbox directory for testing without affecting real projects:

```bash
mkdir -p sandbox
cd sandbox
../venv/bin/galangal init
../venv/bin/galangal start "test feature" --type feature
../venv/bin/galangal resume
```

### Running tests

```bash
source venv/bin/activate
pytest
pytest -v              # verbose output
pytest -x              # stop on first failure
pytest --tb=short      # shorter tracebacks
```

## Common Issues

### Version mismatch after updating source

**Problem:** `pip show galangal-orchestrate` shows an old version even though you updated `pyproject.toml`.

**Cause:** Editable installs cache package metadata at install time.

**Solution:** Reinstall to refresh the metadata:

```bash
pip install -e .
```

### Command not found after venv activation

**Problem:** `galangal` command not found even with venv activated.

**Solution:** Reinstall the package to regenerate entry points:

```bash
pip install -e .
```

### Global pipx version runs instead of local

**Problem:** Running `galangal` uses your pipx-installed version instead of the local one.

**Cause:** The venv is not activated, or the shell is finding the pipx version first.

**Solution:** Either activate the venv or use the full path:

```bash
# Activate venv (local version takes precedence)
source venv/bin/activate
galangal --help

# Or use explicit path
./venv/bin/galangal --help
```

### Import errors when running tests

**Problem:** `ModuleNotFoundError: No module named 'galangal'`

**Solution:** Ensure the package is installed in editable mode:

```bash
source venv/bin/activate
pip install -e .
pytest
```

## Development Workflow

A typical workflow for making and testing changes:

```bash
# 1. Make your code changes
#    (edit files in src/galangal/)

# 2. Changes are immediately available (editable install)
#    No reinstall needed for code changes

# 3. Test your changes
./venv/bin/galangal <command>

# 4. Run the test suite
./venv/bin/pytest

# 5. If you changed pyproject.toml (version, deps, entry points):
./venv/bin/pip install -e .
```

## Checking Your Setup

Quick commands to verify everything is configured correctly:

```bash
# Check package is installed and editable
./venv/bin/pip show galangal-orchestrate

# Check it points to your local source
./venv/bin/pip list --editable

# Check the version matches pyproject.toml
grep "^version" pyproject.toml
./venv/bin/pip show galangal-orchestrate | grep Version

# Check the CLI works
./venv/bin/galangal --help
```
