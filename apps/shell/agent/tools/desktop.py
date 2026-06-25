"""Structured desktop execution helpers for Agent tools."""

from __future__ import annotations

import math
import platform
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

_COMMON_FOLDER_TARGETS = {
    "desktop": "Desktop",
    "desktopfolder": "Desktop",
    "桌面": "Desktop",
    "桌面文件夹": "Desktop",
    "downloads": "Downloads",
    "downloadsfolder": "Downloads",
    "下载": "Downloads",
    "下载文件夹": "Downloads",
    "documents": "Documents",
    "documentsfolder": "Documents",
    "文档": "Documents",
    "文档文件夹": "Documents",
    "文稿": "Documents",
    "文稿文件夹": "Documents",
    "home": "",
    "homefolder": "",
    "homedirectory": "",
    "userfolder": "",
    "userdirectory": "",
    "主目录": "",
    "用户文件夹": "",
    "用户目录": "",
    "个人文件夹": "",
    "个人目录": "",
}

_SAFE_OPEN_PATH_SUFFIXES = {
    ".txt",
    ".text",
    ".md",
    ".markdown",
    ".log",
    ".rtf",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".csv",
    ".tsv",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
    ".htm",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".pages",
    ".numbers",
    ".key",
    ".mp3",
    ".m4a",
    ".wav",
    ".aiff",
    ".flac",
    ".mp4",
    ".mov",
    ".m4v",
    ".avi",
    ".mkv",
    ".webm",
}

_UNSAFE_OPEN_PATH_SUFFIXES = {
    ".app",
    ".command",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".py",
    ".rb",
    ".pl",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jar",
    ".pkg",
    ".dmg",
    ".exe",
    ".bin",
    ".run",
    ".workflow",
    ".scpt",
    ".applescript",
}

_SAFE_SHORTCUTS: dict[str, tuple[str, tuple[str, ...], str]] = {
    "copy": ("c", ("command",), "copy"),
    "copy_current_page_link": ("l", ("command",), "copy current page link"),
    "paste": ("v", ("command",), "paste"),
    "select_all": ("a", ("command",), "select all"),
    "undo": ("z", ("command",), "undo"),
    "redo": ("z", ("command", "shift"), "redo"),
    "find": ("f", ("command",), "find"),
    "focus_address_bar": ("l", ("command",), "focus address bar"),
    "new_tab": ("t", ("command",), "new tab"),
    "new_private_window": ("n", ("command", "shift"), "new private window"),
    "close_tab": ("w", ("command",), "close tab"),
    "next_tab": ("]", ("command", "shift"), "next tab"),
    "previous_tab": ("[", ("command", "shift"), "previous tab"),
    "next_window": ("`", ("command",), "next window"),
    "previous_window": ("`", ("command", "shift"), "previous window"),
    "switch_previous_app": ("tab", ("command",), "switch to previous app"),
    "switch_next_app": ("tab", ("command", "shift"), "switch to next app"),
    "hide_other_apps": ("h", ("command", "option"), "hide other apps"),
    "toggle_full_screen": ("f", ("control", "command"), "toggle full screen"),
    "mission_control": ("up", ("control",), "mission control"),
    "application_windows": ("down", ("control",), "application windows"),
    "spotlight_search": ("space", ("command",), "spotlight search"),
    "emoji_picker": ("space", ("control", "command"), "emoji picker"),
    "lock_screen": ("q", ("control", "command"), "lock screen"),
    "force_quit_dialog": ("escape", ("command", "option"), "force quit dialog"),
    "new_window": ("n", ("command",), "new window"),
    "new_document": ("n", ("command",), "new document"),
    "new_folder": ("n", ("command", "shift"), "new folder"),
    "new_note": ("n", ("command",), "new note"),
    "new_reminder": ("n", ("command",), "new reminder"),
    "new_event": ("n", ("command",), "new calendar event"),
    "refresh": ("r", ("command",), "refresh"),
    "bookmark_page": ("d", ("command",), "bookmark current page"),
    "show_history": ("y", ("command",), "show history"),
    "open_devtools": ("i", ("command", "option"), "open developer tools"),
    "zoom_in": ("+", ("command",), "zoom in"),
    "zoom_out": ("-", ("command",), "zoom out"),
    "reset_zoom": ("0", ("command",), "reset zoom"),
    "browser_back": ("[", ("command",), "browser back"),
    "browser_forward": ("]", ("command",), "browser forward"),
    "reopen_closed_tab": ("t", ("command", "shift"), "reopen closed tab"),
    "finder_quick_look": ("space", (), "Finder Quick Look"),
}

_SAFE_KEYS: dict[str, tuple[int, str]] = {
    "escape": (53, "Escape"),
    "tab": (48, "Tab"),
    "shift_tab": (48, "Shift+Tab"),
    "arrow_up": (126, "Up Arrow"),
    "arrow_down": (125, "Down Arrow"),
    "arrow_left": (123, "Left Arrow"),
    "arrow_right": (124, "Right Arrow"),
    "home": (115, "Home"),
    "end": (119, "End"),
    "page_up": (116, "Page Up"),
    "page_down": (121, "Page Down"),
    "show_desktop": (103, "Show Desktop"),
}

_HOTKEY_KEY_CODES: dict[str, int] = {
    "return": 36,
    "enter": 36,
    "tab": 48,
    "space": 49,
    "escape": 53,
    "esc": 53,
    "delete": 51,
    "backspace": 51,
    "home": 115,
    "end": 119,
    "page_up": 116,
    "pageup": 116,
    "page_down": 121,
    "pagedown": 121,
    "`": 50,
    "grave": 50,
    "backtick": 50,
    "left": 123,
    "right": 124,
    "down": 125,
    "up": 126,
}

_APPLE_MUSIC_MEDIA_KEY_FALLBACKS: dict[str, tuple[int, str, str]] = {
    "toggle": (100, "Play/Pause", "toggle"),
    "play": (100, "Play/Pause", "toggle"),
    "next": (101, "Next", "next"),
    "previous": (98, "Previous", "previous"),
}

_PRIVACY_SECURITY_URLS = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy",
    "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension",
)
_BLUETOOTH_SETTINGS_URLS = (
    "x-apple.systempreferences:com.apple.BluetoothSettings",
    "x-apple.systempreferences:com.apple.preferences.Bluetooth",
)
_NETWORK_SETTINGS_URLS = (
    "x-apple.systempreferences:com.apple.Network-Settings.extension",
    "x-apple.systempreferences:com.apple.preference.network",
)
_WIFI_SETTINGS_URLS = (
    "x-apple.systempreferences:com.apple.wifi-settings-extension",
    "x-apple.systempreferences:com.apple.preference.network?Wi-Fi",
    *_NETWORK_SETTINGS_URLS,
)
_DISPLAY_SETTINGS_URLS = (
    "x-apple.systempreferences:com.apple.Displays-Settings.extension",
    "x-apple.systempreferences:com.apple.preference.displays",
)
_SOUND_SETTINGS_URLS = (
    "x-apple.systempreferences:com.apple.Sound-Settings.extension",
    "x-apple.systempreferences:com.apple.preference.sound",
)
_KEYBOARD_SETTINGS_URLS = (
    "x-apple.systempreferences:com.apple.Keyboard-Settings.extension",
    "x-apple.systempreferences:com.apple.preference.keyboard",
)
_NOTIFICATIONS_SETTINGS_URLS = (
    "x-apple.systempreferences:com.apple.Notifications-Settings.extension",
    "x-apple.systempreferences:com.apple.preference.notifications",
)
_BATTERY_SETTINGS_URLS = (
    "x-apple.systempreferences:com.apple.Battery-Settings.extension",
    "x-apple.systempreferences:com.apple.preference.battery",
)
_MOUSE_SETTINGS_URLS = (
    "x-apple.systempreferences:com.apple.Mouse-Settings.extension",
    "x-apple.systempreferences:com.apple.preference.mouse",
)
_TRACKPAD_SETTINGS_URLS = (
    "x-apple.systempreferences:com.apple.Trackpad-Settings.extension",
    "x-apple.systempreferences:com.apple.preference.trackpad",
)
_PRINTERS_SETTINGS_URLS = (
    "x-apple.systempreferences:com.apple.Print-Scan-Settings.extension",
    "x-apple.systempreferences:com.apple.preference.printfax",
)
_FOCUS_SETTINGS_URLS = (
    "x-apple.systempreferences:com.apple.Focus-Settings.extension",
    "x-apple.systempreferences:com.apple.preference.notifications?Focus",
)
_WALLPAPER_SETTINGS_URLS = (
    "x-apple.systempreferences:com.apple.Wallpaper-Settings.extension",
    "x-apple.systempreferences:com.apple.preference.desktopscreeneffect",
)
_DESKTOP_DOCK_SETTINGS_URLS = (
    "x-apple.systempreferences:com.apple.Desktop-Settings.extension",
    "x-apple.systempreferences:com.apple.preference.dock",
)
_SCREEN_SAVER_SETTINGS_URLS = (
    "x-apple.systempreferences:com.apple.ScreenSaver-Settings.extension",
    "x-apple.systempreferences:com.apple.preference.desktopscreeneffect?ScreenSaver",
)
_SIRI_SETTINGS_URLS = (
    "x-apple.systempreferences:com.apple.Siri-Settings.extension",
    "x-apple.systempreferences:com.apple.preference.speech?Siri",
)
_LANGUAGE_REGION_SETTINGS_URLS = (
    "x-apple.systempreferences:com.apple.Localization-Settings.extension",
    "x-apple.systempreferences:com.apple.Localization",
)
_DATE_TIME_SETTINGS_URLS = (
    "x-apple.systempreferences:com.apple.Date-Time-Settings.extension",
    "x-apple.systempreferences:com.apple.preference.datetime",
)
_SOFTWARE_UPDATE_SETTINGS_URLS = (
    "x-apple.systempreferences:com.apple.Software-Update-Settings.extension",
    "x-apple.systempreferences:com.apple.preferences.softwareupdate",
)
_STORAGE_SETTINGS_URLS = (
    "x-apple.systempreferences:com.apple.Storage-Settings.extension",
    "x-apple.systempreferences:com.apple.settings.Storage",
)
_LOGIN_ITEMS_SETTINGS_URLS = (
    "x-apple.systempreferences:com.apple.LoginItems-Settings.extension",
    "x-apple.systempreferences:com.apple.LoginItems-Settings.extension",
)
_USERS_GROUPS_SETTINGS_URLS = (
    "x-apple.systempreferences:com.apple.Users-Groups-Settings.extension",
    "x-apple.systempreferences:com.apple.preferences.users",
)

_SYSTEM_SETTINGS_TARGETS = {
    "privacysecurity": ("Privacy & Security", _PRIVACY_SECURITY_URLS),
    "privacyandsecurity": ("Privacy & Security", _PRIVACY_SECURITY_URLS),
    "securityprivacy": ("Privacy & Security", _PRIVACY_SECURITY_URLS),
    "securityandprivacy": ("Privacy & Security", _PRIVACY_SECURITY_URLS),
    "隐私与安全性": ("Privacy & Security", _PRIVACY_SECURITY_URLS),
    "隐私和安全性": ("Privacy & Security", _PRIVACY_SECURITY_URLS),
    "隐私安全": ("Privacy & Security", _PRIVACY_SECURITY_URLS),
    "安全性与隐私": ("Privacy & Security", _PRIVACY_SECURITY_URLS),
    "安全与隐私": ("Privacy & Security", _PRIVACY_SECURITY_URLS),
    "桌面权限": ("Privacy & Security", _PRIVACY_SECURITY_URLS),
    "桌面执行权限": ("Privacy & Security", _PRIVACY_SECURITY_URLS),
    "本地工具权限": ("Privacy & Security", _PRIVACY_SECURITY_URLS),
    "权限诊断": ("Privacy & Security", _PRIVACY_SECURITY_URLS),
    "bluetooth": ("Bluetooth", _BLUETOOTH_SETTINGS_URLS),
    "蓝牙": ("Bluetooth", _BLUETOOTH_SETTINGS_URLS),
    "network": ("Network", _NETWORK_SETTINGS_URLS),
    "网络": ("Network", _NETWORK_SETTINGS_URLS),
    "wifi": ("Wi-Fi", _WIFI_SETTINGS_URLS),
    "无线网络": ("Wi-Fi", _WIFI_SETTINGS_URLS),
    "无线局域网": ("Wi-Fi", _WIFI_SETTINGS_URLS),
    "display": ("Displays", _DISPLAY_SETTINGS_URLS),
    "displays": ("Displays", _DISPLAY_SETTINGS_URLS),
    "显示器": ("Displays", _DISPLAY_SETTINGS_URLS),
    "显示": ("Displays", _DISPLAY_SETTINGS_URLS),
    "sound": ("Sound", _SOUND_SETTINGS_URLS),
    "sounds": ("Sound", _SOUND_SETTINGS_URLS),
    "声音": ("Sound", _SOUND_SETTINGS_URLS),
    "声音设置": ("Sound", _SOUND_SETTINGS_URLS),
    "keyboard": ("Keyboard", _KEYBOARD_SETTINGS_URLS),
    "键盘": ("Keyboard", _KEYBOARD_SETTINGS_URLS),
    "键盘设置": ("Keyboard", _KEYBOARD_SETTINGS_URLS),
    "notifications": ("Notifications", _NOTIFICATIONS_SETTINGS_URLS),
    "notification": ("Notifications", _NOTIFICATIONS_SETTINGS_URLS),
    "通知": ("Notifications", _NOTIFICATIONS_SETTINGS_URLS),
    "通知设置": ("Notifications", _NOTIFICATIONS_SETTINGS_URLS),
    "battery": ("Battery", _BATTERY_SETTINGS_URLS),
    "电池": ("Battery", _BATTERY_SETTINGS_URLS),
    "电池设置": ("Battery", _BATTERY_SETTINGS_URLS),
    "mouse": ("Mouse", _MOUSE_SETTINGS_URLS),
    "鼠标": ("Mouse", _MOUSE_SETTINGS_URLS),
    "鼠标设置": ("Mouse", _MOUSE_SETTINGS_URLS),
    "trackpad": ("Trackpad", _TRACKPAD_SETTINGS_URLS),
    "触控板": ("Trackpad", _TRACKPAD_SETTINGS_URLS),
    "触控板设置": ("Trackpad", _TRACKPAD_SETTINGS_URLS),
    "printers": ("Printers & Scanners", _PRINTERS_SETTINGS_URLS),
    "printersscanners": ("Printers & Scanners", _PRINTERS_SETTINGS_URLS),
    "printersandscanners": ("Printers & Scanners", _PRINTERS_SETTINGS_URLS),
    "打印机": ("Printers & Scanners", _PRINTERS_SETTINGS_URLS),
    "打印机与扫描仪": ("Printers & Scanners", _PRINTERS_SETTINGS_URLS),
    "打印机和扫描仪": ("Printers & Scanners", _PRINTERS_SETTINGS_URLS),
    "专注模式": ("Focus", _FOCUS_SETTINGS_URLS),
    "focus": ("Focus", _FOCUS_SETTINGS_URLS),
    "wallpaper": ("Wallpaper", _WALLPAPER_SETTINGS_URLS),
    "墙纸": ("Wallpaper", _WALLPAPER_SETTINGS_URLS),
    "壁纸": ("Wallpaper", _WALLPAPER_SETTINGS_URLS),
    "desktopdock": ("Desktop & Dock", _DESKTOP_DOCK_SETTINGS_URLS),
    "desktopanddock": ("Desktop & Dock", _DESKTOP_DOCK_SETTINGS_URLS),
    "桌面与程序坞": ("Desktop & Dock", _DESKTOP_DOCK_SETTINGS_URLS),
    "桌面和程序坞": ("Desktop & Dock", _DESKTOP_DOCK_SETTINGS_URLS),
    "程序坞": ("Desktop & Dock", _DESKTOP_DOCK_SETTINGS_URLS),
    "dock": ("Desktop & Dock", _DESKTOP_DOCK_SETTINGS_URLS),
    "screensaver": ("Screen Saver", _SCREEN_SAVER_SETTINGS_URLS),
    "screen saver": ("Screen Saver", _SCREEN_SAVER_SETTINGS_URLS),
    "屏幕保护程序": ("Screen Saver", _SCREEN_SAVER_SETTINGS_URLS),
    "屏幕保护": ("Screen Saver", _SCREEN_SAVER_SETTINGS_URLS),
    "siri": ("Siri", _SIRI_SETTINGS_URLS),
    "siri与聚焦": ("Siri", _SIRI_SETTINGS_URLS),
    "siri和聚焦": ("Siri", _SIRI_SETTINGS_URLS),
    "languageregion": ("Language & Region", _LANGUAGE_REGION_SETTINGS_URLS),
    "languageandregion": ("Language & Region", _LANGUAGE_REGION_SETTINGS_URLS),
    "语言与地区": ("Language & Region", _LANGUAGE_REGION_SETTINGS_URLS),
    "语言和地区": ("Language & Region", _LANGUAGE_REGION_SETTINGS_URLS),
    "datetime": ("Date & Time", _DATE_TIME_SETTINGS_URLS),
    "dateandtime": ("Date & Time", _DATE_TIME_SETTINGS_URLS),
    "日期与时间": ("Date & Time", _DATE_TIME_SETTINGS_URLS),
    "日期和时间": ("Date & Time", _DATE_TIME_SETTINGS_URLS),
    "softwareupdate": ("Software Update", _SOFTWARE_UPDATE_SETTINGS_URLS),
    "软件更新": ("Software Update", _SOFTWARE_UPDATE_SETTINGS_URLS),
    "storage": ("Storage", _STORAGE_SETTINGS_URLS),
    "储存空间": ("Storage", _STORAGE_SETTINGS_URLS),
    "存储空间": ("Storage", _STORAGE_SETTINGS_URLS),
    "loginitems": ("Login Items", _LOGIN_ITEMS_SETTINGS_URLS),
    "登录项": ("Login Items", _LOGIN_ITEMS_SETTINGS_URLS),
    "usersgroups": ("Users & Groups", _USERS_GROUPS_SETTINGS_URLS),
    "usersandgroups": ("Users & Groups", _USERS_GROUPS_SETTINGS_URLS),
    "用户与群组": ("Users & Groups", _USERS_GROUPS_SETTINGS_URLS),
    "用户和群组": ("Users & Groups", _USERS_GROUPS_SETTINGS_URLS),
    "accessibility": (
        "Accessibility Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",),
    ),
    "assistive": (
        "Accessibility Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",),
    ),
    "辅助功能": (
        "Accessibility Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",),
    ),
    "无障碍": (
        "Accessibility Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",),
    ),
    "screenrecording": (
        "Screen Recording Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",),
    ),
    "screencapture": (
        "Screen Recording Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",),
    ),
    "屏幕录制": (
        "Screen Recording Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",),
    ),
    "屏幕录像": (
        "Screen Recording Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",),
    ),
    "automation": (
        "Automation Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_Automation",),
    ),
    "appleevents": (
        "Automation Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_Automation",),
    ),
    "自动化": (
        "Automation Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_Automation",),
    ),
    "fulldiskaccess": (
        "Full Disk Access",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles",),
    ),
    "完全磁盘访问": (
        "Full Disk Access",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles",),
    ),
    "filesandfolders": (
        "Files and Folders Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_ApplicationData",),
    ),
    "文件和文件夹": (
        "Files and Folders Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_ApplicationData",),
    ),
    "inputmonitoring": (
        "Input Monitoring Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",),
    ),
    "输入监控": (
        "Input Monitoring Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",),
    ),
    "microphone": (
        "Microphone Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",),
    ),
    "麦克风": (
        "Microphone Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",),
    ),
    "camera": (
        "Camera Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_Camera",),
    ),
    "摄像头": (
        "Camera Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_Camera",),
    ),
    "相机": (
        "Camera Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_Camera",),
    ),
    "locationservices": (
        "Location Services Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_LocationServices",),
    ),
    "定位服务": (
        "Location Services Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_LocationServices",),
    ),
}

