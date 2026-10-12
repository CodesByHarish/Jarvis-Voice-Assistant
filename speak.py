#!/usr/bin/env python3
"""
Jarvis Asynchronous Queued Speech Synthesis Module
Features:
- Completely non-blocking CLI: returns in <20ms while speech plays in the background.
- Queue-based sequential playback: consecutive announcements ("Listening..." -> "Executing..." -> "Completed...")
  never overlap, clip, or collide.
- Windows PowerShell SpeechSynthesizer with pyttsx3 fallback.
- Special flags: --file <path>, --intent-start, --intent-success, --intent-error.
"""

import sys
import os
import time
import json
import subprocess

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
QUEUE_FILE = os.path.join(PROJECT_ROOT, "speech_queue.txt")
LOCK_FILE = os.path.join(PROJECT_ROOT, "speech.lock")
INTENT_FILE = os.path.join(PROJECT_ROOT, "last_intent.json")

def speak_direct(text: str):
    """Speaks text using PowerShell System.Speech with fallback to pyttsx3."""
    if not text or not text.strip():
        return

    print(f"[Jarvis Speaking]: {text.strip()}")
    escaped = text.strip().replace("'", "''").replace('"', '""')
    ps_cmd = (
        f"Add-Type -AssemblyName System.Speech; "
        f"$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$synth.Rate = 0; "
        f"$synth.Speak('{escaped}')"
    )

    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=25,
        )
        if proc.returncode == 0:
            return
    except Exception as e:
        print(f"[speak.py] PowerShell synth note: {e}", file=sys.stderr)

    # Fallback to pyttsx3
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty("rate", 175)
        engine.say(text.strip())
        engine.runAndWait()
    except Exception as e:
        print(f"[speak.py] pyttsx3 fallback note: {e}", file=sys.stderr)

def run_worker():
    """Background worker process that drains the speech queue sequentially."""
    # Write PID to lock file
    try:
        with open(LOCK_FILE, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass

    try:
        while True:
            # Read first item from queue
            phrase = None
            if os.path.exists(QUEUE_FILE):
                try:
                    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                        lines = [line.strip() for line in f if line.strip()]
                    if lines:
                        phrase = lines[0]
                        # Write remaining back
                        with open(QUEUE_FILE, "w", encoding="utf-8") as f:
                            for remaining in lines[1:]:
                                f.write(remaining + "\n")
                except Exception:
                    time.sleep(0.05)
                    continue

            if phrase:
                speak_direct(phrase)
                time.sleep(0.15)
            else:
                # No more items; exit worker
                break
    finally:
        # Clean up lock file
        try:
            if os.path.exists(LOCK_FILE):
                os.remove(LOCK_FILE)
        except Exception:
            pass

def is_worker_active() -> bool:
    """Checks if a worker process is currently running."""
    if not os.path.exists(LOCK_FILE):
        return False
    try:
        with open(LOCK_FILE, "r", encoding="utf-8") as f:
            pid_str = f.read().strip()
        if not pid_str:
            return False
        pid = int(pid_str)
        # Check if process is alive on Windows
        import ctypes
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    except Exception:
        return False

def enqueue_phrase(text: str):
    """Appends phrase to speech_queue.txt and launches background worker if idle."""
    clean = text.strip()
    if not clean:
        return

    # Append to queue file
    with open(QUEUE_FILE, "a", encoding="utf-8") as f:
        f.write(clean + "\n")

    # If worker is not active, spawn worker asynchronously via Popen
    if not is_worker_active():
        python_bin = sys.executable
        subprocess.Popen(
            [python_bin, os.path.abspath(__file__), "--worker"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            close_fds=True,
        )

def resolve_phrase_from_args() -> str:
    """Parses text from CLI args or specialized flags."""
    args = sys.argv[1:]
    if not args:
        return "System online, sir."

    if args[0] == "--file" and len(args) > 1:
        path = args[1]
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
        return ""

    if args[0] == "--intent-start":
        if os.path.exists(INTENT_FILE):
            try:
                with open(INTENT_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("speaking_start", "Executing task, sir.")
            except Exception:
                return "Executing task, sir."
        return "Executing task, sir."

    if args[0] == "--intent-success":
        if os.path.exists(INTENT_FILE):
            try:
                with open(INTENT_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("speaking_success", "Completed the task, sir.")
            except Exception:
                return "Completed the task, sir."
        return "Completed the task, sir."

    if args[0] == "--intent-error":
        if os.path.exists(INTENT_FILE):
            try:
                with open(INTENT_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("speaking_error", "Task failed, sir.")
            except Exception:
                return "Task failed, sir."
        return "Task failed, sir."

    return " ".join(args).strip()

def main():
    if "--worker" in sys.argv:
        run_worker()
        sys.exit(0)

    phrase = resolve_phrase_from_args()
    if phrase:
        enqueue_phrase(phrase)
    sys.exit(0)

if __name__ == "__main__":
    main()
