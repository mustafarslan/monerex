#!/usr/bin/env python3
"""The ablation gate: the tests that prove a committed change must fail without it.

  ablate.py --test "<command>" [--test ...] [--base <commit>] [--keep <path>] [--refactor | --bugfix]

The change is the difference between --base (default HEAD~1) and HEAD, and it must be
committed: with anything uncommitted the gate refuses, so the commit always holds the
whole change. The tests run twice with the change; then every changed file that is not a
test is taken back to the base in the working tree only (the index is never touched), the
tests run again in the real environment, those files are written back from the commit with
a fresh timestamp, and the tests run once more with the change, so outputs and caches are
rebuilt from it.

Only files still exactly as the gate left them are written back: anything someone else
changed meanwhile is left as it is and named. A test command that changes tracked files is
refused before anything is taken out, and anything on disk the take-out would overwrite is
refused up front. A run killed with the change out is put back by the next run, from a note
it wrote first. One run at a time per checkout.

Test files, paths under --keep (helpers and fixtures the tests need), lockfiles and the
manifests that say how tests run (package.json, Makefile, pyproject.toml and the like) stay
as in HEAD. Files hidden from git status (assume-unchanged, skip-worktree) are refused. Commands run at the repository root. A verdict is per command: name the narrowest
command that runs the tests for this change, not the whole suite.

For a bugfix (--bugfix) the test must fail by assertion without the fix (`weak` is a fail),
and the fix must change code. Whether that failure is the reported symptom is not judged
here: text cannot tell a value the broken code produced from the same words echoed from the
test, so the tail of each failure without the change is in the result, `without_output`, for
the session to read.

Results, printed as one JSON object and logged on the open task:
  pass      every command failed by assertion without the change
  weak      every command failed without the change, some only for a missing name
            (a new function or module): it depends on the change, not on its behaviour
  fail      a command passed without the change, did not run properly without it,
            or did not pass with it; for a refactor, did not pass both ways
  flaky     a command did not give the same answer twice
  skipped   no file outside the tests changed
  not-run   uncommitted work, a changed submodule, a timeout, a test that writes tracked
            files, another run in progress, or no usable git
Exit codes: 0 pass, weak or skipped; 1 fail or flaky; 2 not-run; 3 the working tree is not
the commit again, or HEAD moved during the run: see `git status`. Standard library only.
"""

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time

OWN_STATE = (".monerex/state/", ".monerex/log/", ".monerex/tmp/", ".claude/worktrees/")
NOTE = os.path.join(".monerex", "state", "ablate.json")
LOCK = os.path.join(".monerex", "state", "ablate.lock")
TEST_DIRS = {"test", "tests", "__tests__", "testdata"}
TEST_NAME = re.compile(
    r"^(test_.*|tests\.py|conftest\.py)$"  # Python
    r"|.*_(test|spec)\.[^.]+$"  # Go, Ruby, Elixir and the like
    r"|.*\.(test|spec)\.[^.]+$"  # JavaScript and TypeScript
    r"|.*[a-z0-9]Tests?\.[^.]+$"  # Java, C#, Kotlin: FooTest.java, not ABTest.ts
)
# Left in place: lockfiles (not behaviour, and protected by the guard, hooks/monerex_hook.py LOCKFILES)
# and the manifests that say how the tests run, so a test command can still start without the change.
LOCKFILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "uv.lock", "poetry.lock", "cargo.lock", "go.sum", "gemfile.lock", "composer.lock"}
MANIFESTS = {"package.json", "makefile", "gnumakefile", "justfile", "pyproject.toml", "setup.cfg", "tox.ini", "pytest.ini",
             "noxfile.py", "cargo.toml", "go.mod", "gemfile", "pom.xml", "build.gradle", "build.gradle.kts"}
# Failures that come from the change's names being gone, not from its behaviour.
MISSING_NAME = re.compile(
    r"\b(ImportError|ModuleNotFoundError|AttributeError|NameError|ReferenceError)\b"
    r"|cannot find (module|function|symbol|value|type)|undefined: |is not defined|has no attribute|no member named"
    r"|No such file or directory",
    re.IGNORECASE,
)
# Output that means the tests never ran properly.
BROKEN = re.compile(
    r"^\s*(SyntaxError|IndentationError|TabError)\b"
    r"|\bRan 0 tests\b|\bNO TESTS RAN\b|\bno tests ran\b|\bcollected 0 items\b|\bno test files\b"
    r"|command not found|Missing script|no test specified",
    re.MULTILINE | re.IGNORECASE,
)
PRE_RUNS = 2
SHOWN_LINES, SHOWN_CHARS = 30, 4000  # the tail of each command's failure without the change, for the session to read
SUBMODULE = "160000"


