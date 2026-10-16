#!/usr/bin/env python3
"""Monerex's tool-level guards. One module, one process per event.

  monerex_hook.py pre-edit       PreToolUse on Edit, Write, MultiEdit, NotebookEdit
  monerex_hook.py pre-bash       PreToolUse on Bash
  monerex_hook.py pre-web        PreToolUse on WebSearch, WebFetch
  monerex_hook.py post-bash      PostToolUse and PostToolUseFailure on Bash: the commit log, and a
                                warning when a protected file changed while the command ran
  monerex_hook.py session-start  SessionStart: says that this repository uses monerex
  monerex_hook.py config-change  ConfigChange (log only)
  monerex_hook.py agent-log      SubagentStart and SubagentStop (log only)

The guards act only in a repository that has opted in with .monerex/config.json.
They fail closed: an error inside a guard denies the call. The loggers fail open.

These are early warnings, not boundaries. The edit rules cover the edit tools;
a shell command that writes the same file is noticed afterwards, not stopped.
Matching a command's text is defeated by encoding. The boundaries are the sandbox, git's own hooks and
branch protection on the remote. See SECURITY.md.

Standard library only, no network, and no part of the tool input reaches a shell.
"""

import fnmatch
import functools
import glob
import json
import os
import re
import shlex
import subprocess
import sys
import time
import unicodedata

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PLUGIN_ROOT, "githooks"))
sys.path.insert(0, os.path.join(PLUGIN_ROOT, "scripts"))

# Everything below is matched in lower case: the common filesystems on macOS
# and Windows are case-insensitive, so `.CLAUDE/settings.json` is the same file.
AGENT_CONFIG = [
    ".claude/*",
    ".mcp.json",
    ".git",
    ".git/*",
    ".monerex/config.json",
    ".monerex/state/*",
    ".github/workflows/*",
    ".gitlab-ci.yml",
    ".vscode/*",
]
INSTRUCTION_FILES = {"claude.md", "claude.local.md", "agents.md"}
SECRET_NAMES = [".env", ".env.*", "*.pem", "id_rsa*", "id_ed25519*", ".npmrc", ".netrc"]
SECRET_EXAMPLES = (".example", ".sample", ".template")
LOCKFILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "uv.lock",
    "poetry.lock",
    "cargo.lock",
    "go.sum",
    "gemfile.lock",
    "composer.lock",
}
# The parts of monerex that the guards are made of, wherever the plugin lives.
GUARD_DIRECTORIES = ("hooks", "githooks", "scripts", "routing", "bin")


def git(cwd, *args):
    done = subprocess.run(["git", "-C", cwd, *args], capture_output=True)
    return done.stdout.decode("utf-8", errors="replace").strip()


def repo_root(cwd):
    return git(cwd, "rev-parse", "--show-toplevel") or cwd


@functools.lru_cache(maxsize=None)
def owner_root(root):
    """The owner's own checkout, even when `root` is a linked worktree of it.

    Git lists the main worktree first. Three cases give `root` back, because there is no
    owner's checkout to find: a bare repository, a folder outside git, and a repository whose
    git directory is kept apart from its checkout, where git lists the git directory and
    does not record where the checkout is.
    """
    first = git(root, "worktree", "list", "--porcelain").split("\n\n")[0].split("\n")
    if first[0].startswith("worktree ") and "bare" not in first[1:]:
        main = os.path.realpath(first[0][len("worktree ") :])
        common = git(root, "rev-parse", "--git-common-dir")
        # A folder that is not there is a path this could not read back, such as one with
        # a line break in its name.
        if common and main != os.path.realpath(os.path.join(root, common)) and os.path.isdir(main):
            return main
    return os.path.realpath(root)


def load_config(root):
    """None when the repository has not opted in."""
    path = os.path.join(root, ".monerex", "config.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def read_lines(root, name):
    try:
        with open(os.path.join(root, ".monerex", "state", name), encoding="utf-8") as handle:
            return [line.strip() for line in handle if line.strip() and not line.startswith("#")]
    except OSError:
        return []


def protected_entries(root):
    """What tasks have made read-only in this checkout: its own entries and the owner's."""
    entries = []
    for one in dict.fromkeys((os.path.realpath(root), owner_root(root))):
        entries += [entry for entry in read_lines(one, "protected-paths") if entry not in entries]
    return entries


def deny(reason):
    sys.stderr.write("monerex guard: " + reason + "\n")
    return 2


def ask(reason):
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": "monerex guard: " + reason,
            }
        },
        sys.stdout,
    )
    return 0


class Ask(str):
    """A reason the user is asked about. A plain reason is a refusal."""


def restricted(data, reason):
    """A subagent is denied; the main session is asked."""
    if data.get("agent_id"):
        return deny(reason + " A subagent may not do this; hand it back to the main session.")
    return ask(reason)


def confidential(text, root, secrets=False):
    """Rules the text breaks, without the text. Empty when there is no denylist.

    A denylist that cannot be read, or with a line that does not compile, is a
    broken protection, not a missing one, so it raises and the guard that called
    this denies. As in the git guards, a repository that says it keeps no
    denylist is not stopped by one it cannot read. With `secrets`, the text is
    also checked for credentials and hidden characters.
    """
    import monerex_scan

    entries, kind, problem = monerex_scan.load_denylist()
    keeps_none = git(root, "config", "--bool", "--get", "monerex.requireDenylist") == "false"
    if kind == "invalid" or (kind == "unreadable" and not keeps_none):
        raise ValueError(problem)
    scan = monerex_scan.Scan(entries)
    if secrets:
        # The marker that accepts a false positive on a committed line means nothing in a
        # request that is about to leave the machine: anyone can type it.
        scan.content("", text.replace(monerex_scan.ALLOW_MARKER, ""))
    else:
        scan.terms("", text)
    return sorted({rule for _, rule in scan.findings})


# ---------------------------------------------------------------- edits


def fold(text):
    """One spelling for names that a filesystem may treat as the same."""
    return unicodedata.normalize("NFC", text).lower()


def matches(relative, patterns):
    return any(fnmatch.fnmatchcase(fold(relative), fold(pattern)) for pattern in patterns)


def in_worktree(relative):
    """The rest of a path under `.claude/worktrees/<name>/`, or None."""
    parts = relative.split("/")
    if [fold(part) for part in parts[:2]] == [".claude", "worktrees"] and len(parts) > 3:
        return "/".join(parts[3:])
    return None


def classify(relative):
    """Why a repo-relative path is protected, or None."""
    inner = in_worktree(relative)
    if inner is not None:
        return classify(inner)
    parts = fold(relative).split("/")
    name = parts[-1]
    if matches("/".join(parts), AGENT_CONFIG) or name in INSTRUCTION_FILES:
        return "agent configuration"
    if matches(name, SECRET_NAMES) and not name.endswith(SECRET_EXAMPLES):
        return "a secrets file"
    if name in LOCKFILES:
        return "a lockfile"
    return None


def within(path, directory):
    """`path` as seen from `directory`, with `/` between the parts, or None when it is not under it.

    Folders are compared by what they are, not by how they are spelled: on a volume that
    ignores case or the form of an accented letter, `REPO/tests` and `repo/tests` are one
    place, and the path typed is not the path git reports.
    """
    rest, here = [], path
    while True:
        same = here == directory
        if not same:
            try:
                same = os.path.samefile(here, directory)
            except OSError:
                pass
        if same:
            return "/".join(reversed(rest))
        parent = os.path.dirname(here)
        if parent == here:
            return None
        rest.append(os.path.basename(here))
        here = parent


def inside(path, directory):
    return within(path, directory) is not None


def checkouts(root, real):
    """The checkouts of this repository a call can see: the one it came from, the owner's,
    and the one `real` is in when that belongs to the same repository."""
    owner = owner_root(root)
    places = [os.path.realpath(root), owner]
    folder = os.path.dirname(real)
    while not os.path.isdir(folder) and folder != os.path.dirname(folder):
        folder = os.path.dirname(folder)
    home = os.path.realpath(repo_root(folder))
    if owner_root(home) == owner:
        places.append(home)
    return list(dict.fromkeys(places))


def views(root, real):
    """The file as each checkout of this repository that holds it names it: (checkout, name).

    A file in another repository, in one nested inside this one, or in a plain folder gets
    no name from this repository's checkouts beyond the ones that really contain it.
    """
    found = []
    for one in checkouts(root, real):
        name = within(real, one)
        if name:
            found.append((one, name))
    return found


