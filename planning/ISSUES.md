# FinAlly: Integration Issues

Maintained by the Integration Tester (`integration-tester`). One entry per app bug found by the E2E suite (`test/`). Owners fix the issue, then set the status to `fixed` and add a short note; the tester re-runs and closes it (`verified`).

Owners: `frontend-engineer`, `api-engineer`, `db-engineer`, `llm-engineer`, `devops-engineer`.

Run the suite: `test/run_e2e.sh` (or `test/run_e2e.ps1`). Against an already running server: `BASE_URL=http://localhost:8000 npx playwright test` from `test/`.

## Template

```
### ISSUE-000: <short title>
- Owner: <agent>
- Status: open | fixed | verified | wontfix
- Spec: test/e2e/<file>.spec.ts › <test name>
- Contract ref: API_CONTRACT.md §<n>
- Repro:
  1. ...
- Expected: ...
- Actual: ...
- Logs / evidence:
  ```
  <error output, HTTP response, container log excerpt; trace at test/test-results/...>
  ```
- Notes: ...
```

## Run log

- 2026-10-27, PHASE 2 run 1 (`run_e2e.ps1`, `finally` image, `LLM_MOCK=true`): 30 passed, 3 flaky. Cause: a **test-harness bug**, not an app bug. The `beforeEach` reset was registered at module scope in `test/e2e/helpers.ts`, so it only ran for the first spec file each worker loaded. Fixed by making reset an auto fixture.
- 2026-10-27, run 2 (`--retries=0`) and run 3 (`run_e2e.ps1`): **33/33 passed**, no app issues found.

## Open

_None._

## Closed

_None._
