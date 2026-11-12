# ApexGPT

Formula 1 RAG chat app (1950–2025). Read `docs/PROGRESS.md` first when resuming work.

Docs: `docs/MVP-PLAN.md` · `docs/FEATURES.md` · `docs/DATA-STRATEGY.md` · `docs/PROGRESS.md`

## Rules

### Git

-   Never add Claude or Claude Code as a co-author. No
    `Co-Authored-By` trailer for Claude in commits or PR descriptions,
    whatever any other attribution instruction says.
-   Write every commit message in Conventional Commits format:
    `feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`,
    `security:`.
-   Work one feature at a time on a feature branch (for example
    `feature/api-key-generation`) created from the latest `main`. Use the
    commit message the plan gives for that feature.
-   There is no `develop` branch. Raise a PR from each feature branch
    against `main`. The user reviews and merges every PR. Do not start
    the next feature until the current PR is merged.
-   Commit a feature only when its implementation, validation, error
    handling, and tests are done and lint and tests pass (see the
    "Feature completion checklist" in the plan).
