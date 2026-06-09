# Global Editable Install (for cross-project development)

If you develop galangal in one clone but **run `galangal` from other repositories**
(e.g. `galangal start` inside a separate project), you want the global `galangal`
command to track your working tree automatically. This page covers that setup and
the one nuance that trips people up: the version shown in the header.

## The problem

There are two independent installs, and they don't interact:

| Install | Command it provides | Scope |
|---------|--------------------|-------|
| `pip install -e .` inside the repo's `venv` | `galangal` | Only when that venv is **activated** |
| `pipx install galangal-orchestrate` | `galangal` on your global `PATH` (`~/.local/bin/galangal`) | Everywhere |

When you run `galangal start` from another project (with no venv active), your shell
finds the **pipx** copy. If that was installed from PyPI, it's pinned to whatever
version you installed — it does **not** follow your local repo, so you can be "stuck"
on an old version (e.g. `0.38.1`) while your repo is far ahead.

## The fix: point the global command at your local repo (editable)

Replace the pipx install with an **editable** install from your clone:

```bash
pipx uninstall galangal-orchestrate
pipx install --editable /path/to/galangal-orchestrate
```

This puts `galangal` (and `galangal-hub`) on your global `PATH`, but running from
your repo's `src/`. From then on, **code changes and `git pull` are picked up
immediately** — no reinstall — from any directory.

## What updates automatically, and what doesn't

- **Code / behavior** → always live. An editable install imports from your working
  tree, so edits and pulls take effect on the next run.
- **The version in the header** → **frozen at install time.** Galangal resolves its
  version via `importlib.metadata.version("galangal-orchestrate")` (see
  `_read_version()` in `src/galangal/__init__.py`), which reads the `.dist-info`
  metadata written when you ran `pipx install`. A `git pull` that bumps the `VERSION`
  file does **not** update that metadata. So the header number can lag even though
  you're running the latest code. This is cosmetic.

To refresh the displayed version (and to pick up new dependencies or entry points
after a `pyproject.toml` change), reinstall with `--force`:

```bash
pipx install --editable --force /path/to/galangal-orchestrate
```

> The runtime version-update check (PyPI) is separate and unaffected; this is purely
> about what number the local install reports for itself.

## Verifying the setup

```bash
# Global command resolves and reports the repo's current version
galangal --version

# Confirm it imports from your repo source (not a copied install)
"$(pipx environment --value PIPX_LOCAL_VENVS)/galangal-orchestrate/bin/python" \
  -c "import galangal; print(galangal.__file__)"
# -> /path/to/galangal-orchestrate/src/galangal/__init__.py
```

An editable pipx install also leaves an `_editable_impl_galangal_orchestrate.pth`
file in the venv's `site-packages`, pointing at your `src/`.

## Reverting to the published release

```bash
pipx uninstall galangal-orchestrate
pipx install galangal-orchestrate          # latest from PyPI
```

## Notes

- You can keep the in-repo `venv` editable install (`pip install -e .`) as well — it
  takes precedence when its venv is activated. The pipx editable install just makes
  the same source available globally without activating anything.
- Editable installs cache metadata at install time; this is why both `pip show` and
  the header report the install-time version until you reinstall.
