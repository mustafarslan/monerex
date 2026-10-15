# Holdout

Real-task eval cases that are never tuned on. They are the sealed half of the `real` suite:
the cases under `evals/` tagged `real` are what a change to a skill, agent, hook or route is
tried against; these are looked at only at a milestone, to see whether the tuning generalised.

## Where cases come from

From real tasks that went wrong: a task that escalated, failed verify, or was reverted after
it merged. Each becomes a case like the ones under `evals/`: a `fixture.sh` that rebuilds the
repository as it was when the task started, the original request as `prompt.md`, tagged
`[real]`, and deterministic graders (the checks passed, an acceptance test the fixture puts in
`protected-paths`, the implementer ran before the verifier).

## Which half a case goes to

Mechanically, so nobody picks which tasks are easy enough to tune on: a case belongs here
exactly when the SHA-256 of its name, read as a number, is divisible by 3. `tests/test_evals.py`
fails if a real case sits in the wrong half.

```sh
python3 -c 'import hashlib, sys; print(int(hashlib.sha256(sys.argv[1].encode()).hexdigest(), 16) % 3 == 0)' <case-name>
```

## Looking at it

```sh
python3 -I scripts/evalgate.py run --holdout --milestone <release>
```

Every look is logged to `.monerex/log/evalgate.jsonl`, and retro counts them. A case that fails
here is never fixed here: copy it under `evals/` with a new name that the split sends there,
tune against that copy, and leave this one as it was.
