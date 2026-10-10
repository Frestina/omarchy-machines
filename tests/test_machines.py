"""Tests for bin/machines. Run with: python3 -m unittest discover -s tests"""

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin" / "machines"


def load():
    sys.dont_write_bytecode = True  # keep bin/ free of __pycache__
    loader = importlib.machinery.SourceFileLoader("machines", str(SCRIPT))
    spec = importlib.util.spec_from_loader("machines", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


machines = load()

HEALTHY = {
    "label": "desktop", "target": "desktop.lan", "hostname": "desktop", "local": False,
    "uptime_s": "90000", "load": "0.5", "cpus": "8", "mem_pct": "40",
    "disk_pct": "42", "disk_free": "137G", "reboot": "0", "updates": "0",
    "failed": "", "failed_user": "", "crashes": "[]",
}


class ConfigDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        patches = {
            "CONFIG_DIR": base,
            "HOSTS_FILE": base / "hosts",
            "CONFIG_FILE": base / "config",
            "CACHE_DIR": base / "cache",
        }
        for name, value in patches.items():
            p = mock.patch.object(machines, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.base = base

    def tearDown(self):
        self.tmp.cleanup()


class HostsAndConfig(ConfigDir):
    def test_hosts_with_and_without_hostname(self):
        (self.base / "hosts").write_text("# comment\nlaptop local\n\ndesktop me@desktop.lan desktop # trailing\n")
        self.assertEqual(machines.read_hosts(), [
            {"label": "laptop", "target": "local", "hostname": None},
            {"label": "desktop", "target": "me@desktop.lan", "hostname": "desktop"},
        ])

    def test_host_without_target_is_an_error(self):
        (self.base / "hosts").write_text("lonely\n")
        with self.assertRaises(ValueError):
            machines.read_hosts()

    def test_missing_config_is_empty(self):
        self.assertEqual(machines.read_config(), {})

    def test_config_keys(self):
        (self.base / "config").write_text("# optional\ndotfiles = ~/dotfiles\nssh_options = -o IdentityAgent=none\n")
        self.assertEqual(machines.read_config(),
                         {"repos": ["~/dotfiles"], "ssh_options": "-o IdentityAgent=none"})

    def test_repos_gather_in_order(self):
        (self.base / "config").write_text("repo = ~/dotfiles\nrepo = ~/Projects/app\ndotfiles = ~/dotfiles\n")
        self.assertEqual(machines.read_config(), {"repos": ["~/dotfiles", "~/Projects/app"]})

    def test_unknown_config_key_is_an_error(self):
        (self.base / "config").write_text("colour = red\n")
        with self.assertRaises(ValueError):
            machines.read_config()


class ShellPath(unittest.TestCase):
    def run_shell(self, word):
        return subprocess.run(["bash", "-c", f"HOME=/home/x; printf %s {word}"],
                              capture_output=True, text=True).stdout

    def test_tilde_expands_on_the_far_side(self):
        self.assertEqual(self.run_shell(machines.shell_path("~/my dots")), "/home/x/my dots")
        self.assertEqual(self.run_shell(machines.shell_path("~")), "/home/x")

    def test_shell_syntax_stays_literal(self):
        self.assertEqual(self.run_shell(machines.shell_path("/tmp/$(id)'x")), "/tmp/$(id)'x")


class Collect(unittest.TestCase):
    def fake_run(self, stdout, returncode=0, stderr=""):
        return mock.patch.object(machines.subprocess, "run", return_value=subprocess.CompletedProcess(
            [], returncode, stdout=stdout, stderr=stderr))

    def test_far_side_cannot_override_identity(self):
        host = {"label": "desktop", "target": "desktop.lan", "hostname": "desktop"}
        with self.fake_run("hostname=desktop\nlabel=evil\ntarget=-oProxyCommand=x\nlocal=True\nview=x\n"):
            m = machines.collect(host, {})
        self.assertEqual((m["label"], m["target"], m["local"]), ("desktop", "desktop.lan", False))
        self.assertNotIn("view", m)

    def test_ssh_command(self):
        host = {"label": "desktop", "target": "desktop.lan", "hostname": None}
        config = {"ssh_options": "-o IdentityAgent=none", "forwarded_agent_socket": "~/fwd.sock",
                  "agent_socket": "~/local.sock", "repos": ["~/dots", "/srv/my app"]}
        with self.fake_run("hostname=desktop\n") as run:
            machines.collect(host, config)
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[0], "ssh")
        self.assertIn("ForwardAgent=no", cmd)
        self.assertIn("BatchMode=yes", cmd)
        self.assertEqual(cmd[cmd.index("--") + 1:], ["desktop.lan", "bash", "-s"])
        self.assertIn("IdentityAgent=none", cmd[:cmd.index("--")])
        script = run.call_args.kwargs["input"]
        self.assertIn('AGENT_SOCK="$HOME"/fwd.sock\n', script)
        self.assertIn('REPOS=("$HOME"/dots \'/srv/my app\')\n', script)

    def test_local_machine_runs_without_ssh(self):
        host = {"label": "here", "target": "local", "hostname": None}
        with self.fake_run("hostname=here\n") as run:
            m = machines.collect(host, {"agent_socket": "~/local.sock"})
        self.assertEqual(run.call_args.args[0], ["bash", "-s"])
        self.assertIn('AGENT_SOCK="$HOME"/local.sock\n', run.call_args.kwargs["input"])
        self.assertTrue(m["local"])

    def test_unreachable_reports_last_ssh_error(self):
        host = {"label": "gone", "target": "gone.lan", "hostname": None}
        with self.fake_run("", 255, "Pseudo-terminal will not be allocated\nssh: connect: No route to host\n"):
            m = machines.collect(host, {})
        self.assertEqual(m["error"], "ssh: connect: No route to host")


class Assess(unittest.TestCase):
    def status(self, config=None, **changes):
        return machines.assess({**HEALTHY, **changes}, config or {})

    def test_healthy(self):
        v = self.status()
        self.assertEqual(v["status"], "ok")
        self.assertEqual(v["issues"], [])
        self.assertEqual(len(v["cells"]), len(machines.BASE_HEADERS))

    def test_full_disk_is_bad(self):
        v = self.status(disk_pct="93")
        self.assertEqual(v["status"], "bad")
        self.assertIn({"severity": "bad", "text": "disk /: 93% (137G free)"}, v["issues"])

    def test_reboot_and_crashes_warn(self):
        crash = json.dumps([{"exe": "/usr/bin/ghostty"}, {"exe": "/usr/bin/ghostty"}])
        v = self.status(reboot="1", crashes=crash)
        self.assertEqual(v["status"], "warn")
        texts = [i["text"] for i in v["issues"]]
        self.assertIn("running kernel was upgraded, reboot to load the new one", texts)
        self.assertIn("crashed in the last 7 days: ghostty ×2 (coredumpctl list)", texts)

    def test_failed_units_are_bad(self):
        v = self.status(failed="a.service ", failed_user="b.service ")
        self.assertEqual(v["status"], "bad")
        self.assertIn({"severity": "bad", "text": "failed units: a.service, b.service (user)"}, v["issues"])

    def test_unreachable_is_down(self):
        v = machines.assess({"label": "gone", "target": "gone", "hostname": None, "local": False,
                             "error": "timed out after 45s"}, {})
        self.assertEqual(v["status"], "down")
        self.assertEqual(v["issues"], [{"severity": "bad", "text": "timed out after 45s"}])

    def test_optional_columns_follow_config(self):
        self.assertEqual(machines.headers({}), machines.BASE_HEADERS)
        self.assertEqual(machines.headers({"agent_socket": "x", "repos": ["~/dotfiles"]})[-2:], ["AGENT", "DOTFILES"])
        v = self.status({"agent_socket": "x"}, local=True, agent="0")
        self.assertEqual(v["cells"][-1], ("locked (0 keys)", "warn"))
        self.assertEqual(v["status"], "warn")


class FirstRun(ConfigDir):
    def test_creates_both_files_with_this_machine(self):
        with mock.patch("socket.gethostname", return_value="box.example"):
            self.assertEqual(machines.ensure_files(), [self.base / "hosts", self.base / "config"])
            self.assertEqual(machines.read_hosts(), [{"label": "box", "target": "box.example", "hostname": "box.example"}])
            self.assertTrue(machines.is_local(machines.read_hosts()[0]))
        self.assertEqual(machines.read_config(), {})

    def test_never_replaces_existing_files(self):
        (self.base / "hosts").write_text("mine local\n")
        self.assertEqual(machines.ensure_files(), [self.base / "config"])
        self.assertEqual((self.base / "hosts").read_text(), "mine local\n")
        self.assertEqual(machines.ensure_files(), [])

    def test_examples_are_fictional_and_switched_off(self):
        (self.base / "hosts").write_text((machines.PLUGIN_DIR / "examples" / "hosts").read_text())
        self.assertEqual(machines.read_hosts(), [])


class Actions(unittest.TestCase):
    def test_editor_is_omarchys_inline_in_a_terminal(self):
        with mock.patch("shutil.which", return_value="/usr/bin/omarchy-launch-editor"):
            self.assertEqual(machines.editor_command("/f", inline=True), ["omarchy-launch-editor", "--inline", "/f"])
            self.assertEqual(machines.editor_command("/f", inline=False), ["omarchy-launch-editor", "/f"])

    def test_editor_falls_back_to_editor_variable(self):
        with mock.patch("shutil.which", return_value=None), \
                mock.patch.dict(os.environ, {"VISUAL": "", "EDITOR": "code -w"}):
            self.assertEqual(machines.editor_command("/f", inline=True), ["code", "-w", "/f"])

    def test_agent_gets_the_guide(self):
        chosen = subprocess.CompletedProcess([], 0, stdout="claude\n")
        with mock.patch("subprocess.run", return_value=chosen):
            cmd = machines.agent_command()
        self.assertEqual(cmd[0], "omarchy-agent-prompt")
        self.assertIn(str(machines.PLUGIN_DIR / "docs" / "AGENT_SETUP.md"), cmd[1])
        self.assertTrue((machines.PLUGIN_DIR / "docs" / "AGENT_SETUP.md").is_file())

    def test_no_default_agent_opens_the_picker(self):
        with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout="")):
            self.assertEqual(machines.agent_command(), ["omarchy-menu", "summon", "setup.default.agent"])


