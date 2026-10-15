#!/usr/bin/env python3
"""
Jarvis Git Command Execution & Automated Branch Sync Module
Executes validated CLI actions inside the project root directory.
Handles automated merging and syncing from feature branches to master,
dynamically retrieves active branches, handles merge conflicts with graceful abort,
and reports telemetry back to HUD Panel 3 and speech synthesizer.
"""

import sys
import os
import json
import re
import subprocess
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Ensure GitHub CLI and Git are in PATH
GH_PATH = r"C:\Program Files\GitHub CLI"
if os.path.exists(GH_PATH) and GH_PATH not in os.environ.get("PATH", ""):
    os.environ["PATH"] = GH_PATH + os.pathsep + os.environ.get("PATH", "")

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

def get_current_branch(repo_path: str) -> str:
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
    return "feature-branch"

def update_intent_response(intent_file: str, speaking_response: str = None, speaking_error: str = None, speaking_success: str = None):
    """Updates intent file with dynamic spoken replies."""
    try:
        if os.path.exists(intent_file):
            with open(intent_file, "r", encoding="utf-8") as f:
                idat = json.load(f)
            if speaking_response:
                idat["speaking_response"] = speaking_response
            if speaking_error:
                idat["speaking_error"] = speaking_error
            if speaking_success:
                idat["speaking_success"] = speaking_success
            with open(intent_file, "w", encoding="utf-8") as f:
                json.dump(idat, f, indent=2)
    except Exception:
        pass

def handle_merge_to_master(target_repo: str, intent_file: str, status_file: str, data: dict):
    """
    Executes sequential Git merge & push to master pipeline:
    1. Dynamically inspects current active branch using `git rev-parse --abbrev-ref HEAD`.
    2. Runs `git checkout master`.
    3. Runs `git pull origin master`.
    4. Runs `git merge <source_branch> --no-edit`.
       - On conflict: runs `git merge --abort`, logs [GIT ERROR] Merge conflict detected,
         sets speaking_response and speaking_error, and exits 1.
    5. Runs `git push origin master`.
    6. Sets speaking_response and logs [GIT SUCCESS].
    """
    current_branch = get_current_branch(target_repo)
    if current_branch and current_branch.lower() not in ["master", "main"]:
        source_branch = current_branch
    else:
        source_branch = data.get("source_branch", "feature-branch")

    spoken_branch = "feature branch" if "feature" in source_branch.lower() else source_branch
    print(f"[execute_git.py] Starting merge pipeline: merging '{source_branch}' into master in '{target_repo}'")

    # Step 1: Checkout master
    print("[execute_git.py] Step 1: git checkout master")
    res_co = subprocess.run(["git", "checkout", "master"], cwd=target_repo, capture_output=True, text=True)
    if res_co.returncode != 0:
        err = res_co.stderr.strip() or res_co.stdout.strip()
        print(f"[execute_git.py] Checkout master failed: {err}", file=sys.stderr)
        with open(status_file, "w", encoding="utf-8") as f:
            f.write(f"[GIT ERROR] Failed to checkout master: {err}")
        update_intent_response(intent_file, speaking_error=f"Failed to checkout master branch: {err[:80]}")
        sys.exit(res_co.returncode)

    # Step 2: Pull origin master
    print("[execute_git.py] Step 2: git pull origin master")
    res_pull = subprocess.run(["git", "pull", "origin", "master"], cwd=target_repo, capture_output=True, text=True)
    if res_pull.returncode != 0:
        print(f"[execute_git.py] Note on pull origin master: {res_pull.stderr.strip()}")

    # Step 3: Merge source branch --no-edit
    print(f"[execute_git.py] Step 3: git merge {source_branch} --no-edit")
    res_merge = subprocess.run(["git", "merge", source_branch, "--no-edit"], cwd=target_repo, capture_output=True, text=True)
    if res_merge.returncode != 0:
        merge_out = (res_merge.stderr + " " + res_merge.stdout).lower()
        if "conflict" in merge_out or "automatic merge failed" in merge_out:
            # Merge conflict occurred: abort gracefully
            print("[execute_git.py] Merge conflict detected. Executing git merge --abort", file=sys.stderr)
            subprocess.run(["git", "merge", "--abort"], cwd=target_repo, capture_output=True, text=True)

            conflict_branch = "feature-branch" if "feature" in source_branch.lower() else source_branch
            conflict_msg = f"Merge conflict detected while merging {conflict_branch} into master, sir. Manual resolution required."
            with open(status_file, "w", encoding="utf-8") as f:
                f.write("[GIT ERROR] Merge conflict detected\n")

            update_intent_response(intent_file, speaking_response=conflict_msg, speaking_error=conflict_msg)
            print(f"[execute_git.py] {conflict_msg}", file=sys.stderr)
            sys.exit(1)
        else:
            # Other merge error: abort gracefully
            subprocess.run(["git", "merge", "--abort"], cwd=target_repo, capture_output=True, text=True)
            err = res_merge.stderr.strip() or res_merge.stdout.strip()
            with open(status_file, "w", encoding="utf-8") as f:
                f.write(f"[GIT ERROR] {err}")
            update_intent_response(intent_file, speaking_error=f"Merge failed: {err[:80]}")
            sys.exit(res_merge.returncode)

    # Step 4: Push to origin master
    print("[execute_git.py] Step 4: git push origin master")
    res_push = subprocess.run(["git", "push", "origin", "master"], cwd=target_repo, capture_output=True, text=True)
    if res_push.returncode != 0:
        err = res_push.stderr.strip() or res_push.stdout.strip()
        print(f"[execute_git.py] Push origin master failed: {err}", file=sys.stderr)
        with open(status_file, "w", encoding="utf-8") as f:
            f.write(f"[GIT ERROR] Failed to push merged master to origin: {err}")
        update_intent_response(intent_file, speaking_error=f"Merge succeeded but push to master failed: {err[:80]}")
        sys.exit(res_push.returncode)

    # Step 5: Successful completion
    success_resp = "Successfully merged changes from feature branch into master and pushed to remote GitHub repository, sir."
    with open(status_file, "w", encoding="utf-8") as f:
        f.write(f"[GIT SUCCESS] {success_resp}")

    update_intent_response(intent_file, speaking_response=success_resp, speaking_success=success_resp)
    print(f"[execute_git.py] {success_resp}")
    sys.exit(0)