def task_protected(root, real, typed=None):
    """Where a task made this file read-only: (name, state file), or None.

    An entry guards the file of that name in the checkout whose state file holds it. An entry
    in the owner's checkout guards it in every checkout of the repository, which is the safe
    reading of a list that outlives the worktree it was written for. A path under
    `.claude/worktrees/<name>/` is also read as that worktree's own. `typed` is the path
    before links were followed: an entry may name a link, and the file behind it has
    another name.

    An entry without glob characters also guards the file it leads to from each checkout
    the call can see, by identity: a link to it, a second hard link and an entry spelled
    `./x` or as a full path all reach the same file.
    """
    owner = owner_root(root)
    for path in dict.fromkeys(filter(None, (real, typed))):
        for checkout, name in views(root, path):
            for candidate in filter(None, (name, in_worktree(name))):
                for holder in dict.fromkeys((checkout, owner)):
                    if matches(candidate, read_lines(holder, "protected-paths")):
                        return candidate, os.path.join(holder, ".monerex", "state", "protected-paths")
    for checkout in checkouts(root, real):
        for holder in dict.fromkeys((checkout, owner)):
            for entry in read_lines(holder, "protected-paths"):
                if set(entry) & set("*?["):
                    continue
                try:
                    same = os.path.samefile(real, os.path.join(checkout, entry))
                except OSError:
                    same = False
                if same:
                    return entry, os.path.join(holder, ".monerex", "state", "protected-paths")
    return None


def pre_edit(data, root):
    tool_input = data.get("tool_input") or {}
    target = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not target:
        return 0
    cwd = data.get("cwd") or os.getcwd()
    real = os.path.realpath(os.path.join(cwd, target))
    real_root = os.path.realpath(root)

    written = " ".join(str(tool_input.get(key, "")) for key in ("content", "new_string", "new_source"))
    for edit in tool_input.get("edits") or []:
        written += " " + str(edit.get("new_string", ""))
    broken = confidential(written, root)
    if broken:
        return deny("this edit would write a %s. Nothing was written." % broken[0])

    plugin = os.path.realpath(PLUGIN_ROOT)
    if any(inside(real, os.path.join(plugin, name)) for name in GUARD_DIRECTORIES):
        return restricted(data, "%s is part of the guards themselves." % os.path.relpath(real, plugin))

    typed = os.path.normpath(os.path.join(cwd, target))
    protected = task_protected(root, real, typed=typed)
    if protected:
        return deny("%s is read-only for this task (an entry in %s)." % protected)

    # The same file can be configuration in another checkout of this repository than the one
    # the call came from: its name there counts too.
    elsewhere = [(name, classify(name)) for _, name in views(root, real)]
    elsewhere = next(((name, why) for name, why in elsewhere if why), None)

    relative = within(real, real_root)
    if relative is None and data.get("agent_id"):
        return deny("that path resolves outside the repository.")

    # The name the file has and the name it was reached by: a link named like configuration
    # is configuration, whatever it points at.
    allowed_lockfile = False
    for name in dict.fromkeys(filter(lambda one: one is not None, (relative, within(typed, real_root)))):
        why = classify(name)
        if why == "a lockfile" and matches(name, read_lines(root, "allowed-paths")):
            allowed_lockfile = allowed_lockfile or name == relative
        elif why:
            return restricted(data, "%s is %s." % (name, why))
    if allowed_lockfile:
        return 0

    if relative is None:
        if elsewhere:
            return ask("%s is %s, in another checkout of this repository." % elsewhere)
        return 0
    if elsewhere:
        return restricted(data, "%s is %s, in a checkout inside this one." % elsewhere)
    note_task(root, relative, tool_input, data.get("session_id"))
    return 0


def note_task(root, relative, tool_input, session=None):
    """A plan or an intent file is where a task becomes real: make sure the log has its start.

    The stages log the start themselves, but a model sometimes skips that line. Writing the
    file cannot be skipped, so the log does not depend on anyone remembering.
    """
    match = re.fullmatch(r"docs/work/([a-z0-9][a-z0-9-]*)/(plan|intent)\.md", relative)
    if not match:
        return
    try:
        import task

        slug = match.group(1)
        if any(record.get("task") == slug and record.get("event") == "start" for record in task.read(root)):
            return  # this task was started before, whether or not it has finished: an edit to its plan is not a new task
        text = str(tool_input.get("content") or "")
        if not text:  # an edit carries no whole text; the tier is in the file as it stands
            try:
                with open(os.path.join(root, relative), encoding="utf-8") as handle:
                    text = handle.read()
            except OSError:
                pass
        tier = re.search(r"\*\*Tier:\*\*\s*(T[0-3])", text)
        fallback = "T2" if match.group(2) == "intent" else "T1"
        task.append(root, "start", slug=slug, tier=tier.group(1) if tier else fallback, noted_by="the guard", session=session)
    except Exception:
        pass  # the log never gets in the way of an edit


# ---------------------------------------------------------------- shell

SEPARATORS = set(";&|()")
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
# bash's long options, which it takes with one dash as well as two (`bash --help`, `man bash`).
SHELL_LONG_OPTIONS = {
    "debug", "debugger", "dump-po-strings", "dump-strings", "help", "init-file", "login", "noediting", "noprofile",
    "norc", "posix", "pretty-print", "protected", "rcfile", "restricted", "verbose", "version", "wordexp",
}
COMMIT_VALUES = (
    "mFCct",
    {"--message", "--file", "--author", "--date", "--template", "--fixup", "--squash", "--reuse-message", "--reedit-message", "--cleanup", "--pathspec-from-file", "--trailer"},
)
PUSH_VALUES = ("o", {"--push-option", "--repo", "--receive-pack", "--exec"})
# Stand-ins the lexer reads as ordinary letters: a file descriptor number, and each character
# that is an operator or a separator to the shell only when it is not quoted.
FD_MARK = ""
QUOTED = {char: chr(0xE001 + index) for index, char in enumerate("<>;&|()#")}
OPERATORS = set("<>;&|()")
# A line end between commands, kept apart from `;`, and one inside quotes, which is text.
LINE_END, QUOTED_LINE_END = "", ""
# Words that may stand before a command without being it.
BEFORE_A_COMMAND = {"time", "command", "builtin", "exec", "env", "sudo", "nohup", "nice", "then", "do", "else", "elif", "if", "while", "until", "!", "{"}
STAND_INS = dict({FD_MARK: "", QUOTED_LINE_END: "\n"}, **{mark: char for char, mark in QUOTED.items()})
WORD_BREAKS = set(" \t") | OPERATORS | {LINE_END}


