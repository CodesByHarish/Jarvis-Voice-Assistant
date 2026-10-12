# Jarvis - Real-Time Conversational Voice Git Automation

Zero-cost, local, zero-latency voice assistant that automates Git and GitHub CLI operations using **openWakeWord** (Sensitivity: 0.20), **Silero VAD** (Ultra-responsive >=350ms silence cutoff), **Groq Whisper (`whisper-large-v3-turbo`)**, **Groq LLM** (with local **Ollama `qwen2.5-coder:7b`** fallback), **Neural AI TTS (`edge-tts` with `en-US-ChristopherNeural`)**, and **n8n**.

---

## Conversational Voice Architecture

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Mic as Microphone
    participant Listener as jarvis_listener.py (Silero VAD)
    participant Speak as speak.py (Neural AI TTS)
    participant n8n as n8n Webhook Pipeline
    participant ASR as transcribe.py (Groq Whisper)
    participant Router as intent_router.py (Groq / Ollama)
    participant Exec as execute_git.py (Git / gh CLI)

    User->>Mic: "Hey Jarvis"
    Mic->>Listener: Audio Stream (16kHz PCM)
    Listener->>Speak: python speak.py "On it, sir." (Non-blocking)
    Speak-->>User: Neural Spoken Response: "On it, sir."
    User->>Mic: Speaks command (e.g., "Push all my changes with message fixed auth bug")
    Note over Listener: Silero VAD monitors speech.<br/>Stops immediately after >=350ms silence.
    Listener->>n8n: POST multipart/form-data to /webhook/jarvis-git
    n8n->>ASR: cd "..." && python transcribe.py recorded_command.wav
    ASR-->>n8n: Sub-100ms Transcript
    n8n->>Router: cd "..." && python intent_router.py
    Note over Router: Parses intent & saves status metadata.
    n8n->>Speak: cd "..." && python speak.py --intent-start
    Speak-->>User: Neural Announcement: "Executing task: committing and pushing changes, sir."
    n8n->>Exec: cd "..." && python execute_git.py
    alt Git Execution Succeeded (Exit Code 0)
        n8n->>Speak: cd "..." && python speak.py "Task completed successfully, sir."
        Speak-->>User: Neural Response: "Task completed successfully, sir."
    else Git Execution Failed
        n8n->>Speak: cd "..." && python speak.py "Task failed, sir."
        Speak-->>User: Neural Response: "Task failed, sir."
    end
```

---

## Component Architecture

1. [`jarvis_listener.py`](file:///c:/Users/gansk/OneDrive/Desktop/Jarvis%20github/jarvis_listener.py):
   - **Wake Word Detection**: `openWakeWord` (`hey_jarvis`, Sensitivity: 0.20).
   - **Immediate Wake Acknowledgment**: Calls `python speak.py "On it, sir."` non-blocking.
   - **Ultra-Low Latency Silero VAD**: Automatically stops recording within 350ms of trailing silence.
   - **Multipart Webhook Dispatch**: Posts to `http://localhost:5678/webhook/jarvis-git`.
2. [`speak.py`](file:///c:/Users/gansk/OneDrive/Desktop/Jarvis%20github/speak.py):
   - **Single Cache File**: Reuses `temp_speech.mp3` for zero disk bloating.
   - **24kHz Pre-initialized Player**: `pygame.mixer` pre-initialized at native 24000Hz for sub-50ms playback.
   - **Neural Voice**: Exclusive `en-US-ChristopherNeural` (deep cinematic Jarvis tone).
3. [`transcribe.py`](file:///c:/Users/gansk/OneDrive/Desktop/Jarvis%20github/transcribe.py):
   - Primary: Groq Cloud API `whisper-large-v3-turbo` for sub-100ms transcription.
   - Fallback: Local `faster-whisper` (`tiny.en`, `int8`).
4. [`intent_router.py`](file:///c:/Users/gansk/OneDrive/Desktop/Jarvis%20github/intent_router.py):
   - Extracts structured action and CLI command (with `cd "C:\Users\gansk\OneDrive\Desktop\Jarvis github"`).
   - Pure parser: no internal duplicate speech invocations.
5. [`execute_git.py`](file:///c:/Users/gansk/OneDrive/Desktop/Jarvis%20github/execute_git.py):
   - Auto-injects `C:\Program Files\GitHub CLI` into `PATH`.
   - Runs the command inside repository root and returns exact exit code.
6. [`workflows/jarvis_workflow.json`](file:///c:/Users/gansk/OneDrive/Desktop/Jarvis%20github/workflows/jarvis_workflow.json):
   - Streamlined 7-node chained workflow with exactly one start announcement and one completion announcement.

---

## Running Jarvis

```powershell
# 1. Start n8n Server (Terminal 1)
.\start_n8n.bat

# 2. Start Jarvis Listener (Terminal 2)
.\start_jarvis.bat
```
