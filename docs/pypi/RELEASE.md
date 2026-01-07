# Release Process (PyPI)

## Prerequisites

- PyPI account with access to the project
- Credentials configured in `~/.pypirc`
- Python environment with `build` and `twine` installed

```bash
pip install --upgrade build twine
```

## Release Steps

### 1. Update version numbers

Bump the version in both files (keep them in sync):

- `pyproject.toml` — update `[project].version`
- `src/galangal/__init__.py` — update `__version__`

### 2. Run tests

```bash
pytest
```

### 3. Build distribution packages

```bash
rm -rf dist/
python -m build
```

### 4. Verify packages

```bash
twine check dist/*
```

### 5. Publish to PyPI

```bash
twine upload dist/*
```

## Notes

- Activate your virtualenv before running these commands
- The build creates both `.whl` and `.tar.gz` distributions in `dist/`
- For test releases, use TestPyPI first: `twine upload --repository testpypi dist/*`