def marked(text):
    """`text` as the lexer should see it: what the shell does with quotes, comments and line
    ends, done before the words are split.

    - A quoted or escaped operator or separator becomes its stand-in, and a line end inside
      quotes becomes one too: both are text.
    - A backslash at the end of a line joins it to the next, except inside single quotes.
    - A `#` that begins a word, outside quotes, starts a comment, which is left out up to
      the end of its line. Its text never reaches the lexer, so a quote inside a comment
      cannot swallow the commands after it. A backslash does not carry a comment on.
    - Any other line end becomes a word of its own, which ends the command.
    - The body of a here-document is data for its command, not commands: the lines after the
      one that holds `<<DELIM` or `<<-DELIM`, up to the first that is the delimiter, are left
      out. Not one: `<<<`, a `<<` in quotes or a comment, and one in `$((...))`, `$[...]`,
      `${...}` or a subscript (`a[1<<2]=5`). With an unquoted delimiter what a `$(...)` in
      the body holds runs, so that, and only that, is read as commands.
    """
    out, quote, index = [], None, 0
    word_begins = True  # the next character would be the first of a word
    heredocs = []  # (delimiter, leading tabs stripped) for each `<<` on this line, in order
    arithmetic = 0  # how deep inside `$((...))` or `((...))`
    brackets = 0  # how deep inside `$[...]` or a subscript: arithmetic to bash and zsh
    braces = 0  # how deep inside `${...}`
    while index < len(text):
        char = text[index]
        if quote is None and char == "\n":
            brackets = braces = 0  # neither goes on past a line end; when unsure, read the lines
        if quote is None and char == "(" and (arithmetic or text.startswith("((", index) and (word_begins or text[index - 1:index] == "$")):
            arithmetic += 1
        elif quote is None and char == ")" and arithmetic:
            arithmetic -= 1
        elif quote is None and char == "[" and (brackets or braces or text[index - 1:index] == "$" or not word_begins):
            brackets += 1
        elif quote is None and char == "]" and brackets:
            brackets -= 1
        elif quote is None and char == "{" and (braces or text[index - 1:index] == "$"):
            braces += 1
        elif quote is None and char == "}" and braces:
            braces -= 1
        if quote is None and not (arithmetic or brackets or braces) and text.startswith("<<", index):
            if text.startswith("<<<", index):
                out.append("<<<")
                word_begins = True
                index += 3
                continue
            delimiter = heredoc_delimiter(text, index + 2)
            if delimiter[0]:
                heredocs.append(delimiter)
        if char == "\n" and quote is None and heredocs:
            end = heredoc_end(text, index + 1, heredocs)
            out.append(" %s " % LINE_END)
            if any(not quoted for _, _, quoted in heredocs):
                for inner in substitutions(text[index + 1:end]):
                    out.append(marked(inner) + " %s " % LINE_END)
            heredocs = []
            word_begins = True
            index = end
            continue
        if char == "\\" and quote != "'" and index + 1 < len(text):
            following = text[index + 1]
            if following != "\n":  # a joined line leaves `word_begins` as it was
                out.append(char + QUOTED.get(following, following))
                word_begins = False  # an escaped character is part of a word, a space too
            index += 2
            continue
        if quote is None and char == "#" and word_begins:
            end = text.find("\n", index)
            index = len(text) if end < 0 else end
            continue
        if char == "\n":
            out.append(QUOTED_LINE_END if quote else " %s " % LINE_END)
            word_begins = quote is None
        elif quote is None and char in "'\"":
            quote = char
            out.append(char)
            word_begins = False
        elif char == quote:
            quote = None
            out.append(char)
            word_begins = False
        else:
            out.append(QUOTED.get(char, char) if quote else char)
            word_begins = quote is None and char in WORD_BREAKS
        index += 1
    return "".join(out)


def heredoc_delimiter(text, start):
    """(delimiter, leading tabs stripped, quoted) of the here-document whose `<<` ends at `start`.

    The delimiter is the word after `<<` or `<<-`, with quotes removed as the shell removes
    them: in double quotes a backslash escapes only `\\`, `$`, a backtick and `"`. Any quote
    or backslash in it makes the body plain text."""
    strip = text.startswith("-", start)
    index = start + 1 if strip else start
    while index < len(text) and text[index] in " \t":
        index += 1
    delimiter, quote, quoted = [], None, False
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote:
                quote = None
            elif quote == '"' and char == "\\" and text[index + 1:index + 2] in ("\\", "$", "`", '"'):
                index += 1
                delimiter.append(text[index])
            else:
                delimiter.append(char)
        elif char in "'\"":
            quote, quoted = char, True
        elif char == "\\" and index + 1 < len(text):
            index += 1
            quoted = True
            delimiter.append(text[index])
        elif char in " \t\n" or char in OPERATORS:
            break
        else:
            delimiter.append(char)
        index += 1
    return "".join(delimiter), strip, quoted


def substitutions(body):
    """What each outermost `$(...)` in `body` holds; `$((...))` is arithmetic, not one."""
    found, index = [], 0
    while True:
        index = body.find("$(", index)
        if index < 0:
            return found
        if body.startswith("$((", index):
            index += 3
            continue
        depth, end = 1, index + 2
        while end < len(body) and depth:
            depth += {"(": 1, ")": -1}.get(body[end], 0)
            end += 1
        found.append(body[index + 2:end - 1] if not depth else body[index + 2:])
        index = end


def heredoc_end(text, start, heredocs):
    """Where the text goes on after the bodies of `heredocs`, the first starting at `start`.

    Each body ends at the first line that is its delimiter; one that never closes runs to
    the end of the text, as it does in the shell."""
    index = start
    for delimiter, strip, _ in heredocs:
        while index < len(text):
            end = text.find("\n", index)
            end = len(text) if end < 0 else end
            line = text[index:end]
            index = end + 1
            if (line.lstrip("\t") if strip else line) == delimiter:
                break
    return min(index, len(text))


def split_words(command):
    """Shell words, with every command separator as its own word.

    The lexer loses spacing and quoting, so `marked` deals with quotes, comments and line
    ends first. Here the number of a file descriptor (`2` in `2>&1`, not in `2 > f`) is
    left out, a quoted or escaped operator or separator that stands alone (`'>'`, `';'`)
    stays a word that is neither, and a parenthesis glued to an operator (`)>`) is taken
    apart.
    """
    for mark in list(STAND_INS) + [LINE_END]:
        command = command.replace(mark, "")
    text = marked(command.replace("\r\n", "\n").replace("\r", "\n"))
    text = re.sub(r"(?<!\S)(\d+)(?=[<>])", FD_MARK + r"\1", text)
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        words = list(lexer)
    except ValueError:
        # A quote that never closes: take the words apart at spaces, line ends as separators.
        return unmarked(text.replace(LINE_END, ";")).split()
    out = []
    for word in words:
        if word == LINE_END:
            out.append(";")
        elif word.startswith(FD_MARK) and word[1:].isdigit():
            continue
        elif word and set(word) <= OPERATORS:
            out.extend(re.findall(r"[()]|[^()]+", word))
        else:
            plain = unmarked(word)
            out.append(word if plain and set(plain) <= OPERATORS else plain)
    return out


def segments(command, depth=0):
    """Simple commands as word lists, including those inside `sh -c` and `eval`.

    Where a command sends its output is not part of what it is: `gh pr 2>&1 merge 12` is
    `gh pr merge 12` to the shell, so the redirections are left out for every rule.

    They come in the order they are written: what `sh -c` or `eval` reads comes directly
    after the command that holds it, so a checkout inside one is seen before a push after it.
    """
    current, out = [], []
    for word in split_words(command) + [";"]:
        if word and set(word) <= SEPARATORS:
            current = without_redirections(current)
            if current:
                out.append(current)
            current = []
        else:
            current.append(word)
    if depth >= 3:
        return out
    ordered = []
    for words in out:
        read, replaced = [], False
        at = command_index(words)
        if at < len(words) and os.path.basename(words[at]) in ("echo", "printf") and not any(
            word.startswith("-") for word in words[:at]
        ):
            # What `echo` and `printf` are given is text, a shell or `eval` among it too. Not
            # after a wrapper's flag, whose value `command_index` may have taken for the command.
            ordered.append(words)
            continue
        for index, word in enumerate(words):
            name = os.path.basename(word)
            # What these run is read again as a command, by the shell and so here: a
            # character that was quoted on the outside is not quoted on the inside.
            if name in SHELLS:
                for script in shell_scripts(words[index + 1:]):
                    read.extend(segments(unmarked(script), depth + 1))
            elif name == "eval":
                inner = segments(unmarked(" ".join(words[index + 1:])), depth + 1)
                if index == at:
                    # `eval` is the command. Everything after it is read again, so the
                    # words as they stand outside say nothing: `'&&'` is an argument
                    # here and a separator there. Only the second reading is judged.
                    replaced = True
                    if words[:index]:
                        read.append(words[:index])
                    read.extend(inner)
                    break
                # A word `eval` further in may be an argument, such as a branch of that
                # name: the command stays as it is, and the reading as eval is added.
                read.extend(inner)
        if not replaced:
            ordered.append(words)
        ordered.extend(read)
    return ordered


def command_index(words):
    """Where the command is in a simple command's words: the first that is not a wrapper the
    guard knows (by its name, so `/usr/bin/env` is `env`), a flag or an assignment."""
    for index, word in enumerate(words):
        if not (os.path.basename(word) in BEFORE_A_COMMAND or word.startswith("-") or "=" in word):
            return index
    return len(words)


def invocations(command):
    """Every `git` and `gh` word in the command, as (the words from it on, whether it is the
    command word). Every one is judged, so a wrapper does not hide one; a checkout is
    recorded only where git is the command, not a word given to `echo`."""
    for words in segments(command):
        command_at = command_index(words)
        for index, word in enumerate(words):
            if os.path.basename(word) in ("git", "gh"):
                yield words[index:], index == command_at