_PERMISSION_CAPABILITY_TOOLS = {
    "screen_capture": ("screen.capture",),
    "active_window": (
        "desktop.active_window",
        "desktop.running_apps",
        "desktop.windows",
        "desktop.ui_elements",
        "desktop.click_ui_element",
        "desktop.type_into_ui_element",
    ),
    "app_control": (
        "app.status",
        "app.open",
        "system.settings_open",
        "app.focus",
        "app.focus_window",
        "app.show",
        "app.hide",
        "app.minimize",
        "app.quit",
        "desktop.reveal_path",
        "desktop.open_path",
        "system.display_sleep",
        "system.screen_saver_start",
        "notes.create",
        "reminders.create",
        "calendar.create_event",
    ),
    "media_control": (
        "media.system_control",
        "media.apple_music_play",
        "media.apple_music_status",
        "media.apple_music_open_and_play",
        "media.apple_music_control",
        "media.music_app_control",
    ),
    "foreground_input": (
        "media.music_app_open_and_play",
        "media.music_app_control",
        "app.open_and_safe_type_text",
        "app.focus_and_safe_type_text",
        "app.open_and_safe_shortcut",
        "app.focus_and_safe_shortcut",
        "app.open_and_safe_key",
        "app.focus_and_safe_key",
        "app.open_and_hotkey",
        "app.focus_and_hotkey",
        "app.open_and_safe_scroll",
        "app.focus_and_safe_scroll",
        "app.open_and_safe_click",
        "app.focus_and_safe_click",
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
        "app.open_and_type_into_ui_element",
        "app.focus_and_type_into_ui_element",
        "desktop.hide_app",
        "desktop.show_all_apps",
        "desktop.minimize_window",
        "desktop.close_window",
        "desktop.safe_shortcut",
        "desktop.safe_key",
        "desktop.search_submit",
        "desktop.submit_foreground",
        "desktop.safe_type_text",
        "desktop.safe_click",
        "desktop.safe_scroll",
        "desktop.click_ui_element",
        "desktop.type_into_ui_element",
        "desktop.hotkey",
        "desktop.type_text",
        "desktop.click",
    ),
    "browser_control": (
        "browser.open_url",
        "browser.open_url_and_extract_text",
        "browser.open_url_and_screenshot",
        "browser.current_page",
        "browser.click",
        "browser.type_text",
        "browser.extract_text",
        "browser.screenshot",
    ),
}

_PERMISSION_RECOVERY_ACTIONS = {
    "screen_recording": (
        {
            "label": "打开屏幕录制权限",
            "tool": "system.settings_open",
            "input": {"target": "屏幕录制权限"},
            "permission_target": "screen_recording",
            "risk_level": "low",
        },
    ),
    "screen_capture_probe_failed": (
        {
            "label": "打开屏幕录制权限",
            "tool": "system.settings_open",
            "input": {"target": "屏幕录制权限"},
            "permission_target": "screen_recording",
            "risk_level": "low",
        },
    ),
    "automation": (
        {
            "label": "打开自动化权限",
            "tool": "system.settings_open",
            "input": {"target": "自动化权限"},
            "permission_target": "automation",
            "risk_level": "low",
        },
    ),
    "automation_or_accessibility": (
        {
            "label": "打开自动化权限",
            "tool": "system.settings_open",
            "input": {"target": "自动化权限"},
            "permission_target": "automation",
            "risk_level": "low",
        },
        {
            "label": "打开辅助功能权限",
            "tool": "system.settings_open",
            "input": {"target": "辅助功能权限"},
            "permission_target": "accessibility",
            "risk_level": "low",
        },
    ),
    "accessibility": (
        {
            "label": "打开辅助功能权限",
            "tool": "system.settings_open",
            "input": {"target": "辅助功能权限"},
            "permission_target": "accessibility",
            "risk_level": "low",
        },
    ),
    "input_monitoring": (
        {
            "label": "打开输入监控权限",
            "tool": "system.settings_open",
            "input": {"target": "输入监控"},
            "permission_target": "input_monitoring",
            "risk_level": "low",
        },
    ),
    "full_disk_access": (
        {
            "label": "打开完全磁盘访问权限",
            "tool": "system.settings_open",
            "input": {"target": "完全磁盘访问"},
            "permission_target": "full_disk_access",
            "risk_level": "low",
        },
    ),
    "files_and_folders": (
        {
            "label": "打开文件和文件夹权限",
            "tool": "system.settings_open",
            "input": {"target": "文件和文件夹"},
            "permission_target": "files_and_folders",
            "risk_level": "low",
        },
    ),
    "microphone": (
        {
            "label": "打开麦克风权限",
            "tool": "system.settings_open",
            "input": {"target": "麦克风"},
            "permission_target": "microphone",
            "risk_level": "low",
        },
    ),
    "camera": (
        {
            "label": "打开摄像头权限",
            "tool": "system.settings_open",
            "input": {"target": "摄像头"},
            "permission_target": "camera",
            "risk_level": "low",
        },
    ),
    "music_app": (
        {
            "label": "打开 Apple Music",
            "tool": "app.open",
            "input": {"app_name": "Music"},
            "permission_target": "music_app",
            "risk_level": "low",
        },
    ),
    "chrome_cdp": (
        {
            "label": "打开 Google Chrome",
            "tool": "app.open",
            "input": {"app_name": "Google Chrome"},
            "permission_target": "chrome_cdp",
            "risk_level": "low",
        },
    ),
}


def screen_capture(target_path: Path) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("screen.capture")
    from apps.locald.screenshot import capture_screenshot_to_file

    try:
        metadata = capture_screenshot_to_file(target_path)
    except Exception as exc:
        return _error("screen.capture", exc)
    return {
        "ok": True,
        "action": "screen.capture",
        "summary": (
            f"Captured screen {metadata.get('width', 0)}x{metadata.get('height', 0)} "
            f"{str(metadata.get('format') or 'png').upper()}"
        ),
        "data": metadata,
        "permission_error": False,
        "fallback_used": False,
    }


def active_window() -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.active_window")
    script = """
    tell application "System Events"
        set frontApp to first application process whose frontmost is true
        set appName to name of frontApp
        set appPID to unix id of frontApp
        try
            set winTitle to name of front window of frontApp
        on error
            set winTitle to ""
        end try
        return appName & "|" & appPID & "|" & winTitle
    end tell
    """
    result = _run_osascript(script)
    if not result["ok"]:
        return _with_permission_metadata(
            "desktop.active_window",
            {**result, "action": "desktop.active_window", "summary": "desktop.active_window failed"},
        )
    parts = str(result.get("stdout") or "").strip().split("|", 2)
    app_name = parts[0] if len(parts) > 0 else ""
    pid_text = parts[1] if len(parts) > 1 else ""
    title = parts[2] if len(parts) > 2 else ""
    return {
        "ok": True,
        "action": "desktop.active_window",
        "summary": f"Active window: {app_name}{f' - {title}' if title else ''}",
        "data": {
            "app_name": app_name,
            "pid": int(pid_text) if pid_text.isdigit() else None,
            "title": title,
        },
        "permission_error": False,
        "fallback_used": False,
    }


def ui_elements(role_filter: str = "", limit: Any = 80) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.ui_elements")
    clean_filter = str(role_filter or "").strip()
    try:
        clean_limit = max(1, min(200, int(limit or 80)))
    except (TypeError, ValueError):
        clean_limit = 80
    script = """
    on replaceText(findText, replaceTextValue, sourceText)
        set oldDelimiters to AppleScript's text item delimiters
        set AppleScript's text item delimiters to findText
        set textItems to text items of sourceText
        set AppleScript's text item delimiters to replaceTextValue
        set joinedText to textItems as text
        set AppleScript's text item delimiters to oldDelimiters
        return joinedText
    end replaceText

    on cleanText(valueToClean)
        try
            set cleaned to valueToClean as text
        on error
            set cleaned to ""
        end try
        set cleaned to my replaceText(tab, " ", cleaned)
        set cleaned to my replaceText(linefeed, " ", cleaned)
        set cleaned to my replaceText(return, " ", cleaned)
        return cleaned
    end cleanText

    on joinRows(rowList)
        set oldDelimiters to AppleScript's text item delimiters
        set AppleScript's text item delimiters to linefeed
        set joinedRows to rowList as text
        set AppleScript's text item delimiters to oldDelimiters
        return joinedRows
    end joinRows

    on elementRow(targetElement, depthValue)
        set roleText to ""
        set subroleText to ""
        set nameText to ""
        set descriptionText to ""
        set valueText to ""
        set enabledText to ""
        set xText to ""
        set yText to ""
        set widthText to ""
        set heightText to ""
        try
            set roleText to my cleanText(role of targetElement)
        end try
        try
            set subroleText to my cleanText(subrole of targetElement)
        end try
        try
            set nameText to my cleanText(name of targetElement)
        end try
        try
            set descriptionText to my cleanText(description of targetElement)
        end try
        try
            set valueText to my cleanText(value of targetElement)
        end try
        try
            set enabledText to my cleanText(enabled of targetElement)
        end try
        try
            set positionValue to position of targetElement
            set xText to item 1 of positionValue as text
            set yText to item 2 of positionValue as text
        end try
        try
            set sizeValue to size of targetElement
            set widthText to item 1 of sizeValue as text
            set heightText to item 2 of sizeValue as text
        end try
        return (depthValue as text) & tab & roleText & tab & subroleText & tab & nameText & tab & descriptionText & tab & valueText & tab & enabledText & tab & xText & tab & yText & tab & widthText & tab & heightText
    end elementRow

    on collectElements(containerElement, depthValue, maxDepth, maxItems)
        set rows to {}
        if depthValue > maxDepth then return rows
        try
            set childElements to UI elements of containerElement
        on error
            return rows
        end try
        repeat with childElement in childElements
            if (count of rows) >= maxItems then exit repeat
            set end of rows to my elementRow(childElement, depthValue)
            if depthValue < maxDepth then
                set childRows to my collectElements(childElement, depthValue + 1, maxDepth, maxItems - (count of rows))
                repeat with childRow in childRows
                    if (count of rows) >= maxItems then exit repeat
                    set end of rows to childRow as text
                end repeat
            end if
        end repeat
        return rows
    end collectElements

    on run argv
        set maxItems to item 1 of argv as integer
        set maxDepth to item 2 of argv as integer
        tell application "System Events"
            set frontApp to first application process whose frontmost is true
            set appName to my cleanText(name of frontApp)
            set appPID to unix id of frontApp
            try
                set frontWindow to front window of frontApp
                set windowTitle to my cleanText(name of frontWindow)
                set rows to my collectElements(frontWindow, 0, maxDepth, maxItems)
            on error
                set windowTitle to ""
                set rows to my collectElements(frontApp, 0, maxDepth, maxItems)
            end try
            set header to "META" & tab & appName & tab & (appPID as text) & tab & windowTitle
            if (count of rows) is 0 then return header
            return header & linefeed & my joinRows(rows)
        end tell
    end run
    """
    result = _run_osascript(script, [str(clean_limit), "2"])
    if not result["ok"]:
        return _with_permission_metadata(
            "desktop.ui_elements",
            {**result, "action": "desktop.ui_elements", "summary": "desktop.ui_elements failed"},
        )
    parsed = _parse_ui_elements_output(result.get("stdout"), clean_filter, clean_limit)
    return {
        "ok": True,
        "action": "desktop.ui_elements",
        "summary": _ui_elements_summary(parsed.get("elements", []), parsed.get("app_name", "")),
        "data": {
            **parsed,
            "role_filter": clean_filter,
            "limit": clean_limit,
        },
        "permission_error": False,
        "fallback_used": False,
    }


def click_ui_element(
    target: str,
    *,
    role_filter: str = "",
    limit: Any = 80,
    click_count: Any = 1,
) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.click_ui_element")
    clean_target = _clean_required(target, "target")
    clean_filter = str(role_filter or "").strip()
    clean_count = _clean_click_count(click_count)
    observed = ui_elements(role_filter=clean_filter, limit=limit)
    observed_data = observed.get("data") if isinstance(observed.get("data"), dict) else {}
    if not observed.get("ok"):
        payload = {
            **observed,
            "action": "desktop.click_ui_element",
            "summary": "Could not observe foreground UI elements before clicking",
            "data": {
                **dict(observed_data),
                "target": clean_target,
                "role_filter": clean_filter,
                "click_count": clean_count,
            },
            "fallback_result": {"observe": observed},
        }
        return _with_permission_metadata("desktop.click_ui_element", payload)

    elements = observed_data.get("elements") if isinstance(observed_data.get("elements"), list) else []
    matches = _matching_ui_elements(elements, clean_target, clean_filter)
    if not matches:
        return {
            "ok": False,
            "action": "desktop.click_ui_element",
            "summary": f"No foreground UI element matched: {clean_target}",
            "error": "ui_element_not_found",
            "data": {
                "target": clean_target,
                "role_filter": clean_filter,
                "click_count": clean_count,
                "app_name": str(observed_data.get("app_name") or ""),
                "title": str(observed_data.get("title") or ""),
                "observed_count": len(elements),
                "candidates": _candidate_ui_element_previews(elements),
            },
            "permission_error": False,
            "fallback_used": False,
            "fallback_result": {"observe": observed},
        }

    match = matches[0]
    center = match.get("center") if isinstance(match.get("center"), dict) else {}
    x = center.get("x")
    y = center.get("y")
    click_result = _send_desktop_click(
        "desktop.click_ui_element",
        x,
        y,
        click_count=clean_count,
    )
    click_data = click_result.get("data") if isinstance(click_result.get("data"), dict) else {}
    label = _ui_element_display_label(match) or clean_target
    data = {
        **dict(click_data),
        "target": clean_target,
        "matched_label": label,
        "role_filter": clean_filter,
        "app_name": str(observed_data.get("app_name") or ""),
        "title": str(observed_data.get("title") or ""),
        "observed_count": len(elements),
        "match_count": len(matches),
        "element": match,
    }
    if click_result.get("ok"):
        return {
            **click_result,
            "summary": f"Clicked foreground UI element: {label}",
            "data": data,
            "fallback_result": {"observe": observed},
        }
    payload = {
        **click_result,
        "action": "desktop.click_ui_element",
        "summary": f"Matched foreground UI element but click failed: {label}",
        "data": data,
        "fallback_result": {"observe": observed},
    }
    return _with_permission_metadata("desktop.click_ui_element", payload)


def type_into_ui_element(
    target: str,
    text: str,
    *,
    role_filter: str = "",
    limit: Any = 80,
) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.type_into_ui_element")
    clean_target = _clean_required(target, "target")
    clean_text = _clean_required(text, "text")
    clean_filter = str(role_filter or "").strip() or "text"
    observed = ui_elements(role_filter=clean_filter, limit=limit)
    observed_data = observed.get("data") if isinstance(observed.get("data"), dict) else {}
    if not observed.get("ok"):
        payload = {
            **observed,
            "action": "desktop.type_into_ui_element",
            "summary": "Could not observe foreground UI elements before typing",
            "data": {
                **dict(observed_data),
                "target": clean_target,
                "role_filter": clean_filter,
                "character_count": len(clean_text),
            },
            "fallback_result": {"observe": observed},
        }
        return _with_permission_metadata("desktop.type_into_ui_element", payload)

    elements = observed_data.get("elements") if isinstance(observed_data.get("elements"), list) else []
    matches = _matching_ui_elements(elements, clean_target, clean_filter)
    if not matches:
        return {
            "ok": False,
            "action": "desktop.type_into_ui_element",
            "summary": f"No foreground UI element matched for typing: {clean_target}",
            "error": "ui_element_not_found",
            "data": {
                "target": clean_target,
                "role_filter": clean_filter,
                "character_count": len(clean_text),
                "app_name": str(observed_data.get("app_name") or ""),
                "title": str(observed_data.get("title") or ""),
                "observed_count": len(elements),
                "candidates": _candidate_ui_element_previews(elements),
            },
            "permission_error": False,
            "fallback_used": False,
            "fallback_result": {"observe": observed},
        }

    match = matches[0]
    center = match.get("center") if isinstance(match.get("center"), dict) else {}
    label = _ui_element_display_label(match) or clean_target
    click_result = _send_desktop_click(
        "desktop.type_into_ui_element",
        center.get("x"),
        center.get("y"),
        click_count=1,
    )
    click_data = click_result.get("data") if isinstance(click_result.get("data"), dict) else {}
    base_data = {
        **dict(click_data),
        "target": clean_target,
        "matched_label": label,
        "role_filter": clean_filter,
        "character_count": len(clean_text),
        "app_name": str(observed_data.get("app_name") or ""),
        "title": str(observed_data.get("title") or ""),
        "observed_count": len(elements),
        "match_count": len(matches),
        "element": match,
    }
    if not click_result.get("ok"):
        payload = {
            **click_result,
            "action": "desktop.type_into_ui_element",
            "summary": f"Matched foreground UI element but focus click failed: {label}",
            "data": base_data,
            "fallback_result": {"observe": observed, "focus": click_result},
        }
        return _with_permission_metadata("desktop.type_into_ui_element", payload)

    type_result = _send_desktop_text(
        "desktop.type_into_ui_element",
        clean_text,
        summary=f"Typed into foreground UI element: {label}",
    )
    type_data = type_result.get("data") if isinstance(type_result.get("data"), dict) else {}
    data = {**base_data, **dict(type_data)}
    if type_result.get("ok"):
        return {
            **type_result,
            "summary": f"Typed into foreground UI element: {label}",
            "data": data,
            "fallback_result": {"observe": observed, "focus": click_result, "type_text": type_result},
        }
    payload = {
        **type_result,
        "action": "desktop.type_into_ui_element",
        "summary": f"Focused foreground UI element but typing failed: {label}",
        "data": data,
        "fallback_result": {"observe": observed, "focus": click_result, "type_text": type_result},
    }
    return _with_permission_metadata("desktop.type_into_ui_element", payload)


def permissions() -> dict[str, Any]:
    """Return desktop execution permission readiness for observable diagnostics."""

    from apps.shell.yachiyo_agent.desktop_permissions import (
        desktop_permission_missing_by_capability,
    )

    try:
        missing_by_capability = desktop_permission_missing_by_capability(use_cache=True)
    except Exception as exc:
        return _error("desktop.permissions", exc)

    clean_missing = _clean_missing_permissions_by_capability(missing_by_capability)
    missing_targets = _ordered_unique(
        target for targets in clean_missing.values() for target in targets
    )
    affected_tools = _affected_tools_for_missing_permissions(clean_missing)
    ready = not missing_targets
    summary = _desktop_permissions_summary(missing_targets, affected_tools)
    recovery_hints = _permission_recovery_hints_for_targets(missing_targets)
    recovery_actions = _permission_recovery_actions_for_targets(missing_targets)
    return {
        "ok": True,
        "action": "desktop.permissions",
        "summary": summary,
        "data": {
            "ready": ready,
            "missing_permissions": clean_missing,
            "permission_targets": missing_targets,
            "affected_tools": affected_tools,
            "recovery_actions": recovery_actions,
            "diagnostic_route": "/yachiyo/readiness",
        },
        "missing_permissions": missing_targets,
        "permission_targets": missing_targets,
        "affected_tools": affected_tools,
        "recovery_hints": recovery_hints,
        "recovery_actions": recovery_actions,
        "diagnostic_route": "/yachiyo/readiness",
        "permission_error": not ready,
        "fallback_used": False,
    }