class Repos(unittest.TestCase):
    SHA = "a" * 40

    def test_columns_are_named_after_folders(self):
        config = {"repos": ["~/dotfiles", "~/work/app", "~/play/app/", "~/load"]}
        self.assertEqual([h for h, _ in machines.repo_columns(config)],
                         ["DOTFILES", "WORK/APP", "PLAY/APP", "~/LOAD"])

    def test_each_repo_has_its_own_cell(self):
        config = {"repos": ["~/dotfiles", "~/Projects/app"]}
        m = {**HEALTHY, "repo0_head": self.SHA, "repo0_dirty": "0", "repo0_unpushed": "0",
             "repo1_head": self.SHA, "repo1_dirty": "2", "repo1_unpushed": "1"}
        with mock.patch.object(machines, "repo_vs_upstream", return_value=""):
            v = machines.assess(m, config)
        self.assertEqual(v["cells"][-2:], [("aaaaaaa", "ok"), ("aaaaaaa 1 unpushed, 2 uncommitted", "info")])
        self.assertEqual(v["issues"], [{"severity": "info", "text": "app: aaaaaaa 1 unpushed, 2 uncommitted"}])
        # Listed, but not a reason for attention.
        self.assertEqual(v["status"], "ok")

    def test_missing_repo_is_dim(self):
        v = machines.assess({**HEALTHY, "repo1_head": self.SHA}, {"repos": ["~/a", "~/b"]})
        self.assertEqual(v["cells"][-2], ("-", "dim"))

    def test_far_side_sha_never_reaches_git_as_an_option(self):
        with mock.patch("subprocess.run") as run:
            self.assertIsNone(machines.repo_vs_upstream("--output=/tmp/x", "~/dotfiles"))
        run.assert_not_called()

    def test_repo_only_on_the_other_machine_counts_itself(self):
        m = {**HEALTHY, "repo0_head": self.SHA, "repo0_dirty": "0", "repo0_unpushed": "0", "repo0_behind": "4"}
        with mock.patch.object(machines, "repo_vs_upstream", return_value=None):
            self.assertEqual(machines.repo_cell(m, "repo0_", "~/Projects/app"), ("aaaaaaa 4 behind", "info"))
            self.assertEqual(machines.repo_cell({**m, "repo0_behind": "0"}, "repo0_", "~/Projects/app"), ("aaaaaaa", "ok"))
            self.assertEqual(machines.repo_cell({**m, "repo0_unpushed": "?", "repo0_behind": "?"}, "repo0_", "~/app"),
                             ("aaaaaaa no upstream branch", "info"))

    def test_this_machines_copy_wins_when_it_knows_the_commit(self):
        m = {**HEALTHY, "repo0_head": self.SHA, "repo0_dirty": "0", "repo0_unpushed": "0", "repo0_behind": "0"}
        with mock.patch.object(machines, "repo_vs_upstream", return_value="2 behind"):
            self.assertEqual(machines.repo_cell(m, "repo0_", "~/dotfiles"), ("aaaaaaa 2 behind", "info"))


