Release Process (PyPI)

Prereqs
- Access to the PyPI project and credentials configured in ~/.pypirc
- Python environment with build and twine available

Steps
1) Update versions
   - pyproject.toml: bump [project].version
   - src/galangal/__init__.py: bump __version__

2) Optional: run tests
   - pytest

3) Build distributions
   - rm -rf dist
   - python -m build

4) Verify packages
   - python -m twine check dist/*

5) Publish to PyPI
   - python -m twine upload dist/*

Notes
- If you use a virtualenv, activate it before running the commands.
- If build or twine are missing, install them in your environment:
  - python -m pip install --upgrade build twine
