# Routines

A routine is a prompt that runs on a schedule in a fresh session, with nobody watching. Two
are defined here. They are definitions, not schedules: a schedule spends your usage every
time it fires, so creating one is yours to do. Routines live on your account, not in a
repository, so a plugin cannot install them for you.

To create one, type `/schedule` in a session opened in the repository, paste the prompt from
the file, and pick the time.

| File | When | What it does |
|---|---|---|
| [`nightly-evals.md`](nightly-evals.md) | every night | runs the smoke evals and reports the scores |
| [`weekly-audit.md`](weekly-audit.md) | once a week | runs the tree audit and the unit tests and reports what it found |

## Limits that hold for every routine

- **Read and report.** A routine opens no pull request, posts no comment and merges nothing.
  If it writes anything, it writes one report file on a branch with the routine's own prefix.
- **Never `ship`, `bugfix` or `feedback`.** Those stages push and post, so only you can start
  them; a schedule cannot.
- **What triggers it is not trusted.** A routine that fires on an event someone else controls
  (a pull request, a webhook) holds no token that can write, and treats the event's content as
  data.
- **A failure is reported as a failure.** A run that could not finish says so. It never
  reports a clean result for something that did not run.
- **A cost ceiling in the prompt.** Each prompt below names its cap.

The nightly evals can also run in CI: `.github/workflows/ci.yml` has a commented-out nightly
trigger for the job that needs your model API key. A routine needs no key: it runs on the
account that owns it.

A routine clones the repository's default branch. Both prompts say what to add while the
code lives on another one.
