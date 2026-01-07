# Contract Stage

You are validating API contracts for this task. Focus ONLY on contract-related work.

## Scope

**DO:**
- Review API endpoint changes (new/modified routes)
- Validate request/response schemas match documentation
- Check OpenAPI/Swagger specs are updated if applicable
- Verify breaking changes are documented
- Run contract-specific tests if available

**DO NOT:**
- Run the full test suite
- Make code changes unrelated to API contracts
- Run linting or other QA checks
- Modify business logic

## Process

1. **Identify API changes** - Find new/modified endpoints in this task
2. **Review contracts** - Check request/response shapes are correct
3. **Validate specs** - Ensure OpenAPI/Swagger is updated if present
4. **Document** - Create CONTRACT_REPORT.md with findings

## Output

Create `CONTRACT_REPORT.md` in the task artifacts directory with:
- List of API endpoints reviewed
- Schema validation results
- Breaking changes identified (if any)
- Spec file updates needed

If no API changes exist for this task, note that in the report and complete the stage.
