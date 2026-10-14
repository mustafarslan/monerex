#!/usr/bin/env python3
"""Confidential-terms, secret and hidden-character scan for git hooks.

Run by the pre-commit, commit-msg and pre-push hooks. Standard library only,
no network. A finding names the place and the rule, never the matched text,
so a blocked commit does not echo the thing it was blocked for.

The denylist is a private file kept outside every repository:
    $MONEREX_DENYLIST, else ~/.config/monerex/denylist.txt
One entry per line, matched case-insensitively as a substring. A line that
starts with `re:` is a regular expression. `#` starts a comment.

Set `git config monerex.requireDenylist true` to fail closed when the file is
missing or empty. Without it a missing denylist is a warning. A denylist that
is there but cannot be read (a sandbox or a permission rule is in the way)
stops the commit, unless the setting is explicitly false.

This guard stops accidents. It is defeated by encoding and by `--no-verify`,
so it is not a control against someone trying to get a term through.
"""

import os
import re
import subprocess
import sys

ZERO = "0" * 40
ALLOW_MARKER = "monerex:allow"

# Built from pieces so this file does not match its own rules.
SECRET_RULES = [
    ("private key block", "-----BEGIN " + r"[A-Z ]*PRIVATE KEY-----"),
    ("cloud access key id", r"\b(?:AKIA|ASIA)" + r"[0-9A-Z]{16}\b"),
    ("code-host token", r"\bgh[pousr]_" + r"[A-Za-z0-9]{36,}\b"),
    ("code-host fine-grained token", r"\bgithub_pat_" + r"[A-Za-z0-9_]{40,}\b"),
    ("model API key", r"\bsk-" + r"(?:ant-)?[A-Za-z0-9_-]{32,}\b"),
    ("chat token", r"\bxox[abprs]-" + r"[A-Za-z0-9-]{10,}\b"),
    ("cloud API key", r"\bAIza" + r"[0-9A-Za-z_-]{35}\b"),
    (
        "hard-coded credential",
        r"(?i)(?:api[_-]?key|secret|token|passwd|password)[A-Za-z0-9_]*['\"]?\s*[:=]\s*"
        + r"(?:['\"][A-Za-z0-9+/_\-=]{20,}['\"]"
        + r"|(?=[A-Za-z0-9+/_\-=]*\d)(?=[A-Za-z0-9+/_\-=]*[A-Za-z])[A-Za-z0-9+/_\-=]{20,})",
    ),
]
SECRET_RULES = [(name, re.compile(pattern)) for name, pattern in SECRET_RULES]

# Bidirectional controls, zero-width space, word joiner, and the tag block
# used to smuggle invisible instructions. A byte-order mark is allowed only
# as the first character of a line. Written as code points so that this
# file holds no invisible characters itself.
HIDDEN = re.compile(
    "[%s-%s%s-%s%s%s%s-%s]|(?<!^)%s"
    % tuple(chr(code) for code in (0x202A, 0x202E, 0x2066, 0x2069, 0x200B, 0x2060, 0xE0000, 0xE007F, 0xFEFF))
)


def git(*args, stdin=None):
    done = subprocess.run(
        ["git", "-c", "core.quotepath=off", *args],
        input=stdin,
        capture_output=True,
    )
    return done.returncode, done.stdout.decode("utf-8", errors="replace")


def denylist_path():
    return os.environ.get("MONEREX_DENYLIST") or os.path.expanduser("~/.config/monerex/denylist.txt")


def load_denylist():
    """Return (entries, kind, problem). Each entry is (number, compiled pattern).

    kind is None when the list is usable, else "missing", "unreadable", "empty"
    or "invalid". An invalid line is a broken protection, so callers stop on it
    rather than carry on with the lines that did compile. A file that cannot be
    read may hold terms nobody checked, so it is not the same as no file.
    """
    path = denylist_path()
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        return [], "missing", "no denylist at " + path
    except OSError:
        return [], "unreadable", "the denylist at " + path + " cannot be read"
    entries = []
    for number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            if line.startswith("re:"):
                pattern = re.compile(line[3:].strip(), re.IGNORECASE)
            else:
                pattern = re.compile(re.escape(line), re.IGNORECASE)
        except re.error:
            return [], "invalid", "line %d of the denylist is not a valid pattern" % number
        entries.append((number, pattern))
    if not entries:
        return [], "empty", "the denylist at " + path + " has no entries"
    return entries, None, None