def shell_scripts(rest):
    """The scripts a shell is given, out of the words after its name, in their order.

    A real shell takes the script as the first word after its options when one of them
    carries a `c`: `-lc`, `-c -x`, `-c --` and `-co pipefail` all run the word after.
    Options are words that start with `-` or `+`, `--` or `-` ends them, and a bundle with an `o`
    or `O`, `--rcfile` and `--init-file` take the next word as their value. A long option of
    bash's with one dash (`-noprofile`, `-login`, `-rcfile`) is that option, not a bundle. The word
    after a bare `-c` anywhere is read as well, as it was before.
    """
    found, index, script = [], 0, False
    while index < len(rest):
        word = rest[index]
        if word in ("--", "-"):
            index += 1
            break
        if not word.startswith(("-", "+")):
            break
        if word in ("--rcfile", "--init-file", "-rcfile", "-init-file"):
            index += 1
        elif word[:1] == "-" and word[1:] in SHELL_LONG_OPTIONS:
            pass  # bash takes its long options with one dash too: `-noprofile` is no bundle
        elif not word.startswith("--"):
            script = script or "c" in word[1:]
            if set(word[1:]) & set("oO"):
                index += 1
        index += 1
    if script and index < len(rest):
        found.append(index)
    found.extend(at + 1 for at, word in enumerate(rest[:-1]) if word == "-c")
    return [rest[at] for at in sorted(set(found))]


def unmarked(text):
    """`text` with the stand-ins of quoted characters put back as the characters."""
    for mark, char in STAND_INS.items():
        text = text.replace(mark, char)
    return text


def without_redirections(words):
    """A command's words without where its output goes.

    `2>&1` and `> file` are not arguments. Read as arguments of a push they become branches
    to push that do not exist. The words arrive from `split_words`: the number of a file
    descriptor is already gone (`2>&1` is `>&`, `1`), a spaced number is an argument, and a
    quoted `'>'` is not an operator. An operator word is dropped with the word after it.
    """
    out, skip = [], False
    for word in words:
        if skip:
            skip = False
        elif word and set(word) <= set("<>&|") and set(word) & set("<>"):
            skip = True
        else:
            out.append(word)
    return out


def parse_git(words):
    """(subcommand, arguments, config overrides, -C directory) for words[0] == git."""
    rest, overrides, directory = words[1:], [], None
    while rest and rest[0].startswith("-"):
        option = rest[0]
        if option == "-c" and len(rest) > 1:
            overrides.append(rest[1])
            rest = rest[2:]
        elif option == "-C" and len(rest) > 1:
            directory = rest[1]
            rest = rest[2:]
        elif option in ("--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env", "--attr-source") and len(rest) > 1:
            if option == "--config-env":
                overrides.append(rest[1])
            rest = rest[2:]
        else:
            if option.startswith(("-c", "--config-env=")):
                overrides.append(option.split("=", 1)[-1] if option.startswith("--") else option[2:])
            rest = rest[1:]
    return (rest[0] if rest else None), rest[1:], overrides, directory


def parse_options(args, value_short, value_long, attached_short=""):
    """(short flag letters, long option names, positional words).

    Words that are the value of an option are skipped, so a commit message that
    starts with a dash is not read as flags. `attached_short` are flags whose
    value, when present, is glued on: the `no` in `-uno` is not two more flags.
    """
    shorts, longs, positional = set(), [], []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            positional.extend(args[index + 1:])
            break
        if arg.startswith("--"):
            name = arg.split("=", 1)[0]
            longs.append(name)
            if "=" not in arg and name in value_long:
                index += 1
        elif arg.startswith("-") and len(arg) > 1:
            for position, letter in enumerate(arg[1:], start=1):
                shorts.add(letter)
                if letter in attached_short:
                    break
                if letter in value_short:
                    if position == len(arg) - 1:
                        index += 1
                    break
        else:
            positional.append(arg)
        index += 1
    return shorts, longs, positional


def has_long(longs, name, shortest):
    """True when an option is `name`, an accepted abbreviation of it, or extends it."""
    return any(option.startswith(name) or (len(option) >= shortest and name.startswith(option)) for option in longs)


def default_branches(root):
    head = git(root, "symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD")
    return {head.split("/", 1)[1]} if "/" in head else {"main", "master"}


def branch_name(ref, current):
    """The branches a ref names: every one HEAD may be on for `HEAD` and `@`."""
    if ref.startswith("refs/heads/"):
        ref = ref[len("refs/heads/"):]
    return set(current) if ref in ("HEAD", "@") else {ref}


def checked_out(sub, args):
    """(branch, made) for what a `git checkout` or `git switch` leaves checked out, or None.

    The name is the value of the flag that makes the branch (`-b`/`-B` for checkout,
    `-c`/`-C` for switch, `--orphan` for both), glued on or the next word; else, with
    `-t`, the one positional with `refs/`, then `remotes/`, then everything up to the
    first `/` taken off, as git names the branch; else that positional. `made` is false
    for a positional alone, which may be a file: the caller asks whether it is a branch.
    `-` and `@{-1}` are the name `-`, the branch before the last checkout. `--detach` and
    `-d` are (None, True): HEAD on no branch, with or without a commit.
    None where HEAD stays where it is: paths after `--`, two positionals (a path
    restore), `--patch`, `--ours`, `--theirs`, no positional. None too for a
    target that cannot be read from the text: any other `@...`, `HEAD`, a word with `$`.
    """
    making = "bB" if sub == "checkout" else "cC"
    name, track, positional = None, False, []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            if args[index + 1:]:
                return None
            break
        if arg.startswith("--"):
            option, glued, value = arg.partition("=")
            takes_name = has_long([option], "--orphan", 4) or (
                sub == "switch" and (has_long([option], "--create", 4) or has_long([option], "--force-create", 9))
            )
            if takes_name or has_long([option], "--conflict", 5):
                if not glued:
                    index += 1
                    value = args[index] if index < len(args) else ""
                if takes_name:
                    name = value
            elif has_long([option], "--detach", 4):
                return None, True
            elif any(has_long([option], flag, shortest) for flag, shortest in (("--patch", 6), ("--ours", 4), ("--theirs", 4))):
                return None
            elif has_long([option], "--track", 4):
                track = True
        elif arg.startswith("-") and len(arg) > 1:
            for position, letter in enumerate(arg[1:], start=1):
                if letter in making:
                    name = arg[position + 1:]
                    if not name:
                        index += 1
                        name = args[index] if index < len(args) else ""
                    break
                if letter == "d":
                    return None, True
                if letter == "p":
                    return None
                if letter == "t":
                    track = True
        else:
            positional.append(arg)
        index += 1
    made = name is not None or track
    if name is None:
        if len(positional) != 1:
            return None
        name = positional[0]
        if track:
            for prefix in ("refs/", "remotes/"):
                if name.startswith(prefix):
                    name = name[len(prefix):]
            name = name.split("/", 1)[1] if "/" in name else ""
    if name.startswith("refs/heads/"):
        name = name[len("refs/heads/"):]
    if name in ("-", "@{-1}") and not made:
        return "-", False
    if not name or name in ("-", "HEAD") or name.startswith("@") or "$" in name:
        return None
    return name, made


def branch_exists(root, name):
    """True when `name` is a local branch, one a remote has, which a checkout makes it from, or
    the default branch, which a fetch earlier in the line may bring in."""
    if name in default_branches(root) or git(root, "rev-parse", "--verify", "-q", "refs/heads/" + name):
        return True
    return name in git(root, "for-each-ref", "--format=%(refname:strip=3)", "refs/remotes").splitlines()


def push_plan(root, positional, left=None):
    """(target branch names, source commits, forced) for a push's refspecs.

    `left` is the branch a checkout earlier in the same command leaves. HEAD may be on it
    or still on the branch read now, so a push that follows HEAD targets both.
    """
    current = {git(root, "symbolic-ref", "--short", "-q", "HEAD")} | ({left} if left else set())
    refspecs = positional[1:]
    if not refspecs:
        return set(current), [git(root, "rev-parse", "HEAD")], False
    targets, commits, forced = set(), [], False
    for refspec in refspecs:
        if refspec.startswith("+"):
            forced = True
            refspec = refspec[1:]
        source, _, destination = refspec.partition(":")
        targets |= branch_name(destination or source, current)
        if source:
            commits.append(git(root, "rev-parse", "--verify", "-q", source + "^{commit}") or "unknown:" + source)
    return targets, commits, forced


