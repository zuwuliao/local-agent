import os
import re
import subprocess
import anthropic

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = "claude-sonnet-4-6"

_base_dir = os.path.dirname(__file__)

with open(os.path.join(_base_dir, "system_prompt.md")) as f:
    SYSTEM_PROMPT = f.read().strip()

_skills_path = os.path.join(_base_dir, "skills.md")
if os.path.exists(_skills_path):
    with open(_skills_path) as f:
        SYSTEM_PROMPT += "\n\n" + f.read().strip()

# Commands that are always blocked — too destructive to allow
BLOCKED_PATTERNS = [
    r"rm\s+(-[a-zA-Z]*f[a-zA-Z]*|-[a-zA-Z]*r[a-zA-Z]*){1,}\s+[/~*]",  # rm -rf / ~ *
    r"rm\s+--no-preserve-root",
    r":\(\)\s*\{.*\|.*&",           # fork bomb
    r"mkfs",                         # format filesystem
    r"dd\s+.*of=/dev/(sd|hd|nvme|disk)",  # overwrite disk
    r">\s*/dev/(sd|hd|nvme|disk)",   # redirect to disk device
    r"(shred|wipefs|fdisk|parted)\s+/dev/",  # disk wipe tools
    r"chmod\s+-R\s+[0-7]*7+\s+/",   # chmod 777 /
    r"chown\s+-R\s+.*\s+/[^/]",     # chown -R on root paths
    r"mv\s+/\s+",                    # move root
    r"(curl|wget).*\|\s*(ba)?sh",    # pipe remote script to shell
    r"(poweroff|shutdown|halt|reboot|init\s+0)",  # system shutdown
    r">\s*/etc/(passwd|shadow|sudoers|hosts|fstab)",  # overwrite critical files
    r"sudo\s+rm",                    # sudo delete
]

# Commands that are risky but can be allowed with explicit confirmation
WARN_PATTERNS = [
    r"\brm\b",                       # any rm
    r"\bsudo\b",                     # sudo
    r"\bchmod\b",                    # permission changes
    r"\bchown\b",                    # ownership changes
    r"\bcrontab\b",                  # cron modifications
    r"\bkill\b|\bkillall\b",         # killing processes
    r"\bnpm\s+(install|uninstall)\b",  # package changes
    r"\bpip\s+(install|uninstall)\b",
    r"\bconda\s+(install|remove)\b",
    r"\bapt|brew\s+(install|remove|uninstall)\b",
]


def check_command(command: str) -> tuple[str, str | None]:
    """
    Returns ('blocked', reason) | ('warn', reason) | ('ok', None)
    """
    cmd_lower = command.lower()
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, cmd_lower):
            return "blocked", f"matches dangerous pattern: {pattern}"
    for pattern in WARN_PATTERNS:
        if re.search(pattern, cmd_lower):
            return "warn", f"potentially risky command (matches: {pattern})"
    return "ok", None


client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def chat(messages: list[dict]) -> str:
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    return response.content[0].text


def extract_command(reply: str) -> str | None:
    match = re.search(r"<cmd>(.*?)</cmd>", reply, re.DOTALL)
    return match.group(1).strip() if match else None


def run_command(command: str) -> str:
    try:
        result = subprocess.run(
            command,
            shell=True,
            text=True,
            capture_output=True,
            timeout=30,
        )
        output = result.stdout + result.stderr
        return output.strip() if output.strip() else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 30 seconds"
    except Exception as e:
        return f"Error: {e}"


def main():
    print(f"Agent running with {MODEL} via Anthropic. Type 'quit' to exit.\n")
    messages = []

    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in ("quit", "exit"):
            break
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})
        reply = chat(messages)
        messages.append({"role": "assistant", "content": reply})

        while True:
            command = extract_command(reply)
            if not command:
                print(f"Agent: {reply}\n")
                break

            status, reason = check_command(command)

            if status == "blocked":
                print(f"[BLOCKED] Agent wants to run: {command}")
                print(f"Reason: {reason}\n")
                denial_msg = f"Command was blocked by safety guardrails ({reason}). Do not attempt this command."
                messages.append({"role": "user", "content": denial_msg})
                reply = chat(messages)
                messages.append({"role": "assistant", "content": reply})
                continue

            if status == "warn":
                print(f"[WARNING] Agent wants to run: {command}")
                print(f"Caution: {reason}")
                permission = input("This command is potentially risky. Allow? [y/N] ").strip().lower()
            else:
                print(f"Agent wants to run: {command}")
                permission = input("Allow? [y/N] ").strip().lower()

            if permission != "y":
                print("Execution denied.\n")
                break

            output = run_command(command)
            messages.append({"role": "user", "content": f"Command output:\n{output}"})
            reply = chat(messages)
            messages.append({"role": "assistant", "content": reply})


if __name__ == "__main__":
    main()
