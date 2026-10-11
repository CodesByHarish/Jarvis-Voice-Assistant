#!/usr/bin/env python3
"""
Jarvis Dual-LLM Router & Intent Parser
Features:
- Forces explicit project root working directory switch on ALL generated commands.
- Repositories creation fallback: initializes Git, commits, and creates public GitHub repo if push fails.
- Safe argument passing with fallback to last_transcript.txt.
- Primary: Groq Cloud API | Fallback: Local Ollama (qwen2.5-coder:7b).
"""

import sys
import os
import json
import re
import requests
from dotenv import load_dotenv

# Load environment configuration
load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__)).replace("/", "\\")
TRANSCRIPT_CACHE_FILE = os.path.join(PROJECT_ROOT, "last_transcript.txt")
INTENT_CACHE_FILE = os.path.join(PROJECT_ROOT, "last_intent.json")

SYSTEM_PROMPT = f"""You are the Jarvis Git Automation Engine.
Your job is to translate voice transcripts into deterministic, executable Git and GitHub CLI commands.
You must respond with ONLY a valid, raw JSON object matching the exact schema below.
DO NOT include markdown backticks (```json), explanations, markdown formatting, or preamble.

Strict Output Schema:
{{
  "action": "stage_commit_push" | "create_pr" | "checkout_branch" | "status" | "unknown",
  "branch": "<branch_name or empty string>",
  "commit_message": "<commit_message or empty string>",
  "pr_title": "<pr_title or empty string>",
  "command": "<raw_cli_command_to_run>"
}}

IMPORTANT WORKING DIRECTORY RULE:
All CLI commands MUST explicitly prepend: cd "{PROJECT_ROOT}" && ...

Command Mapping Guidelines:
1. "push", "commit and push", "create repo", "push to github", "commit files as <msg>":
   - action: "stage_commit_push"
   - command: cd "{PROJECT_ROOT}" && git init && git add . && git commit -m "<msg>" && (git push || gh repo create "Jarvis-Voice-Assistant" --public --source=. --remote=origin --push)
2. "status", "check git status", "show changes", "what is the status":
   - action: "status"
   - command: cd "{PROJECT_ROOT}" && git status
3. "checkout <branch>", "switch to branch <branch>":
   - action: "checkout_branch"
   - command: cd "{PROJECT_ROOT}" && git checkout <branch>
4. "create new branch <branch>", "make branch <branch>":
   - action: "checkout_branch"
   - command: cd "{PROJECT_ROOT}" && git checkout -b <branch>
5. "create pull request titled <title>", "open pr <title>":
   - action: "create_pr"
   - command: cd "{PROJECT_ROOT}" && gh pr create --title "<title>" --body "Automated PR created by Jarvis"
6. If the request cannot be determined:
   - action: "unknown"
   - command: cd "{PROJECT_ROOT}" && git status
"""

def build_safe_command(action: str, branch: str, commit_msg: str, pr_title: str, raw_cmd: str, transcript: str = "") -> str:
    """Ensures deterministic, properly quoted shell commands with explicit project root cd."""
    cd_prefix = f'cd "{PROJECT_ROOT}"'
    t = transcript.lower()

    if action == "stage_commit_push" or any(w in t for w in ["push", "commit", "repo", "github"]):
        msg = commit_msg.strip() or "Automated update via Jarvis"
        safe_msg = msg.replace('"', '\\"')
        return (
            f'{cd_prefix} && git init && git add . && '
            f'(git commit -m "{safe_msg}" || echo "No changes to commit") && '
            f'(git push || gh repo create "Jarvis-Voice-Assistant" --public --source=. --remote=origin --push)'
        )
    elif action == "create_pr":
        title = pr_title.strip() or "Automated Pull Request via Jarvis"
        safe_title = title.replace('"', '\\"')
        return f'{cd_prefix} && gh pr create --title "{safe_title}" --body "Automated PR created by Jarvis"'
    elif action == "checkout_branch" and branch:
        clean_branch = re.sub(r"[^a-zA-Z0-9_\-\./]", "", branch.strip())
        return f'{cd_prefix} && git checkout {clean_branch}'
    elif action == "status":
        return f'{cd_prefix} && git status'
    elif raw_cmd and raw_cmd.strip():
        clean_cmd = raw_cmd.strip()
        if not clean_cmd.startswith("cd "):
            return f'{cd_prefix} && {clean_cmd}'
        return clean_cmd
    return f'{cd_prefix} && git status'