def permission_preflight() -> dict[str, Any]:
    """Return cached desktop permission readiness without running fresh probes."""

    from apps.shell.yachiyo_agent.desktop_permissions import (
        cached_desktop_permission_missing_by_capability,
    )

    clean_missing = _clean_missing_permissions_by_capability(
        cached_desktop_permission_missing_by_capability()
    )
    missing_targets = _ordered_unique(
        target for targets in clean_missing.values() for target in targets
    )
    affected_tools = _affected_tools_for_missing_permissions(clean_missing)
    ready = not missing_targets
    summary = _desktop_permissions_summary(missing_targets, affected_tools)
    recovery_hints = _permission_recovery_hints_for_targets(missing_targets)
    recovery_actions = _permission_recovery_actions_for_targets(missing_targets)
    return {
        "ok": True,
        "action": "desktop.permission_preflight",
        "summary": summary,
        "data": {
            "ready": ready,
            "missing_permissions": clean_missing,
            "permission_targets": missing_targets,
            "affected_tools": affected_tools,
            "recovery_actions": recovery_actions,
            "diagnostic_route": "/yachiyo/readiness",
        },
        "missing_permissions": missing_targets,
        "permission_targets": missing_targets,
        "affected_tools": affected_tools,
        "recovery_hints": recovery_hints,
        "recovery_actions": recovery_actions,
        "diagnostic_route": "/yachiyo/readiness",
        "permission_error": not ready,
        "fallback_used": False,
    }


def running_apps() -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.running_apps")
    script = """
    tell application "System Events"
        set rows to {}
        repeat with proc in (application processes whose background only is false)
            set appName to name of proc
            set appPID to unix id of proc
            set appFront to frontmost of proc
            set end of rows to appName & "|" & appPID & "|" & appFront
        end repeat
        set AppleScript's text item delimiters to linefeed
        set output to rows as text
        set AppleScript's text item delimiters to ""
        return output
    end tell
    """
    result = _run_osascript(script)
    if not result["ok"]:
        return _with_permission_metadata(
            "desktop.running_apps",
            {**result, "action": "desktop.running_apps", "summary": "desktop.running_apps failed"},
        )
    apps = _parse_running_apps(result.get("stdout"))
    names = [str(app.get("name") or "") for app in apps if str(app.get("name") or "")]
    return {
        "ok": True,
        "action": "desktop.running_apps",
        "summary": _running_apps_summary(names),
        "data": {
            "apps": apps,
            "count": len(apps),
            "frontmost": next((app.get("name") for app in apps if app.get("frontmost")), ""),
        },
        "permission_error": False,
        "fallback_used": False,
    }


def windows(app_name: str = "") -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.windows")
    clean_app = str(app_name or "").strip()
    script = """
    on run argv
        set appFilter to item 1 of argv
        tell application "System Events"
            set rows to {}
            repeat with proc in (application processes whose background only is false)
                set appName to name of proc
                if appFilter is "" or appName is appFilter then
                    set appPID to unix id of proc
                    set appFront to frontmost of proc
                    try
                        set winCount to count of windows of proc
                    on error
                        set winCount to 0
                    end try
                    repeat with winIndex from 1 to winCount
                        try
                            set winTitle to name of window winIndex of proc
                        on error
                            set winTitle to ""
                        end try
                        set end of rows to appName & tab & appPID & tab & winIndex & tab & appFront & tab & winTitle
                    end repeat
                end if
            end repeat
            set AppleScript's text item delimiters to linefeed
            set output to rows as text
            set AppleScript's text item delimiters to ""
            return output
        end tell
    end run
    """
    result = _run_osascript(script, [clean_app])
    if not result["ok"]:
        return _with_permission_metadata(
            "desktop.windows",
            {
                **result,
                "action": "desktop.windows",
                "summary": "desktop.windows failed",
                "data": {"app_name": clean_app},
            },
        )
    windows_payload = _parse_window_rows(result.get("stdout"))
    return {
        "ok": True,
        "action": "desktop.windows",
        "summary": _windows_summary(windows_payload, clean_app),
        "data": {
            "app_name": clean_app,
            "windows": windows_payload,
            "count": len(windows_payload),
        },
        "permission_error": False,
        "fallback_used": False,
    }


def app_status(app_name: str) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("app.status")
    clean_name = _clean_required(app_name, "app_name")
    result = _run_osascript(
        """
        on run argv
            set appName to item 1 of argv
            if application appName is running then
                return "running"
            end if
            return "not_running"
        end run
        """,
        [clean_name],
    )
    if not result["ok"]:
        return _with_permission_metadata(
            "app.status",
            {
                **result,
                "action": "app.status",
                "summary": "app.status failed",
                "data": {"app_name": clean_name},
            },
        )
    status = str(result.get("stdout") or "").strip()
    running = status == "running"
    return {
        "ok": True,
        "action": "app.status",
        "summary": f"{clean_name} is {'running' if running else 'not running'}",
        "data": {
            "app_name": clean_name,
            "running": running,
            "status": status or "unknown",
        },
        "permission_error": False,
        "fallback_used": False,
    }


