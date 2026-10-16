#!/usr/bin/env python3
"""
Jarvis Unified LLM Engine
Primary: Groq Cloud API (llama-3.3-70b-versatile, llama-3.1-8b-instant)
Fallback: Local Ollama (qwen2.5-coder:7b)
Generates natural, dynamic AI responses without hardcoded placeholders.
"""

import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").strip()

GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
]


def query_llm(messages: list, max_tokens: int = 600, temperature: float = 0.3) -> str:
    """Queries Groq Cloud API with automatic fallback to local Ollama."""
    # 1. Attempt Groq Cloud API
    if GROQ_API_KEY and not GROQ_API_KEY.startswith("your_"):
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        }
        for model in GROQ_MODELS:
            try:
                resp = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers,
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"].strip()
                elif resp.status_code == 401:
                    print(f"[llm_client] Groq API Key authentication failed (HTTP 401). Falling back to local Ollama.", file=sys.stderr)
                    break
            except Exception as e:
                print(f"[llm_client] Groq connection notice ({model}): {e}", file=sys.stderr)

    # 2. Offline Fallback: Local Ollama
    try:
        resp = requests.post(
            f"{OLLAMA_HOST}/api/chat",
            json={
                "model": "qwen2.5-coder:7b",
                "messages": messages,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
                "stream": False,
            },
            timeout=25,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("message", {}).get("content", "").strip()
    except Exception as e:
        print(f"[llm_client] Ollama connection error: {e}", file=sys.stderr)

    return ""


def summarize_command_execution(transcript: str, command: str, stdout: str, stderr: str = "") -> str:
    """Generates a natural, intelligent 1-2 sentence spoken reply based on the real terminal command output."""
    output_preview = (stdout.strip() or stderr.strip() or "No output returned.")[:1200]
    messages = [
        {
            "role": "system",
            "content": (
                "You are Jarvis, a brilliant, concise British-accented AI systems assistant. "
                "The user asked a query or gave a command, and the terminal command has just executed. "
                "Analyze the actual terminal output and give a direct, natural 1-2 sentence spoken answer to the user. "
                "Never use markdown asterisks, backticks, or bracket placeholders like [commit message]. "
                "State the actual details (e.g. commit hash, author, branch name, or status summary) smoothly and conversationally."
            ),
        },
        {
            "role": "user",
            "content": (
                f"User request: {transcript}\n"
                f"Executed command: {command}\n"
                f"Actual Terminal Output:\n{output_preview}\n\n"
                f"Spoken response as Jarvis:"
            ),
        },
    ]

    summary = query_llm(messages, max_tokens=500, temperature=0.3)
    if summary:
        # Clean any stray formatting
        summary = summary.replace("*", "").replace("`", "").replace('"', '').strip()
        if summary.startswith("Jarvis:"):
            summary = summary[7:].strip()
        return summary

    return "Task completed successfully, sir."


if __name__ == "__main__":
    test_q = sys.argv[1] if len(sys.argv) > 1 else "What was the last commit?"
    test_out = "commit 73a8185 (HEAD -> master) Author: CodesByHarish Date: Oct 16 Fix syntax error in speak.py"
    ans = summarize_command_execution(test_q, "git log -1", test_out)
    print("Generated AI Speech:", ans)
