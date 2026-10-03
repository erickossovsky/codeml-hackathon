# CodeML Hackathon

> Draft. Created before the hackathon; improve it during the planning session.
> Everything marked TBD is decided at planning time.

## What this is
TBD (fill in at the start of the hackathon).

## Team
Ian, Chandler, Eric. Roles and lanes: TBD.

## Ground rules (hackathon)
- Core feature before wow feature. Stretch items are cut without debate when behind.
- The demo path is the only thing that must work end to end.
- Hourly 10-minute sync: done / next / blocked.
- Every ~3 hours run an end-to-end smoke test of the demo path.
- Prefer the simplest thing that works. No extra infrastructure.
- One shared definition of each cross-lane interface (schemas, endpoints); change it only after telling the others.

## Stack
TBD.

## Repo layout
```
frontend/   UI app
backend/    API services
ml/         models, training, evaluation, notebooks
shared/     cross-lane contracts (schemas, types, constants)
scripts/    setup, dev and deploy helpers
docs/       design docs and notes
data/       local datasets (gitignored contents)
```
Each lane works inside its own folder. Anything two lanes depend on goes in `shared/`.

## Branches
- `main`: base branch.
- `dev`: integration branch. Day-to-day work lands here (feature branches off `dev`, merge back to `dev`).
- `prod`: deployed branch. Only merge `dev` into `prod` when the demo path passes the smoke test.

## Commands
TBD (add setup, run and test commands as the project takes shape).

## Working with Claude Code in this repo
- Plugins are enabled project-wide via `.claude/settings.json`: `superpowers` (workflow skills) and `caveman` (terse replies). Accept the plugin trust/install prompt on first open.
- Use the superpowers workflow: brainstorm, then plan, then implement. For hackathon speed, keep specs short.
- Caveman mode is for chat replies only. Code, commit messages, PR text and docs are written in normal, clear prose.
- **No co-author lines.** Never add `Co-Authored-By` trailers or "Generated with Claude Code" attribution to commits or PRs.
- Never commit secrets. API keys go in `.env` (gitignored); share keys out of band.
- Commit messages: short imperative subject.
