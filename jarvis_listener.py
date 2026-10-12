#!/usr/bin/env python3
"""
Jarvis Zero-Latency Real-Time Conversational Voice Listener
Features:
- Real-time openWakeWord detection (Threshold: 0.20).
- Immediate non-blocking acknowledgment: "Listening, sir." via asynchronous speech queue.
- Dynamic Silero Voice Activity Detection (VAD) + RMS energy boundary tracking.
- Eliminates fixed waits: stops recording immediately after >=600ms of trailing silence.
- Instant multipart HTTP POST dispatch to n8n webhook.
"""

import os
import sys
import time
import wave
import subprocess
import requests
import numpy as np
import pyaudio
from dotenv import load_dotenv

# Load environment configuration
load_dotenv()
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "http://localhost:5678/webhook/jarvis-git").strip()

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
OUTPUT_AUDIO_FILE = os.path.join(PROJECT_ROOT, "recorded_command.wav")

# Wake Word & Audio Parameters
THRESHOLD = 0.20
RATE = 16000
CHUNK = 1280  # 80ms chunks (exact multiple of 160/320/640 for Silero VAD)
FORMAT = pyaudio.paInt16
CHANNELS = 1

# VAD Parameters
SILENCE_TIMEOUT_MS = 600  # Stop immediately on >=600ms trailing silence
MIN_SPEECH_CHUNKS = 4     # ~320ms minimum speech to avoid false silence cutoffs
MAX_RECORDING_SEC = 12    # Safety timeout
VAD_SPEECH_THRESHOLD = 0.35
RMS_ENERGY_THRESHOLD = 250.0

def speak_acknowledgment():
    """Triggers non-blocking acknowledgment: 'Listening, sir.'"""
    python_bin = sys.executable
    speak_script = os.path.join(PROJECT_ROOT, "speak.py")
    try:
        subprocess.Popen(
            [python_bin, speak_script, "Listening, sir."],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
    except Exception as e:
        print(f"[jarvis_listener] Speech trigger notice: {e}", file=sys.stderr)

def record_dynamic_command(stream: pyaudio.Stream, vad_engine) -> bytes:
    """Dynamically records microphone input using Silero VAD until 600ms of silence."""
    print("[Jarvis] Streaming audio: dynamic VAD speech detection active...")
    frames = []
    has_spoken = False
    speech_chunks_count = 0
    silence_duration_ms = 0
    start_time = time.time()

    # Pre-speech buffer (first 160ms) to ensure initial consonant isn't clipped
    max_chunks = int((RATE / CHUNK) * MAX_RECORDING_SEC)

    for _ in range(max_chunks):
        raw_data = stream.read(CHUNK, exception_on_overflow=False)
        frames.append(raw_data)
        audio_chunk = np.frombuffer(raw_data, dtype=np.int16)

        # 1. Silero VAD Speech Score
        try:
            speech_prob = vad_engine.predict(audio_chunk, frame_size=320)
        except Exception:
            speech_prob = 0.0

        # 2. RMS Energy calculation
        rms = np.sqrt(np.mean(audio_chunk.astype(np.float32) ** 2))
        is_speech = (speech_prob >= VAD_SPEECH_THRESHOLD) or (rms >= RMS_ENERGY_THRESHOLD)

        if is_speech:
            has_spoken = True
            speech_chunks_count += 1
            silence_duration_ms = 0
        else:
            if has_spoken and speech_chunks_count >= MIN_SPEECH_CHUNKS:
                silence_duration_ms += 80  # Each chunk is 80ms
                if silence_duration_ms >= SILENCE_TIMEOUT_MS:
                    print(f"[Jarvis] End-of-speech detected ({silence_duration_ms}ms silence). Stopping capture.")
                    break

        # Max recording safety escape
        if time.time() - start_time > MAX_RECORDING_SEC:
            print("[Jarvis] Maximum recording safety timeout reached.")
            break

    return b"".join(frames)

def save_wav(raw_bytes: bytes, audio: pyaudio.PyAudio, filepath: str):
    with wave.open(filepath, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(audio.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(raw_bytes)

def dispatch_to_n8n(audio_path: str):
    """Sends recorded command to n8n webhook."""
    print(f"[Jarvis] Firing webhook payload to: {N8N_WEBHOOK_URL}")
    try:
        with open(audio_path, "rb") as f:
            files = {"file": (os.path.basename(audio_path), f, "audio/wav")}
            resp = requests.post(N8N_WEBHOOK_URL, files=files, timeout=60)
            print(f"[Jarvis] n8n response: HTTP {resp.status_code}")
            if resp.status_code >= 400:
                print(f"[Jarvis] n8n webhook notification: {resp.text}", file=sys.stderr)
    except requests.exceptions.ConnectionError:
        print(f"[Jarvis] Connection refused at {N8N_WEBHOOK_URL}. Is n8n active?", file=sys.stderr)
    except Exception as e:
        print(f"[Jarvis] Webhook dispatch error: {e}", file=sys.stderr)

def main():
    import openwakeword
    from openwakeword.model import Model
    from openwakeword.vad import VAD

    print("==================================================")
    print("   JARVIS REAL-TIME CONVERSATIONAL VOICE AGENT    ")
    print(f"   Wake Sensitivity   : Threshold {THRESHOLD} (High)")
    print(f"   Speech End VAD     : Silero (>= {SILENCE_TIMEOUT_MS}ms silence cutoff)")
    print(f"   Webhook Target     : {N8N_WEBHOOK_URL}")
    print("==================================================")

    # Pre-cache models
    try:
        openwakeword.utils.download_models()
    except Exception:
        pass

    # Initialize openWakeWord & Silero VAD
    try:
        oww_model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        vad_engine = VAD()
    except Exception as e:
        print(f"[Jarvis] Fatal: Unable to initialize voice engines: {e}", file=sys.stderr)
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
            raw_data = stream.read(CHUNK, exception_on_overflow=False)
            audio_array = np.frombuffer(raw_data, dtype=np.int16)

            # Predict wake-word score
            prediction = oww_model.predict(audio_array)
            score = prediction.get("hey_jarvis", 0.0)

            if score >= THRESHOLD:
                print(f"\n[Jarvis] Wake word detected! (Confidence: {score:.2f} >= {THRESHOLD})")
                
                # 1. Immediate non-blocking response: "Listening, sir."
                speak_acknowledgment()

                # 2. Dynamic VAD Recording (cuts off immediately on >=600ms silence)
                audio_bytes = record_dynamic_command(stream, vad_engine)
                save_wav(audio_bytes, audio, OUTPUT_AUDIO_FILE)

                # 3. Fire to n8n webhook
                dispatch_to_n8n(OUTPUT_AUDIO_FILE)

                # Reset model buffers
                oww_model.reset()
                vad_engine.reset_states()
                print("[Jarvis] Standing by for next command...")

    except KeyboardInterrupt:
        print("\n[Jarvis] Voice listener terminated by user.")
    finally:
        stream.stop_stream()
        stream.close()
        audio.terminate()

if __name__ == "__main__":
    main()
