# Headless Media Player — NVDA Add-on
A completely headless, privacy-oriented media player add-on for the [NVDA screen reader](https://www.nvaccess.org/) that seamlessly plays local audio/video files, playlists, and online streams (YouTube, Twitch, SoundCloud, web radio) in the background with zero visible UI or taskbar footprint.

---

## Documentation
- **[English User Guide (readme.md)](HeadlessPlayer/doc/en/readme.md)**
- **[دليل المستخدم باللغة العربية (readme.md)](HeadlessPlayer/doc/ar/readme.md)**

---

# Headless Media Player — Quick Overview & User Guide

**Version:** 1.2.2  
**Author:** Mahmoud Abo El Fotouh <mahmoudaboelfotouh.20@gmail.com>  
**Repository:** [https://github.com/Mahmoud-Abo-El-Fotouh/HeadlessPlayer](https://github.com/Mahmoud-Abo-El-Fotouh/HeadlessPlayer)  
**NVDA Compatibility:** NVDA 2022.1 to 2026.1+

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

## 3. Essential Player Mode Shortcuts
- **Playback:** <kbd>Space</kbd> (Play/Pause), <kbd>s</kbd> (Stop & Rewind to 0:00), <kbd>m</kbd> (Mute/Unmute), <kbd>Escape</kbd> (Exit Player Mode), <kbd>Control</kbd> (Silence speech).
- **Volume & Bass:** <kbd>Up/Down Arrow</kbd> (Volume ±5%), <kbd>b</kbd> (Bass +3dB), <kbd>Shift + b</kbd> (Bass -3dB).
- **Seeking:** <kbd>Left/Right Arrow</kbd> (5s seek), <kbd>Alt + Left/Right</kbd> (1s slow seek), <kbd>Ctrl + Left/Right</kbd> (30s fast seek), <kbd>Shift + Left/Right</kbd> (5m ultrafast seek), <kbd>1</kbd> to <kbd>9</kbd> (10% to 90% direct jump), <kbd>0</kbd> (Jump to start).
- **Pitch-Preserved Speed:** <kbd>Ctrl + Up/Down</kbd> (Fine ±0.1x), <kbd>Shift + Up/Down</kbd> (Preset speeds from 1.0x up to 4.0x).
- **A-B Looping & Repeat:** <kbd>[</kbd> (Set Point A), <kbd>]</kbd> (Set Point B & Loop), <kbd>c</kbd> (Clear Loop), <kbd>r</kbd> (Toggle Repeat mode).
- **Navigation:** <kbd>Page Down</kbd> / <kbd>Tab</kbd> (Next track), <kbd>Page Up</kbd> / <kbd>Shift+Tab</kbd> (Previous track), <kbd>n</kbd> (Toggle Auto-Next), <kbd>z</kbd> (Toggle Shuffle), <kbd>o</kbd> (Open file), <kbd>f</kbd> (Open folder), <kbd>e</kbd> (Play Explorer selection).
- **Speech Queries:** <kbd>i</kbd> (Full media info), <kbd>Ctrl + i</kbd> (Remaining time), <kbd>Shift + i</kbd> (Elapsed time), <kbd>h</kbd> (Shortcuts help dialog).

---

## 4. YouTube & Online Streaming
- **Search (<kbd>u</kbd>):** Press <kbd>u</kbd>, type any search query (e.g., *Beethoven Symphony 5* or *Podcast episode*), and press <kbd>Enter</kbd>. Browse results with Up/Down arrows and press <kbd>Enter</kbd> to play. Press <kbd>Tab</kbd> on a playlist to queue all tracks at once.
- **Direct URLs (<kbd>u</kbd>):** Paste any YouTube video/playlist URL, Twitch stream, SoundCloud link, or radio stream.
- **YouTube Portal (<kbd>p</kbd>):** Browse Subscribed Channels, Latest Subscriptions, Watch History, Liked Videos, Watch Later, and Global Top 100 Music Charts.
- **Copy Link (<kbd>v</kbd>):** Copies active stream URL to Windows Clipboard.

---

## 5. YouTube Cookies & Long-Lived Session Solutions

> [!NOTE]
> **Important Note:** 99% of YouTube features (searching by name, playing any video, exploring public playlists/channels, trending music, and live streams) **do NOT require any sign-in or cookies at all!** Cookies are only needed for Private playlists (like Watch Later `WL` or Liked Videos `LL`) and age-restricted videos.

### Why do Chrome cookies stop working quickly?
In modern Google Chrome and Microsoft Edge on Windows (Chrome 120+), Google enforces **App-Bound Encryption** (preventing direct file extraction) and **Session Token Rotation** (invalidating old cookie snapshots whenever you browse or open other Google services).

### Recommended Solutions for Long-Lived Cookies (lasting months/years):

1. **Option 1 (Best & Most Recommended — Mozilla Firefox):**
   - Firefox uses an independent cookie engine without aggressive session rotation.
   - Install the **[cookies.txt extension for Firefox](https://addons.mozilla.org/firefox/addon/cookies-txt/)**.
   - Log in to [YouTube.com](https://www.youtube.com), export your `cookies.txt`, and set it in HeadlessPlayer settings (**NVDA Menu -> Preferences -> Settings -> Headless Media Player**).
   - **Result:** Cookies exported from Firefox typically last for **6 to 12+ months** without interruption as long as you don't log out.

2. **Option 2 (Dedicated Chrome/Brave/Edge Profile):**
   - Create a separate user profile in Chrome/Brave (e.g. named `Player`).
   - Install **[Get cookies.txt LOCALLY for Chrome/Edge/Brave](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)**.
   - Log in to YouTube, export `cookies.txt`, and save it.
   - **Crucial:** Keep this profile dedicated to the player and avoid using it for heavy daily web browsing so Google doesn't rotate its session tokens.

3. **Option 3 (Incognito / Private Window):**
   - Open an Incognito / InPrivate window in your browser.
   - Log in to YouTube and export `cookies.txt` using the extension (make sure the extension is enabled in Incognito).
   - Close the Incognito window.

---

## 6. Supported Formats
- **Audio:** `.mp3`, `.wav`, `.flac`, `.m4a`, `.aac`, `.ogg`, `.opus`, `.wma`, `.alac`, `.aiff`, `.ape`, `.ac3`, `.dts`, `.mka`, `.mid`, `.amr`, `.spx`
- **Video (Headless):** `.mp4`, `.mkv`, `.avi`, `.webm`, `.mov`, `.wmv`, `.flv`, `.ts`, `.m2ts`, `.vob`, `.ogv`, `.3gp`, `.mpg`
- **Playlists:** `.m3u`, `.m3u8`, `.pls`, `.cue`
- **Online:** YouTube (Videos, Playlists, Channels, Shorts, Live), Twitch, SoundCloud, HTTP/HTTPS audio, HLS (`.m3u8`) radio.

---

## License
Released under the [GNU General Public License v2.0 (GPLv2)](LICENSE).
