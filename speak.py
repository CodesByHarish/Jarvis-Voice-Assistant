#!/usr/bin/env python3
"""
Jarvis Voice Feedback Module
Speaks text locally using Windows PowerShell SpeechSynthesizer and pyttsx3.
"""

import sys
import subprocess

def speak_with_powershell(text: str) -> bool:
    """Invokes native Windows System.Speech.Synthesis SpeechSynthesizer."""
    try:
        escaped = text.replace("'", "''").replace('"', '""')
        ps_cmd = (
            f"Add-Type -AssemblyName System.Speech; "
            f"$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$synth.Rate = 0; "
            f"$synth.Speak('{escaped}')"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[speak.py] PowerShell synth notice: {e}", file=sys.stderr)
        return False

def speak_with_pyttsx3(text: str) -> bool:
    """Fallback local offline TTS with pyttsx3."""
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty("rate", 175)
        engine.say(text)
        engine.runAndWait()
        return True
    except Exception as e:
        print(f"[speak.py] pyttsx3 notice: {e}", file=sys.stderr)
        return False

def main():
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:]).strip()
    else:
        text = "System online, sir."

    if not text:
        return

    print(f"[Jarvis Speaking]: {text}")
    # Try native Windows speech synthesizer first, fallback to pyttsx3
    if not speak_with_powershell(text):
        speak_with_pyttsx3(text)

if __name__ == "__main__":
    main()