class NotRun(Exception):
    """Nothing was taken out: report and go on."""


class Unrestored(Exception):
    """The working tree is not the commit again, or HEAD moved: stop."""


def git(root, *args):
    done = subprocess.run(["git", "--literal-pathspecs", "-C", root, *args], capture_output=True)
    if done.returncode != 0:
        raise NotRun("git %s failed (exit %d): %s" % (" ".join(args[:2]), done.returncode, done.stderr.decode(errors="replace").strip()))
    return done.stdout.decode("utf-8", errors="replace")


def is_test(path):
    parts = path.split("/")
    return bool(TEST_DIRS.intersection(part.lower() for part in parts[:-1])) or bool(TEST_NAME.match(parts[-1]))


def uncommitted(root, tracked_only=False):
    """Paths that differ from HEAD, outside monerex's own folders."""
    entries = git(root, "status", "--porcelain", "-z", "--untracked-files=" + ("no" if tracked_only else "all")).split("\0")
    return [entry[3:] for entry in entries if len(entry) > 3 and not entry[3:].startswith(OWN_STATE)]


def changes(root, base):
    """{path: (present at base, present at HEAD)} for every path the change touches; NotRun for a submodule."""
    fields = git(root, "diff", "--raw", "--no-renames", "-z", base, "HEAD").split("\0")
    result = {}
    for meta, path in zip(fields[0::2], fields[1::2]):
        if not meta.startswith(":"):
            continue
        old_mode, new_mode, _, _, status = meta[1:].split()
        if SUBMODULE in (old_mode, new_mode):
            raise NotRun("the change touches the submodule %s, which the gate cannot take out" % path)
        result[path] = (status != "A", status != "D")
    return result


class Runner:
    """Runs one shell command at a time in its own process group, so a timeout or a signal stops all of it."""

    def __init__(self):
        self.current = None

    def run(self, command, cwd, timeout):
        """(exit code, output); exit None when the command timed out."""
        self.current = subprocess.Popen(command, shell=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        start_new_session=True)
        try:
            output, _ = self.current.communicate(timeout=timeout)
            return self.current.returncode, output.decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            self.stop()
            return None, "timed out after %ds" % timeout
        finally:
            self.current = None

    def stop(self):
        process = self.current
        if process and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
            process.communicate()


# The shell could not find or run the command at all.
CANNOT_START = (126, 127)


def classify(code, output):
    if code in CANNOT_START or BROKEN.search(output):
        return "broken"
    if code == 0:
        return "passed"
    if MISSING_NAME.search(output):
        return "missing-name"
    return "assertion"


def remove(root, path):
    full = os.path.join(root, path)
    if os.path.lexists(full):
        os.remove(full)


def stamp(root, paths, after):
    """Give each path a timestamp at least two seconds past `after` and return it: bytecode and build outputs
    keyed on a file's size and time to the second then cannot be reused across the swap."""
    when = max(time.time() + 1, after + 2)
    follow = os.utime not in os.supports_follow_symlinks  # a symlink's own time where the system allows it
    for path in paths:
        os.utime(os.path.join(root, path), (when, when), follow_symlinks=follow)
    return when


def newest(root, paths):
    times = [os.lstat(os.path.join(root, path)).st_mtime for path in paths if os.path.lexists(os.path.join(root, path))]
    return max(times) if times else 0


def parents(path):
    parts = path.split("/")[:-1]
    return ["/".join(parts[: index + 1]) for index in range(len(parts))]


def matches(root, commit, touched_at, path):
    """Whether the path on disk is exactly its version at `commit`: absent where the commit has none."""
    full = os.path.join(root, path)
    if not touched_at:
        return not os.path.lexists(full)
    if not os.path.lexists(full) or os.path.isdir(full) and not os.path.islink(full):
        return False
    if os.path.islink(full):  # hash-object would hash the target; a link's content is its text
        return os.readlink(full) == git(root, "cat-file", "blob", "%s:%s" % (commit, path))
    return git(root, "hash-object", "--", path).strip() == git(root, "rev-parse", "%s:%s" % (commit, path)).strip()


