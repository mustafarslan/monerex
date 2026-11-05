"""gh_setup.py: install gh through a package manager, drive its login, and point git at it.

Every program it runs is a stand-in on a PATH of its own, so what is installed on the
machine that runs the tests does not count. The stand-ins use only the shell's builtins.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GH_SETUP = os.path.join(ROOT, "scripts", "gh_setup.py")
TOKEN = "gho_" + "Z" * 36

# A stand-in gh. `logged-in` in the state folder means signed in; every call is recorded.
FAKE_GH = """\
echo "$*" >> "$FAKE_STATE/gh.calls"
case "$*" in
  --version) echo "gh version 2.99.0 (2026-01-01)"; echo "https://github.com/cli/cli/releases/tag/v2.99.0" ;;
  "auth status"*)
    echo "  - Token: %(token)s"
    echo "  - Token: %(token)s" >&2
    test -f "$FAKE_STATE/logged-in" ;;
  "auth login"*)
    echo "token %(token)s" >&2
    echo "! First copy your one-time code: AB12-CD34" >&2
    echo "Press Enter to open github.com in your browser..." >&2
    if test -f "$FAKE_STATE/login-completes"; then /bin/sleep 1; : > "$FAKE_STATE/logged-in"; fi ;;
  "auth setup-git"*) echo "%(token)s"; ! test -f "$FAKE_STATE/setup-git-fails" ;;