def handle_checkout_master(target_repo: str, intent_file: str, status_file: str, data: dict):
    """
    Clean Switch to Master Workflow:
    1. Inspects modified tracked files using `git status --porcelain`.
    2. If uncommitted changes exist in code files (like .py files):
       auto-commits them first with message `[Auto-save before branch switch]`.
    3. Runs `git checkout master`.
    4. Runs `git pull origin master`.
    5. Does NOT run `git stash pop` after checkout, avoiding restoring outdated state across branches.
    6. Confirms speech: "Switched to master branch and pulled latest changes, sir."
    """
    print(f"[execute_git.py] Clean switch to master workflow starting in '{target_repo}'")

    # Step 1: Check for modified tracked files
    res_status = subprocess.run(["git", "status", "--porcelain"], cwd=target_repo, capture_output=True, text=True)
    status_out = res_status.stdout.strip()

    if status_out:
        print(f"[execute_git.py] Detected uncommitted changes before branch switch:\n{status_out}")
        subprocess.run(["git", "add", "-A"], cwd=target_repo, capture_output=True, text=True)
        res_commit = subprocess.run(["git", "commit", "-m", "[Auto-save before branch switch]"], cwd=target_repo, capture_output=True, text=True)
        commit_log = res_commit.stdout.strip() or res_commit.stderr.strip()
        print(f"[execute_git.py] Auto-saved state before branch switch: {commit_log}")
    else:
        print("[execute_git.py] Working tree is clean. Proceeding directly with checkout.")

    # Step 2: git checkout master
    print("[execute_git.py] Step 2: git checkout master")
    res_co = subprocess.run(["git", "checkout", "master"], cwd=target_repo, capture_output=True, text=True)
    if res_co.returncode != 0:
        err = res_co.stderr.strip() or res_co.stdout.strip()
        print(f"[execute_git.py] Checkout master failed: {err}", file=sys.stderr)
        with open(status_file, "w", encoding="utf-8") as f:
            f.write(f"[GIT ERROR] Checkout master failed: {err}")
        fail_msg = f"Failed to checkout master branch, sir: {err}"
        update_intent_response(intent_file, speaking_response=fail_msg, speaking_error=fail_msg)
        sys.exit(res_co.returncode)

    # Step 3: git pull origin master
    print("[execute_git.py] Step 3: git pull origin master")
    res_pull = subprocess.run(["git", "pull", "origin", "master"], cwd=target_repo, capture_output=True, text=True)
    if res_pull.returncode != 0:
        pull_err = res_pull.stderr.strip() or res_pull.stdout.strip()
        print(f"[execute_git.py] Pull origin master notice: {pull_err}", file=sys.stderr)

    # Step 4: Spoken confirmation (NO git stash pop)
    success_resp = "Switched to master branch and pulled latest changes, sir."
    with open(status_file, "w", encoding="utf-8") as f:
        f.write(f"[GIT SUCCESS] {success_resp}")

    update_intent_response(intent_file, speaking_response=success_resp, speaking_success=success_resp)
    print(f"[execute_git.py] {success_resp}")
    sys.exit(0)