def take_out(root, base, touched, paths):
    """Write the base version of each path into the working tree only (removals first, for case-only renames).
    Returns the timestamp the base versions were given."""
    before = newest(root, paths)
    for path in paths:
        if not touched[path][0]:
            remove(root, path)
    present = [path for path in paths if touched[path][0]]
    if present:
        git(root, "restore", "--source=" + base, "--worktree", "--", *present)
    return stamp(root, present, before)


def put_back(root, head, base, touched, paths, at, made):
    """Write back from the commit every path still exactly as the gate left it, and remove the folders it made.

    A path already at HEAD counts as put back. Any other path was changed by someone else while the
    change was out: it is left as it is, and returned.
    """
    restore, others = [], []
    for path in paths:
        if matches(root, base, touched[path][0], path):
            restore.append(path)
        elif not matches(root, head, touched[path][1], path):
            others.append(path)
    for path in restore:
        if not touched[path][1]:
            remove(root, path)
    present = [path for path in restore if touched[path][1]]
    if present:
        git(root, "restore", "--source=" + head, "--worktree", "--", *present)
        stamp(root, present, at)
    for folder in sorted(made, key=len, reverse=True):
        try:
            os.rmdir(os.path.join(root, folder))  # only when empty
        except OSError:
            pass
    return others


def alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def lock(root):
    """One run at a time per checkout: an exclusive lock file holding the pid; a dead run's lock is taken over."""
    path = os.path.join(root, LOCK)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for _ in range(2):
        try:
            handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            try:
                with open(path, encoding="utf-8") as existing:
                    pid = int(existing.read().strip() or 0)
            except (OSError, ValueError):
                pid = 0
            if pid and alive(pid):
                raise NotRun("another gate run (pid %d) is in progress in this checkout" % pid)
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            continue
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(str(os.getpid()))
        return path
    raise NotRun("another gate run is starting in this checkout")


def heal(root):
    """Put back what a killed run left out, from its note. Files edited since are left as they are."""
    note = os.path.join(root, NOTE)
    if not os.path.exists(note):
        return
    try:
        with open(note, encoding="utf-8") as handle:
            record = json.load(handle)
        touched = {entry[0]: (entry[1], entry[2]) for entry in record["touched"]}
        head, base, paths = record["head"], record["base"], [path for path in record["paths"] if path in touched]
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        raise NotRun("%s is unreadable; check `git status`, then delete it" % NOTE)
    if head != git(root, "rev-parse", "HEAD").strip():
        raise NotRun("an interrupted run on another commit left %s; check `git status`, then delete it" % NOTE)
    others = put_back(root, head, base, touched, paths, record.get("at", 0), record.get("made", []))
    os.remove(note)
    print("monerex: an interrupted run had left the change out; it is put back", file=sys.stderr)
    if others:
        raise NotRun("an interrupted run had left the change out; these were edited since and are left as they are: %s"
                     % ", ".join(others))


def judge(classes, refactor, bugfix=False):
    """The gate's verdict from each command's runs without the change."""
    if any(len(set(runs)) > 1 for runs in classes):
        return "flaky", "a test gave different answers without the change"
    seen = {runs[0] for runs in classes}
    if refactor:
        return ("pass", "the tests pass with and without the refactor") if seen == {"passed"} else (
            "fail", "a test does not pass without the refactor: it changed behaviour, or no test ran")
    if "passed" in seen:
        return "fail", "a test passes without the change: it does not test it"
    if "broken" in seen:
        return "fail", "a test does not run without the change (syntax error or no tests): it proves nothing"
    if "missing-name" in seen:
        if bugfix:
            return "fail", "a bugfix's test must fail by assertion without the fix, not only because a name is missing"
        return "weak", "a test fails without the change only because a new name is missing"
    return "pass", "every command fails by assertion without the change"


def log(root, result):
    try:  # the task log never gets in the way
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import task

        task.append(root, "ablation", result=result)
    except Exception:
        pass


def ablate(root, tests, base="HEAD~1", keep=(), refactor=False, runs=3, timeout=600, stop_after_taking_out=False, bugfix=False):
    held = lock(root)
    try:
        heal(root)
        return checked_ablate(root, tests, base, keep, refactor, runs, timeout, stop_after_taking_out, bugfix)
    finally:
        try:
            os.remove(held)
        except FileNotFoundError:
            pass


