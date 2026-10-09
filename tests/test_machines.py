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
                         {"dotfiles": "~/dotfiles", "ssh_options": "-o IdentityAgent=none"})

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
                  "agent_socket": "~/local.sock", "dotfiles": "~/dots"}
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
        self.assertIn('DOTFILES="$HOME"/dots\n', script)

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

    def test_optional_columns_follow_config(self):
        self.assertEqual(machines.headers({}), machines.BASE_HEADERS)
        self.assertEqual(machines.headers({"agent_socket": "x", "dotfiles": "y"})[-2:], ["AGENT", "DOTFILES"])
        v = self.status({"agent_socket": "x"}, local=True, agent="0")
        self.assertEqual(v["cells"][-1], ("locked (0 keys)", "warn"))
        self.assertEqual(v["status"], "warn")


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

    def run_cli(self, *args, hosts=None):
        with tempfile.TemporaryDirectory() as tmp:
            if hosts is not None:
                os.makedirs(f"{tmp}/machines")
                Path(f"{tmp}/machines/hosts").write_text(hosts)
            env = {**os.environ, "XDG_CONFIG_HOME": tmp, "XDG_CACHE_HOME": f"{tmp}/cache"}
            return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                                  text=True, env=env, timeout=120)

    def test_missing_hosts_file_explains_itself(self):
        p = self.run_cli("--json", "--max-age", "60")
        self.assertEqual(p.returncode, 2)
        self.assertIn("no machines configured yet", p.stderr)

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
