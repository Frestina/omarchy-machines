<h1 align="center">Machines</h1>

<p align="center">See at a glance which of your machines needs attention: load, memory, disk, pending updates, failed units and crashes, checked locally and over ssh.</p>

<p align="center"><a href="https://github.com/tcballard/omarchy-badges"><img alt="Built for Omarchy: Plugin" height="20" src="https://raw.githubusercontent.com/tcballard/omarchy-badges/75975e5b5bf75e7ede3764bcd2950046f7abfe2c/badges/v1/omarchy-plugin.svg"></a></p>

A bar icon that stays dim while everything is fine, shows a count when a
machine needs attention and turns urgent when one is in trouble or
unreachable. It comes with a `machines` command that prints the same check as
a table in the terminal.

- **Left-click:** a popup with one row per machine and the issues behind its
  status. Click a machine to open an ssh session to it.
- **Middle-click** (or <kbd>r</kbd> in the popup): check now.
- **Right-click:** the full table in a floating terminal.

## What it checks

| Column | Warns when |
| --- | --- |
| Uptime, load, memory | load is at or above the CPU count, memory is 90% used |
| Disk `/` | 80% full (90% is shown as a problem) |
| Updates | 50 or more pending, or the running kernel was upgraded and needs a reboot (pacman with `checkupdates`, `yay` for AUR, or apt) |
| Failed units | any failed systemd unit, system or user |
| Crashes | any core dump in the last 7 days (`coredumpctl`) |
| Agent, dotfiles | optional, see [settings](#optional-settings) |

A machine that cannot be reached within a few seconds shows as down with the
ssh error.

## Requirements

- Omarchy 4 with Python 3 (included in Omarchy).
- The machines you list: Linux with `bash`, reachable with `ssh <target>` using
  a key, without any password prompt. The check never prompts, so a machine
  that asks for a password shows as unreachable.

## Install

```bash
omarchy plugin add https://github.com/Frestina/omarchy-machines --enable
```

Then list your machines, starting from the example:

```bash
mkdir -p ~/.config/machines
cp ~/.config/omarchy/plugins/io.github.frestina.machines/examples/hosts ~/.config/machines/hosts
$EDITOR ~/.config/machines/hosts
```

Each line is `<label> <ssh target> [<hostname>]`. The target is whatever you
would type after `ssh`. The line whose hostname matches the machine you are on,
or whose target is `local`, is checked locally without ssh, so you can copy the
same file to every machine.

To use the `machines` command in a terminal:

```bash
ln -s ~/.config/omarchy/plugins/io.github.frestina.machines/bin/machines ~/.local/bin/machines
```

## Optional settings

Put these in `~/.config/machines/config`; see [examples/config](examples/config).

| Setting | Effect |
| --- | --- |
| `ssh_options` | Extra options for the polling ssh connections, for example `-o IdentityAgent=none` to keep a password manager's agent from asking for approval on every check. |
| `agent_socket` | Adds an AGENT column: whether this agent is running and unlocked on this machine. |
| `forwarded_agent_socket` | On the other machines: whether an ssh session has forwarded your agent there right now. |
| `dotfiles` | Adds a DOTFILES column comparing that git repository across machines: uncommitted and unpushed changes, and commits behind or ahead of its upstream. |

The refresh interval (10 minutes by default) is a widget setting in the bar
settings.

## Know where you are

The popup opens ssh sessions in a terminal with the window class
`org.omarchy.ssh`. Two small additions make those sessions easy to tell apart
from local ones.

Give them their own border, in `~/.config/hypr/hyprland.lua`:

```lua
o.window("^org\\.omarchy\\.ssh$", { border_color = "rgb(e5c07b) rgba(e5c07b88)" })
```

Show the machine's name in the prompt over ssh with starship, on each machine
you connect to. In its `~/.config/starship.toml`, add `$hostname` at the start
of `format`, then:

```toml
[hostname]
ssh_only = true
style = "bold yellow"
```

## What it runs and stores

- The widget runs the bundled `bin/machines` on start, every refresh interval
  and when you ask for a check.
- That runs a read-only shell script on each machine: locally with `bash`, on
  the others with `ssh -T -o BatchMode=yes -o ConnectTimeout=4 -o
  ForwardAgent=no`. It reads system state and changes nothing.
- The last result is cached in `~/.cache/machines/`.
- Your machine list and settings stay in `~/.config/machines/` on your
  machine; nothing is sent anywhere else.

## Remove

```bash
omarchy plugin remove io.github.frestina.machines
```

Your settings and cache are left in place. Delete them with
`rm -r ~/.config/machines ~/.cache/machines`, and `~/.local/bin/machines` if you
linked it.

## Development

Requires Node.js 22 and Python 3. Run the checks from the repository root:

```bash
./tests/run
```

[Develop and test](docs/DEVELOPMENT.md) · [Architecture](ARCHITECTURE.md) · [Release process](docs/RELEASE.md)

## Compatibility

Tested on Omarchy 4 with Hyprland 0.56. Details in
[acceptance evidence](docs/ACCEPTANCE.json).

## Credits

Built from [Build Omarchy Plugins](https://github.com/tcballard/build-omarchy-plugins) guidance and the Omarchy template set. [Sources and assets](CREDITS.md).

## Licence

[MIT](LICENSE).
