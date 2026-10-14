#!/usr/bin/env python3
"""A read-only pass over everything git tracks in this repository.

  audit.py [--json]

The git guards look at what a commit adds. This looks at what is already there:

  - denylisted terms, likely secrets and hidden characters in tracked files and
    in their names;
  - CI files under .github/ that use someone else's action, reusable workflow or
    container image without pinning it to a commit hash or a digest;
  - lockfiles with no tool installed here that could audit them (a note, not a finding).

It changes nothing and touches no network. A finding names the place and the rule,
never the text that matched; a path that holds a denylisted term is printed with the
term cut out. A link is never followed: where it points is scanned as text.

Exit code 0 when clean, 1 when there is a finding, and 1 when git could not list the
files: an audit that read nothing is not a clean audit. Files it could not read are
named in the notes. Standard library only.
"""

import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "githooks"))

import monerex_scan  # noqa: E402

MAX_BYTES = 20_000_000
# `uses` as a key, however it is written: on its own line, in a list item, quoted, or inside { }.
USES = re.compile(r"""(?:^|[\s{,\-])["']?uses["']?\s*:\s*["']?([^"'\s#,}]+)""")
SHA = re.compile(r"@[0-9a-f]{40}$")
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")
AUDIT_TOOLS = {
    "package-lock.json": "npm",
    "yarn.lock": "yarn",
    "pnpm-lock.yaml": "pnpm",
    "uv.lock": "pip-audit",
    "poetry.lock": "pip-audit",
    "Cargo.lock": "cargo-audit",
    "go.sum": "govulncheck",
    "Gemfile.lock": "bundler-audit",
    "composer.lock": "composer",
}


def tracked():
    """(repository root, tracked names), or (None, why) when git cannot say."""
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True)
    if top.returncode != 0 or not top.stdout.strip():
        return None, "this is not a git repository, or git refused to read it"
    root = top.stdout.decode().strip()
    listed = subprocess.run(["git", "-C", root, "-c", "core.quotepath=off", "ls-files", "-z"], capture_output=True)
    if listed.returncode != 0:
        return None, "git could not list the tracked files"
    return root, [name for name in listed.stdout.decode("utf-8", errors="replace").split("\0") if name]


def read_text(path):
    """(text, None), or (None, why it was not read)."""
    if os.path.islink(path):
        return os.readlink(path), None  # where it points, as text; never what is behind it
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return None, "too large"
        with open(path, "rb") as handle:
            data = handle.read()
    except FileNotFoundError:
        return None, "tracked but missing from the working tree"
    except OSError:
        return None, "could not be read"
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace"), None
    if b"\0" in data:
        return None, "binary"
    return data.decode("utf-8", errors="replace"), None


def unpinned(reference):
    """Why a `uses:` reference can change under us, or None."""
    if reference.startswith("./"):
        return None  # part of this repository
    if reference.startswith("docker://"):
        return None if DIGEST.search(reference) else "a container image that is not pinned to a digest"
    return None if SHA.search(reference) else "an action from outside that is not pinned to a commit hash"


def audit():
    root, names = tracked()
    if root is None:
        return {"clean": False, "files": 0, "findings": [{"where": "git", "rule": names + "; nothing was audited"}], "notes": [], "not_read": []}
    entries, kind, problem = monerex_scan.load_denylist()
    findings, notes, not_read = [], [], []
    if kind in ("invalid", "unreadable"):
        findings.append({"where": "the denylist", "rule": problem})
        entries = []
    elif kind:
        notes.append("%s; terms were not checked" % problem)
    scan = monerex_scan.Scan(entries)
    for name in names:
        shown = monerex_scan.redact_path(name, entries)  # a path is printed with any term cut out of it
        scan.paths([name])
        if monerex_scan.HIDDEN.search(name):
            findings.append({"where": "path %s" % monerex_scan.HIDDEN.sub("?", shown), "rule": "hidden or bidirectional Unicode character in a file name"})
            shown = monerex_scan.HIDDEN.sub("?", shown)
        text, why = read_text(os.path.join(root, name))
        if text is None:
            not_read.append("%s (%s)" % (shown, why))
            continue
        lines = text.splitlines()
        for number, line in enumerate(lines, start=1):
            scan.content("%s:%d" % (shown, number), line)
        if name.startswith(".github/") and name.endswith((".yml", ".yaml")):
            for number, line in enumerate(lines, start=1):
                if line.lstrip().startswith("#"):
                    continue
                for reference in USES.findall(line):
                    rule = unpinned(reference)
                    if rule:
                        findings.append({"where": "%s:%d" % (shown, number), "rule": rule})
        tool = AUDIT_TOOLS.get(os.path.basename(name))
        if tool and not shutil.which(tool):
            notes.append("%s has no audit tool installed here (%s)" % (shown, tool))
    seen = set()
    for where, rule in scan.findings:
        if (where, rule) not in seen:
            seen.add((where, rule))
            findings.append({"where": where, "rule": rule})
    if not names:
        notes.append("git tracks no files here")
    if not_read:
        notes.append("%d file(s) were not read: %s" % (len(not_read), "; ".join(not_read[:20]) + ("; and more" if len(not_read) > 20 else "")))
    return {"clean": not findings, "files": len(names), "findings": findings, "notes": notes, "not_read": not_read}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    result = audit()
    if "--json" in argv:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print("monerex audit: %d tracked files, %d not read" % (result["files"], len(result["not_read"])))
        for finding in result["findings"]:
            print("  %s: %s" % (finding["where"], finding["rule"]))
        for note in result["notes"]:
            print("  note: %s" % note)
        print("monerex audit: %s" % ("clean" if result["clean"] else "%d finding(s)" % len(result["findings"])))
    return 0 if result["clean"] else 1


if __name__ == "__main__":
    sys.exit(main())
