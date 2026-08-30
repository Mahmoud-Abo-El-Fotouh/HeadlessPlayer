# Headless Media Player User Guide for NVDA

**Version:** 1.2.3  
**Author:** Mahmoud Abo El-Fotouh <mahmoudaboelfotouh.20@gmail.com>  
**Repository:** [https://github.com/Mahmoud-Abo-El-Fotouh/HeadlessPlayer](https://github.com/Mahmoud-Abo-El-Fotouh/HeadlessPlayer)  
**Telegram:** [https://t.me/mahmoud_EG_1](https://t.me/mahmoud_EG_1)  
**NVDA Compatibility:** NVDA 2022.1 to 2026.1+

---

## Overview
**Headless Media Player** is an ultra-lightweight, high-performance NVDA add-on designed specifically for blind and vision-impaired users to play any audio, video, playlist, or YouTube stream in the background **with zero windows, zero taskbar presence, and zero interruption to your active applications**.

---

## 1. Core Concept: Modal Player Mode
When entering Player Mode (<kbd>NVDA+Ctrl+Shift+P</kbd>):
- All keystrokes are captured exclusively by the media player and will NOT leak into background applications like Microsoft Word or web browsers.
- You can use single-key actions (Space for play/pause, Arrows for seeking, <kbd>u</kbd> for YouTube search, <kbd>Tab</kbd> for next track).
- Press <kbd>Escape</kbd> or <kbd>NVDA+Ctrl+Shift+P</kbd> at any time to exit Player Mode and restore normal keyboard input.

---

## 2. Global NVDA Shortcuts & Multimedia Keys
| Shortcut | Action | Description |
| :--- | :--- | :--- |
| <kbd>NVDA+Ctrl+Shift+P</kbd> | Toggle Player Mode | Enters or exits exclusive player mode layer. |
| <kbd>NVDA+Ctrl+Win+E</kbd> | Play from Windows Explorer | Immediately plays focused or selected file/folder in Explorer or Desktop. |
| <kbd>Media Play/Pause</kbd> | Global Play / Pause | Controls playback from any application or Bluetooth headset. |
| <kbd>Media Next / Previous</kbd> | Global Next / Previous Track | Navigates playlist globally. |
| <kbd>Media Stop</kbd> | Global Stop | Stops playback globally. |

---

## 3. Player Mode Key Commands

### 3.1. Basic Playback & Volume
| Key | Action | Description |
| :--- | :--- | :--- |
| <kbd>Space</kbd> | Play / Pause | Toggles playback. Replays from start if track finished. |
| <kbd>s</kbd> | Stop | Stops playback, saves resume position, and rewinds to 0:00. |
| <kbd>x</kbd> | Close Player | Completely stops engine, terminates background process, and exits mode. |
| <kbd>m</kbd> | Mute / Unmute | Toggles audio mute. |
| <kbd>Up Arrow</kbd> | Volume Up | Increases volume by +5% with speech. |
| <kbd>Down Arrow</kbd> | Volume Down | Decreases volume by -5% with speech. |
| <kbd>b</kbd> | Bass Boost | Increases bass frequencies by +3 dB. |
| <kbd>Shift + b</kbd> | Bass Reduce | Decreases bass frequencies by -3 dB. |
| <kbd>Escape</kbd> | Exit Player Mode | Exits modal layer and restores normal keyboard input. |
| <kbd>Control</kbd> | Silence Speech | Instantly silences NVDA speech without affecting background audio. |

### 3.2. Seeking and Percentage Jumps
| Key | Action | Default Step |
| :--- | :--- | :--- |
| <kbd>Left / Right Arrow</kbd> | Normal Seek | 5 seconds (configurable) |
| <kbd>Alt + Left / Right Arrow</kbd> | Precise / Slow Seek | 1 second (configurable) |
| <kbd>Ctrl + Left / Right Arrow</kbd> | Fast Seek | 30 seconds (configurable) |
| <kbd>Shift + Left / Right Arrow</kbd> | Ultrafast Seek | 5 minutes (300s - configurable) |
| <kbd>1</kbd> to <kbd>9</kbd> | Percent Jumps | Jumps directly to 10% through 90% of file duration. |
| <kbd>0</kbd> | Rewind to 0% | Rewinds to beginning. |
| <kbd>Home</kbd> / <kbd>End</kbd> | Track Start / End | Jumps to beginning (0:00) or end of current track. |

### 3.3. Pitch-Preserved Speed Engine
| Key | Action | Description |
| :--- | :--- | :--- |
| <kbd>Ctrl + Up / Down</kbd> | Fine Speed Adjustment | +/-0.1x speed change with 100% pitch preservation. |
| <kbd>Shift + Up / Down</kbd> | Preset Speeds | Cycles standard presets (1.0x, 1.25x, 1.5x, 1.75x, 2.0x, 2.5x, 3.0x, 4.0x). |

### 3.4. Repeat Modes & A-B Looping
| Key | Action | Description |
| :--- | :--- | :--- |
| <kbd>[</kbd> | Set Point A | Sets start point of A-B loop segment. |
| <kbd>]</kbd> | Set Point B | Sets end point and begins infinite loop playback between A and B. |
| <kbd>c</kbd> | Clear A-B Loop | Clears loop points and returns to normal playback. |
| <kbd>r</kbd> | Toggle Repeat Mode | Cycles: Single Track Repeat -> Playlist Repeat -> Off. |

### 3.5. Playlist Navigation & Chapters
| Key | Action | Description |
| :--- | :--- | :--- |
| <kbd>Page Down</kbd> *(or Tab)* | Next Track | Plays next track in queue. |
| <kbd>Page Up</kbd> *(or Shift+Tab)* | Previous Track | Plays previous track in queue. |
| <kbd>Ctrl + Home</kbd> / <kbd>Ctrl + End</kbd> | First / Last Track | Jumps to first or last track in queue. |
| <kbd>n</kbd> | Toggle Auto-Next | Toggles automatic advancement to next track upon completion. |
| <kbd>z</kbd> | Toggle Shuffle | Toggles random shuffle playback. |
| <kbd>Ctrl + Shift + Left / Right</kbd> | Previous / Next Chapter | Jumps to chapter and speaks chapter title/index. |
| <kbd>a</kbd> | Switch Audio Track | Cycles between multiple audio tracks/languages in video files and YouTube streams while preserving exact playback position. |
| <kbd>o</kbd> | Open File | Opens file selection dialog. |
| <kbd>f</kbd> | Open Folder | Queues entire directory into an ordered playlist. |
| <kbd>e</kbd> | Play Explorer Selection | Immediately plays selected Explorer items. |

### 3.6. Speech Queries
| Key | Action | Description |
| :--- | :--- | :--- |
| <kbd>i</kbd> | Media Info | Speaks title, total duration, and playlist index (e.g. *Track 3 of 15*). |
| <kbd>Ctrl + i</kbd> | Remaining Time | Speaks remaining playback time. |
| <kbd>Shift + i</kbd> | Elapsed Time | Speaks elapsed playback time. |
| <kbd>h</kbd> | Quick Help | Opens interactive key reference dialog. |

---

## 4. YouTube Streaming & SponsorBlock
- **YouTube Search & URL (<kbd>u</kbd>):** Enter search queries or paste direct URLs (videos, playlists, channels, live streams).
- **Trending & Subscriptions Portal (<kbd>p</kbd>):** Browse user playlists, subscriptions, and global trending music.
- **Copy Stream Link (<kbd>v</kbd>):** Copies active stream URL to clipboard.
- **SponsorBlock Integration:** Automatically skips YouTube sponsored segments, self-promotions, interaction reminders, and intros with instant spoken announcements.

---

## 5. Add-on Settings & Customization
Available via **NVDA Menu &larr; Preferences &larr; Settings &larr; Headless Media Player**:
- **Announcement Toggles:** Custom speech feedback for every action.
- **Seek Step Sizes:** Configure jump sizes in seconds.
- **SponsorBlock:** Toggle auto-skipping and speech announcements for YouTube sponsors.
- **In-App Add-on Updater:** Check for updates on GitHub, view changelogs, and install with 1-click.
- **Developer Links:** Follow and connect with developer via Telegram ([@mahmoud_EG_1](https://t.me/mahmoud_EG_1)).
- **Shortcuts Remapper:** Assign multi-key combinations (e.g. `Shift+Tab`) to any action.

---

## 6. Third-Party Components & Licenses

Headless Media Player bundles or utilizes the following open-source third-party software components:

1. **QuickJS (`qjs.exe`):**
   - **Path:** `globalPlugins/HeadlessPlayer/lib/bin/qjs.exe`
   - **Project:** [QuickJS Javascript Engine](https://bellard.org/quickjs/) / [quickjs-ng](https://github.com/quickjs-ng/quickjs) by Fabrice Bellard and Charlie Gordon.
   - **License:** [MIT License](https://opensource.org/licenses/MIT)
   - **Purpose:** A small and fast embedded JavaScript interpreter used by `yt-dlp` to execute YouTube signature deciphering algorithms and challenge solvers headlessly on Windows without requiring Node.js or external system dependencies.

2. **mpv Media Player (`mpv.exe`):**
   - **Path:** `resources/bin/x64/mpv.exe`
   - **Project:** [mpv Media Player](https://mpv.io/) / [mpv GitHub](https://github.com/mpv-player/mpv)
   - **License:** [GNU General Public License v2.0 or later (GPLv2+)](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html) / LGPLv2.1+
   - **Purpose:** The core lightweight, headless media playback engine communicating via Windows Named Pipe JSON IPC (`\\.\pipe\nvda_headless_player`).

3. **yt-dlp (`lib/yt_dlp/`):**
   - **Path:** `globalPlugins/HeadlessPlayer/lib/yt_dlp/`
   - **Project:** [yt-dlp](https://github.com/yt-dlp/yt-dlp)
   - **License:** [The Unlicense (Public Domain)](https://unlicense.org/)
   - **Purpose:** Stream extraction backend and listing metadata parser for YouTube, SoundCloud, Twitch, and web streams.

4. **yt-dlp-ejs (`lib/yt_dlp_ejs/`):**
   - **Path:** `globalPlugins/HeadlessPlayer/lib/yt_dlp_ejs/`
   - **Project:** [yt-dlp External JS Solvers](https://github.com/yt-dlp/yt-dlp)
   - **License:** [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0) / MIT License
   - **Purpose:** JavaScript execution bridge connecting yt-dlp to QuickJS.

---

## License
Headless Media Player is released under the [GNU General Public License v2.0 (GPLv2)](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html).