def stale_base(root, positional, commits):
    """Why a push is built on an old default branch, going by what was last fetched.

    The checks passed on the pushed commit. If the default branch has moved since
    the branch left it, they did not run on what a merge would produce.
    """
    remote = positional[0] if positional else "origin"
    for default in sorted(default_branches(root)):
        tip = git(root, "rev-parse", "--verify", "-q", "refs/remotes/%s/%s" % (remote, default))
        if not tip:
            continue
        for commit in commits:
            missing = "" if commit.startswith("unknown:") else git(root, "rev-list", "--count", "%s..%s" % (commit, tip))
            if missing.isdigit() and int(missing) > 0:
                return (
                    "this branch does not contain the newest %s commit(s) of %s/%s. The checks ran on an "
                    "older base. Bring the branch up to date and run them again, or push it as it is."
                    % (missing, remote, default)
                )
    return None


def moved_before(root, config, heads):
    """Why a push or a PR must wait: the checks gate is on and an earlier command in the line
    moves a branch, so what is pushed is not the commit the gate would read now."""
    if config.get("checks") and root in heads.get(MOVED, ()):
        return (
            "an earlier command in this line moves a branch, so the checks have not run on what "
            "this pushes. Run the checks, then push in a command of its own."
        )
    return None


def checks_gate(root, config, commits=None):
    if not config.get("checks"):
        return None
    import check

    ok, message = check.status(root, commits)
    if ok:
        return None
    return "%s. Run the checks first: python3 %s/scripts/check.py" % (message, PLUGIN_ROOT)


# The setting with which the owner lets one push reach the default branch past the
# pre-push hook. The hook honours it only when it is given on the command line.
OWNER_OVERRIDE = "monerex.allowdefaultpush"
INCLUDE_REASON = "a config include may carry any setting, the ones that turn the guards off too; adding one is the owner's to do."
# Settings an agent may not give or write, matched in a key or anywhere in a value, since a
# value can carry one: an alias body runs `git -c <key>=...` of its own.
GUARD_SETTINGS = (
    (OWNER_OVERRIDE, "the owner's override of the default-branch rule is not for agents."),
    ("core.hookspath", "git's hooks may not be redirected."),
    ("include.path", INCLUDE_REASON),
    ("includeif.", INCLUDE_REASON),
)
# Settings that only restore git's default when they are removed.
SAFE_TO_UNSET = (OWNER_OVERRIDE, "core.hookspath")
CONFIG_READS = {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "--get-color", "--get-colorbool", "-l", "--list"}
CONFIG_WRITES = {"--add", "--replace-all", "--unset", "--unset-all", "--rename-section", "--remove-section", "-e", "--edit"}
CONFIG_VALUES = {"-f", "--file", "--blob", "--type", "--default", "--comment"}
# Commands that write, move or remove a file named on their command line.
FILE_WRITERS = {"rm", "mv", "cp", "chmod", "chown", "ln", "tee", "truncate", "unlink", "install", "touch", "dd", "rsync"}


def setting_refusal(key, value=""):
    """Why an agent may not set `key` (to `value`), or None."""
    key, value = key.lower(), value.lower()
    for name, reason in GUARD_SETTINGS:
        if name in key or name in value:
            return reason
    if key.startswith("monerex."):
        return "monerex's own settings are the owner's to change."
    return None


def config_refusal(args):
    """Why this `git config ...` may not run, or None: a write of a setting the guards rest on."""
    words, mode, skip = [], "write", False
    for arg in args:
        if skip:
            skip = False
        elif arg in CONFIG_VALUES:
            skip = True
        elif arg in CONFIG_READS:
            mode = "read"
        elif arg in ("--unset", "--unset-all"):
            mode = "unset"
        elif not arg.startswith("-"):
            words.append(arg)
    if words[:1] in (["get"], ["list"]):
        mode = "read"
    elif words[:1] in (["set"], ["unset"], ["edit"], ["rename-section"], ["remove-section"]):
        mode = {"unset": "unset", "rename-section": "section", "remove-section": "section"}.get(words[0], "write")
        words = words[1:]
    if any(arg in ("--rename-section", "--remove-section") for arg in args):
        mode = "section"
    if mode == "section":
        # The whole section goes, or moves: `monerex`, `core` with its hooks path, an include.
        section = words[0].lower() if words else ""
        if section == "monerex" or section.startswith("monerex."):
            return "monerex's own settings are the owner's to change."
        return None
    if not words or mode == "read" or (len(words) < 2 and mode == "write" and not set(args) & CONFIG_WRITES):
        return None
    if mode == "unset" and words[0].lower() in SAFE_TO_UNSET:
        return None
    return setting_refusal(words[0], " ".join(words[1:]))


def assignment_refusal(words):
    """Why the variables a simple command sets may not be set: git reads its settings from them."""
    at = command_index(words)
    candidates = list(words[:at])
    if at < len(words) and os.path.basename(words[at]) in ("export", "declare", "typeset", "local", "readonly"):
        candidates += words[at + 1:]
    for word in candidates:
        name, equals, value = word.partition("=")
        if not equals or not name.startswith("GIT_CONFIG"):
            continue
        if name in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM") and value.strip("'\"") != "/dev/null":
            return INCLUDE_REASON  # another file of settings; /dev/null, which holds none, is fine
        if name == "GIT_CONFIG_PARAMETERS" or re.match(r"GIT_CONFIG_(?:KEY|VALUE)_\d+$", name):
            reason = setting_refusal(value.strip("'\""), "")
            if reason:
                return reason
    return None


def redirect_targets(command, depth=0):
    """The files the redirections of `command` write to, those inside `sh -c` and `eval` too."""
    split = split_words(command)
    for index, word in enumerate(split[:-1]):
        if word and set(word) <= set("<>&|") and ">" in word:
            yield split[index + 1]
    if depth >= 3:
        return
    for words in segments(command, 3):
        for index, word in enumerate(words):
            name = os.path.basename(word)
            if name in SHELLS:
                for script in shell_scripts(words[index + 1:]):
                    yield from redirect_targets(unmarked(script), depth + 1)
            elif name == "eval":
                yield from redirect_targets(unmarked(" ".join(words[index + 1:])), depth + 1)


def written_paths(words):
    """The paths a file command writes, moves or removes: its destination for a copy or a link,
    every path it is given for the rest."""
    at = command_index(words)
    if at >= len(words) or os.path.basename(words[at]) not in FILE_WRITERS:
        return []
    name, rest = os.path.basename(words[at]), [word for word in words[at + 1:] if not word.startswith("-")]
    if name == "dd":
        return [word[3:] for word in words[at + 1:] if word.startswith("of=")]
    if name in ("cp", "ln", "install", "rsync"):
        return rest[-1:]
    return rest


def hook_file_refusal(command, root, cwd):
    """Why this command may not run: it writes, moves or removes one of this repository's git hooks."""
    hooks = git(root, "rev-parse", "--git-path", "hooks")
    if not hooks:
        return None
    hooks = os.path.realpath(os.path.join(root, hooks))
    paths = list(redirect_targets(command))
    for words in segments(command):
        paths += written_paths(words)
    for path in paths:
        path = os.path.expanduser(path.replace("${PWD}", cwd).replace("$PWD", cwd))
        if "$" in path and ".git/hooks" in path:
            return "git's hooks may not be changed or removed."  # a variable the guard cannot read
        path = os.path.realpath(os.path.join(cwd, path))
        if path == hooks or path.startswith(hooks + os.sep):
            return "git's hooks may not be changed or removed."
    return None


# Git subcommands that can move a branch or HEAD to another commit.
MOVING = {"commit", "merge", "pull", "rebase", "cherry-pick", "revert", "am", "update-ref"}
MOVED = "moved"  # the key in `heads` for the repositories a command earlier in the line moved
FETCHED = "fetched"  # and for those a fetch earlier in the line may have moved remote-tracking refs in
FETCH_VALUES = ("jo", {"--depth", "--deepen", "--shallow-since", "--shallow-exclude", "--refmap", "--negotiation-tip", "--upload-pack", "--server-option", "--jobs", "--filter"})


