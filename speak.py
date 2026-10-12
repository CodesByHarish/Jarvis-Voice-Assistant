#!/usr/bin/env python3
"""
Jarvis Ultra-Low Latency Neural AI Speech Engine
Features:
- Pre-generates and caches static audio clips: `on_it.mp3` ("On it, sir.") & `listening.mp3` ("Listening, sir.").
- Pre-warmed 24kHz pygame.mixer for sub-50ms instant audio playback.
- Dynamic edge-tts synthesis (en-US-ChristopherNeural) for custom conversational responses.
- Supports direct audio playback of pre-rendered clips and queued dynamic announcements.
- CLI Flags: --file <path>, --intent-start, --intent-response, --intent-success, --intent-error, --init.
"""

import sys
import os
import time
import json
import asyncio
import subprocess

# Suppress Pygame welcome banner
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
QUEUE_FILE = os.path.join(PROJECT_ROOT, "speech_queue.txt")
LOCK_FILE = os.path.join(PROJECT_ROOT, "speech.lock")
INTENT_FILE = os.path.join(PROJECT_ROOT, "last_intent.json")
TEMP_SPEECH_FILE = os.path.join(PROJECT_ROOT, "temp_speech.mp3")

ON_IT_AUDIO = os.path.join(PROJECT_ROOT, "on_it.mp3")
LISTENING_AUDIO = os.path.join(PROJECT_ROOT, "listening.mp3")

NEURAL_VOICE = "en-US-ChristopherNeural"

async def generate_speech_audio(text: str, output_path: str):
    """Renders speech using edge-tts with the Christopher Neural voice."""
    import edge_tts
    communicator = edge_tts.Communicate(
        text=text,
        voice=NEURAL_VOICE,
        rate="+0%",
        pitch="-2Hz",
    )
    await communicator.save(output_path)

def ensure_static_audio():
    """Pre-generates static local audio files for zero-latency instant playback."""
    static_clips = {
        ON_IT_AUDIO: "On it, sir.",
        LISTENING_AUDIO: "Listening, sir.",
    }
    for path, phrase in static_clips.items():
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            try:
                asyncio.run(generate_speech_audio(phrase, path))
                print(f"[speak.py] Pre-rendered static clip: {os.path.basename(path)}")
            except Exception as e:
                print(f"[speak.py] Static clip generation warning ({os.path.basename(path)}): {e}", file=sys.stderr)

def play_audio_file(audio_path: str):
    """Plays audio via pre-warmed 24kHz pygame mixer and releases lock immediately."""
    if not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
        return

    import pygame

    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=24000, buffer=1024)
        pygame.mixer.music.load(audio_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.02)
        pygame.mixer.music.stop()
        if hasattr(pygame.mixer.music, "unload"):
            pygame.mixer.music.unload()
        pygame.mixer.quit()
    except Exception as e:
        print(f"[speak.py] Playback notice: {e}", file=sys.stderr)
        try:
            pygame.mixer.quit()
        except Exception:
            pass

def speak_direct(text: str):
    """Speaks text: plays pre-rendered MP3 if available, otherwise generates dynamic speech."""
    clean = text.strip()
    if not clean:
        return

    # Check for direct audio file requests or known phrases
    if clean.lower() in ["on it, sir.", "on it", "on_it.mp3"]:
        if os.path.exists(ON_IT_AUDIO):
            play_audio_file(ON_IT_AUDIO)
            return
    elif clean.lower() in ["listening, sir.", "listening", "listening.mp3"]:
        if os.path.exists(LISTENING_AUDIO):
            play_audio_file(LISTENING_AUDIO)
            return

    # Dynamic synthesis
    print(f"[Jarvis Neural Voice]: {clean}")
    try:
        asyncio.run(generate_speech_audio(clean, TEMP_SPEECH_FILE))
        play_audio_file(TEMP_SPEECH_FILE)
    except Exception as e:
        print(f"[speak.py] edge-tts error: {e}", file=sys.stderr)

def run_worker():
    """Background worker draining queued phrases sequentially."""
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
                    time.sleep(0.03)
                    continue

            if phrase:
                speak_direct(phrase)
                time.sleep(0.06)
            else:
                break
    finally:
        try:
            if os.path.exists(LOCK_FILE):
                os.remove(LOCK_FILE)
        except Exception:
            pass

def is_worker_active() -> bool:
    """Checks if background speech daemon is running."""
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
    """Appends phrase to queue and triggers background worker."""
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
    """Resolves target phrase from CLI flags or intent files."""
    args = sys.argv[1:]
    if not args:
        return "Neural AI speech engine is online, sir."

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
                return data.get("speaking_start", "")
            except Exception:
                return ""
        return ""

    if args[0] in ["--intent-response", "--intent-success"]:
        if os.path.exists(INTENT_FILE):
            try:
                with open(INTENT_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("speaking_response", data.get("speaking_success", "Task completed successfully, sir."))
            except Exception:
                return "Task completed successfully, sir."
        return "Task completed successfully, sir."

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
    if "--init" in sys.argv:
        ensure_static_audio()
        sys.exit(0)

    if "--worker" in sys.argv:
        run_worker()
        sys.exit(0)

    if "--direct" in sys.argv:
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
