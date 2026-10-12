#!/usr/bin/env python3
"""
Jarvis Dynamic Intent & Task Status Parser
Features:
- Primary: Groq Cloud API (llama-3.3-70b-versatile / qwen) | Fallback: Local Ollama.
- Outputs dynamic status announcements:
  - speaking_start: "Executing task: <short natural description>"
  - speaking_success: "Task completed successfully, sir."
  - speaking_error: "Task failed, sir."
- Saves speaking_start to `last_status.txt` and cached intent to `last_intent.json`.
- Enforces explicit project root working directory on all CLI commands.
- Pure parsing module: leaves speech triggering exclusively to workflow nodes (no double-speech).
"""

import sys
import os
import json
import re
import requests
from dotenv import load_dotenv

# Load configuration
load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__)).replace("/", "\\")
TRANSCRIPT_CACHE_FILE = os.path.join(PROJECT_ROOT, "last_transcript.txt")
INTENT_CACHE_FILE = os.path.join(PROJECT_ROOT, "last_intent.json")
STATUS_CACHE_FILE = os.path.join(PROJECT_ROOT, "last_status.txt")

SYSTEM_PROMPT = f"""You are the Jarvis Git Automation Engine.
Your job is to translate voice transcripts into deterministic, executable Git/GitHub CLI commands
along with concise spoken status phrases.

You must respond with ONLY a valid, raw JSON object matching the exact schema below.
DO NOT include markdown backticks (```json), explanations, markdown formatting, or preamble.

Strict Output Schema:
{{
  "action": "stage_commit_push" | "create_pr" | "checkout_branch" | "status" | "unknown",
  "command": "<chained_shell_command_with_cd_root>",
  "speaking_start": "Executing task: <short natural description of task>",
  "speaking_success": "Task completed successfully, sir.",
  "speaking_error": "Task failed, sir."
}}

IMPORTANT WORKING DIRECTORY RULE:
All CLI commands MUST explicitly prepend: cd "{PROJECT_ROOT}" && ...

Examples:
1. "push my changes with message fix audio bug" ->
{{
  "action": "stage_commit_push",
  "command": "cd \\"{PROJECT_ROOT}\\" && git init && git add . && (git commit -m \\"fix audio bug\\" || echo \\"No changes to commit\\") && (git push || gh repo create \\"Jarvis-Voice-Assistant\\" --public --source=. --remote=origin --push)",
  "speaking_start": "Executing task: committing and pushing your changes, sir.",
  "speaking_success": "Task completed successfully, sir.",
  "speaking_error": "Task failed, sir."
}}

2. "check git status" ->
{{
  "action": "status",
  "command": "cd \\"{PROJECT_ROOT}\\" && git status",
  "speaking_start": "Executing task: checking git status, sir.",
  "speaking_success": "Task completed successfully, sir.",
  "speaking_error": "Task failed, sir."
}}

3. "switch to branch dev" ->
{{
  "action": "checkout_branch",
  "command": "cd \\"{PROJECT_ROOT}\\" && git checkout dev",
  "speaking_start": "Executing task: switching to branch dev, sir.",
  "speaking_success": "Task completed successfully, sir.",
  "speaking_error": "Task failed, sir."
}}
"""

def build_default_intent(transcript: str) -> dict:
    cd_prefix = f'cd "{PROJECT_ROOT}"'
    t = transcript.lower()

    if any(w in t for w in ["push", "commit", "repo", "github"]):
        return {
            "action": "stage_commit_push",
            "command": (
                f'{cd_prefix} && git init && git add . && '
                f'(git commit -m "Automated update via Jarvis" || echo "No changes to commit") && '
                f'(git push || gh repo create "Jarvis-Voice-Assistant" --public --source=. --remote=origin --push)'
            ),
            "speaking_start": "Executing task: committing and pushing changes, sir.",
            "speaking_success": "Task completed successfully, sir.",
            "speaking_error": "Task failed, sir.",
        }
    elif "branch" in t or "checkout" in t:
        match = re.search(r"(?:branch|checkout|switch to)\s+([a-zA-Z0-9_\-\./]+)", t)
        branch = match.group(1) if match else "main"
        return {
            "action": "checkout_branch",
            "command": f'{cd_prefix} && git checkout {branch}',
            "speaking_start": f"Executing task: switching to branch {branch}, sir.",
            "speaking_success": "Task completed successfully, sir.",
            "speaking_error": "Task failed, sir.",
        }
    else:
        return {
            "action": "status",
            "command": f'{cd_prefix} && git status',
            "speaking_start": "Executing task: checking git status, sir.",
            "speaking_success": "Task completed successfully, sir.",
            "speaking_error": "Task failed, sir.",
        }

