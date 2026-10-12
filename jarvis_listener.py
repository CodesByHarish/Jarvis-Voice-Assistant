#!/usr/bin/env python3
"""
Jarvis Zero-Latency Real-Time Conversational Voice Listener
Features:
- Instant openWakeWord detection (Threshold: 0.20).
- Single, non-blocking wake acknowledgment: "On it, sir.".
- Ultra-responsive Silero VAD boundary detection with 350ms silence cutoff.
- Zero duplicate speech triggers prior to webhook dispatch.
- Direct multipart HTTP POST dispatch to n8n webhook.
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

# Audio & Wake Word Parameters
THRESHOLD = 0.20
RATE = 16000
CHUNK = 1280  # 80ms chunks
FORMAT = pyaudio.paInt16
CHANNELS = 1

# Ultra-Low Latency VAD Parameters
SILENCE_TIMEOUT_MS = 350  # 350ms silence cutoff for near-instant dispatch
MIN_SPEECH_CHUNKS = 3     # ~240ms minimum speech
MAX_RECORDING_SEC = 10    # Safety cap
VAD_SPEECH_THRESHOLD = 0.35
RMS_ENERGY_THRESHOLD = 250.0

def speak_acknowledgment():
    """Immediately triggers single non-blocking wake acknowledgment: 'On it, sir.'"""
    python_bin = sys.executable
    speak_script = os.path.join(PROJECT_ROOT, "speak.py")
    try:
        subprocess.Popen(
            [python_bin, speak_script, "On it, sir."],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
    except Exception as e:
        print(f"[jarvis_listener] Speech trigger notice: {e}", file=sys.stderr)

def record_dynamic_command(stream: pyaudio.Stream, vad_engine) -> bytes:
    """Dynamically records microphone audio, stopping within 350ms of silence."""
    print("[Jarvis] Streaming audio: dynamic VAD active (350ms silence cutoff)...")
    frames = []
    has_spoken = False
    speech_chunks_count = 0
    silence_duration_ms = 0
    start_time = time.time()
    max_chunks = int((RATE / CHUNK) * MAX_RECORDING_SEC)

    for _ in range(max_chunks):
        raw_data = stream.read(CHUNK, exception_on_overflow=False)
        frames.append(raw_data)
        audio_chunk = np.frombuffer(raw_data, dtype=np.int16)

        # Silero VAD speech score
        try:
            speech_prob = vad_engine.predict(audio_chunk, frame_size=320)
        except Exception:
            speech_prob = 0.0

        # RMS Energy calculation
        rms = np.sqrt(np.mean(audio_chunk.astype(np.float32) ** 2))
        is_speech = (speech_prob >= VAD_SPEECH_THRESHOLD) or (rms >= RMS_ENERGY_THRESHOLD)

        if is_speech:
            has_spoken = True
            speech_chunks_count += 1
            silence_duration_ms = 0
        else:
            if has_spoken and speech_chunks_count >= MIN_SPEECH_CHUNKS:
                silence_duration_ms += 80
                if silence_duration_ms >= SILENCE_TIMEOUT_MS:
                    print(f"[Jarvis] End-of-speech detected ({silence_duration_ms}ms silence). Stopping capture.")
                    break

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
            resp = requests.post(N8N_WEBHOOK_URL, files=files, timeout=45)
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
    print("   JARVIS ZERO-LATENCY CONVERSATIONAL LISTENER    ")
    print(f"   Wake Sensitivity   : Threshold {THRESHOLD} (High)")
    print(f"   VAD Silence Cutoff : {SILENCE_TIMEOUT_MS}ms")
    print(f"   Webhook Target     : {N8N_WEBHOOK_URL}")
    print("==================================================")

    try:
        openwakeword.utils.download_models()
    except Exception:
        pass

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

            prediction = oww_model.predict(audio_array)
            score = prediction.get("hey_jarvis", 0.0)

            if score >= THRESHOLD:
                print(f"\n[Jarvis] Wake word detected! (Confidence: {score:.2f} >= {THRESHOLD})")
                
                # 1. Single non-blocking acknowledgment
                speak_acknowledgment()

                # 2. Dynamic VAD Recording with 350ms cutoff
                audio_bytes = record_dynamic_command(stream, vad_engine)
                save_wav(audio_bytes, audio, OUTPUT_AUDIO_FILE)

                # 3. Fire to n8n webhook
                dispatch_to_n8n(OUTPUT_AUDIO_FILE)

                # Reset internal buffers
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
