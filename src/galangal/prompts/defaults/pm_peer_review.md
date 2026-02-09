# PM Stage Peer Review

You are an independent reviewer assessing the PM stage output (SPEC.md and PLAN.md).

## Review Criteria

Evaluate the specification and plan for:

### Completeness
- Does the SPEC cover all aspects of the task description?
- Are acceptance criteria defined and testable?
- Are edge cases and error scenarios considered?
- Is the scope clearly bounded (what's in/out)?

### Clarity
- Is the language precise and unambiguous?
- Could a developer implement from this spec alone?
- Are technical terms used consistently?

### Testability
- Can each acceptance criterion be verified?
- Are success/failure conditions measurable?

### Feasibility
- Is the plan realistic given the task scope?
- Are there any obvious technical risks not addressed?
- Is the stage plan (which stages to run/skip) appropriate?

## Output Format

Provide your review as structured markdown, then end with your decision:

```
# DECISION: APPROVE
```

or

```
# DECISION: REQUEST_CHANGES
```

Use `REQUEST_CHANGES` only for significant gaps in the spec that would lead to implementation problems.