class Cache(ConfigDir):
    def test_max_age_shares_one_collection(self):
        hosts = [{"label": "a", "target": "local", "hostname": None}]
        with mock.patch.object(machines, "collect_all", return_value=[{**HEALTHY}]) as collect, \
                mock.patch("sys.stdout"):
            machines.cached_json(hosts, {}, max_age=60)
            machines.cached_json(hosts, {}, max_age=60)
            self.assertEqual(collect.call_count, 1)
            machines.cached_json(hosts, {}, max_age=None, since=os.path.getmtime(self.base / "cache/last.json") + 1)
            self.assertEqual(collect.call_count, 2)


class EndToEnd(unittest.TestCase):
    """Runs the real collector on this machine through the CLI."""

    def run_cli(self, *args, hosts=None, files=None):
        with tempfile.TemporaryDirectory() as tmp:
            if hosts is not None:
                os.makedirs(f"{tmp}/omarchy-machines")
                Path(f"{tmp}/omarchy-machines/hosts").write_text(hosts)
            env = {**os.environ, "XDG_CONFIG_HOME": tmp, "XDG_CACHE_HOME": f"{tmp}/cache"}
            p = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                               text=True, env=env, timeout=120)
            if files is not None:
                files.update({f.name: f.read_text() for f in Path(f"{tmp}/omarchy-machines").iterdir()})
            return p

    def test_first_run_checks_this_machine(self):
        files = {}
        p = self.run_cli("--json", "--max-age", "60", files=files)
        self.assertEqual(p.returncode, 0, p.stderr)
        [m] = json.loads(p.stdout)
        self.assertTrue(m["local"])
        self.assertEqual(sorted(files), ["config", "hosts"])

    def test_empty_hosts_file_explains_itself(self):
        p = self.run_cli("--json", "--max-age", "60", hosts="# nothing yet\n")
        self.assertEqual(p.returncode, 2)
        self.assertIn("no machines listed", p.stderr)

    def test_edit_rejects_other_files(self):
        p = self.run_cli("--edit", "secrets", hosts="")
        self.assertEqual(p.returncode, 2)
        self.assertIn("hosts or config", p.stderr)

    def test_repo_on_this_machine(self):
        with tempfile.TemporaryDirectory() as repo:
            git = ["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@example.com"]
            subprocess.run(["git", "init", "-q", repo], check=True)
            subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "start"], check=True)
            Path(repo, "new").write_text("x")
            with tempfile.TemporaryDirectory() as tmp:
                os.makedirs(f"{tmp}/omarchy-machines")
                Path(f"{tmp}/omarchy-machines/hosts").write_text("here local\n")
                Path(f"{tmp}/omarchy-machines/config").write_text(f"repo = {repo}\n")
                env = {**os.environ, "XDG_CONFIG_HOME": tmp, "XDG_CACHE_HOME": f"{tmp}/cache"}
                p = subprocess.run([sys.executable, str(SCRIPT), "--json"], capture_output=True,
                                   text=True, env=env, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        [m] = json.loads(p.stdout)
        cell = m["view"]["columns"][Path(repo).name.upper()]
        self.assertEqual(cell["style"], "info")
        self.assertTrue(cell["text"].endswith("no upstream branch, 1 uncommitted"), cell["text"])

    def test_local_json(self):
        p = self.run_cli("--json", hosts="here local\n")
        self.assertEqual(p.returncode, 0, p.stderr)
        [m] = json.loads(p.stdout)
        self.assertTrue(m["local"])
        self.assertNotIn("error", m)
        self.assertIn(m["view"]["status"], {"ok", "warn", "bad"})
        self.assertEqual(list(m["view"]["columns"]), machines.BASE_HEADERS)


if __name__ == "__main__":
    unittest.main()