def handle_branch_checkout(target_repo: str, intent_file: str, status_file: str, data: dict):
    """
    Executes branch switching or creation respecting local and remote inspection:
    1. Do NOT use -b when switching to an existing branch like master or main.
    2. Inspect using `git branch --list <branch_name>`:
       - If exists locally: git checkout <branch_name>
       - If exists only on remote: git checkout -b <branch_name> origin/<branch_name>
       - If does not exist anywhere and explicit creation requested: git checkout -b <branch_name> (and push)
    3. Handles errors gracefully, capturing stderr and speaking failure reason out loud.
    """
    bname = str(data.get("branch_name", "")).strip()
    command = str(data.get("command", "")).strip()
    action = str(data.get("action", "")).strip()

    if not bname:
        m = re.search(r'git checkout (?:-b\s+)?([a-zA-Z0-9_\-\.\/]+)', command)
        if m:
            bname = m.group(1).strip()
        else:
            bname = "master"

    # Master/main safe checkout
    if bname.lower() in ["master", "main"]:
        handle_checkout_master(target_repo, intent_file, status_file, data)
        return

    # Auto-commit tracked changes before switching branch if any exist
    res_status = subprocess.run(["git", "status", "--porcelain"], cwd=target_repo, capture_output=True, text=True)
    if res_status.stdout.strip():
        subprocess.run(["git", "add", "-A"], cwd=target_repo, capture_output=True, text=True)
        res_commit = subprocess.run(["git", "commit", "-m", "[Auto-save before branch switch]"], cwd=target_repo, capture_output=True, text=True)
        print(f"[execute_git.py] Auto-saved state before branch checkout: {res_commit.stdout.strip() or res_commit.stderr.strip()}")
    exists_locally, exists_remotely = inspect_branch_status(bname, target_repo)
    explicit_create = (action == "create_branch")
    print(f"[execute_git.py] Branch '{bname}' status: local={exists_locally}, remote={exists_remotely}, explicit_create={explicit_create}")

    if exists_locally:
        run_cmd = f"git checkout {bname}"
        success_msg = f"Switched to branch {bname}, sir."
    elif exists_remotely:
        run_cmd = f"git checkout -b {bname} origin/{bname}"
        success_msg = f"Checked out and switched to remote branch {bname}, sir."
    elif explicit_create:
        run_cmd = f"git checkout -b {bname} && git push -u origin {bname}"
        success_msg = f"Branch {bname} has been created and pushed to GitHub, sir."
    else:
        run_cmd = f"git checkout {bname}"
        success_msg = f"Switched to branch {bname}, sir."

    print(f"[execute_git.py] Executing: {run_cmd}")
    proc = subprocess.run(run_cmd, shell=True, cwd=target_repo, capture_output=True, text=True)

    if proc.returncode != 0:
        err = proc.stderr.strip() or proc.stdout.strip() or f"Checkout failed with exit code {proc.returncode}"
        print(f"[execute_git.py] Checkout failed: {err}", file=sys.stderr)
        with open(status_file, "w", encoding="utf-8") as f:
            f.write(f"[GIT ERROR] Checkout failed: {err}")
        fail_msg = f"Failed to switch to branch {bname}, sir: {err}"
        update_intent_response(intent_file, speaking_response=fail_msg, speaking_error=fail_msg)
        sys.exit(proc.returncode)

    with open(status_file, "w", encoding="utf-8") as f:
        f.write(f"[GIT SUCCESS] {success_msg}")

    update_intent_response(intent_file, speaking_response=success_msg, speaking_success=success_msg)
    print(f"[execute_git.py] {success_msg}")
    sys.exit(0)

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

    target_repo = os.getenv("TARGET_REPO_PATH", PROJECT_ROOT).strip()
    if target_repo == ".":
        target_repo = PROJECT_ROOT
    else:
        target_repo = os.path.abspath(target_repo)

    status_file = os.path.join(PROJECT_ROOT, "last_status.txt")
    action = data.get("action", "")
    command = data.get("command", "git status").strip()

    # Handle Safe Master Checkout Workflow
    if action == "checkout_master" or (
        ("checkout master" in command.lower() or "switch to master" in command.lower())
        and "merge" not in command.lower()
    ):
        handle_checkout_master(target_repo, intent_file, status_file, data)

    # Handle Automated Merge & Push to Master Workflow
    if action == "merge_to_master" or ("merge" in command.lower() and "master" in command.lower()):
        handle_merge_to_master(target_repo, intent_file, status_file, data)

    # Handle Branch Checkout / Switching / Creation
    if (
        action in ["switch_branch", "checkout_branch", "create_branch", "checkout_remote_branch"]
        or "checkout" in command.lower()
    ):
        handle_branch_checkout(target_repo, intent_file, status_file, data)

    # Standard Git execution fallback
    print(f"[Jarvis Executing]: '{command}' in '{target_repo}'")

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
            update_intent_response(intent_file, speaking_error=f"Git operation failed, sir: {err_details[:80]}")
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
