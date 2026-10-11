#!/usr/bin/env python3
"""
Jarvis High-Sensitivity Voice Listener
Features:
- High wake-word sensitivity (Threshold: 0.20).
- Non-blocking asynchronous spoken acknowledgment ("On it, sir.") via subprocess.Popen.
- 7-second audio command capture to ensure long phrases are never clipped.
- Multipart HTTP POST dispatch to n8n webhook.
"""

import os
import sys
import wave
import subprocess
import requests
import numpy as np
import pyaudio
from dotenv import load_dotenv

# Load configuration
load_dotenv()
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "http://localhost:5678/webhook/jarvis-git").strip()

# Tuned Audio Parameters
THRESHOLD = 0.20  # Instant trigger on conversational speaking volume
COMMAND_DURATION_SEC = 7  # Expanded duration for comprehensive command capture
OUTPUT_AUDIO_FILE = "recorded_command.wav"

# PyAudio PCM Stream Parameters (openWakeWord standard)
RATE = 16000
CHUNK = 1280  # 80ms chunk at 16kHz
FORMAT = pyaudio.paInt16
CHANNELS = 1

def speak_acknowledgment():
    """Invokes speak.py asynchronously via Popen so recording begins immediately."""
    python_bin = sys.executable
    script_dir = os.path.dirname(os.path.abspath(__file__))
    speak_script = os.path.join(script_dir, "speak.py")
    try:
        subprocess.Popen(
            [python_bin, speak_script, "On it, sir."],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
    except Exception as e:
        print(f"[jarvis_listener] Asynchronous speech warning: {e}", file=sys.stderr)

def record_command(audio: pyaudio.PyAudio, stream: pyaudio.Stream, duration_sec: int, output_file: str):
    """Records microphone stream for the given duration and saves as WAV."""
    print(f"[Jarvis] Recording command for {duration_sec} seconds...")
    frames = []
    num_chunks = int((RATE / CHUNK) * duration_sec)

    for _ in range(num_chunks):
        data = stream.read(CHUNK, exception_on_overflow=False)
        frames.append(data)

    with wave.open(output_file, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(audio.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b"".join(frames))

    print(f"[Jarvis] Command captured and saved to {output_file}")

def dispatch_to_n8n(audio_path: str):
    """Dispatches recorded WAV file to the n8n orchestration webhook."""
    print(f"[Jarvis] Dispatching audio to n8n webhook: {N8N_WEBHOOK_URL}")
    try:
        with open(audio_path, "rb") as f:
            files = {"file": (os.path.basename(audio_path), f, "audio/wav")}
            resp = requests.post(N8N_WEBHOOK_URL, files=files, timeout=60)
            print(f"[Jarvis] n8n response: HTTP {resp.status_code}")
            if resp.status_code >= 400:
                print(f"[Jarvis] n8n webhook notification: {resp.text}", file=sys.stderr)
    except requests.exceptions.ConnectionError:
        print(f"[Jarvis] Connection refused at {N8N_WEBHOOK_URL}. Is n8n running?", file=sys.stderr)
    except Exception as e:
        print(f"[Jarvis] Webhook dispatch error: {e}", file=sys.stderr)

def main():
    import openwakeword
    from openwakeword.model import Model

    print("==================================================")
    print("   JARVIS HIGH-SENSITIVITY VOICE LISTENER         ")
    print(f"   Wake Sensitivity   : Threshold {THRESHOLD} (High)")
    print(f"   Recording Duration : {COMMAND_DURATION_SEC} Seconds")
    print(f"   Webhook Target     : {N8N_WEBHOOK_URL}")
    print("==================================================")

    # Auto-download models if missing
    try:
        openwakeword.utils.download_models()
    except Exception as e:
        print(f"[Jarvis] Model download note: {e}", file=sys.stderr)

    # Initialize openWakeWord engine
    try:
        oww_model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
    except Exception as e:
        print(f"[Jarvis] Fatal: Unable to initialize openWakeWord: {e}", file=sys.stderr)
        return

    audio = pyaudio.PyAudio()
    try:
        stream = audio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK,
        )
    except Exception as e:
        print(f"[Jarvis] Fatal: Cannot open microphone input: {e}", file=sys.stderr)
        audio.terminate()
        return

    print("[Jarvis] Microphone active. Standing by for wake word...")

    try:
        while True:
            # Read 80ms chunk
            audio_data = stream.read(CHUNK, exception_on_overflow=False)
            audio_array = np.frombuffer(audio_data, dtype=np.int16)

            # Predict score
            prediction = oww_model.predict(audio_array)
            score = prediction.get("hey_jarvis", 0.0)

            if score >= THRESHOLD:
                print(f"\n[Jarvis] Wake word detected! (Confidence: {score:.2f} >= {THRESHOLD})")
                
                # 1. Non-blocking spoken acknowledgment
                speak_acknowledgment()

                # 2. Record 7 seconds of audio command immediately
                record_command(audio, stream, COMMAND_DURATION_SEC, OUTPUT_AUDIO_FILE)

                # 3. Post to n8n webhook
                dispatch_to_n8n(OUTPUT_AUDIO_FILE)

                # Reset openWakeWord internal buffer
                oww_model.reset()
                print("[Jarvis] Standing by for next command...")

    except KeyboardInterrupt:
        print("\n[Jarvis] Voice listener terminated by user.")
    finally:
        stream.stop_stream()
        stream.close()
        audio.terminate()

if __name__ == "__main__":
    main()
