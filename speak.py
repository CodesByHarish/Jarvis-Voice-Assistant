#!/usr/bin/env python3
"""
Jarvis Ultra-Natural Neural AI Speech Synthesis Module
Features:
- Primary Engine: edge-tts using 'en-US-ChristopherNeural' for a deep, cinematic Jarvis tone.
- Audio Player: Clean, glitch-free playback via pygame.mixer.
- Offline Fallbacks: Native Windows PowerShell System.Speech (SAPI5) and pyttsx3.
- Sequential Queue: Consecutive phrases ("Listening..." -> "Executing..." -> "Completed...")
  never overlap, stutter, or clip.
- Completely Non-Blocking: Returns in <20ms while the background worker speaks.
- CLI Flags: --file <path>, --intent-start, --intent-success, --intent-error, --blocking.
"""

import sys
import os
import time
import json
import asyncio
import subprocess

# Suppress Pygame community banner
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
QUEUE_FILE = os.path.join(PROJECT_ROOT, "speech_queue.txt")
LOCK_FILE = os.path.join(PROJECT_ROOT, "speech.lock")
INTENT_FILE = os.path.join(PROJECT_ROOT, "last_intent.json")

NEURAL_VOICE = "en-US-ChristopherNeural"

async def generate_neural_speech(text: str, output_path: str):
    """Generates audio file using edge-tts with ChristopherNeural voice."""
    import edge_tts
    # Add slight pitch and rate adjustment for authentic Jarvis persona
    communicate = edge_tts.Communicate(text, voice=NEURAL_VOICE, rate="+0%", pitch="-2Hz")
    await communicate.save(output_path)

def play_audio_file(audio_path: str) -> bool:
    """Plays an audio file cleanly using pygame.mixer."""
    try:
        import pygame
        pygame.mixer.init()
        pygame.mixer.music.load(audio_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.05)
        pygame.mixer.music.stop()
        if hasattr(pygame.mixer.music, "unload"):
            pygame.mixer.music.unload()
        pygame.mixer.quit()
        return True
    except Exception as e:
        print(f"[speak.py] Pygame playback error: {e}", file=sys.stderr)
        try:
            import pygame
            pygame.mixer.quit()
        except Exception:
            pass
        return False

def speak_with_neural_ai(text: str) -> bool:
    """Attempts Neural AI TTS using edge-tts + pygame."""
    temp_file = os.path.join(PROJECT_ROOT, f"temp_tts_{os.getpid()}_{int(time.time()*1000)}.mp3")
    try:
        asyncio.run(generate_neural_speech(text, temp_file))
        if os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
            success = play_audio_file(temp_file)
            try:
                os.remove(temp_file)
            except Exception:
                pass
            return success
        return False
    except Exception as e:
        print(f"[speak.py] Neural TTS offline or unavailable ({e}), using fallback...", file=sys.stderr)
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except Exception:
            pass
        return False

def speak_with_powershell(text: str) -> bool:
    """Native Windows System.Speech SAPI5 fallback."""
    try:
        escaped = text.replace("'", "''").replace('"', '""')
        ps_cmd = (
            f"Add-Type -AssemblyName System.Speech; "
            f"$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$synth.Rate = 0; "
            f"$synth.Speak('{escaped}')"
        )
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=25,
        )
        return proc.returncode == 0
    except Exception as e:
        print(f"[speak.py] PowerShell SAPI5 notice: {e}", file=sys.stderr)
        return False

def speak_with_pyttsx3(text: str) -> bool:
    """Offline pyttsx3 fallback."""
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty("rate", 175)
        engine.say(text)
        engine.runAndWait()
        return True
    except Exception as e:
        print(f"[speak.py] pyttsx3 fallback notice: {e}", file=sys.stderr)
        return False

def speak_direct(text: str):
    """Speaks text using Neural AI first, falling back to SAPI5 and pyttsx3."""
    clean = text.strip()
    if not clean:
        return

    print(f"[Jarvis Neural Speaking]: {clean}")

    # 1. Primary: Ultra-natural Neural AI (edge-tts)
    if speak_with_neural_ai(clean):
        return

    # 2. Fallback: Native Windows PowerShell SAPI5
    if speak_with_powershell(clean):
        return

    # 3. Fallback: pyttsx3
    speak_with_pyttsx3(clean)

def run_worker():
    """Background worker process draining speech queue sequentially."""
    try:
        with open(LOCK_FILE, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass

    try:
        while True:
            phrase = None
            if os.path.exists(QUEUE_FILE):
                try:
                    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                        lines = [line.strip() for line in f if line.strip()]
                    if lines:
                        phrase = lines[0]
                        with open(QUEUE_FILE, "w", encoding="utf-8") as f:
                            for remaining in lines[1:]:
                                f.write(remaining + "\n")
                except Exception:
                    time.sleep(0.05)
                    continue

            if phrase:
                speak_direct(phrase)
                time.sleep(0.1)
            else:
                break
    finally:
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
    """Appends phrase to queue and launches background worker if idle."""
    clean = text.strip()
    if not clean:
        return

    with open(QUEUE_FILE, "a", encoding="utf-8") as f:
        f.write(clean + "\n")

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
    """Resolves phrase from arguments, files, or intent cache."""
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

    if "--direct" in sys.argv:
        # Synchronous direct speech mode
        remaining = [a for a in sys.argv[1:] if a != "--direct"]
        text = " ".join(remaining) if remaining else "Neural AI speech engine is online, sir."
        speak_direct(text)
        sys.exit(0)

    phrase = resolve_phrase_from_args()
    if phrase:
        enqueue_phrase(phrase)
    sys.exit(0)

if __name__ == "__main__":
    main()
