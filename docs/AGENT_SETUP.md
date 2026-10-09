# Setting up Machines: a guide for coding agents

The user clicked "Set up with your agent" in the Machines bar widget. Help them
list their machines and choose the optional settings. Work with them step by
step: they decide what goes in, you do the looking up and the typing.

## Limits

You may have been started with approvals switched off. Hold yourself to these
regardless:

- Write only `~/.config/omarchy-machines/hosts` and
  `~/.config/omarchy-machines/config` (under `$XDG_CONFIG_HOME` if it is set).
  Both already exist; edit them in place and keep their comments.
- Read anything else you need, but change nothing else: not `~/.ssh/config`,
  keys, `known_hosts`, agents or any other machine. If something there needs
  fixing, explain what and why, and let the user do it or ask them first.
- Ask before connecting to any machine. Connect only to machines the user has
  agreed to list, and only with the read-only test below.
- Never paste file contents from `~/.ssh` beyond host names and addresses into
  your replies. Never read private keys.

## The files

`hosts`: one machine per line, `<label>  <ssh target>  [<hostname>]`.

- The label is the name shown in the widget.
- The target is whatever the user would type after `ssh`: a `Host` alias from
  `~/.ssh/config`, `user@address` or an address. Prefer an existing alias.
- The hostname is what `hostname` prints on that machine. With it, the line for
  the machine the widget runs on is checked locally, and the same file works
  when copied to each listed machine. Fill it in for every line.
- The file already lists this machine. Keep that line.

`config`: optional `key = value` settings, all commented out to begin with.
Comments in the file explain each one.

| Setting | Suggest it when |
| --- | --- |
| `ssh_options` | The user's ssh agent asks for approval on each use (Bitwarden, 1Password, KeePassXC). Polling would then show every machine as unreachable, so suggest `-o IdentityAgent=none` together with a key that works without the agent, or explain the trade-off. |
| `agent_socket` | They use an ssh agent socket that is not the default (look at `SSH_AUTH_SOCK` and `IdentityAgent` in `~/.ssh/config`) and want to see whether it is running and unlocked. |
| `forwarded_agent_socket` | They forward their agent to the other machines through a fixed socket path (an `~/.ssh/rc` that links `SSH_AUTH_SOCK` somewhere). Only when such a setup already exists. |
| `dotfiles` | They keep a dotfiles git repository (often `~/dotfiles` or `~/.dotfiles`) on several machines. |

## Steps

1. Read both files and `~/.ssh/config` (with any `Include`d files). Also look
   at what the user's network tools already know, when they are installed:
   `tailscale status` and `/etc/hosts`. Don't scan the network.
2. Show the candidates as a short list with the target you would use for each,
   and ask which to include and what to call them. Ask about machines you could
   not find.
3. For each chosen machine, ask once for permission, then test it exactly the
   way the widget will connect:

   ```bash
   ssh -T -o BatchMode=yes -o ConnectTimeout=4 -o ForwardAgent=no <target> hostname
   ```

   Add any `ssh_options` from the config. The output is the hostname for the
   third column. If it fails, explain the
   error. The usual causes:
   - `Host key verification failed`: the user has never connected. They run
     `ssh <target>` once themselves and accept the key.
   - `Permission denied`: no key the machine accepts is available without a
     prompt. The widget never prompts.
   - A timeout: the machine is off, asleep or not reachable from here.

   List a machine that fails anyway if the user wants it; it shows as
   unreachable until fixed.
4. Write `hosts`. Then go through the settings table and suggest only the
   settings that fit what you found, and write the ones the user accepts.
5. Run the plugin's `bin/machines` (the user's prompt gives its full path) to
   show the result, and explain any machine that is not OK. The widget checks
   again by itself when either file is saved.
6. Finish with what you changed, and that both files can be edited later from
   the widget's popup.