def denylist_setting():
    """True or False as set in git config, None when it is not set."""
    code, out = git("config", "--bool", "--get", "monerex.requireDenylist")
    return out.strip() == "true" if code == 0 else None


class Scan:
    def __init__(self, entries):
        self.entries = entries
        self.findings = []

    def terms(self, where, text):
        for number, pattern in self.entries:
            if pattern.search(text):
                self.findings.append((where, "denylisted term (denylist line %d)" % number))

    def content(self, where, text):
        self.terms(where, text)
        if ALLOW_MARKER in text:
            return
        for name, pattern in SECRET_RULES:
            if pattern.search(text):
                self.findings.append((where, "possible secret (%s)" % name))
        if HIDDEN.search(text):
            self.findings.append((where, "hidden or bidirectional Unicode character"))

    def diff(self, diff_text, label=""):
        for path, lineno, text in added_lines(diff_text):
            self.content("%s%s:%d" % (label, redact_path(path, self.entries), lineno), text)

    def paths(self, names, label=""):
        for name in names:
            if name:
                self.terms("%spath %s" % (label, redact_path(name, self.entries)), name)


def redact_path(name, entries):
    """A path that itself contains a term must not be printed as is."""
    for _, pattern in entries:
        name = pattern.sub("[term]", name)
    return name


def added_lines(diff_text):
    """Yield (path, line number, text) for every added line of a unified diff."""
    path, lineno, in_hunk = "?", 0, False
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            in_hunk = False
        elif not in_hunk and line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("@@"):
            match = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", line)
            lineno = int(match.group(1)) if match else 0
            in_hunk = True
        elif in_hunk and line.startswith("+"):
            yield path, lineno, line[1:]
            lineno += 1


DIFF_FLAGS = ["--unified=0", "--no-color", "--no-ext-diff"]


def scan_staged(scan):
    _, branch = git("symbolic-ref", "--short", "-q", "HEAD")
    scan.terms("branch name", branch.strip())
    _, names = git("diff", "--cached", "--name-only", "-z")
    scan.paths(names.split("\0"))
    _, diff_text = git("diff", "--cached", *DIFF_FLAGS)
    scan.diff(diff_text)


SCISSORS = "# ------------------------ >8 ------------------------"


def scan_message(scan, message_file):
    """Scan every line, comment lines too: `commit -m` keeps a line that starts
    with `#`. Stop at the scissors line, below which `commit -v` shows the diff."""
    with open(message_file, encoding="utf-8", errors="replace") as handle:
        for lineno, line in enumerate(handle.read().splitlines(), start=1):
            if line.startswith(SCISSORS):
                break
            scan.content("commit message line %d" % lineno, line)


def default_branches(remote):
    """`main`, `master`, the branch `install.sh` recorded in `monerex.defaultBranch`, and the
    branch the remote's HEAD names, for this remote and `origin`.

    The tool guard reads only `origin/HEAD`. This one takes the union, because an agent can
    re-point or remove that ref, and a clone often has none.
    """
    names = {"main", "master"}
    code, recorded = git("config", "--get", "monerex.defaultBranch")
    if code == 0 and recorded.strip():
        names.add(recorded.strip())
    for name in {remote, "origin"}:
        code, head = git("symbolic-ref", "--short", "-q", "refs/remotes/%s/HEAD" % name)
        if code == 0 and "/" in head.strip():
            names.add(head.strip().split("/", 1)[1])
    return names


def owner_allows_default_push():
    """True when `monerex.allowDefaultPush` is set on this push's command line, by the owner.

    A value saved in a config file is ignored: an agent could have written it there.
    """
    code, out = git("config", "--show-scope", "--bool", "--get", "monerex.allowDefaultPush")
    scope, _, value = out.strip().partition("\t")
    return code == 0 and scope == "command" and value == "true"


