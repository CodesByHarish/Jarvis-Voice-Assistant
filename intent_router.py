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

def get_current_active_branch(repo_path: str = PROJECT_ROOT) -> str:
    """Inspects current active branch dynamically using git rev-parse --abbrev-ref HEAD."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        if proc.returncode == 0:
            b = proc.stdout.strip()
            if b and b != "HEAD":
                return b
    except Exception:
        pass
    return "master"

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
    if is_merge_action(t):
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
    if is_merge_action(t) or is_checkout_master(t):
        return False
    patterns = [
        r'\b(?:create|make|new)\s+(?:a\s+)?branch\b',
        r'\bcheckout\s+-b\b',
        r'\bbranch\s+(?:create|make|new)\b',
    ]
    return any(re.search(p, t) for p in patterns)

def is_delete_branch_action(transcript: str) -> bool:
    """Detects git branch deletion requests (e.g. 'delete branch foo', 'remove branch bar')."""
    t = transcript.lower().strip()
    return bool(re.search(r'\b(?:delete|remove)\s+(?:branch\s+)?([a-zA-Z0-9_\-\.\/]+)', t))

def extract_delete_branch(transcript: str) -> str:
    """Extracts target branch name to delete."""
    t = transcript.strip()
    m = re.search(r'\b(?:delete|remove)\s+(?:branch\s+)?([a-zA-Z0-9_\-\.\/]+)', t, re.IGNORECASE)
    if m:
        b = m.group(1).strip()
        if b.lower() not in ["the", "this", "my", "branch"]:
            return b
    return ""

def is_merge_action(transcript: str) -> bool:
    """Detects commands requesting merging, syncing, or integrating two branches."""
    t = transcript.lower().strip()
    if re.search(r'\b(?:merge|sync|integrate)\b.*?\b(?:in)?to\b', t):
        return True
    if re.search(r'\b(?:merge|sync)\s+(?:branch\s+)?[a-zA-Z0-9_\-\.\/]+\s+with\b', t):
        return True
    if re.search(r'\bupdate\s+.*?\s+with\s+.*?\s+changes\b', t):
        return True
    if re.search(r'\b(?:merge|sync)\s+(?:branch\s+)?[a-zA-Z0-9_\-\.\/]+\s+(?:in)?to\b', t):
        return True
    if re.search(r'\bmerge\s+(?:branch\s+)?([a-zA-Z0-9_\-\.\/]+)\b', t) and not any(w in t for w in ["conflict", "abort", "--abort"]):
        m_merge = re.search(r'\bmerge\s+(?:branch\s+)?([a-zA-Z0-9_\-\.\/]+)\b', t)
        if m_merge and m_merge.group(1).lower() not in ["the", "this", "my", "branch", "code", "changes"]:
            return True
    return False

def is_merge_to_master(transcript: str) -> bool:
    """Helper returning true if merge targets master."""
    if not is_merge_action(transcript):
        return False
    src, tgt = extract_merge_branches(transcript)
    return tgt.lower() in ["master", "main"]

def extract_merge_branches(transcript: str) -> tuple[str, str]:
    """
    Extracts (source_branch, target_branch) for git merge operations.
    e.g. 'merge feature into master' -> ('feature', 'master')
         'merge dev into feature' -> ('dev', 'feature')
         'merge feature with master' -> ('feature', 'master')
         'sync feature-branch to master' -> ('feature-branch', 'master')
         'update master branch with feature changes' -> ('feature', 'master')
    """
    t = transcript.strip()

    # 1. Pattern: "merge <source> into/to <target>"
    m1 = re.search(r'(?:merge|sync|integrate)\s+(?:branch\s+)?([a-zA-Z0-9_\-\.\/]+)(?:\s+branch)?\s+(?:in)?to\s+(?:branch\s+)?([a-zA-Z0-9_\-\.\/]+)', t, re.IGNORECASE)
    if m1:
        src = m1.group(1).strip()
        tgt = m1.group(2).strip()
        if src.lower() in ["the", "this", "current", "active"]:
            src = get_current_active_branch()
        return src, tgt

    # 2. Pattern: "merge <source> with <target>"
    m1_with = re.search(r'(?:merge|sync)\s+(?:branch\s+)?([a-zA-Z0-9_\-\.\/]+)(?:\s+branch)?\s+with\s+(?:branch\s+)?([a-zA-Z0-9_\-\.\/]+)', t, re.IGNORECASE)
    if m1_with:
        src = m1_with.group(1).strip()
        tgt = m1_with.group(2).strip()
        return src, tgt

    # 3. Pattern: "update <target> [branch] with <source> changes"
    m2 = re.search(r'update\s+(?:branch\s+)?([a-zA-Z0-9_\-\.\/]+)(?:\s+branch)?\s+with\s+(?:branch\s+)?([a-zA-Z0-9_\-\.\/]+)', t, re.IGNORECASE)
    if m2:
        tgt = m2.group(1).strip()
        src = m2.group(2).strip()
        if src.lower() in ["the", "this", "my"]:
            src = get_current_active_branch()
        return src, tgt

    # 4. Pattern: "merge into <target>"
    m3 = re.search(r'merge\s+(?:changes\s+)?(?:in)?to\s+(?:branch\s+)?([a-zA-Z0-9_\-\.\/]+)', t, re.IGNORECASE)
    if m3:
        tgt = m3.group(1).strip()
        active = get_current_active_branch()
        src = active if (active and active.lower() != tgt.lower()) else "feature-branch"
        return src, tgt

    # 5. Pattern: "merge <source>" (e.g. "merge feature")
    m4 = re.search(r'merge\s+(?:branch\s+)?([a-zA-Z0-9_\-\.\/]+)', t, re.IGNORECASE)
    if m4:
        src = m4.group(1).strip()
        if src.lower() not in ["the", "this", "my", "changes", "branch", "code", "into", "to", "with"]:
            active = get_current_active_branch()
            tgt = active if (active and active.lower() != src.lower()) else "master"
            return src, tgt

    # Fallback: active branch into master
    active = get_current_active_branch()
    src = active if (active and active.lower() not in ["master", "main"]) else "feature-branch"
    return src, "master"

def extract_merge_source_branch(transcript: str) -> str:
    """Wrapper returning source branch for merge."""
    src, _ = extract_merge_branches(transcript)
    return src

def is_pull_action(transcript: str) -> bool:
    """Detects commands requesting git pull from a specific branch or remote."""
    t = transcript.lower().strip()
    if is_merge_action(t):
        return False
    patterns = [
        r'\bpull\s+(?:from|origin|latest|code|changes)\b',
        r'\bgit\s+pull\b',
        r'\bpull\s+(?:branch\s+)?[a-zA-Z0-9_\-\.\/]+',
        r'\bpull\b',
    ]
    return any(re.search(p, t) for p in patterns)

def extract_pull_source_branch(transcript: str) -> str:
    """Extracts target branch to pull from (e.g. 'pull from master', 'pull from feature-branch')."""
    t = transcript.strip()
    m = re.search(r'\bpull\s+(?:latest\s+)?(?:code\s+|changes\s+)?(?:from\s+|origin\s+)?(?:branch\s+)?([a-zA-Z0-9_\-\.\/]+)', t, re.IGNORECASE)
    if m:
        b = m.group(1).strip()
        if b.lower() not in ["the", "my", "this", "changes", "code", "latest", "origin", "remote", "repo", "github"]:
            return b

    m2 = re.search(r'\bfrom\s+(?:branch\s+)?([a-zA-Z0-9_\-\.\/]+)', t, re.IGNORECASE)
    if m2:
        b2 = m2.group(1).strip()
        if b2.lower() not in ["the", "my", "this", "origin", "remote", "github"]:
            return b2

    if "master" in t.lower():
        return "master"
    if "feature-branch" in t.lower():
        return "feature-branch"
    if "feature" in t.lower():
        return "feature"
    if "updated" in t.lower():
        return "updated"

    active = get_current_active_branch()
    return active if active else "master"

def is_branch_switch(transcript: str) -> bool:
    """Detects general branch switching or checkout requests."""
    t = transcript.lower().strip()
    if is_merge_action(t) or is_checkout_master(t) or is_pull_action(t) or is_delete_branch_action(t):
        return False
    patterns = [
        r'\b(?:switch|checkout|go)\s+(?:in)?to\s+(?:branch\s+)?([a-zA-Z0-9_\-\.\/]+)',
        r'\b(?:switch|checkout)\s+branch\s+([a-zA-Z0-9_\-\.\/]+)',
    ]
    return any(re.search(p, t) for p in patterns)

def is_branch_creation(transcript: str) -> bool:
    """Detects git branch creation or switching requests (legacy wrapper)."""
    return is_explicit_branch_creation(transcript) or is_branch_switch(transcript)

def extract_commit_message(transcript: str) -> str:
    """Extracts custom commit message from user transcript if provided."""
    t = transcript.strip()
    patterns = [
        r'(?:commit|push)\s+(?:with\s+)?(?:the\s+)?message\s+[\'"]?([^\'"]+)[\'"]?',
        r'message\s+[\'"]?([^\'"]+)[\'"]?',
    ]
    for p in patterns:
        m = re.search(p, t, re.IGNORECASE)
        if m:
            msg = m.group(1).strip()
            msg = re.sub(r'\s+and\s+push.*$', '', msg, flags=re.IGNORECASE)
            msg = re.sub(r'[,.]?\s*sir\.?$', '', msg, flags=re.IGNORECASE).strip()
            if msg and len(msg) > 1:
                return msg
    return "Automated update via Jarvis"

def extract_push_target_branch(transcript: str) -> str:
    """Extracts target branch for git push, supporting specific branches like feature, master, updated."""
    t = transcript.strip()
    m = re.search(r'\bpush\s+(?:code\s+)?(?:to|into)\s+(?:origin\s+|remote\s+)?(?:branch\s+)?([a-zA-Z0-9_\-\.\/]+)', t, re.IGNORECASE)
    if m:
        b = m.group(1).strip()
        if b.lower() not in ["the", "my", "this", "github", "origin", "remote"]:
            return b
        elif b.lower() in ["github", "origin", "remote"]:
            m_sub = re.search(r'\b(?:github|origin|remote)\s+(?:branch\s+)?([a-zA-Z0-9_\-\.\/]+)', t, re.IGNORECASE)
            if m_sub and m_sub.group(1).lower() not in ["repo", "repository", "remote", "origin"]:
                return m_sub.group(1).strip()
            return "master"

    m2 = re.search(r'\bpush\s+branch\s+([a-zA-Z0-9_\-\.\/]+)', t, re.IGNORECASE)
    if m2:
        b2 = m2.group(1).strip()
        if b2.lower() not in ["the", "my", "this"]:
            return b2

    m3 = re.search(r'\bto\s+branch\s+([a-zA-Z0-9_\-\.\/]+)', t, re.IGNORECASE)
    if m3:
        b3 = m3.group(1).strip()
        if b3.lower() not in ["the", "my", "this"]:
            return b3

    if "master" in t.lower():
        return "master"
    if "feature-branch" in t.lower():
        return "feature-branch"
    if "feature" in t.lower():
        return "feature"
    if "updated" in t.lower():
        return "updated"

    active = get_current_active_branch()
    return active if active else "master"

def is_commit_or_push(transcript: str) -> bool:
    """Detects commands requesting git commit, push, or updating master."""
    t = transcript.lower().strip()
    if is_merge_action(t) or is_checkout_master(t) or is_pull_action(t) or is_delete_branch_action(t):
        return False
    patterns = [
        r'\b(?:commit|push)\b',
        r'\bpush\s+(?:code\s+)?to\s+github\b',
        r'\bupdate\s+master\b',
    ]
    return any(re.search(p, t) for p in patterns)

def is_status_or_log_action(transcript: str) -> bool:
    """Detects git status, diff, or log inquiries."""
    t = transcript.lower().strip()
    return bool(re.search(r'\b(?:git\s+status|status|changes|git\s+log|recent\s+commits|commit\s+history)\b', t))

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
  - For commit and push (e.g. "commit", "push", "push code to github", "update master"):
    command: cd "{PROJECT_ROOT}" && git add -A && git commit -m "Automated update via Jarvis" --allow-empty-message && git push origin master
    If user message provided: cd "{PROJECT_ROOT}" && git add -A && git commit -m "<user_message>" && git push origin master
    speaking_start: "Executing task: committing and pushing changes, sir."
    speaking_response: "Successfully committed and pushed all changes to GitHub, sir."
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

    # 2. Branch Deletion Workflow (e.g. "delete branch foo", "remove branch bar")
    if is_delete_branch_action(transcript):
        bname = extract_delete_branch(transcript)
        return {
            "type": "git_action",
            "action": "delete_branch",
            "branch_name": bname,
            "target_branch": bname,
            "target_file": "",
            "task_description": f"Delete branch {bname}",
            "command": f'{cd_prefix} && git branch -D {bname} && git push origin --delete {bname}',
            "speaking_start": f"Deleting branch {bname} from local and remote repository, sir.",
            "speaking_progress": "",
            "speaking_response": f"Branch {bname} has been deleted from local and remote repository, sir.",
        }

    # 3. Merging Branches Workflow (e.g. "merge feature into master", "merge dev into feature", "sync feature to master")
    if is_merge_action(transcript):
        src, tgt = extract_merge_branches(transcript)
        spoken_src = "feature branch" if "feature" in src.lower() else src
        spoken_tgt = "master branch" if "master" in tgt.lower() else tgt
        return {
            "type": "git_action",
            "action": "merge_branches",
            "source_branch": src,
            "target_branch": tgt,
            "target_file": "",
            "task_description": f"Merge {src} into {tgt} and push",
            "command": (
                f'{cd_prefix} && git checkout {tgt} && git pull origin {tgt} && '
                f'git merge {src} --no-edit && git push origin {tgt}'
            ),
            "speaking_start": f"Merging changes from {spoken_src} into {spoken_tgt}, sir.",
            "speaking_progress": "",
            "speaking_response": f"Successfully merged changes from {spoken_src} into {spoken_tgt} and pushed to remote GitHub repository, sir.",
        }

    # 4. Pulling from Specific Branch Workflow (e.g. "pull from master", "pull from feature", "pull origin master")
    if is_pull_action(transcript):
        src_b = extract_pull_source_branch(transcript)
        return {
            "type": "git_action",
            "action": "pull_branch",
            "source_branch": src_b,
            "target_branch": src_b,
            "target_file": "",
            "task_description": f"Pull latest changes from origin/{src_b}",
            "command": f'{cd_prefix} && git pull origin {src_b}',
            "speaking_start": f"Pulling latest changes from branch {src_b}, sir.",
            "speaking_progress": "",
            "speaking_response": f"Successfully pulled latest code from {src_b}, sir.",
        }

    # 5. Safe Master Checkout Workflow ("switch to master", "checkout master", "go to master branch")
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

    # 6. Branch Switching or Creation
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

    # 7. Git Commit and Push Pipeline
    if is_commit_or_push(transcript) or any(w in t for w in ["push", "commit", "repo", "github"]):
        commit_msg = extract_commit_message(transcript)
        target_branch = extract_push_target_branch(transcript)

        if commit_msg != "Automated update via Jarvis":
            cmd = f'{cd_prefix} && git add -A && git commit -m "{commit_msg}" && git push origin {target_branch}'
        else:
            cmd = f'{cd_prefix} && git add -A && git commit -m "Automated update via Jarvis" --allow-empty-message && git push origin {target_branch}'

        return {
            "type": "git_action",
            "action": "commit_and_push",
            "commit_message": commit_msg,
            "target_branch": target_branch,
            "target_file": "",
            "task_description": f"Git commit and push to {target_branch}",
            "command": cmd,
            "speaking_start": f"Executing task: committing and pushing changes to {target_branch}, sir.",
            "speaking_progress": "",
            "speaking_response": f"Successfully committed and pushed all changes to {target_branch}, sir.",
        }

    # 8. Git Status or Log
    if is_status_or_log_action(transcript):
        if any(w in t for w in ["log", "recent commits", "commit history"]):
            cmd = f'{cd_prefix} && git log -n 5 --oneline'
            action = "git_log"
            start = "Retrieving recent commit history, sir."
            resp = "Recent commit history retrieved, sir."
        else:
            cmd = f'{cd_prefix} && git status -s'
            action = "git_status"
            start = "Checking git status, sir."
            resp = "Repository status check complete, sir."

        return {
            "type": "git_action",
            "action": action,
            "target_file": "",
            "task_description": f"Git {action}",
            "command": cmd,
            "speaking_start": start,
            "speaking_progress": "",
            "speaking_response": resp,
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
        return build_default_intent(transcript)

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

    # IMMEDIATE ROUTING: Branch deletion
    if is_delete_branch_action(cleaned):
        return build_default_intent(cleaned)

    # IMMEDIATE ROUTING: Git merge branches (arbitrary two branches or into master)
    if is_merge_action(cleaned):
        return build_default_intent(cleaned)

    # IMMEDIATE ROUTING: Git pull from specific branch
    if is_pull_action(cleaned):
        return build_default_intent(cleaned)

    # IMMEDIATE ROUTING: Safe master checkout workflow
    if is_checkout_master(cleaned):
        return build_default_intent(cleaned)

    # IMMEDIATE ROUTING: Git branch creation & switching
    if is_explicit_branch_creation(cleaned) or is_branch_switch(cleaned):
        return build_default_intent(cleaned)

    # IMMEDIATE ROUTING: Git commit and push pipeline
    if is_commit_or_push(cleaned):
        return build_default_intent(cleaned)

    # IMMEDIATE ROUTING: Git status / log inquiry
    if is_status_or_log_action(cleaned):
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
