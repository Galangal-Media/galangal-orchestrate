# Troubleshooting Guide

This guide covers common issues and their solutions when using Galangal Orchestrate.

## Quick Diagnostics

Before diving into specific issues, run the doctor command:

```bash
galangal doctor
```

This verifies your environment (Python, Git, Claude CLI, GitHub CLI, config, etc.) and identifies common setup problems.

---

## 1. Installation Issues

### Error: "Could not find a version that satisfies the requirement"

**Symptom:** pip install fails with version compatibility errors.

**Cause:** Python version is below 3.10.

**Solution:**
```bash
# Check your Python version
python --version

# Galangal requires Python 3.10+
# Install a newer Python version if needed
```

### Error: PyTorch/sentence-transformers installation fails

**Symptom:** Installing `galangal-orchestrate[full]` fails during PyTorch installation.

**Cause:** Platform-specific PyTorch wheels may not be available.

**Solutions:**

1. **Use lite install instead** (skip mistake tracking):
   ```bash
   pip install galangal-orchestrate
   ```

2. **Install PyTorch separately first:**
   ```bash
   # For CPU-only (smaller, faster install)
   pip install torch --index-url https://download.pytorch.org/whl/cpu
   pip install galangal-orchestrate[full]
   ```

3. **On Apple Silicon Macs:**
   ```bash
   # Ensure you're using native ARM Python, not Rosetta
   python -c "import platform; print(platform.machine())"
   # Should print "arm64", not "x86_64"
   ```

### Error: "externally-managed-environment"

**Symptom:** pip refuses to install on system Python (common on Ubuntu 23.04+, Fedora 38+).

**Solution:** Use pipx or a virtual environment:
```bash
# Option 1: pipx (recommended for CLI tools)
pipx install galangal-orchestrate

# Option 2: Virtual environment
python -m venv .venv
source .venv/bin/activate
pip install galangal-orchestrate
```

---

## 2. Authentication Errors

### Error: "Claude CLI not found"

**Symptom:** `galangal start` fails with "claude: command not found".

**Cause:** Claude CLI is not installed or not in PATH.

**Solution:**
```bash
# 1. Install Claude CLI
npm install -g @anthropic-ai/claude-code

# 2. Verify installation
claude --version

# 3. If installed but not found, add to PATH
# Check installation location:
npm root -g
# Add that directory to your PATH
```

### Error: "Authentication required"

**Symptom:** Stage execution fails with authentication error from Claude.

**Cause:** Claude CLI is not authenticated.

**Solution:**
```bash
# Check authentication status
claude auth status

# Login if needed
claude auth login

# Verify
claude auth status
```

### Error: "GitHub CLI not authenticated"

**Symptom:** GitHub integration commands fail with 401/403 errors.

**Cause:** GitHub CLI (gh) not authenticated or token expired.

**Solution:**
```bash
# Check status
gh auth status

# Login (browser-based)
gh auth login

# Or with token
gh auth login --with-token < ~/.github_token
```

### Error: "Cannot access repository"

**Symptom:** `galangal github setup` says "Cannot access repository".

**Cause:** Not in a git repo with a GitHub remote, or no push access.

**Solution:**
```bash
# Verify you're in a git repo
git remote -v

# Check if it's a GitHub repo
gh repo view

# If it's a fork, ensure you have push access
gh repo view --json viewerPermission
```

---

## 3. Workflow Failures

### Stage Times Out

**Symptom:** Stage fails after extended runtime with timeout error.

**Cause:** Default timeout (4 hours) exceeded, or specific command timeout exceeded.

**Solution:**

1. **Increase stage timeout:**
   ```yaml
   # .galangal/config.yaml
   stages:
     timeout: 21600  # 6 hours in seconds
   ```

2. **Increase specific validation timeout:**
   ```yaml
   validation:
     test:
       timeout: 1200  # 20 minutes
       commands:
         - name: "e2e tests"
           command: "npm run e2e"
           timeout: 600  # 10 minutes for this command
   ```

