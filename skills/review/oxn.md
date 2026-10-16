# Measuring the change with the architecture gate

Follow this after step 1 of the review stage when the start probe reported an architecture gate.
`<command>` is the command it reported.

The tool measures the files as they are in this checkout, so it can say what a change did only
when the change is committed here:

```sh
<command> review --base <base> > .monerex/tmp/oxn-review.txt
```

- Always pass `--base`; the tool assumes `origin/main` otherwise.
- Uncommitted work: "not run: it measures committed work".
- A pull request reviewed without checking it out: "not run: the pull request is not checked
  out". Do not fetch or check it out for this.
- Exit 0 is the measurement. Any other exit is the tool failing: not run, with its message.

It is a report, never a gate: the repository's own `check` is the gate. Do not give it to the
reviewer; step 2 tells the reviewer nothing about what to find. In the report it goes under
*Architecture (measured)* as it is: its numbers are the tool's, quoted and never restated.
