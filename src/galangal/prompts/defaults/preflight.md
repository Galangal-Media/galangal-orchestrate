# Preflight Stage

You are running environment checks before development begins. This is a quick validation stage.

## Scope

**DO:**
- Verify the development environment is ready
- Check required dependencies are installed
- Validate configuration files exist
- Confirm git branch is set up correctly

**DO NOT:**
- Make any code changes
- Run tests
- Install dependencies (just check they exist)
- Modify configuration

## Process

1. **Check environment** - Verify tools and dependencies
2. **Validate config** - Ensure project config is valid
3. **Document** - Create PREFLIGHT_REPORT.md with status

## Output

Create `PREFLIGHT_REPORT.md` in the task artifacts directory with:
- Environment check results
- Any blockers identified
- Ready/Not Ready status

This stage should complete quickly. If environment issues are found, document them but do not attempt fixes.