### Tests Hang at TEST Stage

**Symptom:** Workflow hangs indefinitely during test execution.

**Cause:** Test framework is running in interactive/watch mode.

**Solution:** Use CI-friendly commands:

```bash
# Playwright
npx playwright test --reporter=list
# Or: PLAYWRIGHT_HTML_OPEN=never npx playwright test

# Jest/Vitest - avoid watch mode
npm test  # NOT: npm test -- --watch

# Cypress - use run, not open
cypress run  # NOT: cypress open
```

### TEST Stage Loops Indefinitely

**Symptom:** TEST stage keeps retrying instead of rolling back.

**Cause:** TEST_PLAN.md doesn't have clear PASS/FAIL markers.

**Solution:**
1. Check TEST_PLAN.md has `**Status:** PASS` or `**Status:** FAIL`
2. If validation is unclear, Galangal (v0.12.0+) prompts for manual decision
3. Ensure test commands return proper exit codes (0 = success)

### Validation Command Fails

**Symptom:** Stage fails because validation command returns non-zero.

**Diagnosis:**
```bash
# Check the validation report
cat galangal-tasks/<task-name>/VALIDATION_REPORT.md
```

**Common fixes:**
1. Fix the actual code issue indicated in the report
2. Mark the validation as `warn_only` if it's not critical:
   ```yaml
   validation:
     dev:
       commands:
         - name: "lint"
           command: "npm run lint"
           warn_only: true  # Warn but don't fail
   ```

### Git Conflicts During Workflow

**Symptom:** Stage fails due to git conflicts.

**Cause:** Branch diverged from base or conflicting changes.

**Solution:**
```bash
# 1. Pause the workflow (Ctrl+Q)
# 2. Resolve conflicts manually
git status
git merge main  # or rebase
# Resolve conflicts...
git add .
git commit

# 3. Resume
galangal resume
```

---

## 4. Performance Issues

### Slow CLI Startup

**Symptom:** `galangal` commands take several seconds to start.

**Cause:** Heavy imports being loaded eagerly.

**Note:** Galangal uses lazy imports for fast startup. If you're still seeing slow starts:

```bash
# Check which imports are slow
python -c "import time; t=time.time(); import galangal; print(f'{time.time()-t:.2f}s')"

# If >1 second, check for slow plugin imports or PATH issues
```

### High Memory Usage with Mistake Tracking

**Symptom:** Python process uses >2GB memory with mistake tracking enabled.

**Cause:** Embedding model loaded in memory.

**Solutions:**

1. **Check if you need full install:**
   ```bash
   # If not using mistake tracking, switch to lite:
   pip uninstall galangal-orchestrate
   pip install galangal-orchestrate
   ```

2. **Memory is expected** with `[full]` install - sentence-transformers loads ~400MB model

### Prompts Getting Too Large

**Symptom:** Later stages fail or are slow due to large prompt context.

**Cause:** Accumulated artifacts bloating prompts.

**Solution:** Configure artifact context filtering:
```yaml
# .galangal/config.yaml
artifact_context:
  review:
    required: [SPEC.md, DEVELOPMENT.md]
    include: [QA_REPORT.md]
    exclude: [PREFLIGHT.md, TEST_PLAN.md, TEST_GATE_RESULTS.md]
```

---

## 5. Common Error Messages

### "Galangal has not been initialized"

**Cause:** No `.galangal/` directory in project.

**Solution:**
```bash
cd your-project
galangal init
```

### "No active task"

**Cause:** No task currently active.

**Solution:**
```bash
# List tasks
galangal list

# Start a new task
galangal start "description"

# Or switch to existing task
galangal switch <task-name>
```

### "Task exits without error message"

**Diagnosis:**
```bash
# Enable debug mode
galangal --debug start "task"

# Check logs
tail -50 logs/galangal_debug.log
```

### "Config validation failed"

**Cause:** Invalid `.galangal/config.yaml`.