def checked_ablate(root, tests, base, keep, refactor, runs, timeout, stop_after_taking_out, bugfix=False):
    dirty = uncommitted(root)
    if dirty:
        raise NotRun("commit the change first: the gate works on a commit, and these are not in one: " + ", ".join(dirty[:5]))
    head = git(root, "rev-parse", "HEAD").strip()
    git(root, "rev-parse", "--verify", "--quiet", base + "^{commit}")
    if subprocess.run(["git", "-C", root, "merge-base", "--is-ancestor", base, "HEAD"], capture_output=True).returncode != 0:
        raise NotRun("%s is not an ancestor of HEAD" % base)

    touched = changes(root, base)
    kept = sorted(path for path in touched
                  if path.startswith(tuple(keep)) or os.path.basename(path).lower() in LOCKFILES | MANIFESTS)
    tests_changed = sorted(path for path in touched if is_test(path) and path not in kept)
    ablated = sorted(path for path in touched if path not in kept and path not in tests_changed)
    result = {"base": base, "ablated": ablated, "tests_changed": tests_changed, "kept": kept, "runs": runs, "refactor": refactor}
    if bugfix:
        if refactor:
            raise NotRun("a bugfix changes behaviour; it is not a refactor")
        result["bugfix"] = True
    if not ablated:
        if bugfix:
            raise NotRun("a bugfix changes code, but no file outside the tests changed")
        return dict(result, result="skipped", reason="no file outside the tests changed")
    if refactor and tests_changed:
        return dict(result, result="fail", reason="a refactor changes no test, but these changed: " + ", ".join(tests_changed))

    hidden = [entry[2:] for entry in git(root, "ls-files", "-v", "-z", "--", *ablated).split("\0")
              if len(entry) > 2 and (entry[0].islower() or entry[0] == "S")]
    off = [path for path in ablated if path not in hidden and not matches(root, head, touched[path][1], path)]
    if hidden or off:  # assume-unchanged and skip-worktree hide local edits from status: never write over them
        raise NotRun("these are not exactly the commit on disk, or are hidden from git status (assume-unchanged or "
                     "skip-worktree), and the gate would overwrite them: %s" % ", ".join(hidden + off))
    written = [path for path in ablated if touched[path][0]]
    in_the_way = [path for path in ablated if not touched[path][1] and os.path.lexists(os.path.join(root, path))]
    in_the_way += sorted({folder for path in written for folder in parents(path)
                          if os.path.lexists(os.path.join(root, folder))
                          and (os.path.islink(os.path.join(root, folder)) or not os.path.isdir(os.path.join(root, folder)))})
    if in_the_way:  # not in the commit but on disk, ignored: taking the change out would overwrite them
        raise NotRun("these are not in the commit but exist on disk, and the gate would overwrite them: %s; move them away first"
                     % ", ".join(in_the_way))
    made = sorted({folder for path in written for folder in parents(path) if not os.path.lexists(os.path.join(root, folder))})

    runner = Runner()
    for command in tests:  # the tests must pass, the same way twice, with the change in
        outcomes = [runner.run(command, root, timeout) for _ in range(PRE_RUNS)]
        if any(code is None for code, _ in outcomes):
            return dict(result, result="not-run", reason="%s timed out with the change" % command)
        changed = uncommitted(root, tracked_only=True)
        if changed:
            raise NotRun("the test command changes tracked files (%s); the gate needs tests that leave the tree as it was. "
                         "Nothing was taken out, and their writes are left as they are" % ", ".join(changed[:5]))
        classes = {classify(code, output) for code, output in outcomes}
        if len(classes) > 1:
            return dict(result, result="flaky", reason="%s did not give the same answer twice with the change" % command)
        if classes != {"passed"}:
            return dict(result, result="fail", reason="%s does not pass with the change" % command)

    note = os.path.join(root, NOTE)
    at = max(time.time() + 1, newest(root, ablated) + 2) + 2  # later than any stamp take_out gives
    with open(note, "w", encoding="utf-8") as handle:  # written before anything is taken out
        json.dump({"pid": os.getpid(), "head": head, "base": base, "at": at, "paths": ablated, "made": made,
                   "touched": [[path, touched[path][0], touched[path][1]] for path in ablated]}, handle)

    def give_back():
        """Put back; the note goes once put back ran, and stays only if it could not."""
        others = put_back(root, head, base, touched, ablated, at, made)
        os.remove(note)
        return others

    def interrupted(number, _frame):
        runner.stop()
        try:
            give_back()
        except Exception:
            pass  # the note stays; the next run puts it back
        os._exit(128 + number)

    handlers = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    outcome = None
    try:
        at = max(at, take_out(root, base, touched, ablated))
        if stop_after_taking_out:  # for tests: leave the tree as a killed run would
            os._exit(0)
        without, shown = [], {}
        for command in tests:
            outcomes = [runner.run(command, root, timeout) for _ in range(runs)]
            if any(code is None for code, _ in outcomes):
                outcome = dict(result, result="not-run", reason="%s timed out without the change" % command)
                break
            without.append([classify(code, output) for code, output in outcomes])
            shown[command] = "\n".join(outcomes[-1][1].splitlines()[-SHOWN_LINES:])[-SHOWN_CHARS:]
    except (NotRun, OSError) as error:
        outcome = dict(result, result="not-run", reason="the change could not be taken out: %s" % error)
    finally:
        try:
            others = give_back()
        except (NotRun, OSError) as error:
            raise Unrestored("the change could not be put back (%s); %s is kept, and the next run puts it back" % (error, NOTE))
        finally:
            for sig, handler in handlers.items():
                signal.signal(sig, handler)
    if others:
        raise Unrestored("these were changed by something else while the change was out, and are left as they are: %s"
                         % ", ".join(others))
    if git(root, "rev-parse", "HEAD").strip() != head:
        raise Unrestored("HEAD moved during the run; the change was written back from %s. Check `git status` and the new commit" % head[:12])
    for command in tests:  # once more with the change: outputs and caches are rebuilt from it, and the put-back is proven
        code, output = runner.run(command, root, timeout)
        if code is None or classify(code, output) != "passed":
            raise Unrestored("after the change was put back, %s no longer passes; check `git status`" % command)
    left = uncommitted(root, tracked_only=True)
    if left:
        raise Unrestored("the working tree is not the commit again: %s" % ", ".join(left[:5]))
    if outcome:
        return outcome
    verdict, reason = judge(without, refactor, bugfix)
    return dict(result, result=verdict, reason=reason, without_change=dict(zip(tests, without)), without_output=shown)


