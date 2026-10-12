#!/usr/bin/env python3
"""
Jarvis Git Command Execution Module
Executes validated CLI actions inside the project root directory.
Guarantees execution in the project directory regardless of caller CWD,
auto-injects GitHub CLI path, and skips execution for general QA queries.
"""

import sys
import os
import json
import subprocess
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Ensure GitHub CLI and Git are in PATH
GH_PATH = r"C:\Program Files\GitHub CLI"
if os.path.exists(GH_PATH) and GH_PATH not in os.environ.get("PATH", ""):
    os.environ["PATH"] = GH_PATH + os.pathsep + os.environ.get("PATH", "")

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

    command = data.get("command", "git status").strip()
    target_repo = os.getenv("TARGET_REPO_PATH", PROJECT_ROOT).strip()
    if target_repo == ".":
        target_repo = PROJECT_ROOT
    else:
        target_repo = os.path.abspath(target_repo)

    print(f"[Jarvis Executing]: '{command}' in '{target_repo}'")
    
    try:
        proc = subprocess.run(command, shell=True, cwd=target_repo, env=os.environ)
        sys.exit(proc.returncode)
    except Exception as e:
        print(f"[execute_git.py] Execution error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
