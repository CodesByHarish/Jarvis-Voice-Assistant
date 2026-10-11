#!/usr/bin/env python3
"""
Jarvis Git Command Execution Module
Reads the validated action from last_intent.json and executes the CLI command inside TARGET_REPO_PATH.
Exits with the process return code (0 for success, non-zero for failure).
"""

import sys
import os
import json
import subprocess
from dotenv import load_dotenv

load_dotenv()

def main():
    intent_file = sys.argv[1] if len(sys.argv) > 1 else "last_intent.json"
    if not os.path.exists(intent_file):
        print(f"[execute_git.py] Error: {intent_file} does not exist.", file=sys.stderr)
        sys.exit(1)

    try:
        with open(intent_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[execute_git.py] Invalid intent JSON: {e}", file=sys.stderr)
        sys.exit(1)

    command = data.get("command", "git status").strip()
    target_repo = os.getenv("TARGET_REPO_PATH", ".").strip()

    if not command:
        command = "git status"

    print(f"[Jarvis Executing]: '{command}' in '{target_repo}'")
    
    # Execute the command in the target repository directory
    try:
        proc = subprocess.run(command, shell=True, cwd=target_repo)
        sys.exit(proc.returncode)
    except Exception as e:
        print(f"[execute_git.py] Execution error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
