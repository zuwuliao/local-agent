import os
import re
import subprocess
import threading

import anthropic
from flask import Flask, jsonify, request

# ── Config ────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = "claude-sonnet-4-6"

_base = os.path.dirname(__file__)

with open(os.path.join(_base, "system_prompt.md")) as f:
    SYSTEM_PROMPT = f.read().strip()

_skills_path = os.path.join(_base, "skills.md")
if os.path.exists(_skills_path):
    with open(_skills_path) as f:
        SYSTEM_PROMPT += "\n\n" + f.read().strip()

BLOCKED_PATTERNS = [
    r"rm\s+(-[a-zA-Z]*f[a-zA-Z]*|-[a-zA-Z]*r[a-zA-Z]*){1,}\s+[/~*]",
    r"rm\s+--no-preserve-root",
    r":\(\)\s*\{.*\|.*&",
    r"mkfs",
    r"dd\s+.*of=/dev/(sd|hd|nvme|disk)",
    r">\s*/dev/(sd|hd|nvme|disk)",
    r"(shred|wipefs|fdisk|parted)\s+/dev/",
    r"chmod\s+-R\s+[0-7]*7+\s+/",
    r"chown\s+-R\s+.*\s+/[^/]",
    r"mv\s+/\s+",
    r"(curl|wget).*\|\s*(ba)?sh",
    r"(poweroff|shutdown|halt|reboot|init\s+0)",
    r">\s*/etc/(passwd|shadow|sudoers|hosts|fstab)",
    r"sudo\s+rm",
]

WARN_PATTERNS = [
    r"\brm\b",
    r"\bsudo\b",
    r"\bchmod\b",
    r"\bchown\b",
    r"\bcrontab\b",
    r"\bkill\b|\bkillall\b",
    r"\bnpm\s+(install|uninstall)\b",
    r"\bpip\s+(install|uninstall)\b",
    r"\bconda\s+(install|remove)\b",
    r"\bapt|brew\s+(install|remove|uninstall)\b",
]


def check_command(cmd: str):
    low = cmd.lower()
    for p in BLOCKED_PATTERNS:
        if re.search(p, low):
            return "blocked", f"matches dangerous pattern: {p}"
    for p in WARN_PATTERNS:
        if re.search(p, low):
            return "warn", f"potentially risky command"
    return "ok", None


_PLACEHOLDER = re.compile(r"^the shell command here$", re.IGNORECASE)

def extract_command(text: str):
    m = re.search(r"<cmd>(.*?)</cmd>", text, re.DOTALL)
    if not m:
        return None
    cmd = m.group(1).strip()
    if _PLACEHOLDER.match(cmd):
        return None
    return cmd


def run_command(cmd: str) -> str:
    try:
        r = subprocess.run(cmd, shell=True, text=True, capture_output=True, timeout=30)
        out = r.stdout + r.stderr
        return out.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 30 seconds"
    except Exception as e:
        return f"Error: {e}"


client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def llm_chat(messages):
    resp = client.messages.create(
        model=MODEL, max_tokens=1024, system=SYSTEM_PROMPT, messages=messages
    )
    return resp.content[0].text


# ── App state (single-session local use) ──────────────────────────────────────
state = {"messages": [], "pending": None}
lock = threading.Lock()

# ── Flask ─────────────────────────────────────────────────────────────────────
app = Flask(__name__)


def _process_reply(reply: str):
    """Walk the reply; auto-handle blocked commands; pause on approve-needed."""
    while True:
        cmd = extract_command(reply)
        if not cmd:
            return jsonify({"type": "reply", "content": reply})

        status, reason = check_command(cmd)

        if status == "blocked":
            denial = f"Command was blocked by safety guardrails ({reason}). Do not attempt this command."
            state["messages"].append({"role": "user", "content": denial})
            reply = llm_chat(state["messages"])
            state["messages"].append({"role": "assistant", "content": reply})
            continue

        # needs user approval
        state["pending"] = {"command": cmd, "status": status, "reason": reason}
        return jsonify({"type": "command", "command": cmd, "status": status, "context": reply})


@app.route("/")
def index():
    return HTML, 200, {"Content-Type": "text/html"}


@app.route("/api/send", methods=["POST"])
def api_send():
    msg = (request.json or {}).get("message", "").strip()
    if not msg:
        return jsonify({"error": "empty message"}), 400
    with lock:
        state["messages"].append({"role": "user", "content": msg})
        reply = llm_chat(state["messages"])
        state["messages"].append({"role": "assistant", "content": reply})
        return _process_reply(reply)


@app.route("/api/approve", methods=["POST"])
def api_approve():
    with lock:
        if not state["pending"]:
            return jsonify({"error": "nothing pending"}), 400
        cmd = state["pending"]["command"]
        state["pending"] = None
        output = run_command(cmd)
        state["messages"].append({"role": "user", "content": f"Command output:\n{output}"})
        reply = llm_chat(state["messages"])
        state["messages"].append({"role": "assistant", "content": reply})
        return _process_reply(reply)


