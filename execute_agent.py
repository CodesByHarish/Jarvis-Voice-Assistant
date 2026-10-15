#!/usr/bin/env python3
"""
Jarvis & Antigravity Autonomous Code Generation, Real Compilation & Hands-Free Bridge
Features:
- Forces VS Code / Antigravity window to absolute foreground before typing.
- Runs actual Python compilation checks: `python -m py_compile <target_file>`.
- Captures exact stdout/stderr tracebacks and line numbers.
- Logs real error output directly to `last_status.txt` for live HUD Panel 3 rendering.
- Hands-free automated input submission via PyAutoGUI & pyperclip directly into Antigravity chat.
- Dynamic voice confirmation for both syntax errors and clean passes.
"""

import sys
import os
import json
import time
import re
import threading
import subprocess
from dotenv import load_dotenv

# Auto-install and import dependencies
try:
    import pyperclip
    import pyautogui
    import pygetwindow as gw
    import win32gui
    import win32con
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "pyperclip", "pyautogui", "pygetwindow", "pywin32"], capture_output=True)
    import pyperclip
    import pyautogui
    import pygetwindow as gw
    import win32gui
    import win32con

load_dotenv()

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
TASK_FILE = os.path.join(PROJECT_ROOT, "antigravity_task.json")
PROMPT_FILE = os.path.join(PROJECT_ROOT, "antigravity_prompt.txt")
LOG_FILE = os.path.join(PROJECT_ROOT, "antigravity_log.txt")
STATUS_FILE = os.path.join(PROJECT_ROOT, "last_status.txt")
INTENT_FILE = os.path.join(PROJECT_ROOT, "last_intent.json")
SPEAK_SCRIPT = os.path.join(PROJECT_ROOT, "speak.py")

def append_hud_log(msg: str):
    """Appends timestamped telemetry log for HUD Panel 3 consumption."""
    timestamp = time.strftime("[%H:%M:%S]")
    line = f"{timestamp} {msg}\n"
    print(f"[execute_agent] {msg}")
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            f.write(msg)
    except Exception:
        pass

def speak_async(phrase: str):
    """Speaks phrase non-blockingly via speak.py."""
    if not phrase:
        return
    try:
        subprocess.Popen(
            [sys.executable, SPEAK_SCRIPT, phrase],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception as e:
        print(f"[execute_agent] Voice announcement notice: {e}", file=sys.stderr)

def bring_ide_to_foreground() -> bool:
    """
    Searches open windows for 'Jarvis', 'Antigravity', or 'Visual Studio Code',
    unminimizes, and brings the window to the absolute foreground.
    """
    try:
        import pygetwindow as gw
        wins = gw.getWindowsWithTitle('Jarvis') or gw.getWindowsWithTitle('Antigravity') or gw.getWindowsWithTitle('Visual Studio Code')
        if not wins:
            # Broader title match across all windows
            all_wins = gw.getAllWindows()
            wins = [w for w in all_wins if any(k.lower() in w.title.lower() for k in ['antigravity', 'visual studio code', 'jarvis', 'code'])]

        if wins:
            win = wins[0]
            print(f"[execute_agent] Found target window: '{win.title}'")
            if win.isMinimized:
                win.restore()
            try:
                win.activate()
            except Exception:
                pass

            # Win32 forceful foreground activation
            try:
                import win32gui
                import win32con
                hwnd = win._hWnd
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass

            time.sleep(0.5)
            return True
        else:
            # Fallback scan with win32gui
            try:
                import win32gui
                import win32con
                found = []
                def _cb(h, _):
                    if win32gui.IsWindowVisible(h):
                        t = win32gui.GetWindowText(h)
                        if any(k.lower() in t.lower() for k in ['jarvis', 'antigravity', 'visual studio code', 'code']):
                            found.append((h, t))
                    return True
                win32gui.EnumWindows(_cb, None)
                if found:
                    h, t = found[0]
                    print(f"[execute_agent] Found target window via win32gui: '{t}'")
                    win32gui.ShowWindow(h, win32con.SW_RESTORE)
                    win32gui.SetForegroundWindow(h)
                    time.sleep(0.5)
                    return True
            except Exception:
                pass

            print("[execute_agent] Notice: Antigravity / VS Code window not detected or already active.")
            return False
    except Exception as e:
        print(f"[execute_agent] Window activation notice: {e}", file=sys.stderr)
        return False

def run_real_compilation_check(filepath: str) -> tuple[bool, str, int | None, str]:
    """
    Runs actual `python -m py_compile <filepath>`.
    Captures exact stdout and stderr compilation tracebacks.
    Returns:
        (is_valid, full_traceback, line_number, error_details)
    """
    if not os.path.exists(filepath):
        return False, f"File does not exist: {os.path.basename(filepath)}", None, "File not found"

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

        # Extract line number (e.g. line 258)
        line_num = None
        m = re.search(r'line\s+(\d+)', err_output, re.IGNORECASE)
        if m:
            line_num = int(m.group(1))

        # Extract specific error line, e.g. "SyntaxError: invalid syntax"
        lines = [l.strip() for l in err_output.splitlines() if l.strip()]
        error_line = lines[-1] if lines else "SyntaxError: compilation failure"

        # Find offending code line if present
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

def submit_to_antigravity_hands_free(prompt_text: str):
    """
    Hands-free automated submission using PyAutoGUI:
    1. Brings VS Code / Antigravity window to the absolute foreground.
    2. Pauses 0.5s for window stability (pyautogui.PAUSE = 0.5).
    3. Copies prompt via pyperclip.copy().
    4. Triggers hotkey Ctrl+L to focus active Antigravity chat input widget.
    5. Pastes the clipboard contents using pyautogui.hotkey('ctrl', 'v').
    6. Presses Enter to submit automatically.
    """
    def _worker():
        try:
            import pyperclip
            import pyautogui

            pyautogui.FAILSAFE = False
            pyautogui.PAUSE = 0.5

            # 1. Bring VS Code window to foreground
            bring_ide_to_foreground()
            time.sleep(0.5)

            # 2. Copy prompt to clipboard
            pyperclip.copy(prompt_text)
            print(f"[execute_agent] Prompt copied to clipboard via pyperclip:\n{prompt_text}")

            # 3. Focus active Antigravity chat input widget ("Ask anything...")
            pyautogui.hotkey('ctrl', 'l')
            time.sleep(0.5)

            # 4. Paste clipboard contents
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.3)

            # 5. Press Enter to submit automatically
            pyautogui.press('enter')
            print("[execute_agent] Fix prompt hands-free submitted to Antigravity successfully.")
        except Exception as e:
            print(f"[execute_agent] Hands-free PyAutoGUI submission error: {e}", file=sys.stderr)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return thread

