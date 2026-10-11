#!/usr/bin/env python3
"""
Jarvis Speech-to-Text Transcription Module
Primary Engine: Groq Cloud API (whisper-large-v3-turbo) for ultra-fast sub-100ms transcription.
Offline Fallback: Local faster-whisper (tiny.en, int8 quantization).
Saves last transcript to `last_transcript.txt` for rock-solid workflow pipeline safety.
"""

import sys
import os
import re
import warnings
import requests
from dotenv import load_dotenv

# Suppress HuggingFace hub symlink warnings on Windows
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
warnings.filterwarnings("ignore")

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
TRANSCRIPT_CACHE_FILE = "last_transcript.txt"

def sanitize_transcript(text: str) -> str:
    """Removes irregular newlines, control characters, and excess whitespace."""
    if not text:
        return ""
    cleaned = re.sub(r"[\r\n\t]+", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned

def transcribe_with_groq(audio_path: str) -> str:
    """Primary ASR: Groq Cloud API whisper-large-v3-turbo."""
    if not GROQ_API_KEY or GROQ_API_KEY.startswith("your_"):
        raise ValueError("GROQ_API_KEY is not configured.")

    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
    }

    with open(audio_path, "rb") as f:
        files = {
            "file": (os.path.basename(audio_path), f, "audio/wav"),
        }
        data = {
            "model": "whisper-large-v3-turbo",
            "temperature": "0.0",
            "response_format": "json",
        }
        response = requests.post(url, headers=headers, files=files, data=data, timeout=15)

    if response.status_code == 200:
        result = response.json()
        return sanitize_transcript(result.get("text", ""))
    else:
        raise RuntimeError(f"Groq Whisper HTTP {response.status_code}: {response.text}")

def transcribe_with_faster_whisper(audio_path: str) -> str:
    """Offline Fallback ASR: Local faster-whisper tiny.en."""
    from faster_whisper import WhisperModel

    model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(
        audio_path,
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=400),
    )
    text_parts = [segment.text.strip() for segment in segments]
    return sanitize_transcript(" ".join(text_parts))

def transcribe(audio_path: str) -> str:
    if not os.path.exists(audio_path):
        print(f"[transcribe.py] Warning: File not found: {audio_path}", file=sys.stderr)
        return ""

    # 1. Primary: Groq Cloud API
    try:
        text = transcribe_with_groq(audio_path)
        if text:
            return text
    except Exception as e:
        print(f"[transcribe.py] Groq Whisper notice ({e}), falling back to local faster-whisper...", file=sys.stderr)

    # 2. Offline Fallback: Local faster-whisper
    try:
        return transcribe_with_faster_whisper(audio_path)
    except Exception as e:
        print(f"[transcribe.py] Local faster-whisper notice: {e}", file=sys.stderr)
        return ""

def main():
    audio_file = sys.argv[1] if len(sys.argv) > 1 else "recorded_command.wav"
    try:
        transcript = transcribe(audio_file)
    except Exception as e:
        print(f"[transcribe.py] Unexpected error: {e}", file=sys.stderr)
        transcript = ""

    # Cache transcript to file for quote-safe downstream access
    try:
        with open(TRANSCRIPT_CACHE_FILE, "w", encoding="utf-8") as f:
            f.write(transcript)
    except Exception as e:
        print(f"[transcribe.py] Could not cache transcript: {e}", file=sys.stderr)

    # Output to stdout
    print(transcript)
    sys.exit(0)

if __name__ == "__main__":
    main()
