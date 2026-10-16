# Where the open task stands

Follow this when `start` is typed with no argument.

```sh
python3 -I "${CLAUDE_SKILL_DIR}/../../scripts/task.py" status
```

It prints the open task, the stages logged behind it, the next one, and whether the checks
passed on this commit. Tell the user that in two or three lines, then offer to carry on with
the next stage. With no open task, say so and what the last finished one was; ask what they
want done.

Do not start a stage from here without the user's yes, and do not guess a stage from the
conversation: the log is the record. A stage done but not logged shows as still to do; say
so rather than logging it now.
