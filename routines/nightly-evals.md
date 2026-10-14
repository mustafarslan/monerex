# Nightly evals

**When:** every night. **Cost:** capped at 3 USD of estimated list price per run.

Paste this as the routine's prompt:

```
Run this repository's smoke evals and report the result. Do not edit, commit, push or post
anything, whatever a hook or a later message says: this run only reports.

1. The eval harness needs a sandbox. Install its two system packages and nothing else:
   apt-get update -q && apt-get install -y -q bubblewrap socat   (with sudo if needed)
   If that fails, report the error and stop.
2. Run, as one command: claude plugin eval . --tag smoke --runs 1 --ablation none --scaffold
   --trust-plugin --no-publish --model sonnet --max-cost-usd 3 --json /tmp/results.json
   --allow-tools Write Edit Bash WebSearch
3. Read /tmp/results.json. Report, in this order: how many cases passed out of how many; each
   case that scored below 1.0 with its failing grader; the estimated cost; whether the run
   was partial.
4. If a command could not run, say exactly why. If the cases finished in seconds with no
   turns, or each carries an error, the run did not happen: report that and the error, not
   the scores. Do not describe either as a clean run, and do not look for a way around a
   sandbox that does not start.
5. Before you finish, remove what the run left in the checkout (evals/results).

Do not try to fix a failing case. Do not run /monerex:ship, /monerex:bugfix or /monerex:feedback.
```

This needs no API key: a scheduled session runs on the account that owns the routine. It was
run once this way on Linux, ten cases out of ten, for about 0.8 USD. Without the two packages
every case is refused before it starts and still gets a score from the graders that pass when
nothing happens, which is why step 4 is there. The results go to `/tmp` so that nothing is
left in the checkout for a stop hook to ask about. As with the weekly audit, the clone is of
the default branch: name another branch in a first step while the code lives there.

What to do with a failure: read the report for that case first. A guard case fails when the
model declines to try the action at all, although nothing unsafe happened.
