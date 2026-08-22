# Headless Media Player — NVDA Add-on User Guide

**Version:** 1.1.6  
**Author:** Mahmoud Abo El Fotouh <mahmoudaboelfotouh.20@gmail.com>  
**Repository:** [https://github.com/Mahmoud-Abo-El-Fotouh/HeadlessPlayer](https://github.com/Mahmoud-Abo-El-Fotouh/HeadlessPlayer)  
**NVDA Compatibility:** NVDA 2022.1 to 2025.3+

---

## Overview
**Headless Media Player** is a high-performance, completely headless, privacy-oriented background media player add-on for the NVDA screen reader. It enables seamless playback of local audio and video files, entire directories, playlists, and online streams (YouTube videos, playlists, channels, search queries, live streams, Twitch, SoundCloud, web radio) with **zero visible UI, zero floating windows, and zero taskbar presence**.

---

## 1. Core Concept: Modal Keyboard Capture (Player Mode)
When Player Mode is active (<kbd>NVDA+Ctrl+Shift+P</kbd>):
- All keystrokes are captured exclusively by the media engine and blocked from leaking into background applications.
- Single keystrokes control playback, seeking, speed, volume, and YouTube searching without typing into documents.
- Press <kbd>Escape</kbd> or <kbd>NVDA+Ctrl+Shift+P</kbd> at any time to exit Player Mode and restore normal keyboard input.

---

## 2. Global NVDA Shortcuts
| Shortcut | Action | Description |
| :--- | :--- | :--- |
| <kbd>NVDA+Ctrl+Shift+P</kbd> *(or Insert/CapsLock)* | Toggle Player Mode | Enters or exits modal keyboard capture. |
| <kbd>NVDA+Ctrl+Windows+E</kbd> *(or Insert/Win)* | Play from Explorer / Desktop | Queues and plays the currently focused/selected file or folder in Explorer. |

---

## 3. Complete Player Mode Shortcuts Reference

### 3.1. Playback & Volume
| Key | Action | Description |
| :--- | :--- | :--- |
| <kbd>Space</kbd> | Play / Pause | Toggles playback. Restarts from start if track reached end. |
| <kbd>s</kbd> | Stop | Stops playback, saves position, rewinds to 0:00. |
| <kbd>m</kbd> | Mute / Unmute | Toggles audio mute. |
| <kbd>Up Arrow</kbd> | Volume Up | Increases volume by +5%. |
| <kbd>Down Arrow</kbd> | Volume Down | Decreases volume by -5%. |
| <kbd>b</kbd> | Bass Boost | Increases equalizer bass (+3 dB). |
| <kbd>Shift + b</kbd> | Bass Reduce | Decreases equalizer bass (-3 dB). |
| <kbd>Escape</kbd> | Exit Player Mode | Deactivates modal capture immediately. |
| <kbd>Control</kbd> | Silence Speech | Instantly cancels ongoing speech. |

### 3.2. Granular Seeking & Direct Percentage Jumps
| Key | Action | Default Step |
| :--- | :--- | :--- |
| <kbd>Left</kbd> / <kbd>Right Arrow</kbd> | Normal Seek | - / + 5 seconds (Configurable) |
| <kbd>Alt + Left</kbd> / <kbd>Alt + Right</kbd> | Slow / Precise Seek | - / + 1 second (Configurable) |
| <kbd>Ctrl + Left</kbd> / <kbd>Ctrl + Right</kbd> | Fast Seek | - / + 30 seconds (Configurable) |
| <kbd>Shift + Left</kbd> / <kbd>Shift + Right</kbd> | Ultrafast Seek | - / + 5 minutes (300s, Configurable) |
| <kbd>1</kbd> to <kbd>9</kbd> | Percentage Jump | Jumps directly to 10% through 90% of file. |
| <kbd>0</kbd> | Jump to Start | Rewinds directly to 0%. |

### 3.3. Pitch-Preserved Variable Speed
| Key | Action | Description |
| :--- | :--- | :--- |
| <kbd>Ctrl + Up</kbd> | Fine Speed Up | +0.1x speed adjustment with 100% natural pitch. |
| <kbd>Ctrl + Down</kbd> | Fine Speed Down | -0.1x speed adjustment. |
| <kbd>Shift + Up</kbd> | Next Preset Speed | Cycles: 1.0x -> 1.25x -> 1.5x -> 1.75x -> 2.0x -> 2.25x -> 2.5x -> 3.0x -> 3.5x -> 4.0x. |
| <kbd>Shift + Down</kbd> | Previous Preset Speed | Cycles down through presets. |

### 3.4. A-B Segment Repeat & Track Repeat
| Key | Action | Description |
| :--- | :--- | :--- |
| <kbd>[</kbd> *(or Arabic <kbd>ج</kbd>)* | Mark Point A | Sets loop starting point. |
| <kbd>]</kbd> *(or Arabic <kbd>د</kbd>)* | Mark Point B | Sets loop ending point and begins endless A-B repetition. |
| <kbd>c</kbd> | Clear A-B Loop | Clears loop points and returns to sequential playback. |
| <kbd>r</kbd> | Toggle Repeat Mode | Cycles: Track Repeat -> Playlist Repeat -> Repeat Off. |

### 3.5. Playlist, Files, and Chapter Navigation
| Key | Action | Description |
| :--- | :--- | :--- |
| <kbd>Page Down</kbd> *(or Tab)* | Next Track | Advances to next track in playlist. |
| <kbd>Page Up</kbd> *(or Shift+Tab)* | Previous Track | Returns to previous track in playlist. |
| <kbd>n</kbd> | Toggle Auto-Next | Toggles automatic advancement to next track upon completion. |
| <kbd>z</kbd> | Toggle Shuffle | Non-destructive shuffle/unshuffle. |
| <kbd>Ctrl + Shift + Right</kbd> | Next Chapter | Jumps to next chapter (speaks title/index). |
| <kbd>Ctrl + Shift + Left</kbd> | Previous Chapter | Jumps to previous chapter. |
| <kbd>a</kbd> | Cycle Audio Track | Switches audio tracks/languages in video files. |
| <kbd>o</kbd> | Open File Dialog | Prompts for single audio/video file. |
| <kbd>f</kbd> | Open Folder Dialog | Prompts for folder to queue in natural order. |
| <kbd>e</kbd> | Play Explorer Selection | Plays focused file/folder from Windows Explorer. |

### 3.6. Speech Queries & Help
| Key | Action | Description |
| :--- | :--- | :--- |
| <kbd>i</kbd> | Speak Media Info | Announces title, formatted duration, and track index (e.g. *Track 3 of 15*). |
| <kbd>Ctrl + i</kbd> | Speak Remaining Time | Announces remaining time in hours:minutes:seconds. |
| <kbd>Shift + i</kbd> | Speak Elapsed Time | Announces elapsed playback time. |
| <kbd>h</kbd> *(or Arabic <kbd>ا</kbd>)* | Shortcuts Help | Opens accessible shortcuts quick reference dialog. |

---

## 4. YouTube & Online Streaming
- **Search (<kbd>u</kbd>):** Press <kbd>u</kbd>, type query, press <kbd>Enter</kbd>. Browse results with Up/Down arrows and press <kbd>Enter</kbd> to play. Press <kbd>Tab</kbd> on a playlist to queue all tracks at once.
- **Direct URLs (<kbd>u</kbd>):** Paste any YouTube video/playlist URL, Twitch stream, SoundCloud link, or radio stream.
- **YouTube Portal (<kbd>p</kbd>):** Browse Regional Trending videos, My Subscriptions, and My Playlists.
- **Copy Link (<kbd>v</kbd>):** Copies active stream URL to Windows Clipboard.

---

## 5. Important: YouTube Login & Cookies Setup
> [!IMPORTANT]
> **Why direct Chrome cookie extraction does not work:**  
> Modern versions of Google Chrome and Microsoft Edge on Windows (Chrome 120+) enforce strict **App-Bound Encryption** (DPAPI + `v20` key protection). This prevents external tools from decrypting cookies directly from Chrome's SQLite files on disk.

### Easy Cookie Export with Browser Extensions:
1. Install an extension to export cookies:
   - **For Chrome, Edge, Brave:** [Get cookies.txt LOCALLY (Chrome Web Store)](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
   - **For Firefox:** [cookies.txt (Firefox Add-ons)](https://addons.mozilla.org/firefox/addon/cookies-txt/)
2. Open [YouTube.com](https://www.youtube.com) and log in to your account.
3. Click the extension icon and export your `cookies.txt` file.
4. In NVDA, open **Preferences -> Settings -> Headless Media Player**.
5. Click **Browse...** next to *Custom Cookies File*, select your `cookies.txt` file, and press **OK**.

---

## 6. NVDA Settings & Customization
Located in **NVDA Menu -> Preferences -> Settings -> Headless Media Player**:
- **Speech Verbosity:** Toggle individual announcements for volume, seek, speed, track changes, repeat, and A-B points.
- **Seek Step Sizes:** Configure seconds for Normal (5s), Slow (1s), Fast (30s), and Ultrafast (300s) seeks.
- **Defaults:** Resume playback position, default speed, auto-next, and auto-entering Player Mode.
- **YouTube Options:** Audio stream quality (Opus, M4A, Best), Custom Cookies file, and In-App "Check for Updates" button.
- **Interactive Shortcut Customizer:** Assign combined modifier keys (e.g. `Shift + Tab`) to any action with live key capture.

---

## 7. Supported Formats
- **Audio:** `.mp3`, `.wav`, `.flac`, `.m4a`, `.aac`, `.ogg`, `.opus`, `.wma`, `.alac`, `.aiff`, `.ape`, `.ac3`, `.dts`, `.mka`, `.mid`, `.amr`, `.spx`
- **Video (Headless):** `.mp4`, `.mkv`, `.avi`, `.webm`, `.mov`, `.wmv`, `.flv`, `.ts`, `.m2ts`, `.vob`, `.ogv`, `.3gp`, `.mpg`
- **Playlists:** `.m3u`, `.m3u8`, `.pls`, `.cue`
- **Online:** YouTube (Videos, Playlists, Channels, Shorts, Live), Twitch, SoundCloud, HTTP/HTTPS audio, HLS (`.m3u8`) radio.