def generate_scaffold(target_file: str, task_desc: str) -> str:
    """Creates a production-grade template if creating a new script."""
    module_name = os.path.splitext(os.path.basename(target_file))[0].capitalize()
    return f'''#!/usr/bin/env python3
"""
{module_name} Module
Generated by Jarvis & Antigravity Autonomous Code Bridge
Task: {task_desc}
"""

import sys
import os
import time

def run():
    print("[{module_name}] Execution initialized.")
    # Implementation logic synthesized by Antigravity
    return True

if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
'''

def main():
    task_path = sys.argv[1] if len(sys.argv) > 1 else TASK_FILE
    if not os.path.exists(task_path):
        if os.path.exists(INTENT_FILE):
            task_path = INTENT_FILE
        else:
            append_hud_log(f"[ANTIGRAVITY] Task payload {os.path.basename(task_path)} not found.")
            sys.exit(1)

    try:
        with open(task_path, "r", encoding="utf-8") as f:
            task = json.load(f)
    except Exception as e:
        append_hud_log(f"[ANTIGRAVITY] Failed to parse task payload: {e}")
        sys.exit(1)

    action = task.get("action", "bug_fix")
    target_rel = task.get("target_file", "speak.py")
    task_desc = task.get("task_description", "")
    target_path = os.path.join(PROJECT_ROOT, target_rel)

    # If target file doesn't exist and action is code generation, scaffold it
    if not os.path.exists(target_path) and action == "code_generation":
        append_hud_log(f"[ANTIGRAVITY] Target does not exist. Synthesizing new module scaffold: {target_rel}")
        scaffold_code = generate_scaffold(target_rel, task_desc)
        with open(target_path, "w", encoding="utf-8") as sf:
            sf.write(scaffold_code)

    # 1. RUN REAL PYTHON COMPILATION CHECK
    append_hud_log(f"[ANTIGRAVITY] Running real compilation check: python -m py_compile {target_rel}...")
    valid, full_traceback, line_num, err_details = run_real_compilation_check(target_path)

    if not valid:
        # REAL SYNTAX ERROR DETECTED
        line_str = f" on line {line_num}" if line_num else ""
        error_log = f"SyntaxError detected{line_str} in {target_rel}: {err_details}"
        append_hud_log(f"[SYNTAX ERROR] {error_log}")

        # Construct exact issue fix prompt
        if line_num:
            fix_prompt = f"@{target_rel} Fix the compilation error on line {line_num}: {err_details}. Resolve this issue now."
        else:
            fix_prompt = f"@{target_rel} Fix the compilation error: {err_details}. Resolve this issue now."

        # Write prompt to antigravity_prompt.txt
        try:
            with open(PROMPT_FILE, "w", encoding="utf-8") as pf:
                pf.write(fix_prompt)
            print(f"[execute_agent] Wrote fix prompt to {PROMPT_FILE}")
        except Exception as e:
            print(f"[execute_agent] Prompt write error: {e}", file=sys.stderr)

        # Hands-free automated input submission via PyAutoGUI & pyperclip (brings VS Code to front first)
        t = submit_to_antigravity_hands_free(fix_prompt)

        # Dynamic voice confirmation for syntax failure
        if line_num:
            speaking_response = f"Syntax error detected on line {line_num} in {target_rel}. Dispatched fix prompt directly to Antigravity, sir."
        else:
            speaking_response = f"Syntax error detected in {target_rel}. Dispatched fix prompt directly to Antigravity, sir."

        append_hud_log(f"[ANTIGRAVITY] {speaking_response}")
        speak_async(speaking_response)

        # Update antigravity_task.json
        task["status"] = "dispatched"
        task["syntax_valid"] = False
        task["line_number"] = line_num
        task["error_details"] = err_details
        task["error_traceback"] = full_traceback
        task["prompt"] = fix_prompt
        task["speaking_response"] = speaking_response
        task["updated_at"] = time.time()
        try:
            with open(TASK_FILE, "w", encoding="utf-8") as f:
                json.dump(task, f, indent=2)
        except Exception:
            pass

        # Update last_intent.json for workflow and speak.py consistency
        try:
            if os.path.exists(INTENT_FILE):
                with open(INTENT_FILE, "r", encoding="utf-8") as inf:
                    idat = json.load(inf)
                idat["speaking_response"] = speaking_response
                with open(INTENT_FILE, "w", encoding="utf-8") as inf:
                    json.dump(idat, inf, indent=2)
        except Exception:
            pass

        # Wait for PyAutoGUI foreground bring + typing actions to finish before exiting
        t.join(timeout=3.0)

        print(json.dumps({
            "type": "antigravity_task",
            "status": "dispatched",
            "syntax_valid": False,
            "line_number": line_num,
            "speaking_response": speaking_response
        }))
        sys.exit(0)

    else:
        # REAL COMPILATION SUCCEEDED CLEANLY
        success_msg = f"Syntax check passed. No compilation errors found in {target_rel}, sir."
        append_hud_log(f"[SYNTAX OK] {success_msg}")

        # Construct prompt for Antigravity session if explicit task was requested
        if str(task_desc).startswith("@"):
            task_prompt = task_desc
        elif task_desc and "bug" in task_desc.lower():
            task_prompt = f"@{target_rel} {task_desc}. Inspect the file and resolve any issues."
        else:
            task_prompt = f"@{target_rel} Verify and inspect {target_rel}."

        try:
            with open(PROMPT_FILE, "w", encoding="utf-8") as pf:
                pf.write(task_prompt)
        except Exception:
            pass

        # Hands-free automated input submission via PyAutoGUI & pyperclip (brings VS Code to front first)
        t = submit_to_antigravity_hands_free(task_prompt)

        # Dynamic voice confirmation for clean pass
        speaking_response = success_msg
        speak_async(speaking_response)

        # Update antigravity_task.json
        task["status"] = "completed"
        task["syntax_valid"] = True
        task["speaking_response"] = speaking_response
        task["updated_at"] = time.time()
        try:
            with open(TASK_FILE, "w", encoding="utf-8") as f:
                json.dump(task, f, indent=2)
        except Exception:
            pass

        # Update last_intent.json
        try:
            if os.path.exists(INTENT_FILE):
                with open(INTENT_FILE, "r", encoding="utf-8") as inf:
                    idat = json.load(inf)
                idat["speaking_response"] = speaking_response
                with open(INTENT_FILE, "w", encoding="utf-8") as inf:
                    json.dump(idat, inf, indent=2)
        except Exception:
            pass

        # Wait for PyAutoGUI typing actions to complete before exiting
        t.join(timeout=3.0)

        print(json.dumps({
            "type": "antigravity_task",
            "status": "completed",
            "syntax_valid": True,
            "speaking_response": speaking_response
        }))
        sys.exit(0)

if __name__ == "__main__":
    main()