**Solution:**
```bash
# Validate config
galangal config validate

# Show current config
galangal config show

# Edit interactively
galangal config edit
```

---

## 6. Hub Environments

### CORS Errors Between Services

**Symptom:** Your environment runs a frontend (e.g. `:3031`) and a backend API (e.g. `:5022`) on different ports. The browser console shows the API request succeeds (200 OK) but the response body says "failed to load response data". The frontend can't read API responses.

**Cause:** This is a CORS (Cross-Origin Resource Sharing) issue. When a frontend on one origin (e.g. `http://localhost:3031`) makes a request to an API on a different origin (e.g. `http://localhost:5022`), the browser blocks the response unless the API explicitly allows it with the `Access-Control-Allow-Origin` header.

Even though both are on `localhost`, different ports = different origins to the browser.

**Diagnosis:** Look at the API response headers. You'll see something like:
```
access-control-allow-credentials: true
```
But no `Access-Control-Allow-Origin` header — that's the missing piece.

**Solution:** Configure CORS on your backend API to allow the frontend origin.

**FastAPI:**
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3031"],  # or use env var
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Express/Node:**
```javascript
const cors = require('cors');
app.use(cors({
  origin: 'http://localhost:3031',
  credentials: true,
}));
```

**Django:**
```python
# settings.py (with django-cors-headers)
CORS_ALLOWED_ORIGINS = ["http://localhost:3031"]
CORS_ALLOW_CREDENTIALS = True
```

**Tip:** Many frameworks support a `CORS_ORIGINS` environment variable. Add it to your environment's env vars in the hub so you can configure it per-environment without changing code:

```
CORS_ORIGINS=http://localhost:3031
```

### Services Can't Reach Each Other in Docker

**Symptom:** Frontend container can't reach the backend via `localhost:5022`.

**Cause:** In Docker Compose, each container has its own network. `localhost` inside a container refers to that container, not the host or other containers.

**Solution:** For server-side calls between containers, use the Docker Compose service name:
```yaml
services:
  frontend:
    environment:
      - API_URL=http://backend:5022
  backend:
    # ...
```

For client-side (browser) calls, `localhost` works because the browser runs on the host — just make sure ports are published in docker-compose.

### Git Pull Fails With "Divergent Branches"

**Symptom:** Pulling latest changes fails with "diverging branches" or "not possible to fast-forward".

**Cause:** The local branch and remote branch have diverged — both have commits the other doesn't.

**Solution:** Use the Git tab in the environment detail page. When a pull fails due to divergence, the hub shows three options:

- **Rebase** — replays your local commits on top of remote (cleanest history)
- **Merge** — creates a merge commit combining both (preserves all history)
- **Reset to remote** — discards all local changes and matches remote exactly

---

## 7. Debug Mode

When all else fails, enable debug mode for detailed logs:

```bash
# Via flag
galangal --debug start "task"
galangal --debug resume

# Via environment variable
GALANGAL_DEBUG=1 galangal start "task"
```

Debug logs are written to:
- `logs/galangal_debug.log` - Human-readable debug trace
- `logs/galangal.jsonl` - Structured JSON logs

Example debug output:
```
[14:32:15.123] Starting stage: DEV
[14:32:15.124] Loading prompt from: .galangal/prompts/dev.md
[14:32:15.125] Invoking claude with args: ['--output-format', 'stream-json', ...]
[14:32:45.678] Claude exited with code: 0
[14:32:45.679] Running validation: pytest tests/
[14:32:50.123] Validation failed: exit code 1
```

---

## Getting Help

If you can't resolve an issue:

1. **Search existing issues:** https://github.com/Galangal-Media/galangal-orchestrate/issues

2. **Open a new issue** with:
   - Galangal version (`galangal --version`)
   - Python version (`python --version`)
   - OS and version
   - Debug log output (`galangal --debug ...`)
   - Steps to reproduce

3. **Check the documentation:**
   - [README.md](../README.md) - Main documentation
   - [docs/local-development/](./local-development/) - Technical details