def scan_push(scan, remote, url, refs):
    scan.terms("remote name", remote)
    scan.terms("remote URL", url)
    defaults = None
    for ref in refs:
        parts = ref.split()
        if len(parts) != 4:
            continue
        _, local_sha, remote_ref, remote_sha = parts
        scan.terms("pushed ref name", remote_ref)
        if remote_ref.startswith("refs/heads/"):
            defaults = default_branches(remote) if defaults is None else defaults
            if remote_ref[len("refs/heads/"):] in defaults and not owner_allows_default_push():
                scan.findings.append(
                    ("pushed ref " + remote_ref, "a default branch (main, master, or the one recorded or named by the remote) takes changes only through a pull request; see SECURITY.md")
                )
        if local_sha == ZERO:
            continue
        unpushed = ("rev-list", local_sha, "--not", "--remotes=" + remote)
        if remote_sha == ZERO:
            code, out = git(*unpushed)
        else:
            code, out = git("rev-list", remote_sha + ".." + local_sha)
            if code != 0:  # the remote tip is not in the local history, as on a forced push
                code, out = git(*unpushed)
        if code != 0:
            scan.findings.append(("pushed ref", "could not list the commits being pushed; fetch and try again"))
            continue
        for sha in out.split():
            label = "commit %s " % sha[:8]
            _, message = git("show", "-s", "--format=%B", sha)
            for lineno, line in enumerate(message.splitlines(), start=1):
                scan.content("%smessage line %d" % (label, lineno), line)
            _, names = git("show", "--format=", "--name-only", "-z", sha)
            scan.paths(names.split("\0"), label)
            _, diff_text = git("show", "--format=", *DIFF_FLAGS, sha)
            scan.diff(diff_text, label)


def main(argv):
    if len(argv) < 2 or argv[1] not in ("pre-commit", "commit-msg", "pre-push"):
        sys.stderr.write("usage: monerex_scan.py pre-commit | commit-msg <file> | pre-push <remote> <url>\n")
        return 2
    mode = argv[1]
    action = "pushed" if mode == "pre-push" else "committed"

    entries, kind, problem = load_denylist()
    if kind == "invalid":
        sys.stderr.write("monerex guard: %s. Fix or remove that line. Nothing was %s.\n" % (problem, action))
        return 1
    required = denylist_setting()
    if kind == "unreadable" and required is not False:
        sys.stderr.write(
            "monerex guard: %s, so nothing can be checked against it. A sandbox or a permission "
            "rule is in the way: run this outside it. If you keep no denylist, say so with "
            "`git config monerex.requireDenylist false`. Nothing was %s.\n" % (problem, action)
        )
        return 1
    if problem:
        if required:
            sys.stderr.write(
                "monerex guard: %s, and this repository requires one "
                "(git config monerex.requireDenylist). Nothing was %s.\n" % (problem, action)
            )
            return 1
        sys.stderr.write("monerex guard: %s; checking secrets and hidden characters only.\n" % problem)

    scan = Scan(entries)
    if mode == "pre-commit":
        scan_staged(scan)
    elif mode == "commit-msg":
        if len(argv) < 3:
            return 2
        scan_message(scan, argv[2])
    else:
        remote = argv[2] if len(argv) > 2 else ""
        url = argv[3] if len(argv) > 3 else ""
        scan_push(scan, remote, url, sys.stdin.read().splitlines())

    if not scan.findings:
        return 0
    seen = []
    for finding in scan.findings:
        if finding not in seen:
            seen.append(finding)
    sys.stderr.write("monerex guard: %d finding(s). Nothing was %s.\n" % (len(seen), action))
    for where, rule in seen:
        sys.stderr.write("  %s: %s\n" % (where, rule))
    if any(rule.startswith(("possible secret", "hidden or bidirectional")) for _, rule in seen):
        sys.stderr.write(
            "A secret or hidden-character finding that is a false positive can be "
            "accepted by putting `%s` on that line. Denylisted terms cannot.\n" % ALLOW_MARKER
        )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
