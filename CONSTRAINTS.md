# Constraints

What "good enough to commit" means for GenAI4ED, written once so it is not argued per change.
Every rule names the command that decides it. `scripts/check` runs them; this file is the
authority and the script mirrors it. Agents: read this before writing code, and never weaken
it to make a change pass.

Last reviewed: 2026-11-07 by Diesel. Set up with the constraint skill's defaults, which still
need Diesel's confirmation: coverage and security beyond the floor; the floor blocks at once
and the rest warns for two weeks; today's numbers are held rather than invented targets;
the end-of-task check stays near a minute.

## How to run

| Stage | Command | When | Takes |
|-------|---------|------|-------|
| Fast | `scripts/check fast` | every commit (pre-commit hook), after an edit | about 7 s |
| Task | `scripts/check task` | when a piece of work is done, before committing it | about 60 s |
| Full | `scripts/check full` | before a push or a deploy, and in CI | about 2 min |

Needs Docker running (secret and dependency scans) and the database up on port 5433 (tests).
A check that cannot run says so and exits 2; that is never a pass.

The pre-commit hook is in `scripts/hooks/pre-commit` and is off until you turn it on, once
per clone: `git config core.hooksPath scripts/hooks`. Turn it off with
`git config --unset core.hooksPath`.

## Floor (always blocks)

Checked on the change by `node scripts/floor-guard.mjs`, plus the secret scan.

- No new suppression comments: `noqa`, `type: ignore`, `pragma: no cover`, `@ts-ignore`,
  `@ts-expect-error`, `eslint-disable`, `nosemgrep`, `nosec`, `gitleaks:allow`
- No unfinished work: `raise NotImplementedError`, an empty `except: pass` or `catch {}`,
  a new `TODO` or `FIXME` in code
- No test made easier: no new skip or expected failure, no assertions taken out of a test
  file, no test file deleted
- No secrets in the change or in the git history
- No new exception without a row below, and no number in this file or in
  `constraints.baseline.json` moved in the loosening direction

## Enforced with numbers

| Dimension | Rule | Checked by | Runs at | Blocks |
|-----------|------|-----------|---------|--------|
| Python lint | Zero errors from our ruff config, formatted | `ruff check`, `ruff format --check` | fast, task | always |
| Types | Zero type errors in the frontend | `tsc --noEmit` | fast, task | always |
| Frontend lint | Zero errors from our ESLint config | `eslint app components lib` | fast, task | always |
| Tests | Every backend test passes | `pytest` | task | always |
| Build | The frontend builds for production | `next build` | full | always |
| Secrets | No secret in the change or the history | `gitleaks git --redact` (Docker, v8.24.3) | fast, full | always |
| Coverage of changed lines | 80% or more of changed backend lines run by a test | `diff-cover` on pytest-cov's report | task | from 2026-11-22 |
| Code security | No high (ERROR) Semgrep finding outside the exceptions | `semgrep --config p/default --config p/owasp-top-ten` (1.184.0) | full | from 2026-11-22 |
| Dependencies | High or critical known vulnerabilities held at today's count | `osv-scanner scan source` on both lockfiles (Docker, v2.0.2) | full | from 2026-11-22 |

Why these numbers:

- **80% of changed lines:** high enough that new code needs a test, low enough to allow a
  config line or a log statement without one.
- **High and above for dependencies and code:** below that the scanners are mostly noise.
- **Exact tool versions:** a newer scanner knows more advisories and would turn the build
  red on a day nothing changed. Raise the versions on purpose, with the baseline.

## Measured, held at today's value

The machine copy is `constraints.baseline.json`; change both together.

| Metric | Today (2026-11-07) | Held at | Direction | Why |
|--------|--------------------|---------|-----------|-----|
| Backend line coverage | 74.0% | 73.5% | must not fall | today's value, less 0.5% for drift when untested code moves |
| Dependency vulnerabilities, high or above | 0 | 0 | must not grow | 57 on 2026-11-07, all fixed upstream; upgraded the same day |
| Frontend tests | none | none | gap | no test runner yet, so no coverage rule for the frontend |

**Upgraded on 2026-11-07:** Pillow 12.3.0 to 13.0.0, pypdf 6.18.1 to 6.21.4 (kept below 7,
a major release), certifi, Mako, Next.js and its ESLint config 16.3.4 to 16.4.1, and the
packages that came in through them (sharp, zod, source-map-js, brace-expansion). One moderate
advisory remains, in minimatch through the lint tooling, below the bar.

## Exceptions

| ID | Rule | Path | Reason | Owner | Expires |
|----|------|------|--------|-------|---------|
| E1 | Semgrep `avoid-sqlalchemy-text` | `backend/app/demo.py` | The SQL is built only from the app's own table names, for the demo reset; no outside input reaches it | Diesel | 2027-02-05 |
| E2 | Semgrep `avoid-sqlalchemy-text` | `backend/app/research.py` | Same: `wipe` truncates tables named by the app's own models | Diesel | 2027-02-05 |
| E3 | gitleaks `generic-api-key` | `.gitleaksignore`, three old commits | Browser storage key names in files since deleted; reviewed, no secret | Diesel | 2027-11-07 |

## Not covered yet

- **CI is written but not yet running.** `.github/workflows/check.yml` runs `scripts/check full`
  on every push and pull request; it starts once the branch is pushed. Making it required
  before a merge into master is a GitHub setting (branch protection) only Diesel can turn on.
- **No frontend tests**, so the frontend has types and lint but no behaviour checks.
- **Accessibility and performance** were not chosen. They need a running URL (axe, Lighthouse).