def positionals(args):
    """The words of a git command that are not options, up to `--`."""
    out = []
    for arg in args:
        if arg == "--":
            break
        if not arg.startswith("-"):
            out.append(arg)
    return out


def moves_a_branch(sub, args, root, heads):
    """Whether `git <sub> <args>` can leave a branch, or HEAD, on another commit.

    Judged with the repository as it is when the command is submitted; where that cannot
    settle it, the answer is yes.
    """
    if sub in ("merge", "rebase", "cherry-pick", "revert", "am") and any(arg in ("--abort", "--quit") for arg in args):
        return False  # back to where the operation started
    if sub in MOVING:
        return True
    commit = lambda name: git(root, "rev-parse", "--verify", "-q", name + "^{commit}")  # noqa: E731
    if sub == "reset":
        named = positionals(args)
        if len(named) != 1:
            return False  # no target, or paths
        target = commit(named[0])
        if target:
            if root in heads.get(FETCHED, ()):
                # A fetch earlier in the line may move a remote-tracking ref past what is read now.
                full = git(root, "rev-parse", "--symbolic-full-name", named[0])
                if full.startswith("refs/remotes/"):
                    return True
            return target != commit("HEAD")
        # Not a commit now: a file, or a ref the guard cannot read or a fetch brings in.
        return not os.path.exists(os.path.join(root, named[0]))
    if sub == "symbolic-ref":
        return "-d" in args or "--delete" in args or len(positionals(args)) >= 2
    if sub in ("checkout", "switch"):
        if any(arg in ("--ours", "--theirs", "-p", "--patch") for arg in args) or (
            "--" in args and args.index("--") + 1 < len(args)
        ):
            return False  # a path restore
        forcing = ("-B",) if sub == "checkout" else ("-C", "--force-create")
        making = ("-b", "-B", "--orphan") if sub == "checkout" else ("-c", "-C", "--create", "--force-create", "--orphan")
        made, start, skip, value = None, [], False, False
        for arg in args:
            if value:
                value = False
            elif skip:
                made, skip = (flag, arg), False
            elif arg in making:
                flag, skip = arg, True
            elif arg in ("--conflict", "--pathspec-from-file"):
                value = True
            elif sub == "checkout" and arg[:2] in making and len(arg) > 2:
                made = (arg[:2], arg[2:])
            elif arg == "--":
                break
            elif not arg.startswith("-"):
                start.append(arg)
        if made:
            # Where HEAD is, a new branch keeps the commit; a start point elsewhere, or one
            # forced over a branch that exists, does not.
            if made[0] == "--orphan" or (start and commit(start[0]) != commit("HEAD")):
                return True
            return made[0] in forcing and branch_exists(root, made[1])
        if any(arg in ("--detach", "-d", "-") for arg in args):
            return True  # HEAD on no branch, or back to the branch before
        if len(start) != 1:
            return False  # nothing named stays where it is; two names are a path restore
        name = start[0]
        if name == "-" or any(mark in name for mark in ("$", "@")) or name.startswith("HEAD"):
            return True
        if branch_exists(root, name):
            here = heads[root][0] if root in heads else git(root, "symbolic-ref", "--short", "-q", "HEAD")
            return name != here
        return bool(commit(name))  # a commit detaches HEAD; anything else is a file
    if sub == "branch":
        shorts = "".join(arg[1:] for arg in args if arg.startswith("-") and not arg.startswith("--"))
        return bool(set(shorts) & set("fMmC")) or any(arg in ("--force", "--move") for arg in args)
    if sub == "stash":
        return args[:1] == ["branch"]
    if sub == "fetch":
        _, _, named = parse_options(args, *FETCH_VALUES)
        # A refspec into a local branch, after the remote, which may be a URL.
        for refspec in named[1:]:
            destination = refspec.lstrip("+").partition(":")[2]
            if destination and not destination.startswith(("refs/remotes/", "refs/tags/")):
                return True
        return any(arg in ("-u", "--update-head-ok") for arg in args)
    return False


def git_rules(words, data, root, config, heads=None, is_command=True):
    """The reason this `git ...` command is refused, or None.

    `heads` maps a repository to the branch the last checkout or switch before this
    command in the same line leaves and the branch it was left from. A checkout here is
    recorded into it when git is the command (`is_command`), not a word given to another.
    Under `MOVED` it holds the repositories an earlier command in the line moved a branch in.
    """
    heads = {} if heads is None else heads
    sub, args, overrides, directory = parse_git(words)
    subagent = bool(data.get("agent_id"))
    for override in overrides:
        key, _, value = override.partition("=")
        reason = setting_refusal(key, value)
        if reason:
            return reason
    if sub == "config":
        reason = config_refusal(without_redirections(args))
        if reason:
            return reason
    if directory:
        root = repo_root(os.path.join(data.get("cwd") or root, directory))
    if is_command and moves_a_branch(sub, without_redirections(args), root, heads):
        heads.setdefault(MOVED, set()).add(root)
    if is_command and sub == "fetch":
        heads.setdefault(FETCHED, set()).add(root)

    if sub in ("checkout", "switch") and is_command:
        left = checked_out(sub, without_redirections(args))
        if left and left[0] == "-":
            # Back to the branch before the last checkout. With none in the line, unread.
            if root in heads:
                heads[root] = heads[root][::-1]
        elif left:
            # A branch; else, for checkout, a commit, which leaves HEAD on no branch (None);
            # else a file, which leaves HEAD where it was. `git switch <commit>` fails.
            name = left[0]
            if not (left[1] or branch_exists(root, name)):
                commit = sub == "checkout" and git(root, "rev-parse", "--verify", "-q", name + "^{commit}")
                name = None if commit else False
            if name is not False:
                here = heads[root][0] if root in heads else git(root, "symbolic-ref", "--short", "-q", "HEAD")
                heads[root] = (name, here)

    if sub == "commit":
        shorts, longs, _ = parse_options(args, *COMMIT_VALUES, attached_short="uS")
        if "n" in shorts or has_long(longs, "--no-verify", 6):
            return "commits may not skip git's hooks."
    if sub in ("merge", "pull", "am", "rebase", "cherry-pick", "revert") and any(
        len(arg) >= 8 and "--no-verify".startswith(arg) for arg in args
    ):
        return "a %s may not skip git's hooks." % sub

    if sub == "push":
        shorts, longs, positional = parse_options(without_redirections(args), *PUSH_VALUES)
        if subagent:
            return "only the main session pushes, inside ship."
        if has_long(longs, "--no-verify", 6):
            return "pushes may not skip git's hooks."
        left = heads.get(root, (None,))[0]
        targets, commits, forced = push_plan(root, positional, left)
        if forced or "f" in shorts or has_long(longs, "--force", 5):
            return "force-pushes are not allowed."
        if has_long(longs, "--mirror", 4) or has_long(longs, "--prune", 5):
            return "a push that deletes or overwrites remote branches is not allowed."
        if has_long(longs, "--all", 4) or has_long(longs, "--branches", 4):
            return "pushing every branch would push the default branch; name the branch to push."
        hit = targets & default_branches(root)
        if hit:
            reason = "pushing to the default branch is not allowed; push a branch and open a PR."
            if left and not push_plan(root, positional)[0] & hit:
                # Only the branch the earlier checkout leaves reaches the default branch.
                reason += " This command checks out `%s` before it pushes, so the push may run on it." % left
            return reason
        if left and root not in heads.get(MOVED, ()):
            # A branch made earlier in the line where HEAD was is not there yet to look up,
            # and holds HEAD's commit.
            commits = [git(root, "rev-parse", "HEAD") if commit == "unknown:" + left else commit for commit in commits]
        blocked = moved_before(root, config, heads) or checks_gate(root, config, commits)
        if blocked:
            return blocked
        behind = stale_base(root, positional, commits)
        return Ask(behind) if behind else None
    return None


# Commands that act on one repository and so must say which.
GH_NEEDS_REPO = {"pr", "issue", "run", "workflow", "release", "cache", "label", "secret", "variable", "ruleset"}
# API paths that list what an account belongs to, or reach across every repository it can see.
GH_WIDE_PATHS = ("user/orgs", "user/memberships", "user/repos", "user/teams", "notifications", "orgs/", "organizations")


