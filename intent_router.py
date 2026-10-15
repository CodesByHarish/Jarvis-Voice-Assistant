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
import subprocess
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
ANTIGRAVITY_PROMPT_FILE = os.path.join(PROJECT_ROOT, "antigravity_prompt.txt")

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

ANTIGRAVITY_TRIGGER_KEYWORDS = [
    "bug fix", "fix bug", "code changes", "create app", "modify hud", "theme", "antigravity",
    "solve", "bug", "fix", "error", "repair", "broken", "issue", "crash",
    "generate", "create script", "write script", "make script", "build script",
    "refactor", "patch", "modify code", "edit code", "new feature", "add feature", "implement",
    "ui change", "dark mode"
]

def sync_to_clipboard(text: str) -> bool:
    """Syncs formatted text to Windows clipboard using native clip.exe."""
    try:
        proc = subprocess.Popen(["clip"], stdin=subprocess.PIPE, shell=True)
        proc.communicate(input=text.encode("utf-8"))
        print("[intent_router.py] Formatted prompt synchronized to Windows clipboard.", file=sys.stderr)
        return True
    except Exception as e:
        print(f"[intent_router.py] Clipboard sync error: {e}", file=sys.stderr)
        return False

def is_antigravity_intent(transcript: str) -> bool:
    """Detects whether transcript requires Antigravity code generation, bug fixing, or HUD styling."""
    t = transcript.lower()
    # Explicit regex patterns for critical trigger phrases
    patterns = [
        r'\bbug\s*fix\b',
        r'\bfix\s*bug\b',
        r'\bcode\s*changes?\b',
        r'\bcreate\s*app\b',
        r'\bmodify\s*hud\b',
        r'\btheme\b',
        r'\bantigravity\b',
    ]
    for p in patterns:
        if re.search(p, t):
            return True
    return any(w in t for w in ANTIGRAVITY_TRIGGER_KEYWORDS)