def extract_json(raw_text: str, transcript: str = "") -> dict:
    """Robustly cleans and extracts valid JSON dictionary from raw model text."""
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
        action_match = re.search(r'"action"\s*:\s*"([^"]+)"', clean)
        commit_match = re.search(r'"commit_message"\s*:\s*"([^"]*)"', clean)
        branch_match = re.search(r'"branch"\s*:\s*"([^"]*)"', clean)
        pr_match = re.search(r'"pr_title"\s*:\s*"([^"]*)"', clean)
        cmd_match = re.search(r'"command"\s*:\s*"([^"]*)"', clean)

        data = {
            "action": action_match.group(1) if action_match else "unknown",
            "commit_message": commit_match.group(1) if commit_match else "",
            "branch": branch_match.group(1) if branch_match else "",
            "pr_title": pr_match.group(1) if pr_match else "",
            "command": cmd_match.group(1) if cmd_match else f'cd "{PROJECT_ROOT}" && git status',
        }

    action = str(data.get("action", "unknown")).strip()
    branch = str(data.get("branch", "")).strip()
    commit_msg = str(data.get("commit_message", "")).strip()
    pr_title = str(data.get("pr_title", "")).strip()
    raw_cmd = str(data.get("command", "")).strip()

    safe_cmd = build_safe_command(action, branch, commit_msg, pr_title, raw_cmd, transcript)

    return {
        "action": action,
        "branch": branch,
        "commit_message": commit_msg,
        "pr_title": pr_title,
        "command": safe_cmd,
    }

def call_groq(transcript: str) -> dict:
    """Primary inference engine: Groq Cloud API."""
    if not GROQ_API_KEY or GROQ_API_KEY.startswith("your_"):
        raise ValueError("Valid GROQ_API_KEY not configured.")

    candidate_models = [
        "llama-3.3-70b-versatile",
        "qwen/qwen3.8-27b",
        "qwen-2.5-32b",
        "openai/gpt-oss-120b",
    ]

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    last_error = None
    for model in candidate_models:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Voice Transcript: {transcript}"},
            ],
            "temperature": 0.1,
            "max_tokens": 256,
        }
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=8,
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                return extract_json(content, transcript)
            elif resp.status_code == 404:
                continue
            else:
                last_error = f"HTTP {resp.status_code}: {resp.text}"
        except Exception as e:
            last_error = str(e)
            break

    raise RuntimeError(f"Groq API call failed: {last_error}")

def call_ollama(transcript: str) -> dict:
    """Offline Fallback inference engine: Local Ollama."""
    url = f"{OLLAMA_HOST}/api/chat"
    payload = {
        "model": "qwen2.5-coder:7b",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Voice Transcript: {transcript}"},
        ],
        "options": {
            "temperature": 0.1,
        },
        "stream": False,
    }

    resp = requests.post(url, json=payload, timeout=25)
    if resp.status_code != 200:
        raise RuntimeError(f"Ollama HTTP {resp.status_code}: {resp.text}")

    content = resp.json().get("message", {}).get("content", "")
    return extract_json(content, transcript)

def route_intent(transcript: str) -> dict:
    """Dispatches transcript to Groq, falling back to Ollama or heuristic fallback."""
    cleaned = transcript.strip()
    if not cleaned or len(cleaned) < 2:
        return {
            "action": "status",
            "branch": "",
            "commit_message": "",
            "pr_title": "",
            "command": f'cd "{PROJECT_ROOT}" && git status',
        }

    # 1. Primary: Groq Cloud API
    try:
        return call_groq(cleaned)
    except Exception as groq_err:
        print(f"[intent_router.py] Groq unavailable ({groq_err}), switching to Ollama...", file=sys.stderr)

    # 2. Offline Fallback: Local Ollama
    try:
        return call_ollama(cleaned)
    except Exception as ollama_err:
        print(f"[intent_router.py] Ollama unavailable ({ollama_err}), using heuristic fallback...", file=sys.stderr)

    # 3. Deterministic Safety Heuristic
    t = cleaned.lower()
    if any(w in t for w in ["push", "commit", "repo", "github"]):
        return {
            "action": "stage_commit_push",
            "branch": "",
            "commit_message": "Automated update via Jarvis",
            "pr_title": "",
            "command": (
                f'cd "{PROJECT_ROOT}" && git init && git add . && '
                f'(git commit -m "Automated update via Jarvis" || echo "No changes to commit") && '
                f'(git push || gh repo create "Jarvis-Voice-Assistant" --public --source=. --remote=origin --push)'
            ),
        }
    return {
        "action": "status",
        "branch": "",
        "commit_message": "",
        "pr_title": "",
        "command": f'cd "{PROJECT_ROOT}" && git status',
    }

def main():
    transcript = ""
    # 1. Read CLI argument if passed
    if len(sys.argv) > 1:
        transcript = " ".join(sys.argv[1:]).strip()

    # 2. Read from last_transcript.txt if argument is empty
    if not transcript and os.path.exists(TRANSCRIPT_CACHE_FILE):
        try:
            with open(TRANSCRIPT_CACHE_FILE, "r", encoding="utf-8") as f:
                transcript = f.read().strip()
        except Exception:
            transcript = ""

    try:
        result = route_intent(transcript)
    except Exception as e:
        print(f"[intent_router.py] Exception recovered: {e}", file=sys.stderr)
        result = {
            "action": "status",
            "branch": "",
            "commit_message": "",
            "pr_title": "",
            "command": f'cd "{PROJECT_ROOT}" && git status',
        }

    # Save intent JSON
    try:
        with open(INTENT_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
    except Exception as e:
        print(f"[intent_router.py] Warning caching intent: {e}", file=sys.stderr)

    # Print strict JSON
    print(json.dumps(result, indent=2))
    sys.exit(0)

if __name__ == "__main__":
    main()
