# ApexGPT: Development workflow

How work gets done in this repository. It's the MVP's workflow ([archived plan](./archive/v1.0.0-mvp/MVP-PLAN.md#5-development-workflow)), kept as is and updated with what the MVP taught. The git rules are also in [CLAUDE.md](../CLAUDE.md).

## Branches and pull requests

- **`main`** is the only long-lived branch. There's no `develop` branch.
- **One feature at a time,** on a branch `feature/<name>` created from the latest `main`.
- **Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/):** `feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`, `security:`.
- **When the feature passes the checklist below, raise a PR against `main`.** The user reviews and merges every PR, and the next feature starts only after the merge.
- **Commits and PRs never include Claude or Claude Code co-author attribution.**
- **Releases:** an annotated tag `vX.Y.Z` on `main` plus a GitHub Release, after the production smoke test passes.

**The cycle:** pull the latest `main` → create `feature/<name>` → build → checklist → commit → push → PR → the user reviews and merges → next feature.

## Feature completion checklist

A feature is committed and merged only when **every** item is true:

- [ ] **Implementation:** everything in scope is built; nothing is stubbed or left as a TODO.
- [ ] **Validation:** inputs are validated at boundaries (API request models, settings and environment, external data from Jolpica, Wikipedia and LLM responses).
- [ ] **Error handling:** expected failures are handled (network errors, rate limits, timeouts, bad data, empty results) with clear messages; no secrets or stack traces reach users.
- [ ] **Tests:** unit tests for new logic, and integration tests where the feature crosses a boundary (database, HTTP, LLM). External services are faked in unit tests.
- [ ] **Lint and format pass:** ruff and black (Python), eslint and prettier (TypeScript), via `pre-commit run --all-files`.
- [ ] **All tests pass:** the full backend, ingestion and frontend suites, not just the new tests.
- [ ] **Docker builds:** images for the affected services build and start (`docker compose up`).
- [ ] **No secret-shaped strings:** no real credentials, and no fake ones that look real. GitGuardian scans every commit in a PR, so a flagged string means rewriting the branch. Build fake URLs at runtime in tests, and avoid `${PASSWORD_VAR:?message}`-style guards.
- [ ] **Docs updated:** `.env.example`, the README and `docs/` reflect any new config or behaviour.
- [ ] **[PROGRESS.md](./PROGRESS.md) updated:** the feature's row is added or updated (🔍 PR raised, ✅ after the merge), with the current status, next up and open issues.
- [ ] **PR raised** against `main`, with a summary of the scope, how it was tested, and anything to review closely. Wait for CI and read **every** check, GitGuardian included.

## Changes that affect answers

- Measure them with the golden set:
  - `python -m evals run` (a category or a few `--id`s while iterating), or `rescore` for expectation-only changes;
  - **pin the judge** (`--judge-provider`), because providers grade differently.
- `python -m evals retrieval` checks search changes without spending LLM quota.
- Keep golden expectations to what a correct answer to *that* question must contain.

## After a deploy

Run the production smoke test from `backend/`. It must pass before a release is tagged:

```bash
uv run python -m evals smoke --frontend https://apexgpt.ruturaj.xyz --api https://apexgpt-api.ruturaj.xyz
```

See [DEPLOYMENT.md](./DEPLOYMENT.md).