def app_open(app_name: str) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("app.open")
    clean_name = _clean_required(app_name, "app_name")
    settings_target = _system_settings_target(clean_name)
    if settings_target is not None:
        return _open_system_settings_target(clean_name, settings_target)
    folder_path = _common_folder_path(clean_name)
    if folder_path is not None:
        return _open_common_folder(clean_name, folder_path)
    try:
        result = subprocess.run(
            ["open", "-a", clean_name],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return _error("app.open", exc)
    if result.returncode != 0:
        return _app_open_failed(clean_name, result)
    verification = _app_running_verification(clean_name)
    return {
        "ok": True,
        "action": "app.open",
        "summary": f"Opened {clean_name}",
        "data": {"app_name": clean_name, **verification},
        "permission_error": False,
        "fallback_used": False,
    }


def system_settings_open(target: str) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("system.settings_open")
    clean_target = _clean_required(target, "target")
    settings_target = _system_settings_target(clean_target)
    if settings_target is not None:
        return _open_system_settings_target(
            clean_target,
            settings_target,
            action="system.settings_open",
        )
    if _looks_like_system_settings_home(clean_target):
        return _open_system_settings_home(clean_target)
    return {
        "ok": False,
        "action": "system.settings_open",
        "summary": "system.settings_open failed",
        "error": f"Unknown System Settings target: {clean_target}",
        "error_code": "unknown_system_settings_target",
        "data": {"target": clean_target, "open_target": "system_settings"},
        "permission_error": False,
        "fallback_used": False,
    }


def reveal_path(path: str) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.reveal_path")
    clean_path = _clean_required(path, "path")
    special = _special_desktop_object_path(clean_path, "desktop.reveal_path", "finder_reveal")
    if special and "error_payload" in special:
        return special["error_payload"]
    target = special["target"] if special else _expanded_local_path(clean_path)
    data_base = special["data"] if special else {"path": clean_path, "expanded_path": str(target)}
    if not target.exists():
        return {
            "ok": False,
            "action": "desktop.reveal_path",
            "summary": "desktop.reveal_path failed",
            "error": f"Path not found: {clean_path}",
            "error_code": "path_not_found",
            "data": {
                **data_base,
                "open_target": "finder_reveal",
                "exists": False,
            },
            "permission_error": False,
            "fallback_used": False,
        }
    try:
        result = subprocess.run(
            ["open", "-R", str(target)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return _error("desktop.reveal_path", exc)
    if result.returncode != 0:
        payload = _failed("desktop.reveal_path", result)
        payload["data"] = {
            **data_base,
            "open_target": "finder_reveal",
            "exists": True,
            "is_dir": target.is_dir(),
        }
        return payload
    return {
        "ok": True,
        "action": "desktop.reveal_path",
        "summary": f"Revealed {target.name or str(target)} in Finder",
        "data": {
            **data_base,
            "open_target": "finder_reveal",
            "exists": True,
            "is_dir": target.is_dir(),
        },
        "permission_error": False,
        "fallback_used": False,
    }


def open_path(path: str) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.open_path")
    clean_path = _clean_required(path, "path")
    special = _special_desktop_object_path(clean_path, "desktop.open_path", "system_open")
    if special and "error_payload" in special:
        return special["error_payload"]
    target = special["target"] if special else _expanded_local_path(clean_path)
    data_base = special["data"] if special else {"path": clean_path, "expanded_path": str(target)}
    if not target.exists():
        return {
            "ok": False,
            "action": "desktop.open_path",
            "summary": "desktop.open_path failed",
            "error": f"Path not found: {clean_path}",
            "error_code": "path_not_found",
            "data": {
                **data_base,
                "open_target": "system_open",
                "exists": False,
            },
            "permission_error": False,
            "fallback_used": False,
        }
    safety_error = _unsafe_open_path_reason(target)
    if safety_error:
        return {
            "ok": False,
            "action": "desktop.open_path",
            "summary": "desktop.open_path blocked",
            "error": safety_error,
            "error_code": "unsafe_path_type",
            "data": {
                **data_base,
                "open_target": "system_open",
                "exists": True,
                "is_dir": target.is_dir(),
                "suffix": target.suffix.lower(),
            },
            "permission_error": False,
            "fallback_used": False,
        }
    try:
        result = subprocess.run(
            ["open", str(target)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return _error("desktop.open_path", exc)
    if result.returncode != 0:
        payload = _failed("desktop.open_path", result)
        payload["data"] = {
            **data_base,
            "open_target": "system_open",
            "exists": True,
            "is_dir": target.is_dir(),
            "suffix": target.suffix.lower(),
        }
        return payload
    return {
        "ok": True,
        "action": "desktop.open_path",
        "summary": f"Opened {target.name or str(target)}",
        "data": {
            **data_base,
            "open_target": "system_open",
            "exists": True,
            "is_dir": target.is_dir(),
            "suffix": target.suffix.lower(),
        },
        "permission_error": False,
        "fallback_used": False,
    }


def _unsafe_open_path_reason(target: Path) -> str:
    suffix = target.suffix.lower()
    if target.is_dir():
        if suffix in _UNSAFE_OPEN_PATH_SUFFIXES:
            return f"Refusing to open unsafe path type: {suffix}"
        return ""
    if suffix in _UNSAFE_OPEN_PATH_SUFFIXES:
        return f"Refusing to open unsafe path type: {suffix}"
    if suffix not in _SAFE_OPEN_PATH_SUFFIXES:
        return f"Refusing to open unknown file type: {suffix or 'no extension'}"
    return ""


def _open_common_folder(label: str, folder_path: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["open", str(folder_path)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return _error("app.open", exc)
    if result.returncode != 0:
        payload = _failed("app.open", result)
        payload["data"] = {
            "app_name": label,
            "path": str(folder_path),
            "open_target": "folder",
        }
        return payload
    return {
        "ok": True,
        "action": "app.open",
        "summary": f"Opened {folder_path.name or 'Home'}",
        "data": {
            "app_name": label,
            "path": str(folder_path),
            "open_target": "folder",
        },
        "permission_error": False,
        "fallback_used": False,
    }


def _open_system_settings_target(
    label: str,
    target: tuple[str, tuple[str, ...]],
    *,
    action: str = "app.open",
) -> dict[str, Any]:
    settings_label, urls = target
    errors: list[str] = []
    for index, url in enumerate(urls):
        try:
            result = subprocess.run(
                ["open", url],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except Exception as exc:
            return _error(action, exc)
        if result.returncode == 0:
            return {
                "ok": True,
                "action": action,
                "summary": f"Opened System Settings: {settings_label}",
                "data": _system_settings_open_data(
                    action,
                    label,
                    settings_label=settings_label,
                    settings_url=url,
                    fallback_used=index > 0,
                ),
                "permission_error": False,
                "fallback_used": index > 0,
            }
        error = "\n".join(
            part.strip()
            for part in (result.stderr, result.stdout)
            if isinstance(part, str) and part.strip()
        )
        errors.append(error or f"{url}: exit code {result.returncode}")
    payload = _failed(action, result)
    payload["data"] = _system_settings_open_data(
        action,
        label,
        settings_label=settings_label,
        attempted_urls=list(urls),
        settings_errors=errors,
    )
    return payload


def _open_system_settings_home(label: str) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["open", "-a", "System Settings"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return _error("system.settings_open", exc)
    if result.returncode != 0:
        payload = _failed("system.settings_open", result)
        payload["data"] = {
            "target": label,
            "open_target": "system_settings",
            "settings_label": "System Settings",
        }
        return payload
    return {
        "ok": True,
        "action": "system.settings_open",
        "summary": "Opened System Settings",
        "data": {
            "target": label,
            "open_target": "system_settings",
            "settings_label": "System Settings",
        },
        "permission_error": False,
        "fallback_used": False,
    }


def _system_settings_open_data(
    action: str,
    label: str,
    *,
    settings_label: str,
    settings_url: str | None = None,
    attempted_urls: list[str] | None = None,
    settings_errors: list[str] | None = None,
    fallback_used: bool | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "open_target": "system_settings",
        "settings_label": settings_label,
    }
    if action == "app.open":
        data["app_name"] = label
    else:
        data["target"] = label
    if settings_url is not None:
        data["settings_url"] = settings_url
    if attempted_urls is not None:
        data["attempted_urls"] = attempted_urls
    if settings_errors is not None:
        data["settings_errors"] = settings_errors
    if fallback_used is not None:
        data["fallback_used"] = fallback_used
    return data


def _system_settings_target(value: str) -> tuple[str, tuple[str, ...]] | None:
    variants = _system_settings_alias_variants(value)
    for variant in variants:
        target = _SYSTEM_SETTINGS_TARGETS.get(variant)
        if target is not None:
            return target
    return None


def _looks_like_system_settings_home(value: str) -> bool:
    variants = _system_settings_alias_variants(value)
    return any(
        variant
        in {
            "systemsettings",
            "systempreferences",
            "settings",
            "preferences",
            "系统设置",
            "系统偏好",
            "系统偏好设置",
            "设置",
            "偏好设置",
        }
        for variant in variants
    )


def _system_settings_alias_variants(value: str) -> list[str]:
    normalized = str(value or "").strip().lower()
    normalized = normalized.replace("&", "and")
    normalized = normalized.replace("-", " ").replace("_", " ")
    normalized = normalized.replace("设置的", " ")
    variants = [_compact_alias(normalized)]
    simplified = _strip_system_settings_noise(normalized)
    simplified_compact = _compact_alias(simplified)
    if simplified_compact and simplified_compact not in variants:
        variants.append(simplified_compact)
    return [variant for variant in variants if variant]


def _strip_system_settings_noise(value: str) -> str:
    return (
        str(value or "")
        .replace("系统设置", " ")
        .replace("设置", " ")
        .replace("里的", " ")
        .replace("中的", " ")
        .replace("里面的", " ")
        .replace("内的", " ")
        .replace("权限", " ")
        .replace("页面", " ")
        .replace("面板", " ")
        .replace("settings", " ")
        .replace("setting", " ")
        .replace("preferences", " ")
        .replace("preference", " ")
        .replace("permissions", " ")
        .replace("permission", " ")
        .replace("pane", " ")
        .replace("page", " ")
    )


def _compact_alias(value: str) -> str:
    return "".join(str(value or "").strip().split())


def _expanded_local_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve(strict=False)


def _special_desktop_object_path(
    value: str,
    action: str,
    open_target: str,
) -> dict[str, Any]:
    compact = re.sub(r"[\s._-]+", "", str(value or "").strip().lower())
    if compact in {
        "finderselection",
        "finderselecteditem",
        "selectedfinderitem",
        "selectedfile",
        "selecteditem",
    }:
        return _finder_selection_desktop_object_path(value, action, open_target)
    if compact in {"latestscreenshot", "recentscreenshot", "lastscreenshot"}:
        return _latest_screenshot_desktop_object_path(value, action, open_target)
    if compact in {
        "latestdesktopitem",
        "recentdesktopitem",
        "latestdesktopfile",
        "recentdesktopfile",
    }:
        return _latest_desktop_item_object_path(value, action, open_target)
    if compact not in {"latestdownload", "recentdownload"}:
        return {}
    downloads = Path.home() / "Downloads"
    base_data = {
        "path": str(value or "").strip(),
        "open_target": open_target,
        "desktop_object": "latest_download",
        "source_folder": str(downloads),
    }
    if not downloads.exists() or not downloads.is_dir():
        return {
            "error_payload": {
                "ok": False,
                "action": action,
                "summary": f"{action} failed",
                "error": "Downloads folder not found",
                "error_code": "downloads_folder_not_found",
                "data": {
                    **base_data,
                    "expanded_path": str(downloads),
                    "exists": False,
                    "source_exists": False,
                },
                "permission_error": False,
                "fallback_used": False,
            }
        }
    target = _latest_download_item(downloads)
    if target is None:
        return {
            "error_payload": {
                "ok": False,
                "action": action,
                "summary": f"{action} failed",
                "error": "No completed downloads found",
                "error_code": "latest_download_not_found",
                "data": {
                    **base_data,
                    "expanded_path": str(downloads),
                    "exists": False,
                    "source_exists": True,
                },
                "permission_error": False,
                "fallback_used": False,
            }
        }
    return {
        "target": target,
        "data": {
            **base_data,
            "expanded_path": str(target),
            "resolved_path": str(target),
            "display_path": str(target),
            "source_exists": True,
        },
    }


def _latest_download_item(downloads: Path) -> Path | None:
    candidates: list[tuple[float, Path]] = []
    try:
        items = list(downloads.iterdir())
    except OSError:
        return None
    for item in items:
        name = item.name
        if name.startswith(".") or name.lower().endswith((".download", ".crdownload", ".part")):
            continue
        try:
            candidates.append((item.stat().st_mtime, item))
        except OSError:
            continue
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _latest_screenshot_desktop_object_path(
    value: str,
    action: str,
    open_target: str,
) -> dict[str, Any]:
    home = Path.home()
    return _latest_desktop_object_from_folders(
        value,
        action,
        open_target,
        desktop_object="latest_screenshot",
        folders=[home / "Desktop", home / "Downloads", home / "Pictures"],
        matcher=_looks_like_screenshot_item,
        missing_error="Screenshot folders not found",
        missing_error_code="screenshot_folders_not_found",
        not_found_error="No recent screenshots found",
        not_found_error_code="latest_screenshot_not_found",
    )


def _latest_desktop_item_object_path(
    value: str,
    action: str,
    open_target: str,
) -> dict[str, Any]:
    desktop = Path.home() / "Desktop"
    return _latest_desktop_object_from_folders(
        value,
        action,
        open_target,
        desktop_object="latest_desktop_item",
        folders=[desktop],
        matcher=lambda _item: True,
        missing_error="Desktop folder not found",
        missing_error_code="desktop_folder_not_found",
        not_found_error="No desktop items found",
        not_found_error_code="latest_desktop_item_not_found",
    )


def _latest_desktop_object_from_folders(
    value: str,
    action: str,
    open_target: str,
    *,
    desktop_object: str,
    folders: list[Path],
    matcher: Any,
    missing_error: str,
    missing_error_code: str,
    not_found_error: str,
    not_found_error_code: str,
) -> dict[str, Any]:
    source_folders = [str(folder) for folder in folders]
    base_data = {
        "path": str(value or "").strip(),
        "open_target": open_target,
        "desktop_object": desktop_object,
        "source_folders": source_folders,
    }
    if len(folders) == 1:
        base_data["source_folder"] = source_folders[0]
    existing_folders = [folder for folder in folders if folder.exists() and folder.is_dir()]
    if not existing_folders:
        return {
            "error_payload": {
                "ok": False,
                "action": action,
                "summary": f"{action} failed",
                "error": missing_error,
                "error_code": missing_error_code,
                "data": {
                    **base_data,
                    "exists": False,
                    "source_exists": False,
                },
                "permission_error": False,
                "fallback_used": False,
            }
        }
    target = _latest_item_in_folders(existing_folders, matcher)
    if target is None:
        return {
            "error_payload": {
                "ok": False,
                "action": action,
                "summary": f"{action} failed",
                "error": not_found_error,
                "error_code": not_found_error_code,
                "data": {
                    **base_data,
                    "exists": False,
                    "source_exists": True,
                },
                "permission_error": False,
                "fallback_used": False,
            }
        }
    return {
        "target": target,
        "data": {
            **base_data,
            "source_folder": str(target.parent),
            "expanded_path": str(target),
            "resolved_path": str(target),
            "display_path": str(target),
            "source_exists": True,
        },
    }


def _latest_item_in_folders(folders: list[Path], matcher: Any) -> Path | None:
    candidates: list[tuple[float, Path]] = []
    for folder in folders:
        try:
            items = list(folder.iterdir())
        except OSError:
            continue
        for item in items:
            name = item.name
            if name.startswith(".") or _is_incomplete_desktop_item(name):
                continue
            if not matcher(item):
                continue
            try:
                candidates.append((item.stat().st_mtime, item))
            except OSError:
                continue
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _is_incomplete_desktop_item(name: str) -> bool:
    return str(name or "").lower().endswith((".download", ".crdownload", ".part"))


def _looks_like_screenshot_item(item: Path) -> bool:
    name = item.name
    lowered = name.lower()
    if item.suffix.lower() not in {".png", ".jpg", ".jpeg", ".heic", ".webp"}:
        return False
    compact = re.sub(r"[\s._-]+", "", lowered)
    return any(
        marker in compact
        for marker in ("screenshot", "截屏", "截圖", "屏幕截图", "螢幕截圖")
    )


def _finder_selection_desktop_object_path(
    value: str,
    action: str,
    open_target: str,
) -> dict[str, Any]:
    base_data = {
        "path": str(value or "").strip(),
        "open_target": open_target,
        "desktop_object": "finder_selection",
        "source_app": "Finder",
    }
    selected = _selected_finder_item_path()
    if not selected.get("ok"):
        payload = {
            **selected,
            "action": action,
            "summary": f"{action} failed",
            "data": {
                **base_data,
                "exists": False,
                "source_exists": False,
            },
        }
        return {"error_payload": _with_permission_metadata("osascript", payload)}
    selected_path = str(selected.get("path") or "").strip()
    if not selected_path:
        return {
            "error_payload": {
                "ok": False,
                "action": action,
                "summary": f"{action} failed",
                "error": "No Finder selection found",
                "error_code": "finder_selection_not_found",
                "data": {
                    **base_data,
                    "exists": False,
                    "source_exists": False,
                },
                "permission_error": False,
                "fallback_used": False,
            }
        }
    target = Path(selected_path).expanduser().resolve(strict=False)
    return {
        "target": target,
        "data": {
            **base_data,
            "expanded_path": str(target),
            "resolved_path": str(target),
            "display_path": str(target),
            "source_exists": True,
        },
    }


def _selected_finder_item_path() -> dict[str, Any]:
    result = _run_osascript(
        """
        tell application "Finder"
            if (count of selection) is 0 then
                return ""
            end if
            set selectedItem to item 1 of selection
            return POSIX path of (selectedItem as alias)
        end tell
        """
    )
    if not result.get("ok"):
        return result
    return {"ok": True, "path": str(result.get("stdout") or "").strip()}


def _common_folder_path(value: str) -> Path | None:
    compact = "".join(str(value or "").strip().lower().replace("-", " ").replace("_", " ").split())
    if compact not in _COMMON_FOLDER_TARGETS:
        return None
    folder_name = _COMMON_FOLDER_TARGETS[compact]
    return Path.home() / folder_name if folder_name else Path.home()


def app_focus(app_name: str) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("app.focus")
    clean_name = _clean_required(app_name, "app_name")
    result = _run_osascript(
        """
        on run argv
            set appName to item 1 of argv
            tell application appName to activate
            return "focused|" & appName
        end run
        """,
        [clean_name],
    )
    if not result["ok"]:
        fallback = app_open(clean_name)
        if fallback.get("ok"):
            fallback_data = fallback.get("data") if isinstance(fallback.get("data"), dict) else {}
            return {
                "ok": True,
                "action": "app.focus",
                "summary": f"Focused {clean_name} via app.open fallback",
                "data": {
                    "app_name": clean_name,
                    **fallback_data,
                    "focus_fallback": "app.open",
                },
                "permission_error": False,
                "fallback_used": True,
                "fallback_result": fallback,
            }
        payload = _with_permission_metadata(
            "app.focus",
            {**result, "action": "app.focus", "summary": "app.focus failed"},
        )
        payload["fallback_used"] = bool(fallback.get("ok"))
        payload["fallback_result"] = fallback
        return payload
    return {
        "ok": True,
        "action": "app.focus",
        "summary": f"Focused {clean_name}",
        "data": {"app_name": clean_name},
        "permission_error": False,
        "fallback_used": False,
    }


def app_focus_window(app_name: str, title_contains: str) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("app.focus_window")
    clean_name = _clean_required(app_name, "app_name")
    clean_title = _clean_required(title_contains, "title_contains")
    result = _run_osascript(
        """
        on lowercaseText(theText)
            set upperChars to "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            set lowerChars to "abcdefghijklmnopqrstuvwxyz"
            set outputText to ""
            repeat with charIndex from 1 to length of theText
                set oneChar to character charIndex of theText
                set charOffset to offset of oneChar in upperChars
                if charOffset > 0 then
                    set outputText to outputText & character charOffset of lowerChars
                else
                    set outputText to outputText & oneChar
                end if
            end repeat
            return outputText
        end lowercaseText

        on run argv
            set appName to item 1 of argv
            set titleQuery to item 2 of argv
            set loweredQuery to my lowercaseText(titleQuery)
            tell application "System Events"
                if not (exists application process appName) then
                    return "not_running|" & appName & "|" & titleQuery
                end if
                set visible of application process appName to true
                tell application process appName
                    set windowIndex to 0
                    set matchedIndex to 0
                    set matchedTitle to ""
                    repeat with windowRef in windows
                        set windowIndex to windowIndex + 1
                        try
                            set windowTitle to name of windowRef
                        on error
                            set windowTitle to ""
                        end try
                        if (my lowercaseText(windowTitle)) contains loweredQuery then
                            set matchedIndex to windowIndex
                            set matchedTitle to windowTitle
                            try
                                if value of attribute "AXMinimized" of windowRef is true then
                                    set value of attribute "AXMinimized" of windowRef to false
                                end if
                            end try
                            try
                                perform action "AXRaise" of windowRef
                            end try
                            try
                                set value of attribute "AXMain" of windowRef to true
                            end try
                            exit repeat
                        end if
                    end repeat
                end tell
            end tell
            if matchedTitle is "" then
                return "not_found|" & appName & "|" & titleQuery
            end if
            tell application appName to activate
            return "focused|" & appName & "|" & matchedIndex & "|" & matchedTitle
        end run
        """,
        [clean_name, clean_title],
    )
    if not result["ok"]:
        return _with_permission_metadata(
            "app.focus_window",
            {
                **result,
                "action": "app.focus_window",
                "summary": "app.focus_window failed",
                "data": {"app_name": clean_name, "title_contains": clean_title},
            },
        )
    stdout = str(result.get("stdout") or "").strip()
    parts = stdout.split("|", 3) if stdout else []
    status = parts[0] if parts else "unknown"
    if status == "not_running":
        return {
            "ok": False,
            "action": "app.focus_window",
            "summary": f"{clean_name} is not running",
            "error": "app_not_running",
            "error_code": "app_not_running",
            "data": {
                "app_name": clean_name,
                "title_contains": clean_title,
                "focus_status": status,
            },
            "permission_error": False,
            "fallback_used": False,
        }
    if status == "not_found":
        return {
            "ok": False,
            "action": "app.focus_window",
            "summary": f"No {clean_name} window matched {clean_title}",
            "error": "window_not_found",
            "error_code": "window_not_found",
            "data": {
                "app_name": clean_name,
                "title_contains": clean_title,
                "focus_status": status,
            },
            "permission_error": False,
            "fallback_used": False,
        }
    window_index = _int_value(parts[2] if len(parts) > 2 else 0)
    window_title = parts[3] if len(parts) > 3 else ""
    return {
        "ok": True,
        "action": "app.focus_window",
        "summary": f"Focused {clean_name} window: {window_title or clean_title}",
        "data": {
            "app_name": clean_name,
            "title_contains": clean_title,
            "focus_status": status,
            "window_index": window_index,
            "window_title": window_title,
        },
        "permission_error": False,
        "fallback_used": False,
    }


def app_show(app_name: str) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("app.show")
    clean_name = _clean_required(app_name, "app_name")
    result = _run_osascript(
        """
        on run argv
            set appName to item 1 of argv
            set statusText to "launched"
            set restoredCount to 0
            tell application "System Events"
                if exists application process appName then
                    set statusText to "shown"
                    set visible of application process appName to true
                    tell application process appName
                        repeat with windowRef in windows
                            try
                                if value of attribute "AXMinimized" of windowRef is true then
                                    set value of attribute "AXMinimized" of windowRef to false
                                    set restoredCount to restoredCount + 1
                                end if
                            end try
                        end repeat
                    end tell
                end if
            end tell
            tell application appName to activate
            return statusText & "|" & appName & "|" & restoredCount
        end run
        """,
        [clean_name],
    )
    if not result["ok"]:
        return _with_permission_metadata(
            "app.show",
            {
                **result,
                "action": "app.show",
                "summary": "app.show failed",
                "data": {"app_name": clean_name},
            },
        )
    stdout = str(result.get("stdout") or "").strip()
    parts = stdout.split("|") if stdout else []
    status = parts[0] if parts else "unknown"
    restored_count = _int_value(parts[2] if len(parts) > 2 else 0)
    summary = (
        f"Launched and showed {clean_name}"
        if status == "launched"
        else f"Showed {clean_name}"
    )
    return {
        "ok": True,
        "action": "app.show",
        "summary": summary,
        "data": {
            "app_name": clean_name,
            "show_status": status,
            "restored_window_count": restored_count,
        },
        "permission_error": False,
        "fallback_used": False,
    }


def app_hide(app_name: str) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("app.hide")
    clean_name = _clean_required(app_name, "app_name")
    result = _run_osascript(
        """
        on run argv
            set appName to item 1 of argv
            tell application "System Events"
                if exists application process appName then
                    set visible of application process appName to false
                    return "hidden|" & appName
                end if
            end tell
            return "not_running|" & appName
        end run
        """,
        [clean_name],
    )
    if not result["ok"]:
        return _with_permission_metadata(
            "app.hide",
            {
                **result,
                "action": "app.hide",
                "summary": "app.hide failed",
                "data": {"app_name": clean_name},
            },
        )
    stdout = str(result.get("stdout") or "").strip()
    status = stdout.split("|", 1)[0] if stdout else "unknown"
    if status == "not_running":
        return {
            "ok": False,
            "action": "app.hide",
            "summary": f"{clean_name} is not running",
            "error": "app_not_running",
            "error_code": "app_not_running",
            "data": {"app_name": clean_name, "hide_status": status},
            "permission_error": False,
            "fallback_used": False,
        }
    return {
        "ok": True,
        "action": "app.hide",
        "summary": f"Hid {clean_name}",
        "data": {"app_name": clean_name, "hide_status": status},
        "permission_error": False,
        "fallback_used": False,
    }


def app_minimize(app_name: str) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("app.minimize")
    clean_name = _clean_required(app_name, "app_name")
    result = _run_osascript(
        """
        on run argv
            set appName to item 1 of argv
            tell application "System Events"
                if not (exists application process appName) then
                    return "not_running|" & appName & "|0"
                end if
                tell application process appName
                    set windowCount to count of windows
                    if windowCount is 0 then
                        return "no_windows|" & appName & "|0"
                    end if
                    repeat with windowRef in windows
                        try
                            set value of attribute "AXMinimized" of windowRef to true
                        on error
                            try
                                set miniaturized of windowRef to true
                            end try
                        end try
                    end repeat
                    return "minimized|" & appName & "|" & windowCount
                end tell
            end tell
        end run
        """,
        [clean_name],
    )
    if not result["ok"]:
        return _with_permission_metadata(
            "app.minimize",
            {
                **result,
                "action": "app.minimize",
                "summary": "app.minimize failed",
                "data": {"app_name": clean_name},
            },
        )
    stdout = str(result.get("stdout") or "").strip()
    parts = stdout.split("|") if stdout else []
    status = parts[0] if parts else "unknown"
    window_count = _int_value(parts[2] if len(parts) > 2 else 0)
    if status == "not_running":
        return {
            "ok": False,
            "action": "app.minimize",
            "summary": f"{clean_name} is not running",
            "error": "app_not_running",
            "error_code": "app_not_running",
            "data": {
                "app_name": clean_name,
                "minimize_status": status,
                "window_count": window_count,
            },
            "permission_error": False,
            "fallback_used": False,
        }
    if status == "no_windows":
        return {
            "ok": False,
            "action": "app.minimize",
            "summary": f"{clean_name} has no windows to minimize",
            "error": "app_no_windows",
            "error_code": "app_no_windows",
            "data": {
                "app_name": clean_name,
                "minimize_status": status,
                "window_count": window_count,
            },
            "permission_error": False,
            "fallback_used": False,
        }
    return {
        "ok": True,
        "action": "app.minimize",
        "summary": f"Minimized {clean_name}",
        "data": {
            "app_name": clean_name,
            "minimize_status": status,
            "window_count": window_count,
        },
        "permission_error": False,
        "fallback_used": False,
    }


def app_quit(app_name: str) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("app.quit")
    clean_name = _clean_required(app_name, "app_name")
    result = _run_osascript(
        """
        on run argv
            set appName to item 1 of argv
            if application appName is running then
                tell application appName to quit
                delay 0.2
                if application appName is running then
                    return "quit_requested_running|" & appName
                end if
                return "quit|" & appName
            end if
            return "not_running|" & appName
        end run
        """,
        [clean_name],
    )
    if not result["ok"]:
        return _with_permission_metadata(
            "app.quit",
            {
                **result,
                "action": "app.quit",
                "summary": "app.quit failed",
                "data": {"app_name": clean_name},
            },
        )
    stdout = str(result.get("stdout") or "").strip()
    status = stdout.split("|", 1)[0] if stdout else "unknown"
    verification = _app_running_verification(clean_name)
    running = verification.get("launch_verified")
    still_running = running is True
    if status == "not_running":
        summary = f"{clean_name} was not running"
    elif still_running:
        summary = f"Sent quit request to {clean_name}"
    else:
        summary = f"Quit {clean_name}"
    return {
        "ok": True,
        "action": "app.quit",
        "summary": summary,
        "data": {
            "app_name": clean_name,
            "quit_status": status,
            "quit_verified": running is False,
            "running": running,
            **verification,
        },
        "permission_error": False,
        "fallback_used": False,
    }


def apple_music_play(query: str) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("media.apple_music_play")
    clean_query = _clean_required(query, "query")
    result = _run_osascript(
        """
        on run argv
            set queryText to item 1 of argv
            tell application "Music"
                activate
                try
                    set matches to (search library playlist 1 for queryText)
                    if (count of matches) is 0 then
                        return "not_found|" & queryText & "|"
                    end if
                    set trackRef to item 1 of matches
                    play trackRef
                    set trackName to name of trackRef
                    set artistName to artist of trackRef
                    return "played|" & trackName & "|" & artistName
                on error errMsg number errNum
                    return "error|" & errNum & "|" & errMsg
                end try
            end tell
        end run
        """,
        [clean_query],
    )
    if not result["ok"]:
        fallback = app_open("Music")
        return {
            **_with_permission_metadata(
                "media.apple_music_play",
                {
                    **result,
                    "action": "media.apple_music_play",
                    "summary": "media.apple_music_play failed",
                },
            ),
            "action": "media.apple_music_play",
            "fallback_used": bool(fallback.get("ok")),
            "fallback_result": fallback,
        }
    status, first, second = _split_status(result.get("stdout"))
    if status == "played":
        detail = f"{first}{f' - {second}' if second else ''}"
        return {
            "ok": True,
            "action": "media.apple_music_play",
            "summary": f"Playing {detail}",
            "data": {"query": clean_query, "track": first, "artist": second},
            "permission_error": False,
            "fallback_used": False,
        }
    fallback = _open_apple_music_search(clean_query)
    payload = {
        "ok": False,
        "action": "media.apple_music_play",
        "summary": (
            f"Could not directly play {clean_query}; opened Apple Music search."
            if fallback.get("ok")
            else f"Could not directly play {clean_query}; Apple Music search fallback failed."
        ),
        "error": second or first or "Music did not return a playable track",
        "data": {
            "query": clean_query,
            "status": status,
            "search_url": str((fallback.get("data") or {}).get("url") or ""),
            "search_opened": bool(fallback.get("ok")),
        },
        "permission_error": status == "error" and _looks_like_permission_error(f"{first}\n{second}"),
        "fallback_used": bool(fallback.get("ok")),
        "fallback": "apple_music_search",
        "fallback_result": fallback,
    }
    return _with_permission_metadata("media.apple_music_play", payload)


def apple_music_status() -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("media.apple_music_status")
    result = _run_osascript(
        """
        if application "Music" is not running then
            return "status|not_running|||"
        end if
        tell application "Music"
            try
                set stateText to player state as text
                try
                    set trackName to name of current track
                    set artistName to artist of current track
                on error
                    set trackName to ""
                    set artistName to ""
                end try
                return "status|" & stateText & "|" & trackName & "|" & artistName
            on error errMsg number errNum
                return "error|" & errNum & "|" & errMsg & "|"
            end try
        end tell
        """,
        [],
    )
    if not result["ok"]:
        return _with_permission_metadata(
            "media.apple_music_status",
            {
                **result,
                "action": "media.apple_music_status",
                "summary": "media.apple_music_status failed",
            },
        )
    parts = str(result.get("stdout") or "").strip().split("|", 4)
    while len(parts) < 5:
        parts.append("")
    status, state, track, artist, extra = parts
    if status == "status":
        return {
            "ok": True,
            "action": "media.apple_music_status",
            "summary": "Read Apple Music playback status",
            "data": {
                "running": state != "not_running",
                "player_state": state,
                "track": track,
                "artist": artist,
            },
            "permission_error": False,
            "fallback_used": False,
        }
    payload = {
        "ok": False,
        "action": "media.apple_music_status",
        "summary": "Could not read Apple Music playback status",
        "error": track or state or extra or "Music did not return playback status",
        "data": {"status": status},
        "permission_error": status == "error" and _looks_like_permission_error(f"{state}\n{track}"),
        "fallback_used": False,
    }
    return _with_permission_metadata("media.apple_music_status", payload)


def apple_music_control(action: str) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("media.apple_music_control")
    clean_action = _clean_music_control_action(action)
    result = _run_osascript(
        """
        on run argv
            set controlAction to item 1 of argv
            tell application "Music"
                try
                    if controlAction is "toggle" then
                        playpause
                    else if controlAction is "play" then
                        play
                    else if controlAction is "pause" then
                        pause
                    else if controlAction is "next" then
                        next track
                    else if controlAction is "previous" then
                        previous track
                    else
                        return "error|-1|unsupported_control"
                    end if
                    delay 0.1
                    set stateText to player state as text
                    try
                        set trackName to name of current track
                        set artistName to artist of current track
                    on error
                        set trackName to ""
                        set artistName to ""
                    end try
                    return "controlled|" & controlAction & "|" & stateText & "|" & trackName & "|" & artistName
                on error errMsg number errNum
                    return "error|" & errNum & "|" & errMsg
                end try
            end tell
        end run
        """,
        [clean_action],
    )
    if not result["ok"]:
        fallback = app_open("Music")
        media_key_result = _apple_music_control_media_key_result(clean_action, result, fallback)
        if media_key_result:
            return media_key_result
        return {
            **_with_permission_metadata(
                "media.apple_music_control",
                {
                    **result,
                    "action": "media.apple_music_control",
                    "summary": "media.apple_music_control failed",
                },
            ),
            "action": "media.apple_music_control",
            "fallback_used": bool(fallback.get("ok")),
            "fallback_result": fallback,
        }
    parts = str(result.get("stdout") or "").strip().split("|", 4)
    while len(parts) < 5:
        parts.append("")
    status, first, second, third, fourth = parts
    if status == "controlled":
        return {
            "ok": True,
            "action": "media.apple_music_control",
            "summary": f"Apple Music {first} executed",
            "data": {
                "control": first or clean_action,
                "player_state": second,
                "track": third,
                "artist": fourth,
            },
            "permission_error": False,
            "fallback_used": False,
        }
    fallback = app_open("Music")
    permission_error = status == "error" and _looks_like_permission_error(f"{first}\n{second}")
    media_key_result = _apple_music_control_media_key_result(
        clean_action,
        {
            "ok": False,
            "action": "media.apple_music_control",
            "summary": "media.apple_music_control failed",
            "error": second or first or "Music did not accept the control action",
            "data": {"control": clean_action, "status": status},
            "permission_error": permission_error,
            "fallback_used": False,
        },
        fallback,
    )
    if media_key_result:
        return media_key_result
    payload = {
        "ok": False,
        "action": "media.apple_music_control",
        "summary": f"Could not control Apple Music with action {clean_action}; opened Music.",
        "error": second or first or "Music did not accept the control action",
        "data": {"control": clean_action, "status": status},
        "permission_error": permission_error,
        "fallback_used": bool(fallback.get("ok")),
        "fallback_result": fallback,
    }
    return _with_permission_metadata("media.apple_music_control", payload)


def _apple_music_control_media_key_result(
    action: str,
    direct_result: dict[str, Any],
    open_result: dict[str, Any],
) -> dict[str, Any]:
    media_key_fallback = _apple_music_media_key_fallback(action)
    if not media_key_fallback.get("ok"):
        return {}
    warning = _with_permission_metadata(
        "media.apple_music_control",
        {
            "ok": False,
            "action": "media.apple_music_control",
            "summary": "Apple Music automation control failed before media key fallback",
            "error": str(direct_result.get("error") or ""),
            "permission_error": bool(direct_result.get("permission_error")),
        },
    )
    media_key_data = (
        media_key_fallback.get("data") if isinstance(media_key_fallback.get("data"), dict) else {}
    )
    return {
        "ok": True,
        "action": "media.apple_music_control",
        "summary": f"Apple Music {action} attempted via media key fallback",
        "data": {
            "control": action,
            "player_state": "unknown",
            "track": "",
            "artist": "",
            "fallback": "system_media_key",
            "fallback_control": str(media_key_data.get("media_control") or ""),
            "media_key": str(media_key_data.get("media_key") or ""),
            "playback_state_unverified": True,
            "direct_error": str(direct_result.get("error") or ""),
        },
        "permission_error": False,
        "missing_permissions": warning.get("missing_permissions", []),
        "permission_targets": warning.get("permission_targets", []),
        "recovery_hints": warning.get("recovery_hints", []),
        "recovery_actions": warning.get("recovery_actions", []),
        "fallback_used": True,
        "fallback": "system_media_key",
        "fallback_result": {
            "open": open_result,
            "media_key": media_key_fallback,
            "direct": {
                **direct_result,
                "action": "media.apple_music_control",
                "summary": "media.apple_music_control failed",
            },
        },
    }


def _apple_music_media_key_fallback(action: str) -> dict[str, Any]:
    media_key = _APPLE_MUSIC_MEDIA_KEY_FALLBACKS.get(action)
    if not media_key:
        return {
            "ok": False,
            "action": "media.apple_music.media_key",
            "summary": f"No safe media key fallback for Apple Music action {action}",
            "error": "unsupported_media_key_fallback",
            "data": {"requested_control": action},
            "permission_error": False,
            "fallback_used": False,
        }
    key_code, key_label, media_control = media_key
    result = _run_osascript(
        """
        on run argv
            set keyCodeValue to item 1 of argv as integer
            set mediaControl to item 2 of argv
            tell application "System Events" to key code keyCodeValue
            return "pressed|" & mediaControl
        end run
        """,
        [str(key_code), media_control],
    )
    if not result["ok"]:
        return _with_permission_metadata(
            "desktop.safe_key",
            {
                **result,
                "action": "media.apple_music.media_key",
                "summary": "Apple Music media key fallback failed",
                "data": {
                    "requested_control": action,
                    "media_control": media_control,
                    "media_key": key_label,
                    "key_code": key_code,
                },
            },
        )
    return {
        "ok": True,
        "action": "media.apple_music.media_key",
        "summary": f"Pressed {key_label} media key for Apple Music",
        "data": {
            "requested_control": action,
            "media_control": media_control,
            "media_key": key_label,
            "key_code": key_code,
        },
        "permission_error": False,
        "fallback_used": False,
    }


def _system_media_key_press(action_name: str, control: str) -> dict[str, Any]:
    media_key = _APPLE_MUSIC_MEDIA_KEY_FALLBACKS.get(control)
    if not media_key:
        return {
            "ok": False,
            "action": action_name,
            "summary": f"No safe media key mapping for control {control}",
            "error": "unsupported_media_key",
            "data": {"requested_control": control},
            "permission_error": False,
            "fallback_used": False,
        }
    key_code, key_label, media_control = media_key
    result = _run_osascript(
        """
        on run argv
            set keyCodeValue to item 1 of argv as integer
            set mediaControl to item 2 of argv
            tell application "System Events" to key code keyCodeValue
            return "pressed|" & mediaControl
        end run
        """,
        [str(key_code), media_control],
    )
    if not result["ok"]:
        return _with_permission_metadata(
            action_name,
            {
                **result,
                "action": action_name,
                "summary": f"{action_name} media key failed",
                "data": {
                    "requested_control": control,
                    "media_control": media_control,
                    "media_key": key_label,
                    "key_code": key_code,
                },
            },
        )
    return {
        "ok": True,
        "action": action_name,
        "summary": f"Pressed {key_label} media key",
        "data": {
            "requested_control": control,
            "media_control": media_control,
            "media_key": key_label,
            "key_code": key_code,
        },
        "permission_error": False,
        "fallback_used": False,
    }


def system_media_control(action: str) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("media.system_control")
    clean_action = _clean_music_control_action(action)
    media_key_control = "toggle" if clean_action in {"play", "pause"} else clean_action
    media_key_result = _system_media_key_press("media.system_control", media_key_control)
    media_key_data = (
        media_key_result.get("data") if isinstance(media_key_result.get("data"), dict) else {}
    )
    data = {
        "control": clean_action,
        "media_key_control": media_key_control,
        "player_state": "unknown",
        "playback_state_unverified": True,
    }
    if media_key_data.get("media_key"):
        data["media_key"] = media_key_data.get("media_key") or ""
    if media_key_data.get("media_control"):
        data["fallback_control"] = media_key_data.get("media_control") or ""
    if media_key_result.get("ok"):
        return {
            "ok": True,
            "action": "media.system_control",
            "summary": f"Sent {clean_action} media key control to current media",
            "data": data,
            "permission_error": False,
            "fallback_used": True,
            "fallback": "system_media_key",
            "fallback_result": {"media_key": media_key_result},
        }

    payload = {
        "ok": False,
        "action": "media.system_control",
        "summary": f"Could not send {clean_action} media key control to current media",
        "error": str(media_key_result.get("error") or "system media control failed"),
        "data": data,
        "permission_error": bool(media_key_result.get("permission_error")),
        "fallback_used": False,
        "fallback_result": {"media_key": media_key_result},
    }
    return _with_permission_metadata("media.system_control", payload)


def apple_music_open_and_play() -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("media.apple_music_open_and_play")
    open_result = app_open("Music")
    control_result = apple_music_control("play")
    control_data = control_result.get("data") if isinstance(control_result.get("data"), dict) else {}
    data = {
        "app_name": "Music",
        "open_ok": bool(open_result.get("ok")),
        "open_summary": str(open_result.get("summary") or ""),
        "playback_ok": bool(control_result.get("ok")),
        "control": control_data.get("control") or "play",
        "player_state": control_data.get("player_state") or "",
        "track": control_data.get("track") or "",
        "artist": control_data.get("artist") or "",
    }
    if control_data.get("fallback") or control_result.get("fallback"):
        data["fallback"] = control_data.get("fallback") or control_result.get("fallback") or ""
    if control_data.get("fallback_control"):
        data["fallback_control"] = control_data.get("fallback_control") or ""
    if control_data.get("media_key"):
        data["media_key"] = control_data.get("media_key") or ""
    if control_data.get("playback_state_unverified"):
        data["playback_state_unverified"] = True
    if control_result.get("ok"):
        payload = {
            "ok": True,
            "action": "media.apple_music_open_and_play",
            "summary": (
                "Opened Music and attempted playback with media key fallback"
                if data.get("playback_state_unverified")
                else "Opened Music and started playback"
            ),
            "data": data,
            "permission_error": False,
            "fallback_used": bool(control_result.get("fallback_used")),
        }
        for key in ("missing_permissions", "permission_targets", "recovery_hints", "recovery_actions"):
            if control_result.get(key):
                payload[key] = control_result[key]
        if control_result.get("fallback"):
            payload["fallback"] = control_result["fallback"]
        if control_result.get("fallback_result"):
            payload["fallback_result"] = control_result["fallback_result"]
        return payload

    payload = {
        "ok": False,
        "action": "media.apple_music_open_and_play",
        "summary": (
            "Opened Music but could not start playback"
            if open_result.get("ok")
            else "Could not open Music or start playback"
        ),
        "error": str(control_result.get("error") or open_result.get("error") or "Music playback failed"),
        "data": data,
        "permission_error": bool(control_result.get("permission_error") or open_result.get("permission_error")),
        "fallback_used": bool(open_result.get("ok") or control_result.get("fallback_used")),
        "fallback_result": {
            "open": open_result,
            "control": control_result,
        },
    }
    return _with_permission_metadata("media.apple_music_open_and_play", payload)


def music_app_open_and_play(app_name: str) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("media.music_app_open_and_play")
    clean_name = _clean_required(app_name, "app_name")
    if clean_name == "Music":
        return apple_music_open_and_play()

    open_result = app_open(clean_name)
    focus_result: dict[str, Any] = {}
    media_key_result: dict[str, Any] = {}
    if open_result.get("ok"):
        focus_result = app_focus(clean_name)
        media_key_result = _system_media_key_press(
            "media.music_app_open_and_play",
            "play",
        )
    open_ok = bool(open_result.get("ok"))
    key_ok = bool(media_key_result.get("ok"))
    data = {
        "app_name": clean_name,
        "open_ok": open_ok,
        "open_summary": str(open_result.get("summary") or ""),
        "focus_ok": bool(focus_result.get("ok")),
        "focus_summary": str(focus_result.get("summary") or ""),
        "playback_ok": key_ok,
        "control": "play",
        "player_state": "unknown",
        "playback_state_unverified": True,
    }
    media_key_data = (
        media_key_result.get("data") if isinstance(media_key_result.get("data"), dict) else {}
    )
    if media_key_data.get("media_key"):
        data["media_key"] = media_key_data.get("media_key") or ""
    if media_key_data.get("media_control"):
        data["fallback_control"] = media_key_data.get("media_control") or ""

    if open_ok and key_ok:
        return {
            "ok": True,
            "action": "media.music_app_open_and_play",
            "summary": f"Opened {clean_name} and attempted playback with media key",
            "data": data,
            "permission_error": False,
            "fallback_used": True,
            "fallback": "system_media_key",
            "fallback_result": {
                "open": open_result,
                "focus": focus_result,
                "media_key": media_key_result,
            },
        }

    payload = {
        "ok": False,
        "action": "media.music_app_open_and_play",
        "summary": (
            f"Opened {clean_name} but could not start playback"
            if open_ok
            else f"Could not open {clean_name} or start playback"
        ),
        "error": str(
            media_key_result.get("error")
            or focus_result.get("error")
            or open_result.get("error")
            or "music app playback failed"
        ),
        "data": data,
        "permission_error": bool(
            media_key_result.get("permission_error")
            or focus_result.get("permission_error")
            or open_result.get("permission_error")
        ),
        "fallback_used": open_ok,
        "fallback_result": {
            "open": open_result,
            "focus": focus_result,
            "media_key": media_key_result,
        },
    }
    return _with_permission_metadata("media.music_app_open_and_play", payload)


def music_app_control(app_name: str, action: str) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("media.music_app_control")
    clean_name = _clean_required(app_name, "app_name")
    clean_action = _clean_music_control_action(action)
    if clean_name == "Music":
        return apple_music_control(clean_action)

    status_result = app_status(clean_name)
    status_data = status_result.get("data") if isinstance(status_result.get("data"), dict) else {}
    if status_result.get("ok") and status_data.get("running") is False:
        return {
            "ok": False,
            "action": "media.music_app_control",
            "summary": f"{clean_name} is not running",
            "error": "music_app_not_running",
            "data": {
                "app_name": clean_name,
                "control": clean_action,
                "running": False,
                "playback_state_unverified": True,
            },
            "permission_error": False,
            "fallback_used": False,
            "fallback_result": {"status": status_result},
        }
    if not status_result.get("ok"):
        return _with_permission_metadata(
            "media.music_app_control",
            {
                **status_result,
                "action": "media.music_app_control",
                "summary": f"Could not check {clean_name} before media control",
                "data": {
                    "app_name": clean_name,
                    "control": clean_action,
                    "status": status_data,
                },
            },
        )

    focus_result = app_focus(clean_name)
    if not focus_result.get("ok"):
        return _with_permission_metadata(
            "media.music_app_control",
            {
                **focus_result,
                "action": "media.music_app_control",
                "summary": f"Could not focus {clean_name} before media control",
                "data": {
                    "app_name": clean_name,
                    "control": clean_action,
                    "focus_ok": False,
                },
                "fallback_result": {"status": status_result, "focus": focus_result},
            },
        )

    media_key_control = "toggle" if clean_action in {"play", "pause"} else clean_action
    media_key_result = _system_media_key_press("media.music_app_control", media_key_control)
    media_key_data = (
        media_key_result.get("data") if isinstance(media_key_result.get("data"), dict) else {}
    )
    data = {
        "app_name": clean_name,
        "control": clean_action,
        "media_key_control": media_key_control,
        "focus_ok": True,
        "player_state": "unknown",
        "playback_state_unverified": True,
    }
    if media_key_data.get("media_key"):
        data["media_key"] = media_key_data.get("media_key") or ""
    if media_key_data.get("media_control"):
        data["fallback_control"] = media_key_data.get("media_control") or ""
    if media_key_result.get("ok"):
        return {
            "ok": True,
            "action": "media.music_app_control",
            "summary": f"Sent {clean_action} media key control to {clean_name}",
            "data": data,
            "permission_error": False,
            "fallback_used": True,
            "fallback": "system_media_key",
            "fallback_result": {
                "status": status_result,
                "focus": focus_result,
                "media_key": media_key_result,
            },
        }

    payload = {
        "ok": False,
        "action": "media.music_app_control",
        "summary": f"Could not send {clean_action} media key control to {clean_name}",
        "error": str(media_key_result.get("error") or "music app media control failed"),
        "data": data,
        "permission_error": bool(media_key_result.get("permission_error")),
        "fallback_used": bool(focus_result.get("ok")),
        "fallback_result": {
            "status": status_result,
            "focus": focus_result,
            "media_key": media_key_result,
        },
    }
    return _with_permission_metadata("media.music_app_control", payload)


def _open_apple_music_search(query: str) -> dict[str, Any]:
    clean_query = _clean_required(query, "query")
    search_url = f"https://music.apple.com/search?term={quote_plus(clean_query)}"
    try:
        result = subprocess.run(
            ["open", "-a", "Music", search_url],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        payload = _error("media.apple_music.search", exc)
        payload["data"] = {"query": clean_query, "url": search_url}
        return payload
    if result.returncode != 0:
        payload = _failed("media.apple_music.search", result)
        payload["data"] = {"query": clean_query, "url": search_url}
        return payload
    return {
        "ok": True,
        "action": "media.apple_music.search",
        "summary": f"Opened Apple Music search for {clean_query}",
        "data": {
            "query": clean_query,
            "url": search_url,
            "open_target": "apple_music_search",
        },
        "permission_error": False,
        "fallback_used": False,
    }


def system_volume(action: str, *, level: Any = None, step: Any = None) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("system.volume")
    clean_action = _clean_system_volume_action(action)
    current = _read_system_volume()
    if not current.get("ok"):
        return current
    old_level = int(current["data"]["level"])
    old_muted = bool(current["data"]["muted"])
    target_level = old_level
    target_muted = old_muted
    if clean_action == "status":
        return {
            "ok": True,
            "action": "system.volume",
            "summary": f"System volume is {old_level}%{' and muted' if old_muted else ''}",
            "data": {
                "requested_action": clean_action,
                "old_level": old_level,
                "level": old_level,
                "muted": old_muted,
                "changed": False,
            },
            "permission_error": False,
            "fallback_used": False,
        }
    if clean_action == "set":
        target_level = _coerce_percentage(level, default=old_level)
        target_muted = False
    elif clean_action == "up":
        target_level = min(100, old_level + _coerce_percentage(step, default=10))
        target_muted = False
    elif clean_action == "down":
        target_level = max(0, old_level - _coerce_percentage(step, default=10))
        target_muted = False
    elif clean_action == "mute":
        target_muted = True
    elif clean_action == "unmute":
        target_muted = False
    result = _run_osascript(
        """
        on run argv
            set targetLevel to item 1 of argv as integer
            set targetMuted to item 2 of argv
            if targetMuted is "true" then
                set volume with output muted true
            else
                set volume output volume targetLevel
                set volume with output muted false
            end if
            delay 0.05
            set volumeSettings to get volume settings
            return (output volume of volumeSettings as text) & "|" & (output muted of volumeSettings as text)
        end run
        """,
        [str(target_level), "true" if target_muted else "false"],
    )
    if not result["ok"]:
        return _with_permission_metadata(
            "system.volume",
            {**result, "action": "system.volume", "summary": "system.volume failed"},
        )
    new_level, muted = _parse_system_volume(result.get("stdout"))
    return {
        "ok": True,
        "action": "system.volume",
        "summary": _system_volume_summary(clean_action, old_level, new_level, muted),
        "data": {
            "requested_action": clean_action,
            "old_level": old_level,
            "old_muted": old_muted,
            "level": new_level,
            "muted": muted,
            "changed": old_level != new_level or old_muted != muted,
        },
        "permission_error": False,
        "fallback_used": False,
    }


def system_brightness(action: str, *, step: Any = None) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("system.brightness")
    clean_action = _clean_system_brightness_action(action)
    clean_step = _clean_brightness_step(step)
    key_code = 145 if clean_action == "up" else 144
    result = _run_osascript(
        """
        on run argv
            set keyCodeValue to item 1 of argv as integer
            set repeatCount to item 2 of argv as integer
            repeat repeatCount times
                tell application "System Events" to key code keyCodeValue
                delay 0.05
            end repeat
            return "adjusted"
        end run
        """,
        [str(key_code), str(clean_step)],
    )
    if not result["ok"]:
        return _with_permission_metadata(
            "system.brightness",
            {**result, "action": "system.brightness", "summary": "system.brightness failed"},
        )
    return {
        "ok": True,
        "action": "system.brightness",
        "summary": (
            "Display brightness increased"
            if clean_action == "up"
            else "Display brightness decreased"
        ),
        "data": {
            "requested_action": clean_action,
            "step": clean_step,
            "key_code": key_code,
        },
        "permission_error": False,
        "fallback_used": False,
    }


def system_display_sleep() -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("system.display_sleep")
    try:
        result = subprocess.run(
            ["pmset", "displaysleepnow"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception as exc:
        return _error("system.display_sleep", exc)
    if result.returncode != 0:
        return _failed("system.display_sleep", result)
    return {
        "ok": True,
        "action": "system.display_sleep",
        "summary": "Display sleep requested",
        "data": {
            "requested_action": "sleep",
            "command": "pmset displaysleepnow",
        },
        "permission_error": False,
        "fallback_used": False,
    }


def system_screen_saver_start() -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("system.screen_saver_start")
    target = "/System/Library/CoreServices/ScreenSaverEngine.app"
    try:
        result = subprocess.run(
            ["open", target],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception as exc:
        return _error("system.screen_saver_start", exc)
    if result.returncode != 0:
        return _failed("system.screen_saver_start", result)
    return {
        "ok": True,
        "action": "system.screen_saver_start",
        "summary": "Screen saver start requested",
        "data": {
            "requested_action": "start",
            "target": target,
            "command": f"open {target}",
        },
        "permission_error": False,
        "fallback_used": False,
    }


def clipboard_write(text: str) -> dict[str, Any]:
    clean_text = _clean_required(text, "text")
    command = _clipboard_write_command()
    if not command:
        return _unsupported("clipboard.write")
    try:
        result = subprocess.run(
            command,
            input=clean_text,
            text=True,
            capture_output=True,
            timeout=3,
            check=False,
        )
    except Exception as exc:
        return _error("clipboard.write", exc)
    if result.returncode != 0:
        return _failed("clipboard.write", result)
    return {
        "ok": True,
        "action": "clipboard.write",
        "summary": f"Copied {len(clean_text)} characters to clipboard",
        "data": {
            "text_length": len(clean_text),
            "platform": _desktop_platform(),
        },
        "permission_error": False,
        "fallback_used": False,
    }


def clipboard_read(max_chars: Any = 2000) -> dict[str, Any]:
    command = _clipboard_read_command()
    if not command:
        return _unsupported("clipboard.read")
    try:
        clean_max_chars = _clean_clipboard_read_limit(max_chars)
    except ValueError as exc:
        return _error("clipboard.read", exc)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception as exc:
        return _error("clipboard.read", exc)
    if result.returncode != 0:
        return _failed("clipboard.read", result)
    text = str(result.stdout or "")
    preview = text[:clean_max_chars]
    return {
        "ok": True,
        "action": "clipboard.read",
        "summary": f"Read {len(text)} characters from clipboard",
        "data": {
            "text": preview,
            "text_length": len(text),
            "truncated": len(text) > clean_max_chars,
            "max_chars": clean_max_chars,
            "platform": _desktop_platform(),
        },
        "permission_error": False,
        "fallback_used": False,
    }


def notes_create(body: str, *, title: str = "", folder_name: str = "") -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("notes.create")
    clean_body = _clean_required(body, "body")
    clean_title = str(title or "").strip() or _note_title_from_body(clean_body)
    clean_folder_name = str(folder_name or "").strip()
    result = _run_osascript(
        """
        on run argv
            set noteTitle to item 1 of argv
            set noteBody to item 2 of argv
            set folderName to item 3 of argv
            tell application "Notes"
                set targetAccount to default account
                if folderName is "" then
                    set targetFolder to first folder of targetAccount
                else
                    set targetFolder to folder folderName of targetAccount
                end if
                set newNote to make new note at targetFolder with properties {name:noteTitle, body:noteBody}
                try
                    return id of newNote
                on error
                    return "created"
                end try
            end tell
        end run
        """,
        [clean_title, clean_body, clean_folder_name],
    )
    if not result["ok"]:
        return _with_permission_metadata(
            "notes.create",
            {**result, "action": "notes.create", "summary": "notes.create failed"},
        )
    return {
        "ok": True,
        "action": "notes.create",
        "summary": f"Created note: {clean_title}",
        "data": {
            "title": clean_title,
            "body_length": len(clean_body),
            "folder_name": clean_folder_name,
            "note_id": str(result.get("stdout") or "").strip(),
        },
        "permission_error": False,
        "fallback_used": False,
    }


def reminders_create(title: str, *, due_at: Any = None, list_name: str = "") -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("reminders.create")
    clean_title = _clean_required(title, "title")
    due = _parse_optional_local_datetime(due_at, "due_at")
    clean_list_name = str(list_name or "").strip()
    args = [clean_title, clean_list_name, *_datetime_argv(due)]
    result = _run_osascript(
        """
        on run argv
            set reminderTitle to item 1 of argv
            set listName to item 2 of argv
            set hasDueDate to item 3 of argv
            tell application "Reminders"
                if listName is "" then
                    set targetList to default list
                else
                    set targetList to list listName
                end if
                set newReminder to make new reminder at end of reminders of targetList with properties {name:reminderTitle}
                if hasDueDate is "true" then
                    set dueDate to current date
                    set year of dueDate to (item 4 of argv as integer)
                    set month of dueDate to (item 5 of argv as integer)
                    set day of dueDate to (item 6 of argv as integer)
                    set hours of dueDate to (item 7 of argv as integer)
                    set minutes of dueDate to (item 8 of argv as integer)
                    set seconds of dueDate to 0
                    set due date of newReminder to dueDate
                end if
                try
                    return id of newReminder
                on error
                    return "created"
                end try
            end tell
        end run
        """,
        args,
    )
    if not result["ok"]:
        return _with_permission_metadata(
            "reminders.create",
            {**result, "action": "reminders.create", "summary": "reminders.create failed"},
        )
    return {
        "ok": True,
        "action": "reminders.create",
        "summary": (
            f"Created reminder: {clean_title}"
            if due is None
            else f"Created reminder: {clean_title} at {_format_local_datetime(due)}"
        ),
        "data": {
            "title": clean_title,
            "due_at": _format_local_datetime(due) if due is not None else "",
            "list_name": clean_list_name,
            "reminder_id": str(result.get("stdout") or "").strip(),
        },
        "permission_error": False,
        "fallback_used": False,
    }


def calendar_create_event(
    title: str,
    *,
    start_at: Any,
    end_at: Any = None,
    calendar_name: str = "",
) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("calendar.create_event")
    clean_title = _clean_required(title, "title")
    start = _parse_required_local_datetime(start_at, "start_at")
    end = _parse_optional_local_datetime(end_at, "end_at")
    if end is None:
        end = start + timedelta(hours=1)
    if end <= start:
        raise ValueError("end_at must be after start_at")
    clean_calendar_name = str(calendar_name or "").strip()
    args = [
        clean_title,
        clean_calendar_name,
        *_datetime_argv(start),
        *_datetime_argv(end),
    ]
    result = _run_osascript(
        """
        on run argv
            set eventTitle to item 1 of argv
            set calendarName to item 2 of argv
            set startDate to current date
            set year of startDate to (item 4 of argv as integer)
            set month of startDate to (item 5 of argv as integer)
            set day of startDate to (item 6 of argv as integer)
            set hours of startDate to (item 7 of argv as integer)
            set minutes of startDate to (item 8 of argv as integer)
            set seconds of startDate to 0
            set endDate to current date
            set year of endDate to (item 10 of argv as integer)
            set month of endDate to (item 11 of argv as integer)
            set day of endDate to (item 12 of argv as integer)
            set hours of endDate to (item 13 of argv as integer)
            set minutes of endDate to (item 14 of argv as integer)
            set seconds of endDate to 0
            tell application "Calendar"
                if calendarName is "" then
                    set targetCalendar to first calendar
                else
                    set targetCalendar to calendar calendarName
                end if
                set newEvent to make new event at end of events of targetCalendar with properties {summary:eventTitle, start date:startDate, end date:endDate}
                try
                    return uid of newEvent
                on error
                    return "created"
                end try
            end tell
        end run
        """,
        args,
    )
    if not result["ok"]:
        return _with_permission_metadata(
            "calendar.create_event",
            {**result, "action": "calendar.create_event", "summary": "calendar.create_event failed"},
        )
    return {
        "ok": True,
        "action": "calendar.create_event",
        "summary": (
            f"Created calendar event: {clean_title} from {_format_local_datetime(start)} "
            f"to {_format_local_datetime(end)}"
        ),
        "data": {
            "title": clean_title,
            "start_at": _format_local_datetime(start),
            "end_at": _format_local_datetime(end),
            "calendar_name": clean_calendar_name,
            "event_id": str(result.get("stdout") or "").strip(),
        },
        "permission_error": False,
        "fallback_used": False,
    }


def desktop_hide_app() -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.hide_app")
    result = _run_osascript(
        """
        on run argv
            tell application "System Events" to keystroke "h" using {command down}
            return "hidden_app"
        end run
        """,
    )
    if not result["ok"]:
        return _with_permission_metadata(
            "desktop.hide_app",
            {
                **result,
                "action": "desktop.hide_app",
                "summary": "desktop.hide_app failed",
            },
        )
    return {
        "ok": True,
        "action": "desktop.hide_app",
        "summary": "Hid the foreground app",
        "data": {"key": "h", "modifiers": ["command"]},
        "permission_error": False,
        "fallback_used": False,
    }


def desktop_show_all_apps() -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.show_all_apps")
    result = _run_osascript(
        """
        on run argv
            set shownCount to 0
            tell application "System Events"
                repeat with processRef in application processes
                    try
                        if visible of processRef is false then
                            set visible of processRef to true
                            set shownCount to shownCount + 1
                        end if
                    end try
                end repeat
            end tell
            return "shown_all|" & shownCount
        end run
        """,
    )
    if not result["ok"]:
        return _with_permission_metadata(
            "desktop.show_all_apps",
            {
                **result,
                "action": "desktop.show_all_apps",
                "summary": "desktop.show_all_apps failed",
            },
        )
    stdout = str(result.get("stdout") or "").strip()
    parts = stdout.split("|") if stdout else []
    shown_count = _int_value(parts[1] if len(parts) > 1 else 0)
    return {
        "ok": True,
        "action": "desktop.show_all_apps",
        "summary": "Showed hidden apps",
        "data": {"shown_app_count": shown_count},
        "permission_error": False,
        "fallback_used": False,
    }


def desktop_minimize_window() -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.minimize_window")
    result = _run_osascript(
        """
        on run argv
            tell application "System Events" to keystroke "m" using {command down}
            return "minimized_window"
        end run
        """,
    )
    if not result["ok"]:
        return _with_permission_metadata(
            "desktop.minimize_window",
            {
                **result,
                "action": "desktop.minimize_window",
                "summary": "desktop.minimize_window failed",
            },
        )
    return {
        "ok": True,
        "action": "desktop.minimize_window",
        "summary": "Minimized the foreground window",
        "data": {"key": "m", "modifiers": ["command"]},
        "permission_error": False,
        "fallback_used": False,
    }


def desktop_close_window() -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.close_window")
    result = _run_osascript(
        """
        on run argv
            tell application "System Events" to keystroke "w" using {command down}
            return "closed_window"
        end run
        """,
    )
    if not result["ok"]:
        return _with_permission_metadata(
            "desktop.close_window",
            {
                **result,
                "action": "desktop.close_window",
                "summary": "desktop.close_window failed",
            },
        )
    return {
        "ok": True,
        "action": "desktop.close_window",
        "summary": "Closed the foreground window",
        "data": {"key": "w", "modifiers": ["command"]},
        "permission_error": False,
        "fallback_used": False,
    }


def desktop_quit_app() -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.quit_app")
    result = _run_osascript(
        """
        on run argv
            tell application "System Events" to keystroke "q" using {command down}
            return "quit_foreground_app"
        end run
        """,
    )
    if not result["ok"]:
        return _with_permission_metadata(
            "desktop.quit_app",
            {
                **result,
                "action": "desktop.quit_app",
                "summary": "desktop.quit_app failed",
            },
        )
    return {
        "ok": True,
        "action": "desktop.quit_app",
        "summary": "Sent quit request to the foreground app",
        "data": {"key": "q", "modifiers": ["command"]},
        "permission_error": False,
        "fallback_used": False,
    }


def desktop_safe_key(action: str, *, repeat_count: Any = 1) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.safe_key")
    clean_action = _clean_safe_key_action(action)
    clean_repeat_count = _clean_key_repeat_count(repeat_count)
    key_code, label = _SAFE_KEYS[clean_action]
    modifier_clause = " using {shift down}" if clean_action == "shift_tab" else ""
    result = _run_osascript(
        f"""
        on run argv
            set keyCodeValue to item 1 of argv as integer
            set repeatCount to item 2 of argv as integer
            repeat repeatCount times
                tell application "System Events" to key code keyCodeValue{modifier_clause}
                delay 0.05
            end repeat
            return "pressed"
        end run
        """,
        [str(key_code), str(clean_repeat_count)],
    )
    if not result["ok"]:
        return _with_permission_metadata(
            "desktop.safe_key",
            {**result, "action": "desktop.safe_key", "summary": "desktop.safe_key failed"},
        )
    return {
        "ok": True,
        "action": "desktop.safe_key",
        "summary": (
            f"Pressed safe foreground key: {label}"
            if clean_repeat_count == 1
            else f"Pressed safe foreground key: {label} x{clean_repeat_count}"
        ),
        "data": {
            "key_action": clean_action,
            "key_label": label,
            "key_code": key_code,
            "repeat_count": clean_repeat_count,
            "explicit_user_key": True,
        },
        "permission_error": False,
        "fallback_used": False,
    }


def desktop_type_text(text: str) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.type_text")
    return _send_desktop_text(
        "desktop.type_text",
        text,
        summary="Typed text into the foreground app",
    )


def desktop_safe_type_text(text: str) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.safe_type_text")
    payload = _send_desktop_text(
        "desktop.safe_type_text",
        text,
        summary="Typed user-provided text into the foreground app",
    )
    if payload.get("ok"):
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        payload["data"] = {**data, "explicit_user_text": True}
    return payload


def _send_desktop_text(
    action_name: str,
    text: str,
    *,
    summary: str,
) -> dict[str, Any]:
    clean_text = _clean_required(text, "text")
    result = _run_osascript(
        """
        on run argv
            set textToType to item 1 of argv
            tell application "System Events" to keystroke textToType
            return "typed"
        end run
        """,
        [clean_text],
    )
    if not result["ok"]:
        return _with_permission_metadata(
            action_name,
            {**result, "action": action_name, "summary": f"{action_name} failed"},
        )
    return {
        "ok": True,
        "action": action_name,
        "summary": summary,
        "data": {"character_count": len(clean_text)},
        "permission_error": False,
        "fallback_used": False,
    }


def desktop_click(x: Any, y: Any, *, click_count: Any = 1) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.click")
    return _send_desktop_click(
        "desktop.click",
        x,
        y,
        click_count=click_count,
    )


def desktop_safe_click(x: Any, y: Any) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.safe_click")
    payload = _send_desktop_click(
        "desktop.safe_click",
        x,
        y,
        click_count=1,
    )
    if payload.get("ok"):
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        payload["summary"] = f"Clicked explicit foreground coordinate at ({data.get('x')}, {data.get('y')})"
        payload["data"] = {**data, "explicit_user_coordinates": True}
    return payload


def desktop_safe_scroll(direction: str, *, pages: Any = 1) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.safe_scroll")
    clean_direction = _clean_scroll_direction(direction)
    clean_pages = _clean_scroll_pages(pages)
    key_code = 121 if clean_direction == "down" else 116
    result = _run_osascript(
        """
        on run argv
            set keyCodeValue to item 1 of argv as integer
            set pageCount to item 2 of argv as integer
            repeat pageCount times
                tell application "System Events" to key code keyCodeValue
                delay 0.05
            end repeat
            return "scrolled"
        end run
        """,
        [str(key_code), str(clean_pages)],
    )
    if not result["ok"]:
        return _with_permission_metadata(
            "desktop.safe_scroll",
            {**result, "action": "desktop.safe_scroll", "summary": "desktop.safe_scroll failed"},
        )
    label = "down" if clean_direction == "down" else "up"
    return {
        "ok": True,
        "action": "desktop.safe_scroll",
        "summary": f"Scrolled foreground desktop {label} {clean_pages} page{'s' if clean_pages != 1 else ''}",
        "data": {
            "direction": clean_direction,
            "pages": clean_pages,
            "key_code": key_code,
            "explicit_user_scroll": True,
        },
        "permission_error": False,
        "fallback_used": False,
    }


def _send_desktop_click(
    action_name: str,
    x: Any,
    y: Any,
    *,
    click_count: Any = 1,
) -> dict[str, Any]:
    clean_x = _clean_coordinate(x, "x")
    clean_y = _clean_coordinate(y, "y")
    clean_count = _clean_click_count(click_count)
    result = _run_osascript(
        """
        on run argv
            set xCoord to item 1 of argv as integer
            set yCoord to item 2 of argv as integer
            set clickCount to item 3 of argv as integer
            repeat clickCount times
                tell application "System Events" to click at {xCoord, yCoord}
                delay 0.05
            end repeat
            return "clicked"
        end run
        """,
        [str(clean_x), str(clean_y), str(clean_count)],
    )
    if not result["ok"]:
        return _with_permission_metadata(
            action_name,
            {**result, "action": action_name, "summary": f"{action_name} failed"},
        )
    return {
        "ok": True,
        "action": action_name,
        "summary": f"Clicked foreground desktop at ({clean_x}, {clean_y})",
        "data": {"x": clean_x, "y": clean_y, "click_count": clean_count},
        "permission_error": False,
        "fallback_used": False,
    }


def desktop_hotkey(key: str, modifiers: list[str] | None = None) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.hotkey")
    payload = _send_desktop_keystroke("desktop.hotkey", key, modifiers or [])
    if not payload.get("ok"):
        return payload
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    clean_key = str(data.get("key") or "").strip()
    clean_modifiers = data.get("modifiers") if isinstance(data.get("modifiers"), list) else []
    payload["summary"] = f"Pressed hotkey { '+'.join([*clean_modifiers, clean_key]) }"
    return payload


def desktop_submit_foreground(action: str = "submit") -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.submit_foreground")
    clean_action = str(action or "submit").strip().lower()
    if clean_action not in {"send", "submit", "confirm"}:
        clean_action = "submit"
    payload = _send_desktop_keystroke("desktop.submit_foreground", "return", [])
    if not payload.get("ok"):
        return payload
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    data["submit_action"] = clean_action
    payload["data"] = data
    payload["summary"] = f"Submitted foreground {clean_action} action"
    return payload


def desktop_search_submit() -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.search_submit")
    payload = _send_desktop_keystroke("desktop.search_submit", "return", [])
    if not payload.get("ok"):
        return payload
    payload["summary"] = "Submitted foreground search query"
    return payload


def desktop_safe_shortcut(action: str) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.safe_shortcut")
    clean_action = _clean_safe_shortcut_action(action)
    if clean_action == "copy_current_page_link":
        return _desktop_copy_current_page_link_shortcut()
    key, modifiers, label = _SAFE_SHORTCUTS[clean_action]
    payload = _send_desktop_keystroke("desktop.safe_shortcut", key, list(modifiers))
    if not payload.get("ok"):
        return payload
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    payload["summary"] = f"Executed safe shortcut: {label}"
    payload["data"] = {
        **data,
        "shortcut_action": clean_action,
        "shortcut_label": label,
    }
    return payload


def _desktop_copy_current_page_link_shortcut() -> dict[str, Any]:
    select_payload = _send_desktop_keystroke("desktop.safe_shortcut", "l", ["command"])
    if not select_payload.get("ok"):
        return select_payload
    copy_payload = _send_desktop_keystroke("desktop.safe_shortcut", "c", ["command"])
    if not copy_payload.get("ok"):
        return copy_payload
    data = copy_payload.get("data") if isinstance(copy_payload.get("data"), dict) else {}
    copy_payload["summary"] = "Executed safe shortcut: copy current page link"
    copy_payload["data"] = {
        **data,
        "shortcut_action": "copy_current_page_link",
        "shortcut_label": "copy current page link",
        "steps": [
            {"key": "l", "modifiers": ["command"]},
            {"key": "c", "modifiers": ["command"]},
        ],
    }
    return copy_payload


def _send_desktop_keystroke(
    action_name: str,
    key: str,
    modifiers: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    clean_key = _clean_required(key, "key")
    clean_modifiers = _clean_modifiers(list(modifiers or []))
    modifier_clause = ""
    if clean_modifiers:
        modifier_clause = " using {" + ", ".join(f"{item} down" for item in clean_modifiers) + "}"
    key_code = _HOTKEY_KEY_CODES.get(clean_key.lower())
    if key_code is None:
        result = _run_osascript(
            f"""
            on run argv
                set keyName to item 1 of argv
                tell application "System Events" to keystroke keyName{modifier_clause}
                return "hotkey"
            end run
            """,
            [clean_key],
        )
    else:
        result = _run_osascript(
            f"""
            on run argv
                set keyCodeValue to item 1 of argv as integer
                tell application "System Events" to key code keyCodeValue{modifier_clause}
                return "hotkey"
            end run
            """,
            [str(key_code)],
        )
    if not result["ok"]:
        return _with_permission_metadata(
            action_name,
            {**result, "action": action_name, "summary": f"{action_name} failed"},
        )
    data = {"key": clean_key, "modifiers": clean_modifiers}
    if key_code is not None:
        data["key_code"] = key_code
    return {
        "ok": True,
        "action": action_name,
        "summary": f"Pressed hotkey { '+'.join([*clean_modifiers, clean_key]) }",
        "data": data,
        "permission_error": False,
        "fallback_used": False,
    }


def _run_osascript(script: str, args: list[str] | None = None) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["osascript", "-e", script, *(args or [])],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return _error("osascript", exc)
    if result.returncode != 0:
        return _failed("osascript", result)
    return {
        "ok": True,
        "stdout": str(result.stdout or "").strip(),
        "stderr": str(result.stderr or "").strip(),
    }


def _desktop_platform() -> str:
    system = platform.system()
    if system == "Darwin":
        return "macos"
    if system == "Windows":
        return "windows"
    if system == "Linux":
        return "linux"
    return str(system or "unknown").lower()


def _unsupported(action: str) -> dict[str, Any]:
    return {
        "ok": False,
        "action": action,
        "summary": f"{action} is not supported on this platform yet.",
        "error": "unsupported_platform",
        "data": {"platform": _desktop_platform()},
        "permission_error": False,
        "fallback_used": False,
    }


def _error(action: str, exc: Exception) -> dict[str, Any]:
    payload = {
        "ok": False,
        "action": action,
        "summary": f"{action} failed",
        "error": str(exc),
        "data": {},
        "permission_error": _looks_like_permission_error(str(exc)),
        "fallback_used": False,
    }
    return _with_permission_metadata(action, payload)


def _failed(action: str, result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    output = "\n".join(
        part.strip()
        for part in (result.stderr, result.stdout)
        if isinstance(part, str) and part.strip()
    )
    payload = {
        "ok": False,
        "action": action,
        "summary": f"{action} failed",
        "error": output or f"exit code {result.returncode}",
        "data": {},
        "returncode": result.returncode,
        "permission_error": _looks_like_permission_error(output),
        "fallback_used": False,
    }
    return _with_permission_metadata(action, payload)


def _app_open_failed(app_name: str, result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    payload = _failed("app.open", result)
    payload["data"] = {"app_name": app_name}
    error = str(payload.get("error") or "")
    if _looks_like_app_not_found(error):
        payload["error_code"] = "app_not_found"
        payload["recovery_hints"] = [
            (
                "确认应用已安装，或换用 macOS 里的精确应用名，例如 "
                "Google Chrome、Safari、Music、Visual Studio Code。"
            )
        ]
        payload["recovery_actions"] = [
            {
                "label": "打开应用程序文件夹",
                "tool": "desktop.open_path",
                "input": {"path": "/Applications"},
                "permission_target": "app_not_found",
                "risk_level": "low",
            },
            {
                "label": "打开 App Store",
                "tool": "app.open",
                "input": {"app_name": "App Store"},
                "permission_target": "app_not_found",
                "risk_level": "low",
            },
        ]
    return payload


def _app_running_verification(app_name: str) -> dict[str, Any]:
    result = _run_osascript(
        """
        on run argv
            set appName to item 1 of argv
            if application appName is running then
                return "running"
            end if
            return "not_running"
        end run
        """,
        [app_name],
    )
    if result.get("ok"):
        status = str(result.get("stdout") or "").strip()
        return {
            "launch_verified": status == "running",
            "launch_status": status or "unknown",
        }
    return {
        "launch_verified": None,
        "launch_status": "unknown",
        "launch_verification_error": str(result.get("error") or result.get("stderr") or ""),
    }


def _looks_like_app_not_found(value: Any) -> bool:
    normalized = str(value or "").lower()
    return any(
        marker in normalized
        for marker in (
            "application not found",
            "unable to find application",
            "was not found",
            "can't find application",
            "can’t find application",
            "does not exist",
        )
    )


def _clean_required(value: str, field: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise ValueError(f"{field} is required")
    return clean


def _note_title_from_body(value: str) -> str:
    first_line = next((line.strip() for line in str(value or "").splitlines() if line.strip()), "")
    if not first_line:
        return "New Note"
    return first_line[:80]


def _parse_required_local_datetime(value: Any, field: str) -> datetime:
    if value in (None, ""):
        raise ValueError(f"{field} is required")
    return _parse_local_datetime(value, field)


def _parse_optional_local_datetime(value: Any, field: str) -> datetime | None:
    if value in (None, ""):
        return None
    return _parse_local_datetime(value, field)


def _parse_local_datetime(value: Any, field: str) -> datetime:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO local datetime") from exc
    return parsed.replace(tzinfo=None, second=0, microsecond=0)


def _datetime_argv(value: datetime | None) -> list[str]:
    if value is None:
        return ["false", "0", "1", "1", "0", "0"]
    return [
        "true",
        str(value.year),
        str(value.month),
        str(value.day),
        str(value.hour),
        str(value.minute),
    ]


def _format_local_datetime(value: datetime) -> str:
    return value.isoformat(timespec="minutes")


def _int_value(value: Any) -> int:
    try:
        return int(float(str(value or 0).strip()))
    except (TypeError, ValueError):
        return 0


def _clean_music_control_action(value: str) -> str:
    aliases = {
        "toggle": "toggle",
        "playpause": "toggle",
        "play_pause": "toggle",
        "pause": "pause",
        "play": "play",
        "resume": "play",
        "next": "next",
        "next_track": "next",
        "previous": "previous",
        "prev": "previous",
        "previous_track": "previous",
    }
    clean = aliases.get(str(value or "").strip().lower())
    if not clean:
        raise ValueError("action must be one of toggle, play, pause, next, or previous")
    return clean


def _clean_system_volume_action(value: str) -> str:
    aliases = {
        "status": "status",
        "read": "status",
        "get": "status",
        "set": "set",
        "up": "up",
        "increase": "up",
        "down": "down",
        "decrease": "down",
        "mute": "mute",
        "unmute": "unmute",
    }
    clean = aliases.get(str(value or "").strip().lower())
    if not clean:
        raise ValueError("action must be one of status, set, up, down, mute, or unmute")
    return clean


def _clean_system_brightness_action(value: str) -> str:
    aliases = {
        "up": "up",
        "increase": "up",
        "brighter": "up",
        "down": "down",
        "decrease": "down",
        "dimmer": "down",
    }
    clean = aliases.get(str(value or "").strip().lower())
    if not clean:
        raise ValueError("action must be one of up or down")
    return clean


def _read_system_volume() -> dict[str, Any]:
    result = _run_osascript(
        """
        set volumeSettings to get volume settings
        return (output volume of volumeSettings as text) & "|" & (output muted of volumeSettings as text)
        """
    )
    if not result["ok"]:
        return _with_permission_metadata(
            "system.volume",
            {**result, "action": "system.volume", "summary": "system.volume failed"},
        )
    level, muted = _parse_system_volume(result.get("stdout"))
    return {
        "ok": True,
        "action": "system.volume",
        "summary": f"System volume is {level}%{' and muted' if muted else ''}",
        "data": {"level": level, "muted": muted},
        "permission_error": False,
        "fallback_used": False,
    }


def _clipboard_write_command() -> list[str]:
    platform_name = _desktop_platform()
    if platform_name == "macos":
        return ["pbcopy"]
    if platform_name == "windows":
        return ["clip"]
    if platform_name == "linux":
        for command in (
            ["wl-copy"],
            ["xclip", "-selection", "clipboard"],
            ["xsel", "--clipboard", "--input"],
        ):
            if shutil.which(command[0]):
                return command
    return []


def _clipboard_read_command() -> list[str]:
    platform_name = _desktop_platform()
    if platform_name == "macos":
        return ["pbpaste"]
    if platform_name == "windows":
        return ["powershell", "-NoProfile", "-Command", "Get-Clipboard"]
    if platform_name == "linux":
        for command in (
            ["wl-paste", "--no-newline"],
            ["xclip", "-selection", "clipboard", "-out"],
            ["xsel", "--clipboard", "--output"],
        ):
            if shutil.which(command[0]):
                return command
    return []


def _clean_clipboard_read_limit(value: Any) -> int:
    if value in (None, ""):
        return 2000
    if isinstance(value, bool):
        raise ValueError("max_chars must be an integer from 1 to 12000")
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_chars must be an integer from 1 to 12000") from exc
    return max(1, min(12000, limit))


def _parse_system_volume(value: Any) -> tuple[int, bool]:
    parts = str(value or "").strip().split("|", 1)
    level_text = parts[0] if parts else "0"
    muted_text = parts[1] if len(parts) > 1 else "false"
    return _coerce_percentage(level_text, default=0), muted_text.strip().lower() == "true"


def _coerce_percentage(value: Any, *, default: int) -> int:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        raise ValueError("percentage must be a number from 0 to 100")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("percentage must be a number from 0 to 100") from exc
    return max(0, min(100, int(round(number))))


def _system_volume_summary(action: str, old_level: int, level: int, muted: bool) -> str:
    if action == "mute":
        return "System volume muted"
    if action == "unmute":
        return f"System volume unmuted at {level}%"
    if action == "set":
        return f"System volume set to {level}%"
    if action == "up":
        return f"System volume increased from {old_level}% to {level}%"
    if action == "down":
        return f"System volume decreased from {old_level}% to {level}%"
    return f"System volume is {level}%{' and muted' if muted else ''}"


def _clean_coordinate(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a non-negative screen coordinate")
    try:
        coordinate = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a non-negative screen coordinate") from exc
    if not math.isfinite(coordinate) or coordinate < 0 or coordinate > 100000:
        raise ValueError(f"{field} must be a non-negative screen coordinate")
    return int(round(coordinate))


def _clean_click_count(value: Any) -> int:
    if value in (None, ""):
        return 1
    if isinstance(value, bool):
        raise ValueError("click_count must be an integer from 1 to 3")
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("click_count must be an integer from 1 to 3") from exc
    if count < 1 or count > 3:
        raise ValueError("click_count must be an integer from 1 to 3")
    return count


def _clean_scroll_direction(value: str) -> str:
    aliases = {
        "down": "down",
        "page_down": "down",
        "pagedown": "down",
        "scroll_down": "down",
        "向下": "down",
        "下": "down",
        "往下": "down",
        "下滚": "down",
        "下滑": "down",
        "up": "up",
        "page_up": "up",
        "pageup": "up",
        "scroll_up": "up",
        "向上": "up",
        "上": "up",
        "往上": "up",
        "上滚": "up",
        "上滑": "up",
    }
    clean = aliases.get(str(value or "").strip().lower().replace("-", "_").replace(" ", "_"))
    if not clean:
        raise ValueError("direction must be up or down")
    return clean


def _clean_scroll_pages(value: Any) -> int:
    if value in (None, ""):
        return 1
    if isinstance(value, bool):
        raise ValueError("pages must be an integer from 1 to 10")
    try:
        pages = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("pages must be an integer from 1 to 10") from exc
    if pages < 1 or pages > 10:
        raise ValueError("pages must be an integer from 1 to 10")
    return pages


def _clean_modifiers(modifiers: list[str]) -> list[str]:
    aliases = {
        "cmd": "command",
        "command": "command",
        "shift": "shift",
        "option": "option",
        "alt": "option",
        "control": "control",
        "ctrl": "control",
    }
    clean: list[str] = []
    for modifier in modifiers:
        name = aliases.get(str(modifier or "").strip().lower())
        if name and name not in clean:
            clean.append(name)
    return clean


def _clean_safe_shortcut_action(action: str) -> str:
    clean = str(action or "").strip().lower().replace("-", "_")
    if clean not in _SAFE_SHORTCUTS:
        raise ValueError(f"unsupported safe shortcut action: {action}")
    return clean


def _clean_safe_key_action(action: str) -> str:
    clean = str(action or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "esc": "escape",
        "退出": "escape",
        "取消": "escape",
        "tab_key": "tab",
        "制表": "tab",
        "制表键": "tab",
        "shift_tab": "shift_tab",
        "shifttab": "shift_tab",
        "shift+tab": "shift_tab",
        "shift_tab_key": "shift_tab",
        "上一个输入框": "shift_tab",
        "上一输入框": "shift_tab",
        "up": "arrow_up",
        "down": "arrow_down",
        "left": "arrow_left",
        "right": "arrow_right",
        "arrowup": "arrow_up",
        "arrowdown": "arrow_down",
        "arrowleft": "arrow_left",
        "arrowright": "arrow_right",
        "上": "arrow_up",
        "下": "arrow_down",
        "左": "arrow_left",
        "右": "arrow_right",
        "上箭头": "arrow_up",
        "下箭头": "arrow_down",
        "左箭头": "arrow_left",
        "右箭头": "arrow_right",
        "向上箭头": "arrow_up",
        "往上箭头": "arrow_up",
        "朝上箭头": "arrow_up",
        "向下箭头": "arrow_down",
        "往下箭头": "arrow_down",
        "朝下箭头": "arrow_down",
        "向左箭头": "arrow_left",
        "往左箭头": "arrow_left",
        "朝左箭头": "arrow_left",
        "向右箭头": "arrow_right",
        "往右箭头": "arrow_right",
        "朝右箭头": "arrow_right",
        "向上键": "arrow_up",
        "向下键": "arrow_down",
        "向左键": "arrow_left",
        "向右键": "arrow_right",
        "home_key": "home",
        "end_key": "end",
        "pageup": "page_up",
        "page_up_key": "page_up",
        "pagedown": "page_down",
        "page_down_key": "page_down",
    }
    clean = aliases.get(clean, clean)
    if clean not in _SAFE_KEYS:
        raise ValueError(f"unsupported safe key action: {action}")
    return clean


def _clean_key_repeat_count(value: Any) -> int:
    if value in (None, ""):
        return 1
    if isinstance(value, bool):
        raise ValueError("repeat_count must be an integer from 1 to 20")
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("repeat_count must be an integer from 1 to 20") from exc
    if count < 1 or count > 20:
        raise ValueError("repeat_count must be an integer from 1 to 20")
    return count


def _clean_brightness_step(value: Any) -> int:
    if value in (None, ""):
        return 2
    if isinstance(value, bool):
        raise ValueError("step must be an integer from 1 to 10")
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("step must be an integer from 1 to 10") from exc
    if count < 1 or count > 10:
        raise ValueError("step must be an integer from 1 to 10")
    return count


def _parse_running_apps(value: Any) -> list[dict[str, Any]]:
    apps: list[dict[str, Any]] = []
    for raw_line in str(value or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        name, pid_text, frontmost_text = _split_status(line)
        if not name:
            continue
        apps.append(
            {
                "name": name,
                "pid": int(pid_text) if pid_text.isdigit() else None,
                "frontmost": frontmost_text.strip().lower() == "true",
            }
        )
    return apps


def _parse_window_rows(value: Any) -> list[dict[str, Any]]:
    windows_payload: list[dict[str, Any]] = []
    for raw_line in str(value or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\t", 4)
        while len(parts) < 5:
            parts.append("")
        app_name, pid_text, index_text, frontmost_text, title = parts
        if not app_name:
            continue
        windows_payload.append(
            {
                "app_name": app_name,
                "pid": int(pid_text) if pid_text.isdigit() else None,
                "index": int(index_text) if index_text.isdigit() else None,
                "frontmost": frontmost_text.strip().lower() == "true",
                "title": title.strip(),
            }
        )
    return windows_payload


def _parse_ui_elements_output(
    value: Any,
    role_filter: str = "",
    limit: int = 80,
) -> dict[str, Any]:
    app_name = ""
    pid: int | None = None
    title = ""
    elements: list[dict[str, Any]] = []
    normalized_filter = str(role_filter or "").strip().lower()
    for raw_line in str(value or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if parts[0] == "META":
            while len(parts) < 4:
                parts.append("")
            app_name = parts[1].strip()
            pid = int(parts[2]) if parts[2].strip().isdigit() else None
            title = parts[3].strip()
            continue
        while len(parts) < 11:
            parts.append("")
        depth, role, subrole, name, description, element_value, enabled, x, y, width, height = parts[:11]
        searchable = " ".join((role, subrole, name, description, element_value)).lower()
        if normalized_filter and normalized_filter not in searchable:
            continue
        element: dict[str, Any] = {
            "depth": _int_or_none(depth) or 0,
            "role": role.strip(),
            "subrole": subrole.strip(),
            "name": name.strip(),
            "description": description.strip(),
            "value": element_value.strip(),
            "enabled": enabled.strip().lower() == "true" if enabled.strip() else None,
        }
        frame = _ui_element_frame(x, y, width, height)
        if frame:
            element["frame"] = frame
            element["center"] = {
                "x": int(round(frame["x"] + frame["width"] / 2)),
                "y": int(round(frame["y"] + frame["height"] / 2)),
            }
        elements.append(element)
        if len(elements) >= limit:
            break
    return {
        "app_name": app_name,
        "pid": pid,
        "title": title,
        "elements": elements,
        "count": len(elements),
        "truncated": len(elements) >= limit,
    }


def _matching_ui_elements(
    elements: list[Any],
    target: str,
    role_filter: str = "",
) -> list[dict[str, Any]]:
    target_text = _normalize_ui_match_text(target)
    if not target_text:
        return []
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for index, raw_element in enumerate(elements):
        if not isinstance(raw_element, dict):
            continue
        element = dict(raw_element)
        if element.get("enabled") is False:
            continue
        center = element.get("center") if isinstance(element.get("center"), dict) else {}
        if center.get("x") is None or center.get("y") is None:
            continue
        score = _ui_element_match_score(element, target_text, role_filter)
        if score <= 0:
            continue
        depth = element.get("depth") if isinstance(element.get("depth"), int) else 0
        scored.append((score - depth, -index, element))
    scored.sort(reverse=True, key=lambda item: (item[0], item[1]))
    return [element for _, _, element in scored]


def _ui_element_match_score(
    element: dict[str, Any],
    normalized_target: str,
    role_filter: str = "",
) -> int:
    label_texts = [_normalize_ui_match_text(_ui_element_field(element, key)) for key in ("name", "description", "value")]
    label_texts = [text for text in label_texts if text]
    searchable = _normalize_ui_match_text(
        " ".join(
            _ui_element_field(element, key)
            for key in ("role", "subrole", "name", "description", "value")
        )
    )
    if not searchable:
        return 0
    score = 0
    if normalized_target in label_texts:
        score = 100
    elif any(normalized_target in text for text in label_texts):
        score = 85
    elif any(text in normalized_target for text in label_texts if len(text) >= 2):
        score = 70
    elif normalized_target in searchable:
        score = 55
    if not score:
        return 0
    normalized_filter = _normalize_ui_match_text(role_filter)
    if normalized_filter and normalized_filter in searchable:
        score += 10
    if str(element.get("role") or "").strip():
        score += 2
    return score


def _candidate_ui_element_previews(elements: list[Any], limit: int = 8) -> list[dict[str, Any]]:
    previews: list[dict[str, Any]] = []
    for raw_element in elements:
        if not isinstance(raw_element, dict):
            continue
        label = _ui_element_display_label(raw_element)
        center = raw_element.get("center") if isinstance(raw_element.get("center"), dict) else None
        if not label and not center:
            continue
        preview: dict[str, Any] = {
            "role": str(raw_element.get("role") or ""),
            "label": label,
            "enabled": raw_element.get("enabled"),
        }
        if center:
            preview["center"] = center
        previews.append(preview)
        if len(previews) >= limit:
            break
    return previews


def _ui_element_display_label(element: dict[str, Any]) -> str:
    return (
        _ui_element_field(element, "name")
        or _ui_element_field(element, "description")
        or _ui_element_field(element, "value")
        or _ui_element_field(element, "role")
    )


def _ui_element_field(element: dict[str, Any], key: str) -> str:
    return str(element.get(key) or "").strip()


def _normalize_ui_match_text(value: Any) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return normalized.strip("\"'“”‘’[]()（） ")


def _ui_element_frame(x: Any, y: Any, width: Any, height: Any) -> dict[str, int] | None:
    values = [_int_or_none(item) for item in (x, y, width, height)]
    if any(value is None for value in values):
        return None
    frame_x, frame_y, frame_width, frame_height = values
    if frame_width is None or frame_height is None or frame_width < 0 or frame_height < 0:
        return None
    return {
        "x": int(frame_x or 0),
        "y": int(frame_y or 0),
        "width": int(frame_width),
        "height": int(frame_height),
    }


def _int_or_none(value: Any) -> int | None:
    try:
        return int(round(float(str(value or "").strip())))
    except (TypeError, ValueError):
        return None


def _ui_elements_summary(elements: list[dict[str, Any]], app_name: str = "") -> str:
    if not elements:
        return f"No visible UI elements found for {app_name}" if app_name else "No visible UI elements found"
    visible = []
    for item in elements[:5]:
        role = str(item.get("role") or "element").strip()
        label = (
            str(item.get("name") or "").strip()
            or str(item.get("description") or "").strip()
            or str(item.get("value") or "").strip()
        )
        visible.append(f"{role}: {label}" if label else role)
    suffix = f" (+{len(elements) - len(visible)} more)" if len(elements) > len(visible) else ""
    prefix = f"{app_name} UI elements" if app_name else "UI elements"
    return f"{prefix}: {', '.join(visible)}{suffix}"


def _running_apps_summary(names: list[str]) -> str:
    if not names:
        return "No foreground apps are running"
    visible = names[:5]
    suffix = f" (+{len(names) - len(visible)} more)" if len(names) > len(visible) else ""
    return f"Running apps: {', '.join(visible)}{suffix}"


def _windows_summary(windows_payload: list[dict[str, Any]], app_name: str = "") -> str:
    if not windows_payload:
        return f"No windows found for {app_name}" if app_name else "No desktop windows found"
    visible = []
    for item in windows_payload[:5]:
        app = str(item.get("app_name") or "").strip()
        title = str(item.get("title") or "").strip()
        visible.append(f"{app}: {title}" if title else app)
    suffix = (
        f" (+{len(windows_payload) - len(visible)} more)"
        if len(windows_payload) > len(visible)
        else ""
    )
    return f"Open windows: {', '.join(visible)}{suffix}"


def _clean_missing_permissions_by_capability(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    clean: dict[str, list[str]] = {}
    for capability, raw_targets in value.items():
        capability_id = str(capability or "").strip()
        if not capability_id:
            continue
        if isinstance(raw_targets, (list, tuple, set)):
            targets = _ordered_unique(str(item or "").strip() for item in raw_targets)
        else:
            targets = _ordered_unique([str(raw_targets or "").strip()])
        clean[capability_id] = [target for target in targets if target]
    return clean


def _affected_tools_for_missing_permissions(
    missing_by_capability: dict[str, list[str]],
) -> list[str]:
    tools: list[str] = []
    for capability_id, missing_targets in missing_by_capability.items():
        if not missing_targets:
            continue
        if capability_id == "desktop_execution":
            tools.extend(
                tool
                for capability_tools in _PERMISSION_CAPABILITY_TOOLS.values()
                for tool in capability_tools
            )
            continue
        tools.extend(_PERMISSION_CAPABILITY_TOOLS.get(capability_id, ()))
    return _ordered_unique(tools)


def _desktop_permissions_summary(
    missing_targets: list[str],
    affected_tools: list[str],
) -> str:
    if not missing_targets:
        return "Desktop execution permissions are ready."
    targets = ", ".join(missing_targets[:6])
    target_suffix = "..." if len(missing_targets) > 6 else ""
    if not affected_tools:
        return f"Missing desktop permissions: {targets}{target_suffix}"
    tools = ", ".join(affected_tools[:6])
    tool_suffix = "..." if len(affected_tools) > 6 else ""
    return f"Missing desktop permissions: {targets}{target_suffix}. Affected tools: {tools}{tool_suffix}"


def _permission_recovery_actions_for_targets(targets: list[str]) -> list[dict[str, Any]]:
    seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
    actions: list[dict[str, Any]] = []
    for target in targets:
        for action in _PERMISSION_RECOVERY_ACTIONS.get(str(target or "").strip(), ()):
            tool_name = str(action.get("tool") or "").strip()
            raw_input = action.get("input") if isinstance(action.get("input"), dict) else {}
            input_key = tuple(
                sorted((str(key), str(value)) for key, value in raw_input.items())
            )
            key = (tool_name, input_key)
            if not tool_name or key in seen:
                continue
            seen.add(key)
            actions.append(
                {
                    "label": str(action.get("label") or tool_name),
                    "tool": tool_name,
                    "input": dict(raw_input),
                    "permission_target": str(action.get("permission_target") or target),
                    "risk_level": str(action.get("risk_level") or "low"),
                }
            )
    return actions


def _ordered_unique(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        clean = str(value or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def _split_status(value: Any) -> tuple[str, str, str]:
    parts = str(value or "").strip().split("|", 2)
    while len(parts) < 3:
        parts.append("")
    return parts[0], parts[1], parts[2]


def _looks_like_permission_error(value: Any) -> bool:
    if value.__class__.__name__ == "ScreenCapturePermissionError":
        return True
    normalized = str(value or "").lower()
    return any(
        marker in normalized
        for marker in (
            "not authorized",
            "not allowed",
            "not permitted",
            "accessibility",
            "automation",
            "privacy",
            "screen capture",
            "screen recording",
            "tcc",
        )
    )


def _with_permission_metadata(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not payload.get("permission_error"):
        return payload
    missing_permissions = _missing_permissions_for_action(action)
    permission_targets = _permission_targets_for_action(action)
    if missing_permissions:
        payload["missing_permissions"] = missing_permissions
    if permission_targets:
        payload["permission_targets"] = permission_targets
    recovery_hints = _permission_recovery_hints_for_targets(permission_targets)
    if recovery_hints:
        payload["recovery_hints"] = recovery_hints
    recovery_actions = _permission_recovery_actions_for_targets(permission_targets)
    if recovery_actions:
        payload["recovery_actions"] = recovery_actions
    return payload


def _missing_permissions_for_action(action: str) -> list[str]:
    return {
        "screen.capture": ["screen_recording"],
        "desktop.active_window": ["automation_or_accessibility"],
        "desktop.running_apps": ["automation_or_accessibility"],
        "desktop.windows": ["automation_or_accessibility"],
        "desktop.ui_elements": ["automation_or_accessibility"],
        "desktop.click_ui_element": ["automation_or_accessibility"],
        "desktop.type_into_ui_element": ["automation_or_accessibility"],
        "app.focus": ["automation"],
        "app.focus_window": ["automation", "accessibility"],
        "app.show": ["automation", "accessibility"],
        "app.hide": ["accessibility"],
        "app.minimize": ["accessibility"],
        "app.quit": ["automation"],
        "media.apple_music_play": ["music_app", "automation"],
        "media.apple_music_status": ["music_app", "automation"],
        "media.apple_music_open_and_play": ["music_app", "automation"],
        "media.apple_music_control": ["music_app", "automation"],
        "media.system_control": ["accessibility"],
        "media.music_app_open_and_play": ["accessibility", "open_command"],
        "media.music_app_control": ["accessibility"],
        "system.brightness": ["accessibility"],
        "notes.create": ["automation"],
        "reminders.create": ["automation"],
        "calendar.create_event": ["automation"],
        "desktop.hide_app": ["accessibility"],
        "desktop.show_all_apps": ["accessibility"],
        "desktop.minimize_window": ["accessibility"],
        "desktop.close_window": ["accessibility"],
        "desktop.quit_app": ["accessibility"],
        "desktop.safe_shortcut": ["accessibility"],
        "desktop.safe_key": ["accessibility"],
        "desktop.search_submit": ["accessibility"],
        "desktop.submit_foreground": ["accessibility"],
        "desktop.safe_type_text": ["accessibility"],
        "desktop.safe_click": ["accessibility"],
        "desktop.safe_scroll": ["accessibility"],
        "app.open_and_safe_type_text": ["accessibility", "open_command"],
        "app.focus_and_safe_type_text": ["accessibility", "automation"],
        "app.open_and_safe_shortcut": ["accessibility", "open_command"],
        "app.focus_and_safe_shortcut": ["accessibility", "automation"],
        "app.open_and_safe_key": ["accessibility", "open_command"],
        "app.focus_and_safe_key": ["accessibility", "automation"],
        "app.open_and_hotkey": ["accessibility", "open_command"],
        "app.focus_and_hotkey": ["accessibility", "automation"],
        "app.open_and_safe_scroll": ["accessibility", "open_command"],
        "app.focus_and_safe_scroll": ["accessibility", "automation"],
        "app.open_and_safe_click": ["accessibility", "open_command"],
        "app.focus_and_safe_click": ["accessibility", "automation"],
        "app.open_and_click_ui_element": ["automation_or_accessibility", "open_command"],
        "app.focus_and_click_ui_element": ["automation_or_accessibility", "automation"],
        "app.open_and_type_into_ui_element": ["automation_or_accessibility", "open_command"],
        "app.focus_and_type_into_ui_element": ["automation_or_accessibility", "automation"],
        "desktop.click": ["accessibility"],
        "desktop.type_text": ["accessibility"],
        "desktop.hotkey": ["accessibility"],
        "osascript": ["automation"],
    }.get(action, [])


def _permission_targets_for_action(action: str) -> list[str]:
    return {
        "screen.capture": ["screen_recording"],
        "desktop.active_window": ["automation", "accessibility"],
        "desktop.running_apps": ["automation", "accessibility"],
        "desktop.windows": ["automation", "accessibility"],
        "desktop.ui_elements": ["automation", "accessibility"],
        "app.focus": ["automation"],
        "app.focus_window": ["automation", "accessibility"],
        "app.show": ["automation", "accessibility"],
        "app.hide": ["accessibility"],
        "app.minimize": ["accessibility"],
        "app.quit": ["automation"],
        "media.apple_music_play": ["music_app", "automation"],
        "media.apple_music_status": ["music_app", "automation"],
        "media.apple_music_open_and_play": ["music_app", "automation"],
        "media.apple_music_control": ["music_app", "automation"],
        "media.system_control": ["accessibility"],
        "media.music_app_control": ["accessibility"],
        "system.brightness": ["accessibility"],
        "notes.create": ["automation"],
        "reminders.create": ["automation"],
        "calendar.create_event": ["automation"],
        "desktop.hide_app": ["accessibility"],
        "desktop.show_all_apps": ["accessibility"],
        "desktop.minimize_window": ["accessibility"],
        "desktop.close_window": ["accessibility"],
        "desktop.quit_app": ["accessibility"],
        "desktop.safe_shortcut": ["accessibility"],
        "desktop.safe_key": ["accessibility"],
        "desktop.search_submit": ["accessibility"],
        "desktop.submit_foreground": ["accessibility"],
        "desktop.safe_type_text": ["accessibility"],
        "desktop.safe_click": ["accessibility"],
        "desktop.safe_scroll": ["accessibility"],
        "app.open_and_safe_type_text": ["accessibility", "open_command"],
        "app.focus_and_safe_type_text": ["accessibility", "automation"],
        "app.open_and_safe_shortcut": ["accessibility", "open_command"],
        "app.focus_and_safe_shortcut": ["accessibility", "automation"],
        "app.open_and_safe_key": ["accessibility", "open_command"],
        "app.focus_and_safe_key": ["accessibility", "automation"],
        "app.open_and_hotkey": ["accessibility", "open_command"],
        "app.focus_and_hotkey": ["accessibility", "automation"],
        "app.open_and_safe_scroll": ["accessibility", "open_command"],
        "app.focus_and_safe_scroll": ["accessibility", "automation"],
        "app.open_and_safe_click": ["accessibility", "open_command"],
        "app.focus_and_safe_click": ["accessibility", "automation"],
        "app.open_and_click_ui_element": ["automation", "accessibility", "open_command"],
        "app.focus_and_click_ui_element": ["automation", "accessibility"],
        "app.open_and_type_into_ui_element": ["automation", "accessibility", "open_command"],
        "app.focus_and_type_into_ui_element": ["automation", "accessibility"],
        "desktop.click": ["accessibility"],
        "desktop.click_ui_element": ["automation", "accessibility"],
        "desktop.type_into_ui_element": ["automation", "accessibility"],
        "desktop.type_text": ["accessibility"],
        "desktop.hotkey": ["accessibility"],
        "osascript": ["automation"],
    }.get(action, [])


def _permission_recovery_hints_for_targets(targets: list[str]) -> list[str]:
    hints_by_target = {
        "accessibility": (
            "Grant Accessibility permission to Oha-Yachiyo or the current terminal "
            "in macOS System Settings > Privacy & Security > Accessibility."
        ),
        "automation": (
            "Grant Automation permission so Oha-Yachiyo can control System Events "
            "or the target app in macOS System Settings > Privacy & Security > Automation."
        ),
        "automation_or_accessibility": (
            "Grant Automation and Accessibility permissions to Oha-Yachiyo or the current "
            "runtime in macOS System Settings > Privacy & Security."
        ),
        "music_app": (
            "Open Music.app once, confirm the track exists in the local library, "
            "and allow Automation when macOS asks for Music control."
        ),
        "screen_recording": (
            "Grant Screen Recording permission to Oha-Yachiyo or the current terminal "
            "in macOS System Settings > Privacy & Security > Screen Recording."
        ),
        "screen_capture_probe_failed": (
            "Open Screen Recording permission in macOS System Settings and confirm "
            "Oha-Yachiyo or the current runtime is allowed."
        ),
        "input_monitoring": (
            "Grant Input Monitoring permission to Oha-Yachiyo or the current runtime "
            "in macOS System Settings > Privacy & Security > Input Monitoring."
        ),
        "full_disk_access": (
            "Grant Full Disk Access to Oha-Yachiyo or the current runtime in macOS "
            "System Settings > Privacy & Security > Full Disk Access."
        ),
        "files_and_folders": (
            "Grant Files and Folders permission to Oha-Yachiyo or the current runtime "
            "in macOS System Settings > Privacy & Security > Files and Folders."
        ),
        "microphone": (
            "Grant Microphone permission to Oha-Yachiyo or the current runtime in "
            "macOS System Settings > Privacy & Security > Microphone."
        ),
        "camera": (
            "Grant Camera permission to Oha-Yachiyo or the current runtime in macOS "
            "System Settings > Privacy & Security > Camera."
        ),
        "chrome_cdp": (
            "Open or configure Google Chrome with a reachable Chrome DevTools/CDP endpoint "
            "before retrying browser control."
        ),
        "open_command": (
            "macOS open command is unavailable in this environment, so local app launch "
            "cannot be recovered from System Settings."
        ),
        "unsupported_platform": (
            "Desktop execution is currently implemented for macOS in this runtime."
        ),
    }
    hints: list[str] = []
    for target in targets:
        hint = hints_by_target.get(str(target or "").strip())
        if hint and hint not in hints:
            hints.append(hint)
    return hints
