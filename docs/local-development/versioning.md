# Versioning Guide

Galangal Orchestrate follows [Semantic Versioning](https://semver.org/) (SemVer) with adaptations for pre-1.0 development.

## Version Format

```
MAJOR.MINOR.PATCH
```

**Current stage:** `0.x.y` (pre-1.0 development)

## Version Components

### MAJOR (0.x.x → 1.x.x)

- **Currently:** Stays at `0` during active development
- **Bump to 1.0.0 when:**
  - Core workflow pipeline is stable and battle-tested
  - Public API (CLI commands, config schema) is considered stable
  - Breaking changes will be rare going forward

### MINOR (0.X.0)

Bump for notable changes that users should be aware of:

- **New features** - New commands, new workflow stages, new config options
- **Significant improvements** - Major TUI enhancements, new validation capabilities
- **Behavioral changes** - Changes to default behavior (even if non-breaking)
- **Dependency updates** - Major version bumps of key dependencies

Examples:
- Adding a new workflow stage (e.g., SECURITY stage)
- Adding a new CLI command (e.g., `galangal export`)
- Significant TUI redesign

### PATCH (0.0.X)

Bump for incremental changes:

- **Bug fixes** - Fixing incorrect behavior
- **Small improvements** - Minor TUI tweaks, better error messages
- **Documentation** - Doc-only changes that warrant a release
- **Refactoring** - Internal changes with no user-visible effect

Examples:
- Fixing a crash when config file is missing
- Adding version display to TUI header
- Improving error panel visibility

## Pre-1.0 Considerations

During `0.x.y` development:

- **MINOR** bumps may include breaking changes (document in changelog)
- **PATCH** bumps should never break existing functionality
- Aim for frequent small releases over infrequent large ones

## Release Checklist

1. **Update version** in `src/galangal/__init__.py`:
   ```python
   __version__ = "0.2.28"
   ```

2. **Commit the change**:
   ```bash
   git add src/galangal/__init__.py
   git commit -m "chore: bump version to 0.2.28"
   ```

3. **Create and push tag**:
   ```bash
   git tag v0.2.28
   git push origin main
   git push origin v0.2.28
   ```

4. **Create GitHub release**:
   ```bash
   gh release create v0.2.28 --title "v0.2.28" --notes "Release notes here"
   ```

   Or use the GitHub web interface to create a release from the tag.

5. **Verify PyPI publication** (automated via GitHub Actions):
   - Check https://pypi.org/project/galangal-orchestrate/
   - Test installation: `pipx upgrade galangal-orchestrate`

## Version Location

The version is defined in **one place only**:

```
src/galangal/__init__.py
```

The `pyproject.toml` uses dynamic versioning to read from this file:

```toml
[project]
dynamic = ["version"]

[tool.hatch.version]
path = "src/galangal/__init__.py"
```

## Commit Message Conventions

Use conventional commit prefixes:

- `feat:` - New feature (bumps MINOR)
- `fix:` - Bug fix (bumps PATCH)
- `chore:` - Maintenance, version bumps
- `docs:` - Documentation changes
- `refactor:` - Code refactoring
- `test:` - Test additions/changes

Examples:
```
feat(tui): add error panel widget for prominent error display
fix(claude): handle large prompts exceeding shell limit
chore: bump version to 0.2.28
docs: add versioning guide
```
