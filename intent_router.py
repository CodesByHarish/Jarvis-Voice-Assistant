#!/usr/bin/env python3
"""
Jarvis Low-Latency Codebase & Conversational AI Router
Features:
- Fast cached repository file crawler: `get_project_context()` with 120s TTL cache.
- Concise architectural digest keeps Groq prompt under 800 tokens for sub-200ms responses.
- Tri-mode routing: `codebase_qa` | `git_action` | `general_qa`.
- Output Schema:
  {
    "type": "codebase_qa" | "git_action" | "general_qa",
    "command": "<cli_command_if_git>",
    "speaking_start": "<task_description_if_git>",
    "speaking_response": "<direct_concise_spoken_answer_for_qa_or_completion>"
  }
"""

import sys
import os
import json
import re
import time
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
CODEBASE_CACHE_FILE = os.path.join(PROJECT_ROOT, "codebase_cache.json")

def get_project_context(force_refresh: bool = False) -> str:
    """Scans and caches key project source files to answer codebase questions with zero delay."""
    if not force_refresh and os.path.exists(CODEBASE_CACHE_FILE):
        try:
            mtime = os.path.getmtime(CODEBASE_CACHE_FILE)
            if time.time() - mtime < 120:
                with open(CODEBASE_CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    cached_text = data.get("context", "")
                    if cached_text:
                        return cached_text
        except Exception:
            pass

    context_parts = []
    core_files = [
        "jarvis_listener.py",
        "speak.py",
        "transcribe.py",
        "intent_router.py",
        "execute_git.py",
        "workflows/jarvis_workflow.json",
        "README.md",
    ]

    for relpath in core_files:
        filepath = os.path.join(PROJECT_ROOT, relpath)
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                # Extract first 25 lines (docstrings, imports, core parameters)
                snippet = "".join(lines[:25]).strip()
                context_parts.append(f"[{relpath}]\n{snippet}\n")
            except Exception:
                continue

    summary = "\n".join(context_parts)
    try:
        with open(CODEBASE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"context": summary, "timestamp": time.time()}, f)
    except Exception:
        pass

    return summary

def build_system_prompt() -> str:
    codebase_context = get_project_context()
    return f"""You are Jarvis, a brilliant AI systems assistant and pair programmer.
You automate Git/GitHub commands and answer questions about this codebase or general topics.

=== CODEBASE DIGEST ({PROJECT_ROOT}) ===
{codebase_context}
========================================

Classify the user's input into one of three types:
1. "codebase_qa": Question about this project, its code, files, architecture, or behavior.
2. "git_action": An instruction to perform Git/GitHub CLI actions (push, commit, status, branch, pr, repo).
3. "general_qa": General knowledge question, reasoning, conversation, or math.

You must respond with ONLY a valid, raw JSON object matching the exact schema below.
DO NOT include markdown code blocks (```json), explanations, or preamble.

Strict Output Schema:
{{
  "type": "codebase_qa" | "git_action" | "general_qa",
  "command": "<cli_command_if_git_otherwise_empty>",
  "speaking_start": "<short_task_description_if_git_otherwise_empty>",
  "speaking_response": "<direct_spoken_answer_2_to_3_sentences_max>"
}}

Rules:
- For "codebase_qa":
  - Use the codebase digest above to give an accurate, crisp, 2-sentence conversational answer.
  - command: ""
  - speaking_start: ""
- For "git_action":
  - command MUST begin with: cd "{PROJECT_ROOT}" && ...
  - speaking_start: "Executing task: <description>, sir."
  - speaking_response: "Task completed successfully, sir."
- For "general_qa":
  - Provide a concise spoken answer (1-2 sentences maximum).
  - command: ""
  - speaking_start: ""

Examples:
1. "Explain how speak.py works" ->
{{
  "type": "codebase_qa",
  "command": "",
  "speaking_start": "",
  "speaking_response": "Speak.py uses Microsoft Edge TTS with the Christopher Neural voice and Pygame. It uses pre-rendered static clips and a non-blocking queue so audio playback never blocks the listener."
}}

2. "Push all my changes with message fix audio bug" ->
{{
  "type": "git_action",
  "command": "cd \\"{PROJECT_ROOT}\\" && git init && git add . && (git commit -m \\"fix audio bug\\" || echo \\"No changes to commit\\") && (git push || gh repo create \\"Jarvis-Voice-Assistant\\" --public --source=. --remote=origin --push)",
  "speaking_start": "Executing task: committing and pushing your changes, sir.",
  "speaking_response": "Task completed successfully, sir."
}}

3. "What is standard deviation?" ->
{{
  "type": "general_qa",
  "command": "",
  "speaking_start": "",
  "speaking_response": "Standard deviation measures how spread out numbers are around their average. A low standard deviation means values are closely clustered around the mean."
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
        "qwen/qwen3.8-27b",
        "llama-3.3-70b-versatile",
        "qwen-2.5-32b",
        "openai/gpt-oss-120b",
    ]

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    system_prompt = build_system_prompt()
    last_err = None

    for m in models:
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json={
                    "model": m,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"User: {transcript}"},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 150,
                },
                timeout=10,
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
    system_prompt = build_system_prompt()
    resp = requests.post(
        f"{OLLAMA_HOST}/api/chat",
        json={
            "model": "qwen2.5-coder:7b",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"User: {transcript}"},
            ],
            "options": {"temperature": 0.2, "num_predict": 150},
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

    # 1. Primary: Groq Cloud API
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

    # Output strict JSON
    print(json.dumps(result, indent=2))
    sys.exit(0)

if __name__ == "__main__":
    main()
