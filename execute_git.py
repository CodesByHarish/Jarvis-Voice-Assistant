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
    status_file = os.path.join(PROJECT_ROOT, "last_status.txt")

    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=target_repo,
            env=os.environ,
            capture_output=True,
            text=True
        )
        print(f"[execute_git.py] Process finished with exit code {proc.returncode}")
        if proc.stdout:
            print(f"[execute_git.py] Output:\n{proc.stdout.strip()}")
        if proc.stderr:
            print(f"[execute_git.py] Notice/Stderr:\n{proc.stderr.strip()}", file=sys.stderr)

        if proc.returncode != 0:
            err_details = proc.stderr.strip() or proc.stdout.strip() or f"Execution failed with code {proc.returncode}"
            print(f"[execute_git.py] Git execution FAILED: {err_details}", file=sys.stderr)
            try:
                with open(status_file, "w", encoding="utf-8") as f:
                    f.write(f"[GIT ERROR] {err_details}")
            except Exception:
                pass
            try:
                if os.path.exists(intent_file):
                    with open(intent_file, "r", encoding="utf-8") as inf:
                        idat = json.load(inf)
                    idat["speaking_error"] = f"Git operation failed, sir: {err_details[:80]}"
                    with open(intent_file, "w", encoding="utf-8") as inf:
                        json.dump(idat, inf, indent=2)
            except Exception:
                pass
            sys.exit(proc.returncode)

        # Execution succeeded
        try:
            with open(status_file, "w", encoding="utf-8") as f:
                f.write(f"[GIT SUCCESS] {data.get('speaking_response', 'Git action completed.')}")
        except Exception:
            pass
        sys.exit(0)
    except Exception as e:
        print(f"[execute_git.py] Execution error: {e}", file=sys.stderr)
        try:
            with open(status_file, "w", encoding="utf-8") as f:
                f.write(f"[GIT ERROR] {e}")
        except Exception:
            pass
        sys.exit(1)

if __name__ == "__main__":
    main()
