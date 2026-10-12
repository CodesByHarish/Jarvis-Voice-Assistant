#!/usr/bin/env python3
"""
Jarvis General-Purpose Dual AI Voice Router & Intent Parser
Features:
- Handles both Git operations AND general conversational queries (General QA, definitions, chat).
- Primary: Groq Cloud API (llama-3.3-70b-versatile) | Fallback: Local Ollama (qwen2.5-coder:7b).
- Output Schema:
  {
    "type": "git_action" | "general_qa",
    "command": "<cli_command_if_git>",
    "speaking_start": "<short_task_description_if_git>",
    "speaking_response": "<direct_concise_spoken_answer_for_qa_or_completion>"
  }
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

SYSTEM_PROMPT = f"""You are Jarvis, a highly intelligent conversational AI assistant and systems engineer.
Classify the user's voice input into either a Git/GitHub operation ("git_action") OR a general conversation/knowledge query ("general_qa").

You must respond with ONLY a valid, raw JSON object matching the exact schema below.
DO NOT include markdown code blocks (```json), explanations, markdown formatting, or preamble.

Strict Output Schema:
{{
  "type": "git_action" | "general_qa",
  "command": "<cli_command_if_git_or_empty>",
  "speaking_start": "<short_task_description_if_git_or_empty>",
  "speaking_response": "<direct_concise_spoken_answer_for_qa_or_completion>"
}}

Rules for "git_action":
- Triggered when the user asks for Git/GitHub tasks: commit, push, git status, checkout, branch, pull request, repo creation.
- command MUST begin with: cd "{PROJECT_ROOT}" && ...
- speaking_start: "Executing task: <short task description, e.g. checking git status, sir.>"
- speaking_response: "Task completed successfully, sir."

Rules for "general_qa":
- Triggered for ANY general questions, facts, calculations, coding advice, jokes, or chit-chat.
- command: ""
- speaking_start: ""
- speaking_response: Provide a direct, natural, conversational spoken answer (1-3 sentences maximum, no bullet points or markdown).

Examples:
1. Input: "Push my changes with message updated voice pipeline" ->
{{
  "type": "git_action",
  "command": "cd \\"{PROJECT_ROOT}\\" && git init && git add . && (git commit -m \\"updated voice pipeline\\" || echo \\"No changes to commit\\") && (git push || gh repo create \\"Jarvis-Voice-Assistant\\" --public --source=. --remote=origin --push)",
  "speaking_start": "Executing task: committing and pushing your changes, sir.",
  "speaking_response": "Task completed successfully, sir."
}}

2. Input: "What is standard deviation?" ->
{{
  "type": "general_qa",
  "command": "",
  "speaking_start": "",
  "speaking_response": "Standard deviation measures the amount of variation or dispersion in a set of values relative to their mean. A low standard deviation means values are clustered closely around the average."
}}

3. Input: "Check git status" ->
{{
  "type": "git_action",
  "command": "cd \\"{PROJECT_ROOT}\\" && git status",
  "speaking_start": "Executing task: checking git status, sir.",
  "speaking_response": "Task completed successfully, sir."
}}
"""

def build_default_intent(transcript: str) -> dict:
    cd_prefix = f'cd "{PROJECT_ROOT}"'
    t = transcript.lower()

    if any(w in t for w in ["push", "commit", "repo", "github"]):
        return {
            "type": "git_action",
            "command": (
                f'{cd_prefix} && git init && git add . && '
                f'(git commit -m "Automated update via Jarvis" || echo "No changes to commit") && '
                f'(git push || gh repo create "Jarvis-Voice-Assistant" --public --source=. --remote=origin --push)'
            ),
            "speaking_start": "Executing task: committing and pushing changes, sir.",
            "speaking_response": "Task completed successfully, sir.",
        }
    elif any(w in t for w in ["status", "changes"]):
        return {
            "type": "git_action",
            "command": f'{cd_prefix} && git status',
            "speaking_start": "Executing task: checking git status, sir.",
            "speaking_response": "Task completed successfully, sir.",
        }
    else:
        return {
            "type": "general_qa",
            "command": "",
            "speaking_start": "",
            "speaking_response": "I am standing by, sir. How may I assist you?",
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

    req_type = str(data.get("type", "general_qa")).strip()
    cmd = str(data.get("command", "")).strip()

    if req_type == "git_action":
        cd_prefix = f'cd "{PROJECT_ROOT}"'
        if not cmd.startswith("cd "):
            cmd = f'{cd_prefix} && {cmd}' if cmd else f'{cd_prefix} && git status'

    return {
        "type": req_type,
        "command": cmd,
        "speaking_start": str(data.get("speaking_start", "")),
        "speaking_response": str(data.get("speaking_response", "Task completed successfully, sir.")),
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
                        {"role": "user", "content": f"User: {transcript}"},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 300,
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
                {"role": "user", "content": f"User: {transcript}"},
            ],
            "options": {"temperature": 0.3},
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

    # Save to status & intent cache
    try:
        with open(STATUS_CACHE_FILE, "w", encoding="utf-8") as f:
            f.write(result.get("speaking_start", ""))
    except Exception as e:
        print(f"[intent_router.py] Status caching notice: {e}", file=sys.stderr)

    try:
        with open(INTENT_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
    except Exception as e:
        print(f"[intent_router.py] Intent caching notice: {e}", file=sys.stderr)

    # Output strict JSON to stdout
    print(json.dumps(result, indent=2))
    sys.exit(0)

if __name__ == "__main__":
    main()
