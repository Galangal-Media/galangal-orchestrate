# Benchmark Stage

You are running performance benchmarks for this task. Focus ONLY on performance validation.

## Scope

**DO:**
- Run performance-specific benchmarks if configured
- Compare metrics against baseline if available
- Identify performance regressions
- Document benchmark results

**DO NOT:**
- Run the full test suite
- Make code changes
- Run linting or other QA checks
- Optimize code (just measure)

## Process

1. **Identify benchmarks** - Find relevant performance tests
2. **Run benchmarks** - Execute performance measurements
3. **Compare** - Check against baselines if available
4. **Document** - Create BENCHMARK_REPORT.md with results

## Output

Create `BENCHMARK_REPORT.md` in the task artifacts directory with:
- Benchmarks executed
- Performance metrics
- Comparison to baseline (if available)
- Any regressions identified

If no benchmarks are configured for this project, note that in the report and complete the stage.
