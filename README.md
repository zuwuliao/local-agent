# Local Agent

A terminal-based AI agent powered by the Anthropic API (Claude). It can answer questions and execute shell commands on your machine with your permission.

## How it works

- You chat with the agent in your terminal
- When the agent determines a shell command is needed, it checks it against safety guardrails before asking for permission
- The agent runs commands one at a time, feeding each result back to continue reasoning
- Once the agent has enough information, it responds in plain text — no raw command output is shown

## Setup

**1. Install the dependency**

```bash
pip install anthropic
```

**2. Set your Anthropic API key**

```bash
export ANTHROPIC_API_KEY="your-key-here"
```

To make it permanent, add the line above to your `~/.zshrc` and run `source ~/.zshrc`.

Get your API key at [console.anthropic.com/keys](https://console.anthropic.com/keys).

## Usage

```bash
python local-agent.py
```

### Example session

```
Agent running with claude-sonnet-4-6 via Anthropic. Type 'quit' to exit.

You: what files are in the current directory?
Agent wants to run: ls
Allow? [y/N] y
Agent: The current directory contains two files: local-agent.py and README.md.

You: quit
```

## Configuration

To change the model, edit the `MODEL` variable in `local-agent.py`:

```python
MODEL = "claude-haiku-4-5-20251001"   # fast and cheap
MODEL = "claude-sonnet-4-6"           # more capable (default)
MODEL = "claude-opus-4-6"             # most capable
```

## Customization

The agent's behaviour is controlled by two markdown files — no Python editing needed:

### `system_prompt.md`
Defines the agent's core instructions and command format. Edit this to change how the agent reasons or responds.

### `skills.md`
Defines additional capabilities the agent can use. Each skill is a `## skill_name` section describing when and how to handle a specific type of request.

Example skill:

```markdown
## git_status
When the user asks about git changes, staged files, or repo status, run:
`git status` and `git log --oneline -5`
```

Skills are appended to the system prompt at startup. If `skills.md` is missing, the agent starts normally. The following skills are included by default:

| Skill | Trigger |
|---|---|
| `git_status` | Questions about git changes or repo state |
| `disk_usage` | Questions about disk space or storage |
| `process_monitor` | Questions about running processes or resource usage |
| `find_file` | Requests to locate a file by name |
| `environment` | Questions about environment variables or PATH |
| `web_browse` | Questions about an external URL or website content |

## Safety Guardrails

Every command is checked before execution against two tiers of rules:

**Blocked (always denied):**
- Recursive deletes on root/home (`rm -rf /`, `rm -rf ~`)
- Disk formatting (`mkfs`, `dd of=/dev/...`, `shred`, `wipefs`)
- Overwriting critical system files (`/etc/passwd`, `/etc/shadow`, etc.)
- Piping remote scripts to shell (`curl ... | sh`)
- System shutdown/reboot commands
- `sudo rm`
- Fork bombs

**Warned (extra confirmation required):**
- Any `rm`, `sudo`, `chmod`, `chown`
- Process killing (`kill`, `killall`)
- Package installs/uninstalls (`pip`, `npm`, `brew`, `conda`)
- Crontab modifications

When a command is blocked, the agent is notified and will try a safer alternative. All commands time out after 30 seconds. Never share your API key publicly.