def sanitize_json(raw_text: str, transcript: str) -> dict:
    clean = raw_text.strip()
    clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.MULTILINE)
    clean = re.sub(r"\s*```$", "", clean, flags=re.MULTILINE)
    clean = clean.replace("```json", "").replace("```", "").strip()

    start = clean.find("{")
    end = clean.rfind("}")
    if start != -1 and end != -1 and end > start:
        clean = clean[start : end + 1].strip()

    try:
        data = json.loads(clean)
    except Exception:
        return build_default_intent(transcript)

    cd_prefix = f'cd "{PROJECT_ROOT}"'
    cmd = str(data.get("command", "")).strip()
    if not cmd.startswith("cd "):
        cmd = f'{cd_prefix} && {cmd}' if cmd else f'{cd_prefix} && git status'

    return {
        "action": str(data.get("action", "unknown")),
        "command": cmd,
        "speaking_start": str(data.get("speaking_start", "Executing task, sir.")),
        "speaking_success": "Task completed successfully, sir.",
        "speaking_error": "Task failed, sir.",
    }

def call_groq(transcript: str) -> dict:
    if not GROQ_API_KEY or GROQ_API_KEY.startswith("your_"):
        raise ValueError("GROQ_API_KEY not configured.")

    models = [
        "llama-3.3-70b-versatile",
        "qwen/qwen3.8-27b",
        "qwen-2.5-32b",
        "openai/gpt-oss-120b",
    ]

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    last_err = None
    for m in models:
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json={
                    "model": m,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": f"Voice Transcript: {transcript}"},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 256,
                },
                timeout=8,
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                return sanitize_json(content, transcript)
            elif resp.status_code == 404:
                continue
            else:
                last_err = f"HTTP {resp.status_code}"
        except Exception as e:
            last_err = str(e)
            break

    raise RuntimeError(f"Groq API error: {last_err}")

def call_ollama(transcript: str) -> dict:
    resp = requests.post(
        f"{OLLAMA_HOST}/api/chat",
        json={
            "model": "qwen2.5-coder:7b",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Voice Transcript: {transcript}"},
            ],
            "options": {"temperature": 0.1},
            "stream": False,
        },
        timeout=25,
    )
    if resp.status_code == 200:
        content = resp.json().get("message", {}).get("content", "")
        return sanitize_json(content, transcript)
    raise RuntimeError(f"Ollama HTTP {resp.status_code}")

def route_intent(transcript: str) -> dict:
    cleaned = transcript.strip()
    if not cleaned or len(cleaned) < 2:
        return build_default_intent(cleaned)

    # 1. Primary: Groq API
    try:
        return call_groq(cleaned)
    except Exception as e:
        print(f"[intent_router.py] Groq fallback notice: {e}", file=sys.stderr)

    # 2. Offline Fallback: Local Ollama
    try:
        return call_ollama(cleaned)
    except Exception as e:
        print(f"[intent_router.py] Ollama fallback notice: {e}", file=sys.stderr)

    # 3. Deterministic Fallback
    return build_default_intent(cleaned)

def main():
    transcript = ""
    if len(sys.argv) > 1:
        transcript = " ".join(sys.argv[1:]).strip()

    if not transcript and os.path.exists(TRANSCRIPT_CACHE_FILE):
        try:
            with open(TRANSCRIPT_CACHE_FILE, "r", encoding="utf-8") as f:
                transcript = f.read().strip()
        except Exception:
            transcript = ""

    result = route_intent(transcript)

    # Save outputs to cache files
    try:
        with open(STATUS_CACHE_FILE, "w", encoding="utf-8") as f:
            f.write(result["speaking_start"])
    except Exception as e:
        print(f"[intent_router.py] Status caching notice: {e}", file=sys.stderr)

    try:
        with open(INTENT_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
    except Exception as e:
        print(f"[intent_router.py] Intent caching notice: {e}", file=sys.stderr)

    # Pure output: stdout JSON only (no duplicate speech trigger)
    print(json.dumps(result, indent=2))
    sys.exit(0)

if __name__ == "__main__":
    main()