def gh_command(words):
    """The subcommand of a `gh ...` call, skipping options and the values of the ones that take one."""
    skip = False
    for word in words[1:]:
        if skip:
            skip = False
        elif word in ("-R", "--repo", "--hostname"):
            skip = True
        elif not word.startswith("-"):
            return word
    return ""


def api_words(words):
    """Every word after `api`, with a host and a leading slash taken off, in lower case.

    The endpoint is whichever of them it is. Options and their values may come
    before it, so the rules below try every word, not the first one.
    """
    seen = False
    for word in words[1:]:
        if seen:
            yield re.sub(r"^https?://[^/]+/", "", word).lstrip("/").lower()
        elif word == "api":
            seen = True


def gh_scope(words, plain):
    """Why this `gh ...` command reaches further than one named repository, or None.

    A plain reason is a refusal. An Ask is a command that works on the repository
    it is run in, which is usually right but was not said. A query read from a
    file (`-F query=@file`) is not seen.
    """
    command = gh_command(words)
    named = any(
        word in ("-R", "--repo") or word.startswith("--repo=") or (word.startswith("-R") and len(word) > 2) or "github.com/" in word
        for word in words[1:]
    )
    if command in ("org", "status"):
        return "`gh %s` reports across everything the account belongs to. Name one repository instead." % command
    if command == "search" and not named and not any(word.startswith("--owner") for word in words):
        return "a search with no --owner or --repo reaches across every organisation. Scope it."
    if command == "api":
        candidates = list(api_words(words))
        line = " ".join(words).lower()
        if any(word.startswith(GH_WIDE_PATHS) for word in candidates):
            return "that API path lists memberships or activity across organisations. Ask for one repository."
        if any(word.startswith("search/") for word in candidates) and not any(mark in line for mark in ("repo:", "org:", "user:")):
            return "an API search with no repo:, org: or user: qualifier reaches across every organisation. Scope it."
        if "graphql" in candidates and "organizations" in line:
            return "that query lists the account's organisations. Ask for one repository."
    if command in GH_NEEDS_REPO and not named:
        return Ask("this `gh %s` command does not name its repository. Add --repo owner/name." % command)
    return None


def gh_rules(words, data, root, config, heads=None):
    """The reason this `gh ...` command is refused, or None."""
    # The words that are not options, nor the value of an option that takes one: with
    # `--repo o/r` between `pr` and `merge` the two are still next to each other.
    plain, skip = [], False
    for word in words[1:]:
        if skip:
            skip = False
        elif word in ("-R", "--repo", "--hostname"):
            skip = True
        elif not word.startswith("-"):
            plain.append(word)
    pairs = list(zip(plain, plain[1:]))
    if ("pr", "merge") in pairs:
        return "merging is the user's decision; monerex never merges."
    if "api" in plain and any(word.rstrip("/").endswith("/merge") for word in plain):
        return "merging is the user's decision; monerex never merges."
    if ("pr", "create") in pairs:
        if data.get("agent_id"):
            return "only the main session opens a PR, inside ship."
        blocked = moved_before(root, config, heads or {}) or checks_gate(root, config)
        if blocked:
            return blocked
    wide = gh_scope(words, plain)
    if isinstance(wide, Ask) and data.get("agent_id"):
        return str(wide) + " A subagent may not run it unscoped."
    return wide


def pre_bash(data, root, config):
    command = (data.get("tool_input") or {}).get("command") or ""
    broken = confidential(command, root)
    if broken:
        return deny("this command contains a %s. Nothing was run." % broken[0])
    for words in segments(command):
        reason = assignment_refusal(words)
        if reason:
            return deny(reason + " Nothing was run.")
    reason = hook_file_refusal(command, root, data.get("cwd") or root)
    if reason:
        return deny(reason + " Nothing was run.")
    question = None
    heads = {}  # repository root to (the branch a checkout earlier in the line leaves, the one before it)
    # Every `git` and `gh` word, not only the first, so a wrapper such as `env`, `time`,
    # `command` or a shell keyword does not hide one.
    for words, is_command in invocations(command):
        if os.path.basename(words[0]) == "git":
            reason = git_rules(words, data, root, config, heads, is_command)
        else:
            reason = gh_rules(words, data, root, config, heads)
        if isinstance(reason, Ask):
            question = question or reason
        elif reason:
            return deny(reason)
    remember(root, data)
    return ask(question) if question else 0


# ---------------------------------------------------------------- shell writes

ROOT_FILES = (".mcp.json", ".monerex/config.json", ".gitlab-ci.yml", ".monerex/state/allowed-paths", ".monerex/state/protected-paths")
ROOT_FOLDERS = (".claude", ".github/workflows", ".vscode")
SNAPSHOTS = "shell"  # a folder under .monerex/state, one file per shell call in flight
SNAPSHOT_MAX_AGE = 86400
WATCH_LIMIT = 2000


def fingerprint(path):
    """What a path looks like: where it points if it is a link, and the time and size of what it leads to."""
    link = None
    try:
        if os.path.islink(path):
            link = os.readlink(path)
        status = os.stat(path)
        return [link, status.st_mtime_ns, status.st_size]
    except OSError:
        return [link, None, None] if link is not None else None


def watched(root, protected):
    """Protected files a shell command could change, each with a cheap fingerprint.

    Looked for where they normally live: the repository root, the folders of agent
    configuration, the two task lists, the task's protected paths, and the guards
    themselves when the plugin lives in this repository. Links are followed, so a
    change to what a link leads to is seen. Git's own folder, compiled Python and
    the rest of monerex's state are left out: commands write there legitimately.
    Protected files deeper in the tree are not watched.
    """
    found = {}

    def add(relative):
        if len(found) < WATCH_LIMIT:
            mark = fingerprint(os.path.join(root, relative))
            if mark is not None:
                found[relative.replace(os.sep, "/")] = mark

    def walk(folder, skip=()):
        top = os.path.join(root, folder)
        if os.path.islink(top):
            add(folder)
        for directory, names, files in os.walk(top, followlinks=True):
            if len(found) >= WATCH_LIMIT:
                break
            names[:] = [name for name in names if name != "__pycache__" and os.path.join(directory, name) not in skip]
            for name in names:
                if os.path.islink(os.path.join(directory, name)):
                    add(os.path.relpath(os.path.join(directory, name), root))
            for name in files:
                if not name.endswith((".pyc", ".pyo")):
                    add(os.path.relpath(os.path.join(directory, name), root))

    for name in ROOT_FILES:
        add(name)
    try:
        for name in os.listdir(root):
            if classify(name) and not os.path.isdir(os.path.join(root, name)):
                add(name)
    except OSError:
        pass
    for folder in ROOT_FOLDERS:
        walk(folder, skip=(os.path.join(root, ".claude", "worktrees"),))
    for entry in protected:
        if any(mark in entry for mark in "*?["):  # a pattern, as the edit rule reads it: it may reach into folders
            hits = glob.glob(os.path.join(root, entry)) + glob.glob(os.path.join(root, entry, "**"), recursive=True)
            for hit in hits[:500]:
                if not os.path.isdir(hit) or os.path.islink(hit):
                    add(os.path.relpath(hit, root))
        else:
            add(entry)
    plugin = os.path.realpath(PLUGIN_ROOT)
    if inside(plugin, os.path.realpath(root)):
        for name in GUARD_DIRECTORIES:
            walk(os.path.relpath(os.path.join(plugin, name), os.path.realpath(root)))
    return found


def where(root):
    return [git(root, "rev-parse", "--verify", "-q", "HEAD"), git(root, "symbolic-ref", "-q", "HEAD")]


def as_committed(root, relative):
    """Whether a plain file now holds exactly what HEAD has for it.

    A fingerprint is a time and a size, so a file written back with the bytes it already had
    reads as changed: build's ablation gate does that, stamping the change it puts back with a
    fresh time so caches are rebuilt. Such a file was not changed. Asked only of the few paths
    whose fingerprint moved, with HEAD known and where it was.
    """
    full = os.path.join(root, relative)
    if os.path.islink(full) or not os.path.isfile(full):
        return False
    committed = git(root, "rev-parse", "--verify", "-q", "HEAD:" + relative)
    return bool(committed) and git(root, "hash-object", "--", relative) == committed


def snapshot_path(root, call):
    name = re.sub(r"[^A-Za-z0-9_-]", "", str(call or ""))[:80] or "unnamed"
    return os.path.join(root, ".monerex", "state", SNAPSHOTS, name + ".json")


