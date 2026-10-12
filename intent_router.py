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
ANTIGRAVITY_TASK_FILE = os.path.join(PROJECT_ROOT, "antigravity_task.json")

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

def extract_target_file(transcript: str) -> str:
    """Extracts target python filename from transcript or matches known codebase files."""
    m = re.search(r'([a-zA-Z0-9_\-]+\.py)', transcript, re.IGNORECASE)
    if m:
        return m.group(1).lower()

    known_files = [
        "jarvis_listener", "speak", "transcribe", "intent_router",
        "jarvis_hud", "execute_git", "execute_agent", "start_hud", "start_jarvis"
    ]
    t = transcript.lower()
    for kf in known_files:
        if kf in t:
            return f"{kf}.py"

    if any(w in t for w in ["generate", "create", "write", "build", "new script"]):
        return "custom_tool.py"
    return "jarvis_listener.py"

def build_system_prompt() -> str:
    codebase_context = get_project_context()
    return f"""You are Jarvis, a brilliant AI systems assistant and autonomous coding engineer.
You automate Git commands, dispatch code generation and bug fixes to Antigravity, and answer questions about this codebase or general topics.

=== CODEBASE DIGEST ({PROJECT_ROOT}) ===
{codebase_context}
========================================

Classify the user's input into one of four types:
1. "antigravity_task": Instruction to fix a bug, solve an error, write a new script, generate code, or refactor code.
   - action: "bug_fix" | "code_generation" | "refactor"
   - target_file: specific file mentioned or implied (e.g. "speak.py", "jarvis_listener.py", "custom_tool.py")
   - task_description: detailed actionable instructions for the code fix or generation.
   - speaking_start: "Delegating task to Antigravity: fixing bug in <filename>, sir." (or "generating <filename>")
   - speaking_progress: "Antigravity is reading <filename> and applying code patches..."
   - speaking_response: "Task completed, sir. Antigravity has resolved the issue in <filename>."
2. "codebase_qa": Question about this project, its code, files, architecture, or behavior (no code change requested).
3. "git_action": An instruction to perform Git/GitHub CLI actions (push, commit, status, branch, pr, repo).
4. "general_qa": General knowledge question, reasoning, conversation, or math.

You must respond with ONLY a valid, raw JSON object matching the exact schema below.
DO NOT include markdown code blocks (```json), explanations, or preamble.

Strict Output Schema:
{{
  "type": "antigravity_task" | "codebase_qa" | "git_action" | "general_qa",
  "action": "bug_fix" | "code_generation" | "refactor" | "",
  "target_file": "<filename_if_antigravity_task>",
  "task_description": "<detailed_prompt_for_code_fix_if_antigravity>",
  "command": "<cli_command_if_git_or_antigravity>",
  "speaking_start": "<short_task_start_announcement>",
  "speaking_progress": "<spoken_progress_announcement_if_antigravity>",
  "speaking_response": "<direct_spoken_answer_2_to_3_sentences_max>"
}}

Rules:
- For "antigravity_task":
  - command: "cd \"{PROJECT_ROOT}\" && python execute_agent.py antigravity_task.json"
- For "codebase_qa":
  - Use the codebase digest above to give an accurate, crisp, 2-sentence conversational answer.
  - command: "", action: "", target_file: "", speaking_start: "", speaking_progress: ""
- For "git_action":
  - command MUST begin with: cd "{PROJECT_ROOT}" && ...
  - speaking_start: "Executing task: <description>, sir."
  - speaking_progress: ""
  - speaking_response: "Task completed successfully, sir."
- For "general_qa":
  - Provide a concise spoken answer (1-2 sentences maximum).
  - command: "", action: "", target_file: "", speaking_start: "", speaking_progress: ""

Examples:
1. "Jarvis, solve the bug in speak.py" ->
{{
  "type": "antigravity_task",
  "action": "bug_fix",
  "target_file": "speak.py",
  "task_description": "Diagnose and resolve audio playback and edge-tts synthesis locking bug in speak.py",
  "command": "cd \\"{PROJECT_ROOT}\\" && python execute_agent.py antigravity_task.json",
  "speaking_start": "Delegating task to Antigravity: fixing bug in speak.py, sir.",
  "speaking_progress": "Antigravity is reading speak.py and applying code patches...",
  "speaking_response": "Task completed, sir. Antigravity has resolved the issue in speak.py."
}}

2. "Jarvis, generate a new script to backup git repository" ->
{{
  "type": "antigravity_task",
  "action": "code_generation",
  "target_file": "repo_backup.py",
  "task_description": "Generate an automated python script to backup git repository commits and tags",
  "command": "cd \\"{PROJECT_ROOT}\\" && python execute_agent.py antigravity_task.json",
  "speaking_start": "Delegating task to Antigravity: generating repo_backup.py, sir.",
  "speaking_progress": "Antigravity is reading repo_backup.py and synthesizing code scaffold...",
  "speaking_response": "Task completed, sir. Antigravity has generated repo_backup.py."
}}

3. "Push all my changes with message fix audio bug" ->
{{
  "type": "git_action",
  "action": "",
  "target_file": "",
  "task_description": "",
  "command": "cd \\"{PROJECT_ROOT}\\" && git init && git add . && (git commit -m \\"fix audio bug\\" || echo \\"No changes to commit\\") && (git push || gh repo create \\"Jarvis-Voice-Assistant\\" --public --source=. --remote=origin --push)",
  "speaking_start": "Executing task: committing and pushing your changes, sir.",
  "speaking_progress": "",
  "speaking_response": "Task completed successfully, sir."
}}
"""

