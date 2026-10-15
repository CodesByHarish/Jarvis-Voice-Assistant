#!/usr/bin/env python3
"""
Jarvis Git Command Execution Module
Executes validated CLI actions inside the project root directory.
Guarantees execution in the project directory regardless of caller CWD,
auto-injects GitHub CLI path, normalizes commands, and handles errors gracefully.
"""

import sys
import os
import re
import json
import subprocess
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
STATUS_FILE = os.path.join(PROJECT_ROOT, "last_status.txt")

# Ensure GitHub CLI and Git are in PATH
GH_PATH = r"C:\Program Files\GitHub CLI"
if os.path.exists(GH_PATH) and GH_PATH not in os.environ.get("PATH", ""):
    os.environ["PATH"] = GH_PATH + os.pathsep + os.environ.get("PATH", "")

def set_hud_status(status_text: str):
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            f.write(status_text.strip() + "\n")
    except Exception:
        pass

def sanitize_git_command(command: str) -> str:
    # 1. Strip any leading cd ... && so execution is guaranteed to happen in target_repo
    clean_cmd = re.sub(r'^\s*cd\s+("[^"]+"|[^\s&]+)\s*&&\s*', '', command, flags=re.IGNORECASE).strip()

    # 2. Prevent git commit from failing the whole chain if nothing changed
    # e.g., git commit -m "..." && -> (git commit -m "..." || echo No changes to commit) &&
    def make_commit_resilient(match):
        part = match.group(0).rstrip('& ').strip()
        if '||' not in part:
            return f'({part} || echo No changes to commit) && '
        return match.group(0)

    clean_cmd = re.sub(r'git commit -m\s+(?:"[^"]*"|\'[^\']*\')\s*&&\s*', make_commit_resilient, clean_cmd)

    # 3. Clean gh repo create repo names with spaces: "Jarvis 2.0" -> "Jarvis-2.0"
    def sanitize_repo_name(match):
        prefix = match.group(1)
        name = match.group(2).replace(" ", "-")
        return f'{prefix}"{name}"'

    clean_cmd = re.sub(r'(gh repo create\s+)"([^"]+)"', sanitize_repo_name, clean_cmd)

    return clean_cmd

def main():
    intent_file = sys.argv[1] if len(sys.argv) > 1 else os.path.join(PROJECT_ROOT, "last_intent.json")
    if not os.path.exists(intent_file):
        print(f"[execute_git.py] Error: {intent_file} does not exist.", file=sys.stderr)
        sys.exit(1)

    try:
        with open(intent_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[execute_git.py] Invalid intent JSON: {e}", file=sys.stderr)
        sys.exit(1)

    # Delegate to execute_agent if Antigravity task
    if data.get("type") == "antigravity_task":
        print("[execute_git.py] Antigravity task detected; delegating to execute_agent.py.")
        agent_script = os.path.join(PROJECT_ROOT, "execute_agent.py")
        proc = subprocess.run([sys.executable, agent_script], cwd=PROJECT_ROOT)
        sys.exit(proc.returncode)

    # Bypass if query is General QA or Codebase QA
    if data.get("type") in ["general_qa", "codebase_qa"]:
        print("[execute_git.py] QA query detected; bypassing Git CLI.")
        sys.exit(0)

    raw_command = data.get("command", "git status").strip()
    target_repo = os.getenv("TARGET_REPO_PATH", PROJECT_ROOT).strip()
    if target_repo == ".":
        target_repo = PROJECT_ROOT
    else:
        target_repo = os.path.abspath(target_repo)

    command = sanitize_git_command(raw_command)
    print(f"[Jarvis Executing]: '{command}' in '{target_repo}'")
    set_hud_status(f"Executing: {command}")
    
    try:
        proc = subprocess.run(command, shell=True, cwd=target_repo, env=os.environ)
        if proc.returncode == 0:
            set_hud_status(f"Completed: {command}")
        else:
            set_hud_status(f"Failed (code {proc.returncode}): {command}")
        sys.exit(proc.returncode)
    except Exception as e:
        print(f"[execute_git.py] Execution error: {e}", file=sys.stderr)
        set_hud_status(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
