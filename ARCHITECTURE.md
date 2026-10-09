# Architecture

Two parts with one rule: `bin/machines` decides, `Machines.qml` displays.

## `bin/machines` (Python 3, standard library only)

- Reads `~/.config/machines/hosts` and the optional `~/.config/machines/config`
  (`$XDG_CONFIG_HOME` is honoured).
- Runs one read-only bash collector per machine in parallel: `bash -s` for this
  machine, `ssh -T -o BatchMode=yes -o ConnectTimeout=4 -o ForwardAgent=no
  [ssh_options] -- <target> bash -s` for the others, with a 45 second deadline.
  Optional checks receive their paths as shell-quoted variables ahead of the
  script; `~/` expands on the far side.
- The far side only reports `key=value` facts. Fields that identify the machine
  (`label`, `target`, `local`) and the computed `error` and `view` always come
  from this side, so a machine cannot redirect the widget's ssh click.
- `assess()` turns facts into display cells, issues with a severity, and a
  status (`ok`, `warn`, `bad`, `down`). The terminal table and `--json` share
  it.
- `--json --max-age N` / `--since EPOCH` serve `~/.cache/machines/last.json`
  under an exclusive `flock`, so the widget's copies on several monitors share
  one collection. The cache's mtime is when its collection started.

## `Machines.qml` (bar widget)

- One instance per monitor (`allowMultiple: false` per bar). Each runs the
  bundled script through a Quickshell `Process` with an argument array; the
  script path comes from `Qt.resolvedUrl`, so it follows wherever the plugin
  is installed.
- A timer refreshes every `refreshIntervalSec` (60 to 86400, default 600) with
  `--max-age`; refresh-now passes one shared `--since` timestamp to every
  instance so only the first collects.
- A start failure only flips `running`, so completion is handled on
  `onRunningChanged`; exit code, JSON parsing and shape are checked separately
  and the last stderr line becomes the visible error.
- All external text is rendered with `Text.PlainText`. The ssh click and the
  table action go through the bar's `run()` with `Util.shellQuote`.
- IPC target `io.github.frestina.machines`: `open`, `close`, `toggle`,
  `refresh`.

Nothing runs with elevated privileges, nothing is installed outside the plugin
folder, and removal leaves only `~/.config/machines` and `~/.cache/machines`.
Node.js is a development dependency for the repository checks only.