def remember(root, data):
    """Before a shell command runs: what the protected files look like, and which lists apply.

    Each call gets its own snapshot, so two commands in flight do not erase each
    other's. The two task lists are read now and kept with it: a command cannot
    add a path to the allowed list and then change that path unseen.
    """
    try:
        path = snapshot_path(root, data.get("tool_use_id"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        for name in os.listdir(os.path.dirname(path)):  # calls that never came back
            old = os.path.join(os.path.dirname(path), name)
            if time.time() - os.path.getmtime(old) > SNAPSHOT_MAX_AGE:
                os.remove(old)
        protected, allowed = protected_entries(root), read_lines(root, "allowed-paths")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"at": where(root), "protected": protected, "allowed": allowed, "files": watched(root, protected)}, handle)
    except OSError:
        pass  # a snapshot that cannot be written only costs the warning afterwards


def shell_changes(data, root):
    """After a shell command: say so if a protected file changed while it ran.

    The command has already run, so this cannot refuse it. It turns a silent way
    around the edit rules into a visible one. A command that moved HEAD (a
    checkout, a pull, a commit) changes files legitimately and is not reported.
    Something else that writes one of these files in the same moment is reported
    too; the message says "while it ran", not "it did". When git cannot say where
    HEAD is, before or after, the change is reported rather than taken for a move.
    """
    path = snapshot_path(root, data.get("tool_use_id"))
    try:
        with open(path, encoding="utf-8") as handle:
            before = json.load(handle)
        os.remove(path)
    except (OSError, ValueError):
        return 0
    at, now_at = before.get("at") or [], where(root)
    if all(at) and all(now_at) and at != now_at:
        return 0  # HEAD moved: a checkout, a pull or a commit changes files legitimately
    now, was = watched(root, before.get("protected") or []), before.get("files") or {}
    allowed = before.get("allowed") or []
    changed = sorted(
        relative for relative in set(now) | set(was)
        if now.get(relative) != was.get(relative)
        # As in the edit rule, the allowed list opens lockfiles and nothing else.
        and not (classify(relative) == "a lockfile" and matches(relative, allowed))
    )
    if all(at) and all(now_at):
        changed = [relative for relative in changed if not as_committed(root, relative)]
    if not changed:
        return 0
    log(root, "guard.jsonl", {"event": "shell-changed-protected", "paths": changed, "session_id": data.get("session_id"), "by": data.get("agent_type") or "main session"})
    listed = ", ".join(changed[:5]) + (" and %d more" % (len(changed) - 5) if len(changed) > 5 else "")
    if data.get("agent_id"):
        advice = "A subagent may not change these. Put them back as they were and report this to the main session."
    else:
        advice = "Tell the user what changed and why before you go on."
    sys.stderr.write("monerex guard: protected files changed while this shell command ran: %s. The edit rules cover them. %s\n" % (listed, advice))
    return 2


# ---------------------------------------------------------------- web


def pre_web(data, root):
    """A search query or a fetched address leaves the machine as it is written."""
    tool_input = data.get("tool_input") or {}
    sent = "\n".join(str(tool_input.get(key) or "") for key in ("query", "url", "prompt"))
    broken = confidential(sent, root, secrets=True)
    if broken:
        return deny("this web request carries a %s. Nothing was sent." % broken[0])
    return 0


# ---------------------------------------------------------------- logs


def log(root, name, record):
    directory = os.path.join(root, ".monerex", "log")
    os.makedirs(directory, exist_ok=True)
    record["at"] = time.time()
    with open(os.path.join(directory, name), "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def agent_log(data, root):
    keys = ("hook_event_name", "session_id", "agent_id", "agent_type", "model", "effort", "agent_transcript_path", "transcript_path")
    record = {key: data.get(key) for key in keys}  # the transcript is pointed at, never copied
    record = {key: value for key, value in record.items() if value is not None}
    if isinstance(record.get("effort"), dict):  # arrives as {"level": "medium"}, on stop only
        record["effort"] = record["effort"].get("level")
    log(root, "routing.jsonl", record)
    return 0


COMMITTING = {"commit", "merge", "cherry-pick", "revert"}
FRESH_SECONDS = 120


def session_agents(root, session):
    """The agents this session has run so far, as "type/effort", in order."""
    found = []
    try:
        with open(os.path.join(root, ".monerex", "log", "routing.jsonl"), encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                if record.get("session_id") == session and record.get("hook_event_name") == "SubagentStop":
                    label = "%s/%s" % (record.get("agent_type"), record.get("effort") or "?")
                    if label not in found:
                        found.append(label)
    except (OSError, ValueError):
        pass
    return found


def last_logged(root):
    try:
        with open(os.path.join(root, ".monerex", "log", "commits.jsonl"), encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        return json.loads(lines[-1]).get("commit") if lines else None
    except (OSError, ValueError):
        return None


def commit_log(data, root):
    """One line per commit made through the shell tool: what changed, and who was behind it."""
    command = (data.get("tool_input") or {}).get("command") or ""
    where = None
    for words in segments(command):
        for index, word in enumerate(words):
            if os.path.basename(word) != "git":
                continue
            sub, _, _, directory = parse_git(words[index:])
            if sub in COMMITTING:
                where = repo_root(os.path.join(data.get("cwd") or root, directory)) if directory else root
    if not where or not os.path.exists(os.path.join(where, ".monerex", "config.json")):
        return 0  # no commit, or one in a repository that never opted in: write nothing there
    head = git(where, "rev-parse", "--verify", "-q", "HEAD")
    made = git(where, "show", "-s", "--format=%ct", "HEAD")
    if not head or head == last_logged(where) or not made.isdigit() or time.time() - int(made) > FRESH_SECONDS:
        return 0  # nothing new, or a commit this call did not make
    record = {
        "commit": head,
        "branch": git(where, "symbolic-ref", "--short", "-q", "HEAD"),
        "paths": git(where, "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", head).splitlines(),
        "session_id": data.get("session_id"),
        "by": data.get("agent_type") or "main session",
        "agents": session_agents(where, data.get("session_id")),
    }
    log(where, "commits.jsonl", record)
    return 0


ENGAGE = (
    "This repository uses monerex (it has a .monerex/config.json). For any request that adds, changes, fixes or "
    "refactors code, invoke the monerex:start skill first, before reading or editing files, also when the request "
    "comes in plain words and no command was typed. A question that changes nothing is answered directly. "
    "When the user typed another monerex command, follow that command as written instead."
)


def session_start(data, root, config):
    """Tell a new session that the loop applies here. A skill's description alone was not reliable."""
    if config.get("engage") == "typed":  # the repository wants the loop only when the command is typed
        return 0
    json.dump({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ENGAGE}}, sys.stdout)
    return 0


def config_change(data, root):
    log(root, "config-changes.jsonl", {key: data.get(key) for key in ("session_id", "source", "file_path", "agent_id")})
    return 0


def opted_in_root(data):
    """The guarded repository: where the call runs, else where the session started."""
    for start in (data.get("cwd"), os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd()):
        if start and os.path.isdir(start):
            root = repo_root(start)
            if os.path.exists(os.path.join(root, ".monerex", "config.json")):
                return root
    return None


def main(argv):
    event = argv[1] if len(argv) > 1 else ""
    guard = event in ("pre-edit", "pre-bash", "pre-web")
    try:
        data = json.load(sys.stdin)
        root = opted_in_root(data)
        if root is None:
            return 0
        config = load_config(root)
        if event == "pre-edit":
            return pre_edit(data, root)
        if event == "pre-bash":
            return pre_bash(data, root, config)
        if event == "pre-web":
            return pre_web(data, root)
        if event == "commit-log":
            return commit_log(data, root)
        if event == "post-bash":
            commit_log(data, root)
            return shell_changes(data, root)
        if event == "session-start":
            return session_start(data, root, config)
        if event == "agent-log":
            return agent_log(data, root)
        if event == "config-change":
            return config_change(data, root)
        return 0
    except Exception as error:  # a guard that cannot decide must not wave the call through
        if guard and "denylist" in str(error):
            return deny("%s. Until that is fixed nothing is let through." % error)
        if guard:
            return deny("the guard itself failed (%s), so the call was stopped." % type(error).__name__)
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
