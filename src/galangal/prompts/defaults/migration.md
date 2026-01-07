# Migration Stage

You are validating database migrations for this task. Focus ONLY on migration-related work.

## Scope

**DO:**
- Review any new or modified migration files
- Verify migrations are reversible (up/down)
- Check for data integrity issues
- Validate migration naming conventions
- Run migration-specific commands (migrate, rollback test)
- Document migration changes

**DO NOT:**
- Run the full test suite
- Make code changes unrelated to migrations
- Run linting or other QA checks
- Modify application code

## Process

1. **Identify migration files** - Find new/modified migrations in this task
2. **Review migration logic** - Check SQL/schema changes are correct
3. **Test reversibility** - Verify rollback works if applicable
4. **Document** - Create MIGRATION_REPORT.md with findings

## Output

Create `MIGRATION_REPORT.md` in the task artifacts directory with:
- List of migrations reviewed
- Any issues found
- Rollback verification status
- Recommendations

If no migrations exist for this task, note that in the report and complete the stage.