def build_default_intent(transcript: str) -> dict:
    cd_prefix = f'cd "{PROJECT_ROOT}"'
    t = transcript.lower()

    # 1. Antigravity Coding & Bug Fixing Intent
    coding_keywords = [
        "solve", "fix", "bug", "error", "repair", "broken", "issue", "crash",
        "generate", "create script", "write script", "make script", "build script",
        "refactor", "patch", "modify code", "edit code"
    ]
    if any(w in t for w in coding_keywords):
        target_file = extract_target_file(transcript)
        if "refactor" in t:
            action = "refactor"
            start_msg = f"Delegating task to Antigravity: refactoring {target_file}, sir."
            prog_msg = f"Antigravity is analyzing AST tree and refactoring {target_file}..."
            resp_msg = f"Task completed, sir. Antigravity has refactored {target_file}."
        elif any(w in t for w in ["generate", "create", "write", "make", "build"]):
            action = "code_generation"
            start_msg = f"Delegating task to Antigravity: generating {target_file}, sir."
            prog_msg = f"Antigravity is scaffolding and synthesizing {target_file}..."
            resp_msg = f"Task completed, sir. Antigravity has generated {target_file}."
        else:
            action = "bug_fix"
            start_msg = f"Delegating task to Antigravity: fixing bug in {target_file}, sir."
            prog_msg = f"Antigravity is reading {target_file} and applying code patches..."
            resp_msg = f"Task completed, sir. Antigravity has resolved the issue in {target_file}."

        return {
            "type": "antigravity_task",
            "action": action,
            "target_file": target_file,
            "task_description": transcript,
            "command": f'{cd_prefix} && python execute_agent.py antigravity_task.json',
            "speaking_start": start_msg,
            "speaking_progress": prog_msg,
            "speaking_response": resp_msg,
        }

    # 2. Git Action Intent
    if any(w in t for w in ["push", "commit", "repo", "github"]):
        return {
            "type": "git_action",
            "action": "",
            "target_file": "",
            "task_description": "Git commit and push",
            "command": (
                f'{cd_prefix} && git init && git add . && '
                f'(git commit -m "Automated update via Jarvis" || echo "No changes to commit") && '
                f'(git push || gh repo create "Jarvis-Voice-Assistant" --public --source=. --remote=origin --push)'
            ),
            "speaking_start": "Executing task: committing and pushing changes, sir.",
            "speaking_progress": "",
            "speaking_response": "Task completed successfully, sir.",
        }
    elif any(w in t for w in ["status", "changes"]):
        return {
            "type": "git_action",
            "action": "",
            "target_file": "",
            "task_description": "Git status check",
            "command": f'{cd_prefix} && git status',
            "speaking_start": "Executing task: checking git status, sir.",
            "speaking_progress": "",
            "speaking_response": "Task completed successfully, sir.",
        }
    else:
        return {
            "type": "general_qa",
            "action": "",
            "target_file": "",
            "task_description": "",
            "command": "",
            "speaking_start": "",
            "speaking_progress": "",
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
    cd_prefix = f'cd "{PROJECT_ROOT}"'

    if req_type == "antigravity_task":
        target_file = str(data.get("target_file", "")).strip() or extract_target_file(transcript)
        action = str(data.get("action", "bug_fix")).strip() or "bug_fix"
        task_desc = str(data.get("task_description", transcript)).strip()
        start = str(data.get("speaking_start", f"Delegating task to Antigravity: fixing bug in {target_file}, sir."))
        prog = str(data.get("speaking_progress", f"Antigravity is reading {target_file} and applying code patches..."))
        resp = str(data.get("speaking_response", f"Task completed, sir. Antigravity has resolved the issue in {target_file}."))
        if not cmd:
            cmd = f'{cd_prefix} && python execute_agent.py antigravity_task.json'
        elif not cmd.startswith("cd "):
            cmd = f'{cd_prefix} && {cmd}'

        return {
            "type": "antigravity_task",
            "action": action,
            "target_file": target_file,
            "task_description": task_desc,
            "command": cmd,
            "speaking_start": start,
            "speaking_progress": prog,
            "speaking_response": resp,
        }

    if req_type == "git_action":
        if not cmd.startswith("cd "):
            cmd = f'{cd_prefix} && {cmd}' if cmd else f'{cd_prefix} && git status'

    return {
        "type": req_type,
        "action": str(data.get("action", "")),
        "target_file": str(data.get("target_file", "")),
        "task_description": str(data.get("task_description", "")),
        "command": cmd,
        "speaking_start": str(data.get("speaking_start", "")),
        "speaking_progress": str(data.get("speaking_progress", "")),
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
            status_text = result.get("speaking_start") or f"Jarvis routing: {result.get('type')}"
            f.write(status_text)
    except Exception as e:
        print(f"[intent_router.py] Status caching notice: {e}", file=sys.stderr)

    # Save structured payload to antigravity_task.json
    if result.get("type") == "antigravity_task":
        try:
            task_payload = {
                "type": "antigravity_task",
                "action": result.get("action", "bug_fix"),
                "target_file": result.get("target_file", ""),
                "task_description": result.get("task_description", transcript),
                "speaking_start": result.get("speaking_start", ""),
                "speaking_progress": result.get("speaking_progress", ""),
                "speaking_response": result.get("speaking_response", ""),
                "status": "pending",
                "created_at": time.time()
            }
            with open(ANTIGRAVITY_TASK_FILE, "w", encoding="utf-8") as f:
                json.dump(task_payload, f, indent=2)
            print(f"[intent_router.py] Wrote structured task to {ANTIGRAVITY_TASK_FILE}", file=sys.stderr)
        except Exception as e:
            print(f"[intent_router.py] Antigravity task caching notice: {e}", file=sys.stderr)

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
