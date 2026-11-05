#!/usr/bin/env python3
"""Make sure `gh` is installed and signed in to github.com, and that git uses its credential.

Prints one JSON line: {status, gh, version, installed_now, auth, git_credential} and, when a
login was started or waited for, `login`. Ship runs it before it pushes. Standard library only.

  gh_setup.py              read whether gh is installed and signed in; when it is missing,
                           name the install command it would run
  gh_setup.py --install    install gh if it is missing (a command of its own, so it is seen)
  gh_setup.py --login      when signed out, start the browser login and print its one-time code
  gh_setup.py --wait N     wait at most N seconds (300 at most) for that login to finish

`bin/monerex-setup` runs this script, so a sandbox profile can leave it out by name.

gh is installed only through a package manager already on the machine: brew, winget, apt-get
(only when sudo needs no password) or conda. Nothing is downloaded and run. gh's own output is
never printed; only what this script parsed from it, and never a token.

Status: ready, needs-install, logged-out, awaiting-browser, login-failed, login-timeout,
needs-credential (signed in, but git was not pointed at gh's credential).
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HOST = "github.com"
DEVICE_URL = "https://github.com/login/device"
INSTALL_URL = "https://cli.github.com"
CODE = re.compile(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b")
VERSION = re.compile(r"gh version ([0-9][0-9A-Za-z.\-]*)")
# What a GitHub token looks like, removed from anything printed, should one ever reach it.
TOKEN = re.compile(r"\b(?:gh[opusr]_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{16,})")
WAIT_CAP = 300


def seconds(name, default):
    """A time from the environment (the tests shorten them), else the default."""
    try:
        return max(0.0, float(os.environ.get(name, default)))
    except ValueError:
        return float(default)


def gh_path():
    """gh on PATH, else where winget installs it, which an open shell's PATH may not have yet."""
    found = shutil.which("gh")
    if found:
        return found
    folder = os.environ.get("ProgramFiles")
    if folder:
        candidate = os.path.join(folder, "GitHub CLI", "gh.exe")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def run(argv, timeout=600):
    """Run a program found on PATH, quietly. Its return code, or None when it cannot run."""
    path = gh_path() if argv[0] == "gh" else shutil.which(argv[0])
    if not path:
        return None
    try:
        done = subprocess.run([path, *argv[1:]], stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.returncode


def installers():
    """The package-manager commands that could install gh here, in order."""
    found = []
    if shutil.which("brew"):
        found.append(["brew", "install", "gh"])
    if shutil.which("winget"):
        found.append(["winget", "install", "--id", "GitHub.cli", "-e", "--silent"])
    if shutil.which("apt-get") and shutil.which("sudo") and run(["sudo", "-n", "true"], timeout=30) == 0:
        found.append(["sudo", "-n", "apt-get", "install", "-y", "gh"])
    if shutil.which("conda"):
        found.append(["conda", "install", "-y", "-c", "conda-forge", "gh"])
    return found


def install(found=None):
    """(installed, reason). Tries each package manager present until gh can be found."""
    tried = []
    for argv in found if found is not None else installers():
        tried.append(" ".join(argv))
        run(argv)
        if gh_path():
            return True, "installed with: " + " ".join(argv)
    if not tried:
        return False, "gh is not installed and no package manager that has it (brew, winget, apt-get with sudo, conda) is usable here. Install it from %s." % INSTALL_URL
    return False, "gh is not installed, and this did not install it: %s. Install it from %s." % ("; ".join(tried), INSTALL_URL)


def version():
    path = gh_path()
    try:
        done = subprocess.run([path, "--version"], stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError, TypeError):
        return None
    match = VERSION.search(done.stdout.decode("utf-8", errors="replace"))
    return match.group(1) if match else None


def logged_in():
    return run(["gh", "auth", "status", "--hostname", HOST], timeout=60) == 0


def start_login():
    """Start the browser login detached and return its one-time code, or None.

    gh writes the code to stderr, here a file in a private folder. The file is removed once
    the code is read; gh keeps writing to it while it waits for the browser.
    """
    folder = tempfile.mkdtemp(prefix="monerex-gh-login-")
    path = os.path.join(folder, "stderr")
    detached = {"start_new_session": True} if os.name != "nt" else {"creationflags": 0x00000008}  # DETACHED_PROCESS
    try:
        with open(path, "wb") as sink:
            process = subprocess.Popen(
                [gh_path(), "auth", "login", "--hostname", HOST, "--git-protocol", "https", "--web"],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=sink, **detached,
            )
        try:
            process.stdin.write(b"\n")
            process.stdin.close()
        except OSError:
            pass
        deadline = time.monotonic() + seconds("MONEREX_GH_CODE_SECONDS", 60)
        while True:
            with open(path, "rb") as handle:
                match = CODE.search(handle.read().decode("utf-8", errors="replace"))
            if match:
                return match.group(1)
            if process.poll() is not None or time.monotonic() >= deadline:
                return None
            time.sleep(0.1)
    except OSError:
        return None
    finally:
        # On Windows a file gh still holds open cannot be removed; it is left in the temp folder.
        for remove, target in ((os.remove, path), (os.rmdir, folder)):
            try:
                remove(target)
            except OSError:
                pass


def wait_for_login(limit):
    deadline = time.monotonic() + min(max(limit, 0), WAIT_CAP)
    interval = seconds("MONEREX_GH_POLL_SECONDS", 3)
    while True:
        if logged_in():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def ensure(login=False, wait=None, install_now=False):
    result = {"status": "needs-install", "gh": False, "version": None, "installed_now": False, "auth": None, "git_credential": None}
    if not gh_path():
        found = installers()
        if found and not install_now:
            result["install"] = " ".join(found[0])
            result["reason"] = "gh is not installed. Run this script again with --install to run: %s" % result["install"]
            return result
        installed, reason = install(found)
        if not installed:
            result["reason"] = reason
            return result
        result["installed_now"] = True
    result["gh"] = True
    result["version"] = version()
    signed_in = logged_in()
    if not signed_in and wait is not None:
        signed_in = wait_for_login(wait)
        result["login"] = "done" if signed_in else "timed-out"
    if not signed_in and login and wait is None:
        code = start_login()
        result["auth"] = "logged-out"
        if code:
            result.update(status="awaiting-browser", login="started", code=code, url=DEVICE_URL)
        else:
            result.update(status="login-failed", login="failed", reason="gh auth login did not show a one-time code.")
        return result
    if not signed_in:
        result["auth"] = "logged-out"
        result["status"] = "login-timeout" if wait is not None else "logged-out"
        return result
    result["auth"] = "logged-in"
    ok = run(["gh", "auth", "setup-git", "--hostname", HOST], timeout=60) == 0
    result["git_credential"] = "configured" if ok else "failed"
    result["status"] = "ready" if ok else "needs-credential"
    if not ok:
        result["reason"] = "gh auth setup-git failed, so git has no credential from gh for %s." % HOST
    return result


def parse(argv):
    login, wait, install_now, index = False, None, False, 0
    while index < len(argv):
        word = argv[index]
        if word == "--login":
            login = True
        elif word == "--install":
            install_now = True
        elif word == "--wait" and index + 1 < len(argv):
            index += 1
            try:
                wait = float(argv[index])
            except ValueError:
                raise SystemExit("gh_setup.py: --wait takes a number of seconds")
        else:
            raise SystemExit("usage: gh_setup.py [--install] [--login] [--wait N]")
        index += 1
    return login, wait, install_now


def main(argv):
    login, wait, install_now = parse(argv)
    result = ensure(login=login, wait=wait, install_now=install_now)
    sys.stdout.write(TOKEN.sub("[redacted]", json.dumps(result)) + "\n")
    return 0 if result["status"] in ("ready", "awaiting-browser") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