@app.route("/api/deny", methods=["POST"])
def api_deny():
    with lock:
        state["pending"] = None
        return jsonify({"type": "denied"})


@app.route("/api/reset", methods=["POST"])
def api_reset():
    with lock:
        state["messages"] = []
        state["pending"] = None
    return jsonify({"ok": True})


# ── Inline HTML UI ────────────────────────────────────────────────────────────
HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Local Agent</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'Segoe UI', system-ui, sans-serif;
    background: #0f1117;
    color: #e2e8f0;
    height: 100vh;
    display: flex;
    flex-direction: column;
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 20px;
    background: #161b27;
    border-bottom: 1px solid #2d3448;
    flex-shrink: 0;
  }

  header h1 { font-size: 1rem; font-weight: 600; letter-spacing: .04em; color: #7dd3fc; }

  #btn-reset {
    background: transparent;
    border: 1px solid #374151;
    color: #94a3b8;
    padding: 5px 14px;
    border-radius: 6px;
    cursor: pointer;
    font-size: .8rem;
    transition: border-color .15s, color .15s;
  }
  #btn-reset:hover { border-color: #7dd3fc; color: #7dd3fc; }

  #chat {
    flex: 1;
    overflow-y: auto;
    padding: 24px 20px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .bubble {
    max-width: 72%;
    padding: 11px 15px;
    border-radius: 12px;
    line-height: 1.6;
    font-size: .92rem;
    white-space: pre-wrap;
    word-break: break-word;
    flex-shrink: 0;
  }
  .bubble.user {
    align-self: flex-end;
    background: #1e40af;
    color: #dbeafe;
    border-bottom-right-radius: 4px;
  }
  .bubble.agent {
    align-self: flex-start;
    background: #1e2535;
    color: #e2e8f0;
    border-bottom-left-radius: 4px;
  }

  /* Command card */
  .cmd-card {
    align-self: flex-start;
    max-width: 72%;
    background: #1a1f2e;
    border: 1px solid #334155;
    border-radius: 12px;
    overflow: hidden;
    font-size: .9rem;
    flex-shrink: 0;
  }
  .cmd-card .cmd-header {
    padding: 8px 14px;
    font-size: .75rem;
    font-weight: 600;
    letter-spacing: .06em;
    text-transform: uppercase;
  }
  .cmd-card.warn .cmd-header  { background: #451a03; color: #fdba74; }
  .cmd-card.ok   .cmd-header  { background: #052e16; color: #86efac; }
  .cmd-card .cmd-body { padding: 12px 14px; }
  .cmd-card pre {
    background: #0f1117;
    border-radius: 6px;
    padding: 10px 12px;
    color: #f8fafc;
    font-family: 'Fira Code', 'Cascadia Code', monospace;
    font-size: .85rem;
    overflow-x: auto;
    margin-bottom: 12px;
  }
  .cmd-card .btn-row { display: flex; gap: 8px; }
  .cmd-card button {
    padding: 6px 18px;
    border-radius: 6px;
    border: none;
    cursor: pointer;
    font-size: .83rem;
    font-weight: 600;
    transition: opacity .15s;
  }
  .cmd-card button:hover { opacity: .85; }
  .btn-approve { background: #16a34a; color: #fff; }
  .btn-deny    { background: #374151; color: #d1d5db; }

  /* Output bubble */
  .bubble.output {
    align-self: flex-start;
    background: #0f1117;
    border: 1px solid #334155;
    font-family: 'Fira Code', monospace;
    font-size: .82rem;
    color: #94a3b8;
    border-radius: 8px;
    max-width: 80%;
  }

  /* Thinking indicator */
  .thinking {
    align-self: flex-start;
    display: flex;
    gap: 5px;
    padding: 14px;
  }
  .thinking span {
    width: 7px; height: 7px;
    background: #475569;
    border-radius: 50%;
    animation: bounce .9s infinite ease-in-out;
  }
  .thinking span:nth-child(2) { animation-delay: .15s; }
  .thinking span:nth-child(3) { animation-delay: .30s; }
  @keyframes bounce {
    0%,80%,100% { transform: translateY(0); }
    40%         { transform: translateY(-8px); }
  }

  /* Input row */
  #input-row {
    display: flex;
    gap: 10px;
    padding: 14px 20px;
    background: #161b27;
    border-top: 1px solid #2d3448;
    flex-shrink: 0;
  }

  #msg-input {
    flex: 1;
    background: #0f1117;
    border: 1px solid #334155;
    border-radius: 8px;
    color: #e2e8f0;
    font-size: .92rem;
    padding: 10px 14px;
    resize: none;
    outline: none;
    line-height: 1.5;
    max-height: 140px;
    overflow-y: auto;
    transition: border-color .15s;
  }
  #msg-input:focus { border-color: #3b82f6; }
  #msg-input::placeholder { color: #475569; }

  #btn-send {
    background: #2563eb;
    border: none;
    color: #fff;
    padding: 10px 20px;
    border-radius: 8px;
    cursor: pointer;
    font-size: .9rem;
    font-weight: 600;
    align-self: flex-end;
    transition: background .15s;
  }
  #btn-send:hover:not(:disabled) { background: #1d4ed8; }
  #btn-send:disabled { background: #1e3a5f; color: #475569; cursor: default; }
</style>
</head>
<body>

<header>
  <h1>&#x25B6; Local Agent</h1>
  <button id="btn-reset">New Chat</button>
</header>

<div id="chat"></div>

<div id="input-row">
  <textarea id="msg-input" rows="1" placeholder="Ask the agent anything…"></textarea>
  <button id="btn-send">Send</button>
</div>

<script>
const chat    = document.getElementById('chat');
const input   = document.getElementById('msg-input');
const btnSend = document.getElementById('btn-send');
const btnReset= document.getElementById('btn-reset');

let busy = false;

function setbusy(b) {
  busy = b;
  btnSend.disabled = b;
  input.disabled   = b;
}

function scrollBottom() {
  requestAnimationFrame(() => {
    chat.scrollTop = chat.scrollHeight;
  });
}

function addBubble(role, text) {
  const d = document.createElement('div');
  d.className = 'bubble ' + role;
  d.textContent = text;
  chat.appendChild(d);
  scrollBottom();
  return d;
}

function addThinking() {
  const d = document.createElement('div');
  d.className = 'thinking';
  d.innerHTML = '<span></span><span></span><span></span>';
  chat.appendChild(d);
  scrollBottom();
  return d;
}

function addCmdCard(data) {
  console.log('[addCmdCard] data:', JSON.stringify(data));

  const card = document.createElement('div');
  card.className = 'cmd-card ' + data.status;

  const label = data.status === 'warn' ? '⚠ Risky Command' : '⚡ Command Request';
  card.innerHTML = `
    <div class="cmd-header">${label}</div>
    <div class="cmd-body">
      <pre>${escHtml(data.command)}</pre>
      <div class="btn-row">
        <button class="btn-approve">Allow</button>
        <button class="btn-deny">Deny</button>
      </div>
    </div>`;

  chat.appendChild(card);
  console.log('[addCmdCard] card dimensions:', card.offsetWidth, 'x', card.offsetHeight);
  console.log('[addCmdCard] chat scrollHeight before scroll:', chat.scrollHeight, 'scrollTop:', chat.scrollTop, 'clientHeight:', chat.clientHeight);
  scrollBottom();
  requestAnimationFrame(() => {
    console.log('[addCmdCard] after rAF — card dimensions:', card.offsetWidth, 'x', card.offsetHeight);
    console.log('[addCmdCard] after rAF — chat scrollHeight:', chat.scrollHeight, 'scrollTop:', chat.scrollTop);
  });

  card.querySelector('.btn-approve').onclick = () => respond('/api/approve', card);
  card.querySelector('.btn-deny').onclick    = () => respondDeny(card);
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

async function respond(url, card) {
  card.querySelectorAll('button').forEach(b => b.disabled = true);
  const think = addThinking();
  try {
    const res = await fetch(url, { method: 'POST', headers: {'Content-Type':'application/json'} });
    const data = await res.json();
    think.remove();
    handleResponse(data);
  } catch(e) {
    think.remove();
    addBubble('agent', 'Error: ' + e.message);
    setbusy(false);
  }
}

async function respondDeny(card) {
  card.querySelectorAll('button').forEach(b => b.disabled = true);
  await fetch('/api/deny', { method: 'POST' });
  addBubble('agent', '(command denied)');
  setbusy(false);
}

function handleResponse(data) {
  if (data.type === 'reply') {
    addBubble('agent', data.content);
    setbusy(false);
  } else if (data.type === 'command') {
    addCmdCard(data);
    // stay busy until user approves/denies
  } else if (data.type === 'denied') {
    setbusy(false);
  }
}

async function sendMessage() {
  const text = input.value.trim();
  if (!text || busy) return;
  input.value = '';
  input.style.height = 'auto';

  addBubble('user', text);
  setbusy(true);
  const think = addThinking();

  try {
    const res = await fetch('/api/send', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ message: text })
    });
    const data = await res.json();
    think.remove();
    handleResponse(data);
  } catch(e) {
    think.remove();
    addBubble('agent', 'Error: ' + e.message);
    setbusy(false);
  }
}

btnSend.addEventListener('click', sendMessage);

input.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

// Auto-resize textarea
input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 140) + 'px';
});

btnReset.addEventListener('click', async () => {
  await fetch('/api/reset', { method: 'POST' });
  chat.innerHTML = '';
  setbusy(false);
});
</script>
</body>
</html>
"""

if __name__ == "__main__":
    import socket
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    print(f"Starting Local Agent UI")
    print(f"  Local:   http://localhost:8080")
    print(f"  Network: http://{local_ip}:8080")
    app.run(host="0.0.0.0", port=8080, debug=False)