esac
""" % {"token": TOKEN}


class GhSetupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="monerex-gh-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bin = os.path.join(self.tmp, "bin")
        self.state = os.path.join(self.tmp, "state")
        os.makedirs(self.bin)
        os.makedirs(self.state)
        self.env = {
            "PATH": self.bin,
            "HOME": self.tmp,
            "FAKE_STATE": self.state,
            "MONEREX_GH_POLL_SECONDS": "0.1",
            "MONEREX_GH_CODE_SECONDS": "10",
        }

    def program(self, name, body):
        path = os.path.join(self.bin, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\n" + body + "\n")
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)

    def calls(self, name):
        try:
            with open(os.path.join(self.state, name + ".calls"), encoding="utf-8") as handle:
                return handle.read().splitlines()
        except OSError:
            return []

    def run_setup(self, *args):
        done = subprocess.run([sys.executable, "-I", GH_SETUP, *args], cwd=self.tmp, env=self.env, capture_output=True, text=True, timeout=60)
        self.assertNotIn(TOKEN, done.stdout + done.stderr)
        self.assertNotIn("gho_", done.stdout + done.stderr)
        lines = done.stdout.strip().split("\n")
        self.assertEqual(len(lines), 1, done.stdout + done.stderr)
        return done, json.loads(lines[0])

    def test_with_no_gh_and_no_package_manager_it_says_where_to_get_it(self):
        _, result = self.run_setup()
        self.assertEqual((result["status"], result["gh"], result["installed_now"]), ("needs-install", False, False))
        self.assertIn("https://cli.github.com", result["reason"])

    def test_with_no_gh_brew_installs_it(self):
        # The brew stand-in puts the gh stand-in next to itself, as brew links into its bin.
        template = os.path.join(self.tmp, "gh.template")
        with open(template, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\n" + FAKE_GH)
        self.program("brew", 'echo "$*" >> "$FAKE_STATE/brew.calls"\n'
                     'while IFS= read -r line; do printf "%%s\\n" "$line"; done < "%s" > "%s/gh"\n'
                     '/bin/chmod +x "%s/gh"' % (template, self.bin, self.bin))
        _, result = self.run_setup()
        # Without --install it only says what it would run.
        self.assertEqual((result["status"], result["install"], self.calls("brew")), ("needs-install", "brew install gh", []))
        _, result = self.run_setup("--install")
        self.assertEqual(self.calls("brew"), ["install gh"])
        self.assertEqual((result["gh"], result["installed_now"], result["version"]), (True, True, "2.99.0"))
        self.assertEqual((result["auth"], result["status"]), ("logged-out", "logged-out"))

    def test_apt_get_is_used_only_when_sudo_needs_no_password(self):
        self.program("apt-get", 'echo "$*" >> "$FAKE_STATE/apt-get.calls"')
        self.program("sudo", 'echo "$*" >> "$FAKE_STATE/sudo.calls"\nexit 1')
        _, result = self.run_setup("--install")
        self.assertEqual(self.calls("sudo"), ["-n true"])
        self.assertEqual(self.calls("apt-get"), [])
        self.assertEqual(result["status"], "needs-install")
        self.program("sudo", 'echo "$*" >> "$FAKE_STATE/sudo.calls"\nexit 0')
        self.run_setup("--install")
        self.assertEqual(self.calls("sudo")[-1], "-n apt-get install -y gh")

    def test_logged_out_with_login_it_prints_the_one_time_code(self):
        self.program("gh", FAKE_GH)
        _, result = self.run_setup()
        self.assertEqual((result["status"], result["auth"]), ("logged-out", "logged-out"))
        self.assertNotIn("code", result)
        _, result = self.run_setup("--login")
        self.assertEqual((result["status"], result["code"], result["url"]), ("awaiting-browser", "AB12-CD34", "https://github.com/login/device"))
        login = [call for call in self.calls("gh") if call.startswith("auth login")]
        self.assertEqual(login, ["auth login --hostname github.com --git-protocol https --web"])
        self.assertFalse([call for call in self.calls("gh") if call.startswith("auth setup-git")])

    def test_when_the_browser_login_completes_wait_sets_up_git(self):
        self.program("gh", FAKE_GH)
        open(os.path.join(self.state, "login-completes"), "w").close()
        _, result = self.run_setup("--login")
        self.assertEqual(result["status"], "awaiting-browser")
        _, result = self.run_setup("--wait", "20")
        self.assertEqual((result["status"], result["auth"], result["git_credential"]), ("ready", "logged-in", "configured"))
        self.assertIn("auth setup-git --hostname github.com", self.calls("gh"))

    def test_wait_gives_up_after_its_time(self):
        self.program("gh", FAKE_GH)
        started = time.monotonic()
        _, result = self.run_setup("--wait", "1")
        self.assertLess(time.monotonic() - started, 15)
        self.assertEqual((result["status"], result["auth"]), ("login-timeout", "logged-out"))

    def test_logged_in_it_points_git_at_gh(self):
        self.program("gh", FAKE_GH)
        open(os.path.join(self.state, "logged-in"), "w").close()
        done, result = self.run_setup("--login")
        self.assertEqual(done.returncode, 0)
        self.assertEqual((result["status"], result["auth"], result["git_credential"], result["installed_now"]),
                         ("ready", "logged-in", "configured", False))
        self.assertIn("auth status --hostname github.com", self.calls("gh"))
        self.assertIn("auth setup-git --hostname github.com", self.calls("gh"))
        self.assertFalse([call for call in self.calls("gh") if call.startswith("auth login")])


    def test_a_failed_git_credential_setup_stops_ship(self):
        self.program("gh", FAKE_GH)
        open(os.path.join(self.state, "logged-in"), "w").close()
        open(os.path.join(self.state, "setup-git-fails"), "w").close()
        done, result = self.run_setup("--login")
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual((result["status"], result["git_credential"]), ("needs-credential", "failed"))

    def test_after_winget_gh_is_found_where_it_installs(self):
        # winget puts gh under Program Files, which an open shell's PATH does not have yet.
        program_files = os.path.join(self.tmp, "Program Files")
        self.env["ProgramFiles"] = program_files
        template = os.path.join(self.tmp, "gh.template")
        with open(template, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\n" + FAKE_GH)
        target = os.path.join(program_files, "GitHub CLI")
        self.program("winget", 'echo "$*" >> "$FAKE_STATE/winget.calls"\n'
                     '/bin/mkdir -p "%s"\n'
                     'while IFS= read -r line; do printf "%%s\\n" "$line"; done < "%s" > "%s/gh.exe"\n'
                     '/bin/chmod +x "%s/gh.exe"' % (target, template, target, target))
        _, result = self.run_setup("--install")
        self.assertEqual(self.calls("winget"), ["install --id GitHub.cli -e --silent"])
        self.assertEqual((result["gh"], result["installed_now"], result["version"]), (True, True, "2.99.0"))

    def test_the_launcher_runs_the_script(self):
        self.program("gh", FAKE_GH)
        open(os.path.join(self.state, "logged-in"), "w").close()
        self.env["PATH"] = os.pathsep.join([self.bin, os.path.dirname(sys.executable), "/usr/bin", "/bin"])
        done = subprocess.run([os.path.join(ROOT, "bin", "monerex-setup")], cwd=self.tmp, env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual((done.returncode, json.loads(done.stdout)["status"]), (0, "ready"), done.stderr)

    def test_a_token_in_a_reason_is_redacted(self):
        script = (
            "import sys; sys.path.insert(0, %r); import gh_setup\n"
            "gh_setup.ensure = lambda **_: {'status': 'login-failed', 'reason': 'gh said %s'}\n"
            "sys.exit(gh_setup.main([]))\n" % (os.path.dirname(GH_SETUP), TOKEN)
        )
        done = subprocess.run([sys.executable, "-I", "-c", script], cwd=self.tmp, env=self.env, capture_output=True, text=True)
        self.assertNotIn(TOKEN, done.stdout)
        self.assertEqual(json.loads(done.stdout)["reason"], "gh said [redacted]")
        self.assertEqual(done.returncode, 1)


if __name__ == "__main__":
    unittest.main()