EXIT = {"pass": 0, "weak": 0, "skipped": 0, "fail": 1, "flaky": 1, "not-run": 2}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--test", action="append", default=[], help="a command that runs the tests proving the change; repeatable")
    parser.add_argument("--base", default="HEAD~1", help="the commit before the change (default HEAD~1)")
    parser.add_argument("--keep", action="append", default=[], help="a path or folder prefix the tests need, left as in HEAD; repeatable")
    parser.add_argument("--refactor", action="store_true", help="the change keeps behaviour: tests must pass with and without it")
    parser.add_argument("--bugfix", action="store_true",
                        help="a bugfix: its test must fail by assertion without the fix, and the fix must change code")
    parser.add_argument("--runs", type=int, default=3, help="runs of each command without the change (default 3)")
    parser.add_argument("--timeout", type=int, default=600, help="seconds one run of a command may take (default 600)")
    parser.add_argument("--stop-after-taking-out", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not args.test:
        parser.error("name at least one --test command")
    if args.runs < 1 or args.timeout < 1:
        parser.error("--runs and --timeout must be at least 1")
    root, code = None, None
    try:
        root = git(os.getcwd(), "rev-parse", "--show-toplevel").strip()
        git(root, "rev-parse", "--verify", "--quiet", "HEAD")
        result = ablate(root, args.test, base=args.base, keep=args.keep, refactor=args.refactor, runs=args.runs,
                        timeout=args.timeout, stop_after_taking_out=args.stop_after_taking_out, bugfix=args.bugfix)
    except NotRun as error:
        result = {"result": "not-run", "reason": str(error)}
    except Unrestored as error:
        result, code = {"result": "not-run", "reason": str(error)}, 3
    if root:
        log(root, result["result"])
    print(json.dumps(result, indent=2))
    return code if code is not None else EXIT[result["result"]]


if __name__ == "__main__":
    sys.exit(main())
