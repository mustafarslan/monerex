#!/usr/bin/env python3
"""Split a large saved diff into a few segments for a segmented `review-wide`.

  segment_diff.py .monerex/tmp/review.diff [--min-lines 400] [--max 3]

Files are grouped by their top-level folder (files at the root form one group). The smallest
groups are merged until at most --max remain; each segment's part of the diff is written next
to the input as review-<n>.diff, byte for byte, so every file is in exactly one segment.
Prints {"segments": [{name, paths, diff}]}; the list is empty when the diff changes fewer than
--min-lines lines or touches one group only, and then review-wide reviews the whole diff.
A diff whose paths cannot be read (git's diff.noprefix, say) is an error, exit 2, never an
empty split. Standard library only.
"""

import argparse
import json
import os
import sys

ESCAPES = {b"a": 7, b"b": 8, b"t": 9, b"n": 10, b"v": 11, b"f": 12, b"r": 13, b'"': 34, b"\\": 92}


class Unreadable(Exception):
    pass


def unquote(token):
    """Undo git's C-style quoting of a path: "web/t\\303\\251st.py" -> web/tést.py, as bytes."""
    if not token.startswith(b'"'):
        return token
    out, index, body = bytearray(), 0, token[1:-1]
    while index < len(body):
        char = body[index:index + 1]
        if char != b"\\":
            out += char
            index += 1
            continue
        following = body[index + 1:index + 2]
        if following.isdigit():
            out.append(int(body[index + 1:index + 4], 8))
            index += 4
        else:
            out.append(ESCAPES.get(following, following[0] if following else 92))
            index += 2
    return bytes(out)


def strip_prefix(path, prefixes=(b"a/", b"b/")):
    for prefix in prefixes:
        if path.startswith(prefix):
            return path[len(prefix):]
    return None


def header_path(rest):
    """The new path from `diff --git <a> <b>`, used only when no ---/+++/rename line names it."""
    if rest.startswith(b'"'):
        end = rest.index(b'"', 1)
        while rest[end - 1:end] == b"\\":
            end = rest.index(b'"', end + 1)
        second = rest[end + 2:]
        return strip_prefix(unquote(second), (b"b/",))
    second_quoted = rest.find(b' "b/')
    if second_quoted != -1:
        return strip_prefix(unquote(rest[second_quoted + 1:]), (b"b/",))
    if rest.startswith(b"a/") and (len(rest) - 5) % 2 == 0:  # the same path twice: a/P b/P
        half = (len(rest) - 5) // 2
        if rest[2:2 + half] == rest[2 + half + 3:] and rest[2 + half:2 + half + 3] == b" b/":
            return rest[2:2 + half]
    split = rest.rfind(b" b/")
    return rest[split + 3:] if rest.startswith(b"a/") and split != -1 else None


def block_path(lines):
    """The path a file block is about: +++, then rename to, then ---, then the header."""
    fields = {}
    for line in lines[1:]:
        if line.startswith(b"@@"):
            break
        for key in (b"+++ ", b"--- ", b"rename to ", b"copy to "):
            if line.startswith(key) and key not in fields:
                fields[key] = line[len(key):].rstrip(b"\n").rstrip(b"\t")
    new = fields.get(b"+++ ")
    if new is not None and new != b"/dev/null":
        return strip_prefix(unquote(new), (b"b/",))
    for key in (b"rename to ", b"copy to "):
        if key in fields:
            return unquote(fields[key])
    old = fields.get(b"--- ")
    if old is not None and old != b"/dev/null":
        return strip_prefix(unquote(old), (b"a/",))
    return header_path(lines[0][len(b"diff --git "):].rstrip(b"\n"))


def blocks(data):
    """(path, block bytes) for each file in a unified git diff; a renamed file goes by its new name."""
    found, current = [], None
    for line in data.splitlines(keepends=True):
        if line.startswith(b"diff --git "):
            if current:
                found.append(current)
            current = [line]
        elif current is not None:
            current.append(line)
    if current:
        found.append(current)
    result = []
    for number, lines in enumerate(found, start=1):
        path = block_path(lines)
        if path is None:
            raise Unreadable("cannot read the path of file %d in this diff (made with diff.noprefix or diff.mnemonicPrefix?)" % number)
        result.append((path.decode("utf-8", errors="replace"), b"".join(lines)))
    return result


def changed_lines(block):
    if isinstance(block, str):
        block = block.encode("utf-8")
    return sum(1 for line in block.splitlines() if line[:1] in (b"+", b"-") and not line.startswith((b"+++", b"---")))


def group_of(path):
    return path.split("/", 1)[0] if "/" in path else "(root)"


def segment(data, min_lines, most):
    groups = {}
    for path, body in blocks(data):
        group = groups.setdefault(group_of(path), {"paths": [], "data": b"", "size": 0})
        group["paths"].append(path)
        group["data"] += body
        group["size"] += changed_lines(body)
    if len(groups) < 2 or sum(group["size"] for group in groups.values()) < min_lines:
        return []
    named = [([name], group) for name, group in sorted(groups.items())]
    while len(named) > most:  # merge the two smallest
        named.sort(key=lambda item: (item[1]["size"], item[0]))
        (first_names, first), (second_names, second) = named[0], named[1]
        merged = {"paths": first["paths"] + second["paths"], "data": first["data"] + second["data"], "size": first["size"] + second["size"]}
        named = named[2:] + [(sorted(first_names + second_names), merged)]
    named.sort(key=lambda item: -item[1]["size"])
    return [{"name": "+".join(names), "paths": group["paths"], "data": group["data"]} for names, group in named]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("diff")
    parser.add_argument("--min-lines", type=int, default=400, help="split only a diff that changes at least this many lines")
    parser.add_argument("--max", type=int, default=3, help="at most this many segments (review-wide refuses more)")
    args = parser.parse_args(argv)
    with open(args.diff, "rb") as handle:
        data = handle.read()
    try:
        parts = segment(data, args.min_lines, max(2, min(args.max, 3)))
    except Unreadable as error:
        print("monerex: %s" % error, file=sys.stderr)
        return 2
    out = []
    for number, part in enumerate(parts, start=1):
        path = os.path.join(os.path.dirname(args.diff), "review-%d.diff" % number)
        with open(path, "wb") as handle:
            handle.write(part["data"])
        out.append({"name": part["name"], "paths": part["paths"], "diff": path})
    json.dump({"segments": out}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