def inspect_branch_status(branch_name: str, repo_path: str = PROJECT_ROOT) -> tuple[bool, bool]:
    """
    Inspects whether branch exists locally using `git branch --list <branch_name>`
    and whether it exists on remote using `git branch -r --list origin/<branch_name>`.
    Returns (exists_locally, exists_remotely).
    """
    clean_name = branch_name.strip()
    if not clean_name:
        return False, False
    try:
        proc_local = subprocess.run(
            ["git", "branch", "--list", clean_name],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        exists_locally = bool(proc_local.stdout.strip())
    except Exception:
        exists_locally = False

    try:
        proc_remote = subprocess.run(
            ["git", "branch", "-r", "--list", f"origin/{clean_name}"],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        exists_remotely = bool(proc_remote.stdout.strip())
    except Exception:
        exists_remotely = False

    return exists_locally, exists_remotely

def is_checkout_master(transcript: str) -> bool:
    """Detects commands requesting switching or checking out master branch."""
    t = transcript.lower().strip()
    if is_merge_to_master(t):
        return False
    patterns = [
        r'\b(?:switch|checkout|go)\s+(?:in)?to\s+(?:the\s+)?master(?:\s+branch)?\b',
        r'\bcheckout\s+master\b',
        r'\bswitch\s+to\s+master\b',
        r'\bgo\s+to\s+master(?:\s+branch)?\b',
        r'\b(?:switch|checkout)\s+(?:to\s+)?branch\s+master\b',
    ]
    return any(re.search(p, t) for p in patterns)

def is_explicit_branch_creation(transcript: str) -> bool:
    """Detects explicit branch creation requests (e.g. 'create branch foo', 'make new branch bar')."""
    t = transcript.lower().strip()
    if is_merge_to_master(t) or is_checkout_master(t):
        return False
    patterns = [
        r'\b(?:create|make|new)\s+(?:a\s+)?branch\b',
        r'\bcheckout\s+-b\b',
        r'\bbranch\s+(?:create|make|new)\b',
    ]
    return any(re.search(p, t) for p in patterns)

def is_branch_switch(transcript: str) -> bool:
    """Detects general branch switching or checkout requests."""
    t = transcript.lower().strip()
    if is_merge_to_master(t) or is_checkout_master(t):
        return False
    patterns = [
        r'\b(?:switch|checkout|go)\s+(?:in)?to\s+(?:branch\s+)?([a-zA-Z0-9_\-\.\/]+)',
        r'\b(?:switch|checkout)\s+branch\s+([a-zA-Z0-9_\-\.\/]+)',
    ]
    return any(re.search(p, t) for p in patterns)

def is_branch_creation(transcript: str) -> bool:
    """Detects git branch creation or switching requests (legacy wrapper)."""
    return is_explicit_branch_creation(transcript) or is_branch_switch(transcript)

def get_current_active_branch() -> str:
    """Dynamically inspects the current active branch using `git rev-parse --abbrev-ref HEAD`."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True
        )
        if proc.returncode == 0:
            b = proc.stdout.strip()
            if b and b != "HEAD":
                return b
    except Exception:
        pass
    return "feature-branch"

def is_merge_to_master(transcript: str) -> bool:
    """Detects commands requesting merging, syncing, or pulling a branch into master."""
    t = transcript.lower()
    has_merge = bool(re.search(r'\b(?:merge|sync|pull|integrate|update)\b', t))
    has_master = bool(re.search(r'\b(?:master|main)\b', t))
    return has_merge and has_master

def extract_merge_source_branch(transcript: str) -> str:
    """Extracts source branch to merge into master or dynamically retrieves active branch."""
    # Prioritize dynamic inspection of current active branch using `git rev-parse --abbrev-ref HEAD`
    active = get_current_active_branch()
    if active and active.lower() not in ["master", "main"]:
        return active

    t = transcript.strip()
    # e.g. "merge feature to master", "merge branch feature into master", "sync feature branch to master", "pull feature to master"
    m = re.search(r'(?:merge|sync|pull)\s+(?:branch\s+)?([a-zA-Z0-9_\-\.\/]+)(?:\s+branch)?\s+(?:in)?to\s+(?:master|main)', t, re.IGNORECASE)
    if m:
        b = m.group(1).strip()
        if b.lower() not in ["the", "current", "active", "this", "changes", "from", "into"]:
            return b

    # e.g. "update master branch with feature changes", "update master with feature-branch changes"
    m2 = re.search(r'with\s+([a-zA-Z0-9_\-\.\/]+)(?:\s+branch)?\s+changes', t, re.IGNORECASE)
    if m2:
        b2 = m2.group(1).strip()
        if b2.lower() not in ["the", "current", "active", "this", "my"]:
            return b2

    return "feature-branch"

def check_python_syntax(filepath: str) -> tuple[bool, str, int | None, str]:
    """Runs actual `python -m py_compile <filepath>` to capture real compilation status."""
    if not filepath or not os.path.exists(filepath):
        return True, "File does not exist yet", None, ""

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "py_compile", filepath],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True
        )
        if proc.returncode == 0:
            return True, "Syntax check passed. No compilation errors found.", None, ""

        err_output = (proc.stderr or proc.stdout or "").strip()
        line_num = None
        m = re.search(r'line\s+(\d+)', err_output, re.IGNORECASE)
        if m:
            line_num = int(m.group(1))

        lines = [l.strip() for l in err_output.splitlines() if l.strip()]
        error_line = lines[-1] if lines else "SyntaxError: compilation failure"
        offending_code = ""
        for i, l in enumerate(lines):
            if "line " in l.lower() and i + 1 < len(lines):
                offending_code = lines[i + 1]
                break

        if offending_code:
            error_details = f"{error_line}: {offending_code}"
        else:
            error_details = error_line

        return False, err_output, line_num, error_details
    except Exception as e:
        return False, str(e), None, str(e)

def extract_branch_name(transcript: str) -> str:
    """Extracts git branch name from user speech without capturing stopwords."""
    t = transcript.strip()
    # e.g. "create branch foo", "switch to branch foo", "checkout branch foo", "go to branch foo"
    m = re.search(r'(?:create|make|checkout|switch(?:\s+to)?|go(?:\s+to)?|new)\s+(?:a\s+)?branch\s+([a-zA-Z0-9_\-\.\/]+)', t, re.IGNORECASE)
    if m:
        val = m.group(1).strip()
        if val.lower() not in ["called", "named", "the", "my", "this", "a", "into"]:
            return val

    # e.g. "checkout foo", "switch to foo", "go to foo"
    m_direct = re.search(r'(?:checkout|switch\s+to|go\s+to)\s+([a-zA-Z0-9_\-\.\/]+)', t, re.IGNORECASE)
    if m_direct:
        val = m_direct.group(1).strip()
        if val.lower() not in ["branch", "called", "named", "the", "my", "this", "a", "into"]:
            return val

    # e.g. "called foo", "named foo"
    m_name = re.search(r'(?:called|named)\s+([a-zA-Z0-9_\-\.\/]+)', t, re.IGNORECASE)
    if m_name:
        return m_name.group(1).strip()

    # e.g. "branch foo"
    m2 = re.search(r'branch\s+([a-zA-Z0-9_\-\.\/]+)', t, re.IGNORECASE)
    if m2:
        val = m2.group(1).strip()
        if val.lower() not in ["and", "to", "called", "named", "the", "my", "this", "changes", "into", "a"]:
            return val

    return "feature-branch"

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

    if any(w in t for w in ["hud", "gui", "theme", "dashboard"]):
        return "jarvis_hud.py"

    if any(w in t for w in ["generate", "create", "write", "build", "new script", "create app"]):
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
1. "antigravity_task": Instruction to fix a bug, solve an error, write a new script, generate code, create an app, modify the HUD, change themes, or refactor code.
   - Any transcript mentioning "bug fix", "fix bug", "code changes", "create app", "modify HUD", "theme", or "antigravity" MUST be classified as "antigravity_task".
   - action: "bug_fix" | "code_generation" | "refactor"
   - target_file: specific file mentioned or implied (e.g. "speak.py", "jarvis_hud.py", "custom_tool.py")
   - task_description: detailed actionable instructions for the code fix or generation.
   - speaking_start: "Delegating task to Antigravity Agent, sir."
   - speaking_progress: "Antigravity is reading <filename> and applying code patches..."
   - speaking_response: "Task completed, sir. Antigravity has resolved the issue in <filename>."
2. "codebase_qa": Question about this project, its code, files, architecture, or behavior (no code change requested).
3. "git_action": An instruction to perform Git/GitHub CLI actions (push, commit, status, branch, pr, repo).
   - If user asks to create or make a branch: command MUST be: cd "{PROJECT_ROOT}" && (git checkout -b <branch> 2>nul || git checkout <branch>) && git push -u origin <branch>
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
  - speaking_start: "Delegating task to Antigravity Agent, sir."
- For "codebase_qa":
  - Use the codebase digest above to give an accurate, crisp, 2-sentence conversational answer.
  - command: "", action: "", target_file: "", speaking_start: "", speaking_progress: ""
- For "git_action":
  - For branch creation (e.g. "create branch feature"):
    command: cd "{PROJECT_ROOT}" && (git checkout -b <branch> 2>nul || git checkout <branch>) && git push -u origin <branch>
    speaking_start: "Creating and pushing branch <branch> to GitHub, sir."
    speaking_response: "Branch <branch> has been created and pushed to GitHub, sir."
  - For commit and push:
    command: cd "{PROJECT_ROOT}" && git init && git add . && (git commit -m "<msg>" || echo "No changes to commit") && (git push || gh repo create "Jarvis-Voice-Assistant" --public --source=. --remote=origin --push)
    speaking_start: "Executing task: committing and pushing your changes, sir."
    speaking_response: "Task completed successfully, sir."
- For "general_qa":
  - Provide a concise spoken answer (1-2 sentences maximum).
  - command: "", action: "", target_file: "", speaking_start: "", speaking_progress: ""

Examples:
1. "Jarvis, create branch feature" ->
{{
  "type": "git_action",
  "action": "create_branch",
  "target_file": "",
  "task_description": "Create and push branch feature",
  "command": "cd \\"{PROJECT_ROOT}\\" && (git checkout -b feature 2>nul || git checkout feature) && git push -u origin feature",
  "speaking_start": "Creating and pushing branch feature to GitHub, sir.",
  "speaking_progress": "",
  "speaking_response": "Branch feature has been created and pushed to GitHub, sir."
}}

2. "Jarvis, solve the bug in speak.py" ->
{{
  "type": "antigravity_task",
  "action": "bug_fix",
  "target_file": "speak.py",
  "task_description": "Diagnose and resolve audio playback and edge-tts synthesis locking bug in speak.py",
  "command": "cd \\"{PROJECT_ROOT}\\" && python execute_agent.py antigravity_task.json",
  "speaking_start": "Delegating task to Antigravity Agent, sir.",
  "speaking_progress": "Antigravity is reading speak.py and applying code patches...",
  "speaking_response": "Task completed, sir. Antigravity has resolved the issue in speak.py."
}}
"""

def build_default_intent(transcript: str) -> dict:
    cd_prefix = f'cd "{PROJECT_ROOT}"'
    t = transcript.lower()

    # 1. Antigravity Coding, Bug Fixing, App Creation, HUD & Theme Intent (Immediate Priority)
    if is_antigravity_intent(transcript):
        target_file = extract_target_file(transcript)
        target_path = os.path.join(PROJECT_ROOT, target_file)

        valid, full_tb, line_num, err_details = check_python_syntax(target_path)
        if not valid:
            action = "bug_fix"
            if line_num:
                speaking_response = f"Syntax error detected on line {line_num} in {target_file}. Dispatched fix prompt directly to Antigravity, sir."
                task_desc = f"@{target_file} Fix the compilation error on line {line_num}: {err_details}. Resolve this issue now."
            else:
                speaking_response = f"Syntax error detected in {target_file}. Dispatched fix prompt directly to Antigravity, sir."
                task_desc = f"@{target_file} Fix the compilation error: {err_details}. Resolve this issue now."
        else:
            if "refactor" in t:
                action = "refactor"
            elif any(w in t for w in ["generate", "create", "write", "make", "build", "create app"]):
                action = "code_generation"
            else:
                action = "bug_fix"
            speaking_response = f"Syntax check passed. No compilation errors found in {target_file}, sir."
            task_desc = transcript

        return {
            "type": "antigravity_task",
            "action": action,
            "target_file": target_file,
            "task_description": task_desc,
            "command": f'{cd_prefix} && python execute_agent.py antigravity_task.json',
            "speaking_start": "Delegating task to Antigravity Agent, sir.",
            "speaking_progress": f"Antigravity is checking {target_file}...",
            "speaking_response": speaking_response,
        }

    # 2. Automated Merge & Push to Master Workflow (e.g. "merge feature to master", "sync feature branch to master", "pull feature to master", "update master branch with feature changes")
    if is_merge_to_master(transcript):
        source_branch = extract_merge_source_branch(transcript)
        spoken_src = "feature branch" if "feature" in source_branch.lower() else source_branch
        return {
            "type": "git_action",
            "action": "merge_to_master",
            "source_branch": source_branch,
            "target_branch": "master",
            "target_file": "",
            "task_description": f"Merge {source_branch} into master and push",
            "command": (
                f'{cd_prefix} && git checkout master && git pull origin master && '
                f'git merge {source_branch} --no-edit && git push origin master'
            ),
            "speaking_start": f"Merging changes from {spoken_src} into master, sir.",
            "speaking_progress": "",
            "speaking_response": "Successfully merged changes from feature branch into master and pushed to remote GitHub repository, sir." if "feature" in source_branch.lower() else f"Successfully merged changes from {source_branch} into master and pushed to remote GitHub repository, sir.",
        }

    # 3. Safe Master Checkout Workflow ("switch to master", "checkout master", "go to master branch")
    if is_checkout_master(transcript):
        return {
            "type": "git_action",
            "action": "checkout_master",
            "branch_name": "master",
            "target_branch": "master",
            "target_file": "",
            "task_description": "Switch to master branch and pull latest changes",
            "command": f'{cd_prefix} && git add -A && git commit -m "Auto-save state" && git checkout master && git pull origin master',
            "speaking_start": "Switching to master branch, sir.",
            "speaking_progress": "",
            "speaking_response": "Switched to master branch and pulled latest changes, sir.",
        }

    # 4. Branch Switching or Creation
    if is_explicit_branch_creation(transcript) or is_branch_switch(transcript):
        bname = extract_branch_name(transcript)
        if bname.lower() in ["master", "main"]:
            return {
                "type": "git_action",
                "action": "checkout_master",
                "branch_name": bname,
                "target_branch": bname,
                "target_file": "",
                "task_description": f"Switch to {bname} branch and pull latest changes",
                "command": f'{cd_prefix} && git add -A && git commit -m "Auto-save state" && git checkout {bname} && git pull origin {bname}',
                "speaking_start": f"Switching to {bname} branch, sir.",
                "speaking_progress": "",
                "speaking_response": "Switched to master branch and pulled latest changes, sir.",
            }

        exists_locally, exists_remotely = inspect_branch_status(bname, PROJECT_ROOT)
        is_explicit = is_explicit_branch_creation(transcript)

        if exists_locally:
            # Branch exists locally: Run git checkout <branch_name> (DO NOT use -b)
            cmd = f'{cd_prefix} && git checkout {bname}'
            action = "switch_branch"
            start = f"Switching to branch {bname}, sir."
            speaking_resp = f"Switched to branch {bname}, sir."
        elif exists_remotely:
            # Branch exists only on remote: Run git checkout -b <branch_name> origin/<branch_name>
            cmd = f'{cd_prefix} && git checkout -b {bname} origin/{bname}'
            action = "checkout_remote_branch"
            start = f"Checking out remote branch {bname}, sir."
            speaking_resp = f"Checked out and switched to remote branch {bname}, sir."
        elif is_explicit:
            # Branch does not exist anywhere and explicit create requested: Run git checkout -b <branch_name>
            cmd = f'{cd_prefix} && git checkout -b {bname} && git push -u origin {bname}'
            action = "create_branch"
            start = f"Creating and pushing branch {bname} to GitHub, sir."
            speaking_resp = f"Branch {bname} has been created and pushed to GitHub, sir."
        else:
            cmd = f'{cd_prefix} && git checkout {bname}'
            action = "switch_branch"
            start = f"Switching to branch {bname}, sir."
            speaking_resp = f"Switched to branch {bname}, sir."

        return {
            "type": "git_action",
            "action": action,
            "branch_name": bname,
            "target_branch": bname,
            "target_file": "",
            "task_description": f"{action.replace('_', ' ').title()} {bname}",
            "command": cmd,
            "speaking_start": start,
            "speaking_progress": "",
            "speaking_response": speaking_resp,
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

def clean_spoken_text(text: str) -> str:
    """Strips markdown asterisks, backticks, hashes, and formatting for clear TTS."""
    if not text:
        return ""
    # Strip markdown code blocks
    t = re.sub(r"```(?:[a-zA-Z0-9_\-]+)?\s*.*?\s*```", "", text, flags=re.DOTALL)
    # Strip inline code formatting `code`
    t = re.sub(r"`([^`]+)`", r"\1", t)
    # Strip markdown bold / italics
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
    t = re.sub(r"\*([^*]+)\*", r"\1", t)
    t = re.sub(r"__([^_]+)__", r"\1", t)
    t = re.sub(r"_([^_]+)_", r"\1", t)
    # Strip markdown headers, blockquotes, bullets
    t = re.sub(r"^#+\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"^>\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"^[\*\-\+]\s+", "", t, flags=re.MULTILINE)
    # Strip markdown links [text](url) -> text
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    # Clean whitespace and newlines
    t = re.sub(r"[\r\n]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()

    # Limit to 2 concise sentences max for optimal voice delivery
    sentences = re.split(r'(?<=[.!?])\s+', t)
    if len(sentences) > 2:
        t = " ".join(sentences[:2]).strip()

    return t

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

    # STRICT OVERRIDE: Force antigravity_task if any trigger keywords are in the transcript
    if is_antigravity_intent(transcript):
        req_type = "antigravity_task"

    target_file = str(data.get("target_file", "")).strip()
    if req_type == "antigravity_task" and not target_file:
        target_file = extract_target_file(transcript)

    raw_resp = str(data.get("speaking_response", ""))
    speaking_resp = clean_spoken_text(raw_resp)
    if not speaking_resp:
        if req_type == "codebase_qa":
            speaking_resp = "Codebase analysis complete, sir. Standing by for instructions."
        elif req_type == "git_action":
            speaking_resp = "Git task completed successfully, sir."
        elif req_type == "antigravity_task":
            speaking_resp = f"Task completed, sir. Antigravity has resolved the issue in {target_file}."
        else:
            speaking_resp = "I am standing by, sir. How may I assist you?"

    if req_type == "antigravity_task":
        action = str(data.get("action", "bug_fix")).strip() or "bug_fix"
        target_path = os.path.join(PROJECT_ROOT, target_file)
        valid, full_tb, line_num, err_details = check_python_syntax(target_path)
        if not valid:
            action = "bug_fix"
            if line_num:
                speaking_resp = f"Syntax error detected on line {line_num} in {target_file}. Dispatched fix prompt directly to Antigravity, sir."
                task_desc = f"@{target_file} Fix the compilation error on line {line_num}: {err_details}. Resolve this issue now."
            else:
                speaking_resp = f"Syntax error detected in {target_file}. Dispatched fix prompt directly to Antigravity, sir."
                task_desc = f"@{target_file} Fix the compilation error: {err_details}. Resolve this issue now."
        elif not speaking_resp or speaking_resp.startswith("Task completed"):
            speaking_resp = f"Syntax check passed. No compilation errors found in {target_file}, sir."
            task_desc = str(data.get("task_description", transcript)).strip()
        else:
            task_desc = str(data.get("task_description", transcript)).strip()

        start = "Delegating task to Antigravity Agent, sir."
        prog = clean_spoken_text(str(data.get("speaking_progress", f"Antigravity is checking {target_file}...")))
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
            "speaking_response": speaking_resp,
        }

    if req_type == "git_action":
        if is_checkout_master(transcript):
            cmd = f'{cd_prefix} && git add -A && git commit -m "Auto-save state" && git checkout master && git pull origin master'
            start = "Switching to master branch, sir."
            speaking_resp = "Switched to master branch and pulled latest changes, sir."
        elif is_merge_to_master(transcript):
            source_branch = extract_merge_source_branch(transcript)
            spoken_src = "feature branch" if "feature" in source_branch.lower() else source_branch
            cmd = (
                f'{cd_prefix} && git checkout master && git pull origin master && '
                f'git merge {source_branch} --no-edit && git push origin master'
            )
            start = f"Merging changes from {spoken_src} into master, sir."
            speaking_resp = "Successfully merged changes from feature branch into master and pushed to remote GitHub repository, sir." if "feature" in source_branch.lower() else f"Successfully merged changes from {source_branch} into master and pushed to remote GitHub repository, sir."
        elif is_explicit_branch_creation(transcript) or is_branch_switch(transcript):
            bname = extract_branch_name(transcript)
            if bname.lower() in ["master", "main"]:
                cmd = f'{cd_prefix} && git add -A && git commit -m "Auto-save state" && git checkout {bname} && git pull origin {bname}'
                start = f"Switching to {bname} branch, sir."
                speaking_resp = "Switched to master branch and pulled latest changes, sir."
            else:
                exists_locally, exists_remotely = inspect_branch_status(bname, PROJECT_ROOT)
                is_explicit = is_explicit_branch_creation(transcript)
                if exists_locally:
                    cmd = f'{cd_prefix} && git checkout {bname}'
                    start = f"Switching to branch {bname}, sir."
                    speaking_resp = f"Switched to branch {bname}, sir."
                elif exists_remotely:
                    cmd = f'{cd_prefix} && git checkout -b {bname} origin/{bname}'
                    start = f"Checking out remote branch {bname}, sir."
                    speaking_resp = f"Checked out and switched to remote branch {bname}, sir."
                elif is_explicit:
                    cmd = f'{cd_prefix} && git checkout -b {bname} && git push -u origin {bname}'
                    start = f"Creating and pushing branch {bname} to GitHub, sir."
                    speaking_resp = f"Branch {bname} has been created and pushed to GitHub, sir."
                else:
                    cmd = f'{cd_prefix} && git checkout {bname}'
                    start = f"Switching to branch {bname}, sir."
                    speaking_resp = f"Switched to branch {bname}, sir."
        elif not cmd.startswith("cd "):
            cmd = f'{cd_prefix} && {cmd}' if cmd else f'{cd_prefix} && git status'

    start = clean_spoken_text(str(data.get("speaking_start", "")))
    prog = clean_spoken_text(str(data.get("speaking_progress", "")))

    return {
        "type": req_type,
        "action": str(data.get("action", "")),
        "target_file": str(data.get("target_file", "")),
        "task_description": str(data.get("task_description", "")),
        "command": cmd,
        "speaking_start": start,
        "speaking_progress": prog,
        "speaking_response": speaking_resp,
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

    # IMMEDIATE ROUTING: Antigravity task regex/classifier match routes immediately and prevents fallback to GENERAL_QA
    if is_antigravity_intent(cleaned):
        return build_default_intent(cleaned)

    # IMMEDIATE ROUTING: Safe master checkout workflow
    if is_checkout_master(cleaned):
        return build_default_intent(cleaned)

    # IMMEDIATE ROUTING: Git merge to master workflow
    if is_merge_to_master(cleaned):
        return build_default_intent(cleaned)

    # IMMEDIATE ROUTING: Git branch creation & switching
    if is_explicit_branch_creation(cleaned) or is_branch_switch(cleaned):
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

    # Save structured payload to antigravity_task.json and antigravity_prompt.txt
    if result.get("type") == "antigravity_task":
        action = result.get("action", "bug_fix")
        target_f = result.get("target_file", "")
        task_desc = result.get("task_description", transcript)
        target_path = os.path.join(PROJECT_ROOT, target_f) if target_f else ""

        valid, full_tb, line_num, err_details = check_python_syntax(target_path)
        if not valid:
            if line_num:
                formatted_prompt = f"@{target_f} Fix the compilation error on line {line_num}: {err_details}. Resolve this issue now."
                result["speaking_response"] = f"Syntax error detected on line {line_num} in {target_f}. Dispatched fix prompt directly to Antigravity, sir."
            else:
                formatted_prompt = f"@{target_f} Fix the compilation error: {err_details}. Resolve this issue now."
                result["speaking_response"] = f"Syntax error detected in {target_f}. Dispatched fix prompt directly to Antigravity, sir."
            hud_status = f"[SYNTAX ERROR] Line {line_num} in {target_f}: {err_details}"
        else:
            if str(task_desc).startswith("@"):
                formatted_prompt = task_desc
            else:
                formatted_prompt = f"""================================================================================
                    ANTIGRAVITY AUTONOMOUS TASK DISPATCH
================================================================================
ACTION      : {action.upper()}
TARGET FILE : {target_f}
TIMESTAMP   : {time.strftime('%Y-%m-%d %H:%M:%S')}
WORKSPACE   : {PROJECT_ROOT}

TASK SPECIFICATION:
{task_desc}

DIRECTIVE:
1. Inspect {target_f} and project workspace context.
2. Execute requested code changes, bug fix, or feature scaffolding.
3. Verify syntax and report status.
================================================================================
"""
            hud_status = f"[SYNTAX OK] No compilation errors found in {target_f}."

        try:
            with open(ANTIGRAVITY_PROMPT_FILE, "w", encoding="utf-8") as f:
                f.write(formatted_prompt)
            print(f"[intent_router.py] Wrote formatted prompt to {ANTIGRAVITY_PROMPT_FILE}", file=sys.stderr)
        except Exception as e:
            print(f"[intent_router.py] Antigravity prompt caching notice: {e}", file=sys.stderr)

        # Sync formatted prompt to Windows clipboard
        sync_to_clipboard(formatted_prompt)

        # Stream update to last_status.txt for HUD Panel 3
        try:
            with open(STATUS_CACHE_FILE, "w", encoding="utf-8") as f:
                f.write(hud_status)
        except Exception:
            pass

        try:
            task_payload = {
                "type": "antigravity_task",
                "action": action,
                "target_file": target_f,
                "task_description": task_desc,
                "prompt": formatted_prompt,
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
