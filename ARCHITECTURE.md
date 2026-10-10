# Architecture

Two parts with one rule: `bin/machines` decides, `Machines.qml` displays.

## `bin/machines` (Python 3, standard library only)

- Reads `~/.config/omarchy-machines/hosts` and `config` (`$XDG_CONFIG_HOME` is
  honoured). Every run first creates whichever is missing, with `open(…, "x")`
  so an existing file is never replaced: `hosts` from `examples/hosts` plus a
  line for this machine, `config` as `examples/config`. The folder has a name of
  its own because `~/.config/machines` could belong to anything.
- Runs one read-only bash collector per machine in parallel: `bash -s` for this
  machine, `ssh -T -o BatchMode=yes -o ConnectTimeout=4 -o ForwardAgent=no
  [ssh_options] -- <target> bash -s` for the others, with a 45 second deadline.
  Optional checks receive their paths as shell-quoted variables ahead of the
  script (`REPOS=(…)` for the `repo` lines, numbered `repo0_…` in its
  report); `~/` expands on the far side. A repo's HEAD comes back from the far
  side, so only a plain object id is passed to git here. Behind and ahead
  are measured against this machine's copy of the repo; when it has none, or
  doesn't know that commit, the far side's own count from its last fetch is
  used instead.
- The far side only reports `key=value` facts. Fields that identify the machine
  (`label`, `target`, `local`) and the computed `error` and `view` always come
  from this side, so a machine cannot redirect the widget's ssh click.
- `assess()` turns facts into display cells, issues with a severity, and a
  status (`ok`, `warn`, `bad`, `down`). Repository issues have the severity
  `info`: listed, but never raising the status. The terminal table and `--json` share
  it.
- `--json --max-age N` / `--since EPOCH` serve `~/.cache/omarchy-machines/last.json`
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
- The footer runs the script with `--edit hosts|config` (Omarchy's default
  editor) or `--setup-with-agent` (`omarchy agent prompt` pointing at
  `docs/AGENT_SETUP.md`, or Omarchy's agent picker when none is chosen). A
  `FileView` watches both files; a save waits 500 ms for the editor to finish,
  then refreshes with `--since` the save, so every monitor shares one check.
- All external text is rendered with `Text.PlainText`. The ssh click and the
  table action go through the bar's `run()` with `Util.shellQuote`.
- IPC target `io.github.frestina.machines`: `open`, `close`, `toggle`,
  `refresh`.

Nothing runs with elevated privileges, nothing is installed outside the plugin
folder, and removal leaves only `~/.config/omarchy-machines` and
`~/.cache/omarchy-machines`.
Node.js is a development dependency for the repository checks only.
