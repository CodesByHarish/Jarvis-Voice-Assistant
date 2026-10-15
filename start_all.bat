@echo off
title JARVIS - HUD & Voice Listener Launcher
echo ======================================================
echo   Launching JARVIS Cybernetic HUD + Voice Listener
echo ======================================================
echo.
cd /d "%~dp0"
call "%~dp0python.bat" jarvis_listener.py
