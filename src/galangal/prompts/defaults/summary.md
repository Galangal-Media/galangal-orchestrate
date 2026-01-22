# SUMMARY Stage - Generate Workflow Summary

You are generating a concise summary of what was accomplished in this task.

## Your Task

Create a SUMMARY.md file that provides a clear, reviewer-friendly overview of the changes made. This summary will be displayed to the user before PR creation and included in the PR body.

## Your Output

Create SUMMARY.md in the task's artifacts directory with the following sections:

```markdown
# Summary

## What Was Done
- [2-4 bullet points summarizing the key changes made]
- [Focus on user-visible outcomes and functionality]
- [Be specific but concise]

## Files Changed
- [List key files added or modified - not exhaustive]
- [Group by type if helpful: src/, tests/, docs/]
- [Focus on significant changes, not every file]

## Testing Instructions
[How to manually verify the changes work]
- [Specific steps to test the functionality]
- [What to look for to confirm success]

## Test Results
[Summary of automated test outcomes]
- [Which test suites passed]
- [Any notable test coverage information]

## Notes
[Optional: Any limitations, follow-up items, or things a reviewer should know]
- [Known limitations or edge cases]
- [Future improvements deferred]
- [Dependencies on other changes]
```

## Process

1. Review all previous stage artifacts:
   - SPEC.md for original requirements
   - DESIGN.md or PLAN.md for implementation approach
   - TEST_SUMMARY.md for test results
   - QA_REPORT.md for quality findings
   - SECURITY_CHECKLIST.md for security review
   - REVIEW_NOTES.md for code review feedback

2. Check `git diff --stat` to see files changed

3. Synthesize a clear summary that:
   - Highlights the most important changes
   - Provides clear testing instructions
   - Notes any caveats or follow-ups

## Important Rules

- Keep it concise - this is for quick review, not documentation
- Focus on "what changed" and "how to verify", not implementation details
- Be specific in testing instructions - a reviewer should be able to follow them
- Don't duplicate the full content of other artifacts - summarize key points
- If certain artifacts don't exist (stage was skipped), note that and continue
- Write in a neutral, professional tone
