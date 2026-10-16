#!/usr/bin/env python3
"""
Jarvis Antigravity Bridge - UI Automation & Autonomous Task Dispatch
Locates Antigravity IDE on Windows, brings it to the foreground,
focuses the agent chat panel (Ctrl+L), pastes the prompt (Ctrl+V),
and automatically submits it (Enter).
"""

import sys
import os
import time
import subprocess
import ctypes
from ctypes import wintypes
import psutil

# Win32 Virtual Key Constants
VK_CONTROL = 0x11
VK_L = 0x4C
VK_V = 0x56
VK_RETURN = 0x0D
KEYEVENTF_KEYUP = 0x0002
SW_RESTORE = 9

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


def sync_to_clipboard(text: str) -> bool:
    """Syncs formatted text to the Windows clipboard via pyperclip and native clip.exe."""
    success = False
    try:
        import pyperclip
        pyperclip.copy(text)
        success = True
    except Exception:
        pass

    try:
        proc = subprocess.Popen(["clip"], stdin=subprocess.PIPE, shell=True)
        proc.communicate(input=text.encode("utf-8"))
        success = True
    except Exception as e:
        if not success:
            print(f"[antigravity_bridge] Clipboard sync error: {e}", file=sys.stderr)

    return success


def attach_to_default_desktop():
    """Attaches current thread to the default interactive desktop station (WinSta0\\default)."""
    try:
        hdesk = user32.OpenDesktopW("default", 0, False, 0x01FF)
        if hdesk:
            user32.SetThreadDesktop(hdesk)
            return hdesk
    except Exception:
        pass
    return None


def find_antigravity_window() -> int | None:
    """
    Scans the default desktop for the Antigravity IDE main top-level window.
    Matches window process ('antigravity ide.exe') or window title containing 'antigravity'.
    """
    attach_to_default_desktop()
    matched_hwnds = []

    def enum_cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True

        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True

        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        title = buff.value.lower()

        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        pname = ""
        try:
            pname = psutil.Process(pid.value).name().lower()
        except Exception:
            pass

        # Check for Antigravity IDE process or title
        is_ag_proc = "antigravity" in pname
        is_ag_title = "antigravity" in title

        if is_ag_proc or is_ag_title:
            # Top-level window check
            if user32.GetParent(hwnd) == 0:
                matched_hwnds.append((hwnd, length, title))
        return True

    cb = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(enum_cb)
    user32.EnumDesktopWindows(None, cb, 0)

    if not matched_hwnds:
        return None

    # Prefer window with title mentioning project or longest title
    matched_hwnds.sort(key=lambda item: item[1], reverse=True)
    return matched_hwnds[0][0]


def force_foreground_window(hwnd: int) -> bool:
    """
    Bypasses Windows LockSetForegroundWindow restrictions to reliably bring
    Antigravity IDE to the active foreground.
    """
    attach_to_default_desktop()

    # 1. Un-minimize / restore if minimized
    user32.ShowWindow(hwnd, SW_RESTORE)

    # 2. Simulate Alt key down/up to grant foreground rights
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, KEYEVENTF_KEYUP, 0)

    # 3. Attach thread inputs
    curr_tid = kernel32.GetCurrentThreadId()
    fg_hwnd = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None)
    target_tid = user32.GetWindowThreadProcessId(hwnd, None)

    if fg_tid != 0 and fg_tid != curr_tid:
        user32.AttachThreadInput(curr_tid, fg_tid, True)
    if target_tid != 0 and target_tid != curr_tid:
        user32.AttachThreadInput(curr_tid, target_tid, True)

    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    user32.SetFocus(hwnd)

    if fg_tid != 0 and fg_tid != curr_tid:
        user32.AttachThreadInput(curr_tid, fg_tid, False)
    if target_tid != 0 and target_tid != curr_tid:
        user32.AttachThreadInput(curr_tid, target_tid, False)

    time.sleep(0.15)
    return True


def send_key_combo(vk_mod: int, vk_key: int):
    """Sends a modifier + key combination using User32 keybd_event."""
    user32.keybd_event(vk_mod, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(vk_key, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(vk_key, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.05)
    user32.keybd_event(vk_mod, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.05)


def send_key_press(vk_key: int):
    """Sends a single key down and up event using User32 keybd_event."""
    user32.keybd_event(vk_key, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(vk_key, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.05)


def dispatch_prompt_to_antigravity(prompt: str) -> bool:
    """
    Autonomous pipeline:
    1. Synchronizes prompt text to Windows clipboard.
    2. Brings Antigravity IDE to the foreground.
    3. Triggers Ctrl+L to focus agent chat panel prompt input.
    4. Pastes the prompt via Ctrl+V.
    5. Presses Enter to submit the prompt to the Antigravity agent.
    """
    if not prompt or not prompt.strip():
        print("[antigravity_bridge] Warning: Empty prompt provided.", file=sys.stderr)
        return False

    clean_prompt = prompt.strip()

    # Step 1: Copy to clipboard
    sync_to_clipboard(clean_prompt)
    print("[antigravity_bridge] Prompt copied to clipboard.", file=sys.stderr)

    # Step 2: Locate Antigravity IDE
    hwnd = find_antigravity_window()
    if not hwnd:
        print("[antigravity_bridge] Warning: Antigravity IDE window not detected on desktop.", file=sys.stderr)
        return False

    # Step 3: Bring window to foreground
    force_foreground_window(hwnd)
    print(f"[antigravity_bridge] Focused Antigravity IDE window (HWND={hwnd}).", file=sys.stderr)
    time.sleep(0.3)

    # Step 4: Focus agent chat input via Ctrl+L
    # We try PyAutoGUI first if available, with robust User32 fallback
    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.hotkey("ctrl", "l")
        time.sleep(0.35)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.25)
        pyautogui.press("enter")
    except Exception as e:
        print(f"[antigravity_bridge] PyAutoGUI fallback to keybd_event: {e}", file=sys.stderr)
        send_key_combo(VK_CONTROL, VK_L)
        time.sleep(0.35)
        send_key_combo(VK_CONTROL, VK_V)
        time.sleep(0.25)
        send_key_press(VK_RETURN)

    print("[antigravity_bridge] Prompt pasted and Enter submitted successfully.", file=sys.stderr)
    return True


if __name__ == "__main__":
    test_text = sys.argv[1] if len(sys.argv) > 1 else ""
    if test_text:
        print(f"[antigravity_bridge] Dispatching: {test_text}")
        dispatch_prompt_to_antigravity(test_text)
    else:
        hwnd = find_antigravity_window()
        print(f"[antigravity_bridge] Detected Antigravity IDE HWND: {hwnd}")
