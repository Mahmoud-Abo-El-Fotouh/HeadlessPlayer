# -*- coding: utf-8 -*-
from __future__ import annotations
"""
HeadlessPlayer Settings Panel for NVDA Preferences -> Settings Dialog.
Provides accessible wxPython configuration controls for speech feedback, seek step sizes, and playback defaults.
"""

import logging
import os
import threading
from typing import Any, Dict, List, Optional, Tuple
import webbrowser

logger = logging.getLogger("HeadlessPlayer.SettingsPanel")

try:
    import addonHandler
    addonHandler.initTranslation()
except Exception:
    pass

try:
    from .. import _  # type: ignore
except (ImportError, ValueError):
    try:
        from . import _  # type: ignore
    except (ImportError, ValueError):
        try:
            _ = _  # type: ignore
        except NameError:
            def _(s: str) -> str:
                return s

try:
    import wx
    import gui
    from gui import guiHelper
    from gui.settingsDialogs import SettingsPanel
except Exception:
    # Fallback placeholders when running in environments without wx/gui
    wx = None
    gui = None
    guiHelper = None

    class SettingsPanel:  # type: ignore
        title = ""
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

try:
    import ui
except Exception:
    ui = None

try:
    from ..utils.config_spec import (
        getConfig,
        saveConfig,
        setConfigValue,
        getConfigValue,
        DEFAULT_KEYMAP,
        getKeymap,
        setKeymap,
    )
except Exception:
    getConfig = None  # type: ignore
    saveConfig = None  # type: ignore
    setConfigValue = None  # type: ignore
    getConfigValue = None  # type: ignore
    DEFAULT_KEYMAP = {}
    getKeymap = None  # type: ignore
    setKeymap = None  # type: ignore

try:
    from ..streaming import engine as stream_engine
except Exception:
    stream_engine = None

try:
    from ..utils import updater as addon_updater
    from ..utils.updater import AddonUpdateDialog
except Exception:
    addon_updater = None
    AddonUpdateDialog = None

try:
    from ..core import diagnostics
except Exception:
    diagnostics = None

try:
    from ..core.controller import get_controller
except Exception:
    def get_controller() -> Any:
        return None

try:
    from ..core.engine import get_engine
except Exception:
    def get_engine() -> Any:
        return None

try:
    from ..history.state_store import get_state_store
except Exception:
    def get_state_store() -> Any:
        return None

from .key_capture import (
    KeyCaptureDialog,
    ACTION_DISPLAY_NAMES,
    ACTION_CATEGORIES,
    ACTION_CATEGORY_MAP,
    get_all_key_suggestions,
    ARABIC_TO_ENGLISH_KEY_MAP,
)
from .shortcuts_dialog import HeadlessPlayerShortcutsDialog
from .updater_dialog import YtdlpUpdateDialog

SPEED_CHOICES: List[Tuple[str, str]] = [
    ("0.5", _("0.5x")),
    ("0.75", _("0.75x")),
    ("1.0", _("1.0x (Normal)")),
    ("1.25", _("1.25x")),
    ("1.5", _("1.5x")),
    ("1.75", _("1.75x")),
    ("2.0", _("2.0x")),
    ("2.5", _("2.5x")),
    ("3.0", _("3.0x")),
]

REPEAT_CHOICES: List[Tuple[str, str]] = [
    ("off", _("Off")),
    ("track", _("Repeat Current Track")),
    ("playlist", _("Repeat Entire Playlist")),
]

STREAM_QUALITY_CHOICES: List[Tuple[str, str]] = [
    ("high", _("High (Opus ~160 kbps - Best fidelity)")),
    ("medium", _("Medium (AAC ~128 kbps - Standard)")),
    ("low", _("Low (~64 kbps - Data saver)")),
]

YTDLP_CHANNEL_CHOICES: List[Tuple[str, str]] = [
    ("stable", _("Stable (PyPI - Recommended)")),
    ("nightly", _("Nightly (Daily YouTube Fixes)")),
    ("master", _("Master (Development)")),
]


class HeadlessPlayerSettingsPanel(SettingsPanel):
    """
    Settings panel category for Headless Media Player in NVDA Settings Dialog.
    """
    title = _("Headless Media Player")

    def makeSettings(self, settingsSizer: Any) -> None:
        if guiHelper is None or wx is None:
            return

        helper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
        cfg = getConfig()

        # -------------------------------------------------------------
        # Category Selector at the top
        # -------------------------------------------------------------
        categoryChoices = [
            _("General & Playback"),
            _("Speech & Announcements"),
            _("Online Streaming & SponsorBlock"),
            _("Downloads & Clip Export"),
            _("Shortcuts, Updates & About"),
        ]
        self.categoryChoice = helper.addLabeledControl(
            _("&Category:"),
            wx.Choice,
            choices=categoryChoices
        )
        self.categoryChoice.SetSelection(0)
        if hasattr(wx, "EVT_CHOICE"):
            self.categoryChoice.Bind(wx.EVT_CHOICE, self.onCategoryChanged)

        # Create category container panels
        self.panelGeneral = wx.Panel(self)
        self.panelSpeech = wx.Panel(self)
        self.panelStreaming = wx.Panel(self)
        self.panelExport = wx.Panel(self)
        self.panelShortcuts = wx.Panel(self)

        self.categoryPanels = [
            self.panelGeneral,
            self.panelSpeech,
            self.panelStreaming,
            self.panelExport,
            self.panelShortcuts,
        ]

        # =============================================================
        # Category 1: General & Playback
        # =============================================================
        sizerGeneral = wx.BoxSizer(wx.VERTICAL)
        generalHelper = guiHelper.BoxSizerHelper(self.panelGeneral, sizer=sizerGeneral)

        # Section 1.1: Playback Defaults & Options
        playbackGroupLabel = _("Playback Defaults & Options")
        playbackBox = wx.StaticBox(self.panelGeneral, label=playbackGroupLabel)
        playbackGroup = guiHelper.BoxSizerHelper(
            self.panelGeneral,
            sizer=wx.StaticBoxSizer(playbackBox, wx.VERTICAL)
        )

        speedLabels = [label for val_opt, label in SPEED_CHOICES]
        self.defaultSpeedChoice = playbackGroup.addLabeledControl(
            _("Default playback s&peed:"),
            wx.Choice,
            choices=speedLabels
        )
        curSpeedStr = str(cfg.get("defaultSpeed", "1.0"))
        try:
            curSpeedVal = float(curSpeedStr)
        except (ValueError, TypeError):
            curSpeedVal = 1.0

        speedIdx = 2  # Default to "1.0"
        for i, (val, label) in enumerate(SPEED_CHOICES):
            if abs(float(val) - curSpeedVal) < 0.01:
                speedIdx = i
                break
        self.defaultSpeedChoice.SetSelection(speedIdx)

        repeatLabels = [label for rep_opt, label in REPEAT_CHOICES]
        self.defaultRepeatChoice = playbackGroup.addLabeledControl(
            _("Default &repeat mode:"),
            wx.Choice,
            choices=repeatLabels
        )
        curRepeat = str(cfg.get("defaultRepeatMode", "off")).lower()
        repeatIdx = 0
        for i, (val, label) in enumerate(REPEAT_CHOICES):
            if val.lower() == curRepeat:
                repeatIdx = i
                break
        self.defaultRepeatChoice.SetSelection(repeatIdx)

        self.autoNextChk = playbackGroup.addItem(
            wx.CheckBox(self.panelGeneral, label=_("Auto-advance to &next track when media finishes"))
        )
        self.autoNextChk.SetValue(bool(cfg.get("defaultAutoNext", True)))

        self.resumePositionChk = playbackGroup.addItem(
            wx.CheckBox(self.panelGeneral, label=_("Remember and &resume playback position for media"))
        )
        self.resumePositionChk.SetValue(bool(cfg.get("resumePosition", True)))

        self.rememberPlaybackStateChk = playbackGroup.addItem(
            wx.CheckBox(self.panelGeneral, label=_("Remember and &restore last playback session on reopening"))
        )
        self.rememberPlaybackStateChk.SetValue(bool(cfg.get("rememberPlaybackState", False)))

        self.autoEnterPlayerModeChk = playbackGroup.addItem(
            wx.CheckBox(self.panelGeneral, label=_("Automatically enter &Player Mode when loading new media"))
        )
        self.autoEnterPlayerModeChk.SetValue(bool(cfg.get("autoEnterPlayerMode", True)))

        generalHelper.addItem(playbackGroup.sizer)

        # Section 1.2: Seek Jump Step Sizes (Seconds)
        seekGroupLabel = _("Seek Jump Step Sizes (Seconds)")
        seekBox = wx.StaticBox(self.panelGeneral, label=seekGroupLabel)
        seekGroup = guiHelper.BoxSizerHelper(
            self.panelGeneral,
            sizer=wx.StaticBoxSizer(seekBox, wx.VERTICAL)
        )

        self.seekStepNormalCtrl = seekGroup.addLabeledControl(
            _("&Normal seek jump (Left/Right arrows):"),
            wx.SpinCtrl,
            min=1,
            max=3600,
            initial=int(cfg.get("seekStepNormal", 5))
        )

        self.seekStepSlowCtrl = seekGroup.addLabeledControl(
            _("&Slow / precise seek jump (Alt + Left/Right):"),
            wx.SpinCtrl,
            min=1,
            max=3600,
            initial=int(cfg.get("seekStepSlow", 1))
        )

        self.seekStepFastCtrl = seekGroup.addLabeledControl(
            _("&Fast seek jump (Ctrl + Left/Right):"),
            wx.SpinCtrl,
            min=1,
            max=3600,
            initial=int(cfg.get("seekStepFast", 30))
        )

        self.seekStepUltrafastCtrl = seekGroup.addLabeledControl(
            _("&Ultrafast seek jump (Shift + Left/Right):"),
            wx.SpinCtrl,
            min=5,
            max=7200,
            initial=int(cfg.get("seekStepUltrafast", 300))
        )

        generalHelper.addItem(seekGroup.sizer)

        # Section 1.3: Recent Media History
        recentsGroupLabel = _("Recent Media History")
        recentsBox = wx.StaticBox(self.panelGeneral, label=recentsGroupLabel)
        recentsGroup = guiHelper.BoxSizerHelper(
            self.panelGeneral,
            sizer=wx.StaticBoxSizer(recentsBox, wx.VERTICAL)
        )

        self.recentsEnabledChk = recentsGroup.addItem(
            wx.CheckBox(self.panelGeneral, label=_("&Enable recent media history tracking"))
        )
        self.recentsEnabledChk.SetValue(bool(cfg.get("recentsEnabled", True)))

        self.recentsMaxEntriesCtrl = recentsGroup.addLabeledControl(
            _("&Maximum recent entries per category:"),
            wx.SpinCtrl,
            min=5,
            max=200,
            initial=int(cfg.get("recentsMaxEntries", 30))
        )

        self.recentsKeepFilesChk = recentsGroup.addItem(
            wx.CheckBox(self.panelGeneral, label=_("Keep recent &local files in history"))
        )
        self.recentsKeepFilesChk.SetValue(bool(cfg.get("recentsKeepFiles", True)))

        self.recentsKeepFoldersChk = recentsGroup.addItem(
            wx.CheckBox(self.panelGeneral, label=_("Keep recent local &folders in history"))
        )
        self.recentsKeepFoldersChk.SetValue(bool(cfg.get("recentsKeepFolders", True)))

        self.recentsKeepPlaylistsChk = recentsGroup.addItem(
            wx.CheckBox(self.panelGeneral, label=_("Keep recent &playlists in history"))
        )
        self.recentsKeepPlaylistsChk.SetValue(bool(cfg.get("recentsKeepPlaylists", True)))

        self.recentsKeepStreamsChk = recentsGroup.addItem(
            wx.CheckBox(self.panelGeneral, label=_("Keep recent online &streams in history"))
        )
        self.recentsKeepStreamsChk.SetValue(bool(cfg.get("recentsKeepStreams", True)))

        generalHelper.addItem(recentsGroup.sizer)
        self.panelGeneral.SetSizer(sizerGeneral)
        helper.addItem(self.panelGeneral)

        # =============================================================
        # Category 2: Speech & Announcements
        # =============================================================
        sizerSpeech = wx.BoxSizer(wx.VERTICAL)
        speechHelper = guiHelper.BoxSizerHelper(self.panelSpeech, sizer=sizerSpeech)

        speechGroupLabel = _("Speech Feedback & Announcements")
        speechBox = wx.StaticBox(self.panelSpeech, label=speechGroupLabel)
        speechGroup = guiHelper.BoxSizerHelper(
            self.panelSpeech,
            sizer=wx.StaticBoxSizer(speechBox, wx.VERTICAL)
        )

        self.announceVolumeChk = speechGroup.addItem(
            wx.CheckBox(self.panelSpeech, label=_("Announce &volume changes"))
        )
        self.announceVolumeChk.SetValue(bool(cfg.get("announceVolume", True)))

        self.announceSeekChk = speechGroup.addItem(
            wx.CheckBox(self.panelSpeech, label=_("Announce &seek position and jump offsets"))
        )
        self.announceSeekChk.SetValue(bool(cfg.get("announceSeek", True)))

        self.announceSpeedChk = speechGroup.addItem(
            wx.CheckBox(self.panelSpeech, label=_("Announce playback s&peed adjustments"))
        )
        self.announceSpeedChk.SetValue(bool(cfg.get("announceSpeed", True)))

        self.announceTrackChk = speechGroup.addItem(
            wx.CheckBox(self.panelSpeech, label=_("Announce &track titles and playlist navigation"))
        )
        self.announceTrackChk.SetValue(bool(cfg.get("announceTrack", True)))

        self.announceLoopChk = speechGroup.addItem(
            wx.CheckBox(self.panelSpeech, label=_("Announce A-B &loop and segment markers"))
        )
        self.announceLoopChk.SetValue(bool(cfg.get("announceLoop", True)))

        self.announceChapterChk = speechGroup.addItem(
            wx.CheckBox(self.panelSpeech, label=_("Announce &chapter markers and names"))
        )
        self.announceChapterChk.SetValue(bool(cfg.get("announceChapter", True)))

        self.announceChapterAutoChk = speechGroup.addItem(
            wx.CheckBox(self.panelSpeech, label=_("Announce chapter transitions &automatically during playback"))
        )
        self.announceChapterAutoChk.SetValue(bool(cfg.get("announceChapterAuto", True)))

        self.announcePlaylistTotalDurationChk = speechGroup.addItem(
            wx.CheckBox(self.panelSpeech, label=_("Announce playlist &total duration when loaded"))
        )
        self.announcePlaylistTotalDurationChk.SetValue(bool(cfg.get("announcePlaylistTotalDuration", False)))

        self.remainingTimeAccountsForSpeedChk = speechGroup.addItem(
            wx.CheckBox(self.panelSpeech, label=_("Calculate remaining &time based on current playback speed"))
        )
        self.remainingTimeAccountsForSpeedChk.SetValue(bool(cfg.get("remainingTimeAccountsForSpeed", True)))

        self.elapsedTimeAccountsForSpeedChk = speechGroup.addItem(
            wx.CheckBox(self.panelSpeech, label=_("Calculate elapsed ti&me based on current playback speed"))
        )
        self.elapsedTimeAccountsForSpeedChk.SetValue(bool(cfg.get("elapsedTimeAccountsForSpeed", True)))

        speechHelper.addItem(speechGroup.sizer)

        self.panelSpeech.SetSizer(sizerSpeech)
        helper.addItem(self.panelSpeech)

        # =============================================================
        # Category 3: Online Streaming & SponsorBlock
        # =============================================================
        sizerStreaming = wx.BoxSizer(wx.VERTICAL)
        streamingHelper = guiHelper.BoxSizerHelper(self.panelStreaming, sizer=sizerStreaming)

        streamGroupLabel = _("YouTube & Online Streaming (yt-dlp)")
        streamBox = wx.StaticBox(self.panelStreaming, label=streamGroupLabel)
        streamGroup = guiHelper.BoxSizerHelper(
            self.panelStreaming,
            sizer=wx.StaticBoxSizer(streamBox, wx.VERTICAL)
        )

        ver_info = stream_engine.get_channel_info() if stream_engine and hasattr(stream_engine, "get_channel_info") else {}
        ver = ver_info.get("installed_version") or (stream_engine.get_bundled_version() if stream_engine and hasattr(stream_engine, "get_bundled_version") else None) or _("not installed")
        chan_name = str(ver_info.get("installed_channel", "stable")).capitalize()
        self.ytdlpVersionText = streamGroup.addItem(
            wx.StaticText(self.panelStreaming, label=_("Streaming engine (yt-dlp) version: %s (%s)") % (ver, chan_name))
        )

        channelLabels = [label for _val, label in YTDLP_CHANNEL_CHOICES]
        self.ytdlpChannelChoice = streamGroup.addLabeledControl(
            _("yt-dlp update &channel:"),
            wx.Choice,
            choices=channelLabels
        )
        curChan = str(cfg.get("ytdlpUpdateChannel", "stable")).lower()
        chanIdx = 0
        for i, (val, label) in enumerate(YTDLP_CHANNEL_CHOICES):
            if val.lower() == curChan:
                chanIdx = i
                break
        self.ytdlpChannelChoice.SetSelection(chanIdx)

        self.checkUpdatesBtn = streamGroup.addItem(
            wx.Button(self.panelStreaming, label=_("Check for &Updates of the streaming engine now..."))
        )
        self.rollbackYtdlpBtn = streamGroup.addItem(
            wx.Button(self.panelStreaming, label=_("&Revert streaming engine to previous version..."))
        )
        self.resetBundledYtdlpBtn = streamGroup.addItem(
            wx.Button(self.panelStreaming, label=_("Restore &original bundled streaming engine..."))
        )
        if hasattr(wx, "EVT_BUTTON"):
            self.checkUpdatesBtn.Bind(wx.EVT_BUTTON, self.onCheckYtdlpUpdates)
            self.rollbackYtdlpBtn.Bind(wx.EVT_BUTTON, self.onRollbackYtdlp)
            self.resetBundledYtdlpBtn.Bind(wx.EVT_BUTTON, self.onResetBundledYtdlp)

        self._refreshYtdlpButtons()

        qualityLabels = [label for _val, label in STREAM_QUALITY_CHOICES]
        self.streamAudioQualityChoice = streamGroup.addLabeledControl(
            _("Streaming audio &quality:"),
            wx.Choice,
            choices=qualityLabels
        )
        curQuality = str(cfg.get("streamAudioQuality", "high")).lower()
        qualityIdx = 0
        for i, (val, label) in enumerate(STREAM_QUALITY_CHOICES):
            if val.lower() == curQuality:
                qualityIdx = i
                break
        self.streamAudioQualityChoice.SetSelection(qualityIdx)

        self.searchResultsCountCtrl = streamGroup.addLabeledControl(
            _("Number of YouTube search &results:"),
            wx.SpinCtrl,
            min=5,
            max=50,
            initial=int(cfg.get("searchResultsCount", 20))
        )

        self.maxStreamItemsCtrl = streamGroup.addLabeledControl(
            _("&Maximum items loaded from an online playlist or channel:"),
            wx.SpinCtrl,
            min=10,
            max=1000,
            initial=int(cfg.get("maxStreamPlaylistItems", 50))
        )

        self.cookiesBrowserChoices: List[Tuple[str, str]] = [
            ("none", _("None (anonymous, default)")),
            ("firefox", _("Mozilla Firefox (compatible on Windows)")),
        ]
        self.cookiesBrowserChoice = streamGroup.addLabeledControl(
            _("Use sign-in coo&kies from browser (Firefox only on Windows):"),
            wx.Choice,
            choices=[label for val, label in self.cookiesBrowserChoices]
        )
        curBrowser = str(cfg.get("ytdlpCookiesBrowser", "none")).lower()
        if curBrowser not in ("none", "firefox"):
            curBrowser = "none"
        browserIdx = 0
        for i, (val, label) in enumerate(self.cookiesBrowserChoices):
            if val == curBrowser:
                browserIdx = i
                break
        self.cookiesBrowserChoice.SetSelection(browserIdx)

        self.cookiesFileCtrl = streamGroup.addLabeledControl(
            _("Manual sign-in cookies &file (cookies.txt in Netscape format):"),
            wx.TextCtrl
        )
        self.cookiesFileCtrl.SetValue(str(cfg.get("ytdlpCookiesFile", "") or ""))

        cookiesBtnSizer = wx.BoxSizer(wx.HORIZONTAL)
        self.browseCookiesBtn = wx.Button(self.panelStreaming, label=_("&Browse for cookies file..."))
        cookiesBtnSizer.Add(self.browseCookiesBtn, 0, wx.RIGHT, 5)
        if hasattr(wx, "EVT_BUTTON"):
            self.browseCookiesBtn.Bind(wx.EVT_BUTTON, self.onBrowseCookiesFile)

        self.testCookiesBtn = wx.Button(self.panelStreaming, label=_("&Test cookies file validity..."))
        cookiesBtnSizer.Add(self.testCookiesBtn, 0)
        if hasattr(wx, "EVT_BUTTON"):
            self.testCookiesBtn.Bind(wx.EVT_BUTTON, self.onTestCookiesFile)

        streamGroup.addItem(cookiesBtnSizer)

        cookiesHint = wx.StaticText(
            self.panelStreaming,
            label=_(
                "Tip: On Windows, Chrome and Edge block automated cookie decryption. Use Firefox or "
                "export cookies.txt using a browser extension from a Private/Incognito window while signed in "
                "to YouTube. The manual cookies file takes priority over the browser choice above."
            )
        )
        cookiesHint.Wrap(560)
        streamGroup.addItem(cookiesHint)

        streamingHelper.addItem(streamGroup.sizer)

        # Section 3.2: SponsorBlock
        if hasattr(wx, "CheckBox") and hasattr(wx, "StaticBox"):
            sbGroupLabel = _("SponsorBlock (Auto-Skip YouTube Ads & Sponsors)")
            sbBox = wx.StaticBox(self.panelStreaming, label=sbGroupLabel)
            sbGroup = guiHelper.BoxSizerHelper(
                self.panelStreaming,
                sizer=wx.StaticBoxSizer(sbBox, wx.VERTICAL)
            )

            self.sponsorBlockEnabledChk = sbGroup.addItem(
                wx.CheckBox(
                    self.panelStreaming,
                    label=_("Enable &SponsorBlock (Auto-skip YouTube sponsors, promos & intros)")
                )
            )
            self.sponsorBlockEnabledChk.SetValue(bool(cfg.get("sponsorBlockEnabled", True)))

            self.announceSponsorSkipChk = sbGroup.addItem(
                wx.CheckBox(
                    self.panelStreaming,
                    label=_("&Announce when a sponsor or promo segment is skipped")
                )
            )
            self.announceSponsorSkipChk.SetValue(bool(cfg.get("announceSponsorSkip", True)))

            # Customizable categories to skip
            active_cats = set(
                c.strip().lower()
                for c in str(cfg.get("sponsorBlockCategories", "sponsor,selfpromo,interaction,intro,outro")).split(",")
                if c.strip()
            )

            self.sbCatSponsorChk = sbGroup.addItem(
                wx.CheckBox(self.panelStreaming, label=_("Skip &sponsors and paid advertisements"))
            )
            self.sbCatSponsorChk.SetValue("sponsor" in active_cats)

            self.sbCatIntroChk = sbGroup.addItem(
                wx.CheckBox(self.panelStreaming, label=_("Skip &intro animations and intermission breaks"))
            )
            self.sbCatIntroChk.SetValue("intro" in active_cats)

            self.sbCatOutroChk = sbGroup.addItem(
                wx.CheckBox(self.panelStreaming, label=_("Skip &outro credits and end cards"))
            )
            self.sbCatOutroChk.SetValue("outro" in active_cats)

            self.sbCatSelfpromoChk = sbGroup.addItem(
                wx.CheckBox(self.panelStreaming, label=_("Skip self-&promotions and unpaid merchandise"))
            )
            self.sbCatSelfpromoChk.SetValue("selfpromo" in active_cats)

            self.sbCatInteractionChk = sbGroup.addItem(
                wx.CheckBox(self.panelStreaming, label=_("Skip subscribe and like inter&action reminders"))
            )
            self.sbCatInteractionChk.SetValue("interaction" in active_cats)

            self.sbCatMusicOfftopicChk = sbGroup.addItem(
                wx.CheckBox(self.panelStreaming, label=_("Skip non-&music sections in music videos"))
            )
            self.sbCatMusicOfftopicChk.SetValue("music_offtopic" in active_cats)

            streamingHelper.addItem(sbGroup.sizer)

        self.panelStreaming.SetSizer(sizerStreaming)
        helper.addItem(self.panelStreaming)

        # =============================================================
        # Category 4: Shortcuts, Updates & About
        # =============================================================
        sizerShortcuts = wx.BoxSizer(wx.VERTICAL)
        shortcutsHelper = guiHelper.BoxSizerHelper(self.panelShortcuts, sizer=sizerShortcuts)

        # Section 4.1: Player Mode Keyboard Shortcuts
        if hasattr(wx, "Button") and hasattr(wx, "StaticBox"):
            shortcutsGroupLabel = _("Player Mode Keyboard Shortcuts")
            shortcutsBox = wx.StaticBox(self.panelShortcuts, label=shortcutsGroupLabel)
            shortcutsGroup = guiHelper.BoxSizerHelper(
                self.panelShortcuts,
                sizer=wx.StaticBoxSizer(shortcutsBox, wx.VERTICAL)
            )

            self.customizeShortcutsBtn = shortcutsGroup.addItem(
                wx.Button(self.panelShortcuts, label=_("Customize Player Mode &Shortcuts..."))
            )
            if hasattr(wx, "EVT_BUTTON"):
                self.customizeShortcutsBtn.Bind(wx.EVT_BUTTON, self.onCustomizeShortcuts)

            shortcutsHelper.addItem(shortcutsGroup.sizer)

        # Section 4.2: Add-on Self-Updater
        if hasattr(wx, "Button") and hasattr(wx, "StaticBox"):
            addonUpdatesGroupLabel = _("Headless Media Player Add-on Updates")
            addonUpdatesBox = wx.StaticBox(self.panelShortcuts, label=addonUpdatesGroupLabel)
            addonUpdatesGroup = guiHelper.BoxSizerHelper(
                self.panelShortcuts,
                sizer=wx.StaticBoxSizer(addonUpdatesBox, wx.VERTICAL)
            )

            cur_ver_str = (addon_updater.get_current_addon_version() if addon_updater and hasattr(addon_updater, "get_current_addon_version") else "") or "1.0.0"
            self.addonVersionText = addonUpdatesGroup.addItem(
                wx.StaticText(self.panelShortcuts, label=_("Installed add-on version: %s") % cur_ver_str)
            )

            self.autoCheckAddonUpdateChk = addonUpdatesGroup.addItem(
                wx.CheckBox(
                    self.panelShortcuts,
                    label=_("Automatically &check for add-on updates on NVDA startup")
                )
            )
            self.autoCheckAddonUpdateChk.SetValue(bool(cfg.get("autoCheckAddonUpdateOnStartup", True)))

            self.checkAddonUpdatesBtn = addonUpdatesGroup.addItem(
                wx.Button(self.panelShortcuts, label=_("Check for &Add-on Updates on GitHub..."))
            )
            if hasattr(wx, "EVT_BUTTON"):
                self.checkAddonUpdatesBtn.Bind(wx.EVT_BUTTON, self.onCheckAddonUpdates)

            shortcutsHelper.addItem(addonUpdatesGroup.sizer)

        # Section 4.3: System Diagnostics & Health Check
        if hasattr(wx, "Button") and hasattr(wx, "StaticBox"):
            diagGroupLabel = _("System Diagnostics & Health Check")
            diagBox = wx.StaticBox(self.panelShortcuts, label=diagGroupLabel)
            diagGroup = guiHelper.BoxSizerHelper(
                self.panelShortcuts,
                sizer=wx.StaticBoxSizer(diagBox, wx.VERTICAL)
            )

            diagHint = wx.StaticText(
                self.panelShortcuts,
                label=_(
                    "Inspects player components (mpv, yt-dlp, database, translation catalogs) "
                    "and copies a diagnostic health report directly to clipboard to share with the developer."
                )
            )
            diagHint.Wrap(560)
            diagGroup.addItem(diagHint)

            self.copyDiagnosticsBtn = diagGroup.addItem(
                wx.Button(self.panelShortcuts, label=_("&Copy System Health & Diagnostics Report to Clipboard..."))
            )
            if hasattr(wx, "EVT_BUTTON"):
                self.copyDiagnosticsBtn.Bind(wx.EVT_BUTTON, self.onCopyDiagnosticsReport)

            shortcutsHelper.addItem(diagGroup.sizer)

        # Section 4.4: About & Developer
        if hasattr(wx, "Button") and hasattr(wx, "StaticBox"):
            aboutGroupLabel = _("About & Developer")
            aboutBox = wx.StaticBox(self.panelShortcuts, label=aboutGroupLabel)
            aboutGroup = guiHelper.BoxSizerHelper(
                self.panelShortcuts,
                sizer=wx.StaticBoxSizer(aboutBox, wx.VERTICAL)
            )

            self.followDevBtn = aboutGroup.addItem(
                wx.Button(self.panelShortcuts, label=_("&Follow Developer on Telegram (Mahmoud Abo El Fotouh)..."))
            )
            if hasattr(wx, "EVT_BUTTON"):
                self.followDevBtn.Bind(wx.EVT_BUTTON, self.onFollowDeveloper)

            shortcutsHelper.addItem(aboutGroup.sizer)

        self.panelShortcuts.SetSizer(sizerShortcuts)
        helper.addItem(self.panelShortcuts)

        # =============================================================
        # Category: Downloads & Clip Export
        # =============================================================
        sizerExport = wx.BoxSizer(wx.VERTICAL)
        exportHelper = guiHelper.BoxSizerHelper(self.panelExport, sizer=sizerExport)
        exBox = wx.StaticBox(self.panelExport, label=_("Clip Export & Downloads (D / Shift+D)"))
        exGroup = guiHelper.BoxSizerHelper(self.panelExport, sizer=wx.StaticBoxSizer(exBox, wx.VERTICAL))
        self.exportFolderCtrl = exGroup.addLabeledControl(
            _("Default download &folder (empty = Downloads\\HeadlessPlayer):"), wx.TextCtrl)
        self.exportFolderCtrl.SetValue(str(cfg.get("exportFolder", "") or ""))
        self.browseExportFolderBtn = exGroup.addItem(wx.Button(self.panelExport, label=_("&Browse for folder...")))
        if hasattr(wx, "EVT_BUTTON"):
            self.browseExportFolderBtn.Bind(wx.EVT_BUTTON, self.onBrowseExportFolder)
        self.exportFormatChoices = [("mp3", _("Audio MP3")), ("m4a", _("Audio M4A / AAC")), ("mp4", _("Video MP4"))]
        self.exportFormatChoice = exGroup.addLabeledControl(
            _("Default export f&ormat:"), wx.Choice, choices=[l for _v, l in self.exportFormatChoices])
        curFmt = str(cfg.get("exportFormat", "mp3")).lower()
        self.exportFormatChoice.SetSelection(next((i for i, (v, _l) in enumerate(self.exportFormatChoices) if v == curFmt), 0))
        self.exportQualityChoices = [("high", _("Highest quality")), ("story", _("Story optimized (small file)"))]
        self.exportQualityChoice = exGroup.addLabeledControl(
            _("Default &quality:"), wx.Choice, choices=[l for _v, l in self.exportQualityChoices])
        curQ = str(cfg.get("exportQuality", "high")).lower()
        self.exportQualityChoice.SetSelection(next((i for i, (v, _l) in enumerate(self.exportQualityChoices) if v == curQ), 0))
        self.exportAutoCopyChk = exGroup.addItem(
            wx.CheckBox(self.panelExport, label=_("Automatically &copy the saved file path to the clipboard")))
        self.exportAutoCopyChk.SetValue(bool(cfg.get("exportAutoCopy", True)))
        exHint = wx.StaticText(self.panelExport, label=_(
            "D: export the A-B selection (or the whole item) as MP3, M4A or MP4 video; if only point A is set, "
            "the current position becomes point B. Shift+D: quick export with the settings remembered from the last dialog. "
            "Shift+V: copy the direct audio link of the playing YouTube item. Conversion is done by the bundled mpv encoder."
        ))
        exHint.Wrap(560)
        exGroup.addItem(exHint)
        exportHelper.addItem(exGroup.sizer)
        self.panelExport.SetSizer(sizerExport)
        helper.addItem(self.panelExport)

        # Initially show only the first category (General & Playback)
        self.panelGeneral.Show()
        self.panelSpeech.Hide()
        self.panelStreaming.Hide()
        self.panelExport.Hide()
        self.panelShortcuts.Hide()

    def onCategoryChanged(self, evt: Any) -> None:
        """Switches active settings category panel when user changes the dropdown."""
        if not hasattr(self, "categoryChoice") or not hasattr(self, "categoryPanels"):
            return
        sel = self.categoryChoice.GetSelection()
        for idx, p in enumerate(self.categoryPanels):
            if idx == sel:
                p.Show()
            else:
                p.Hide()
        self.Layout()
        if evt:
            try:
                evt.Skip()
            except Exception:
                pass

    def onFollowDeveloper(self, evt: Any) -> None:
        """Opens developer's Telegram link in the default browser."""
        try:
            webbrowser.open("https://t.me/mahmoud_EG_1")
        except Exception as e:
            logger.error("Failed to open developer Telegram link: %s", e)

    def _refreshYtdlpButtons(self) -> None:
        """Refreshes the enabled status and labels of yt-dlp rollback and reset buttons."""
        if not wx:
            return
        try:
            ver_info = stream_engine.get_channel_info() if stream_engine and hasattr(stream_engine, "get_channel_info") else {}
            can_roll = bool(ver_info.get("can_rollback", False))
            can_reset = bool(ver_info.get("can_reset_bundled", False))
            prev_ver = ver_info.get("previous_version", "")

            if hasattr(self, "rollbackYtdlpBtn") and self.rollbackYtdlpBtn and getattr(self.rollbackYtdlpBtn, "thisown", True):
                if can_roll:
                    self.rollbackYtdlpBtn.Enable()
                    if prev_ver:
                        self.rollbackYtdlpBtn.SetLabel(_("&Revert to previous version (%s)...") % prev_ver)
                    else:
                        self.rollbackYtdlpBtn.SetLabel(_("&Revert streaming engine to previous version..."))
                else:
                    self.rollbackYtdlpBtn.Disable()
                    self.rollbackYtdlpBtn.SetLabel(_("&Revert streaming engine to previous version (none available)"))

            if hasattr(self, "resetBundledYtdlpBtn") and self.resetBundledYtdlpBtn and getattr(self.resetBundledYtdlpBtn, "thisown", True):
                if can_reset:
                    self.resetBundledYtdlpBtn.Enable()
                else:
                    self.resetBundledYtdlpBtn.Disable()
        except Exception as e:
            logger.debug("Error refreshing ytdlp buttons: %s", e)

    def onCheckYtdlpUpdates(self, evt: Any) -> None:
        """
        Checks the chosen channel for a newer yt-dlp streaming engine and installs it into
        the add-on using an accessible modal progress dialog with live progress bar and spoken announcements.
        """
        if not wx:
            return

        selected_channel = "stable"
        if hasattr(self, "ytdlpChannelChoice") and self.ytdlpChannelChoice and getattr(self.ytdlpChannelChoice, "thisown", True):
            sel = self.ytdlpChannelChoice.GetSelection()
            if 0 <= sel < len(YTDLP_CHANNEL_CHOICES):
                selected_channel = YTDLP_CHANNEL_CHOICES[sel][0]

        ver_info = stream_engine.get_channel_info() if stream_engine and hasattr(stream_engine, "get_channel_info") else {}
        cur_ver = ver_info.get("installed_version") or (stream_engine.get_bundled_version() if stream_engine and hasattr(stream_engine, "get_bundled_version") else "")

        dlg = YtdlpUpdateDialog(self, channel=selected_channel, current_version=cur_ver)
        dlg.ShowModal()

        if getattr(dlg, "is_success", False) and getattr(dlg, "updated_version", None):
            if hasattr(self, "ytdlpVersionText") and self.ytdlpVersionText and getattr(self.ytdlpVersionText, "thisown", True):
                self.ytdlpVersionText.SetLabel(
                    _("Streaming engine (yt-dlp) version: %s (%s - restart NVDA to activate)") % (dlg.updated_version, selected_channel.capitalize())
                )
        self._refreshYtdlpButtons()
        try:
            dlg.Destroy()
        except Exception:
            pass

    def onRollbackYtdlp(self, evt: Any) -> None:
        """Rolls back the streaming engine to the previous version."""
        if not wx or not stream_engine:
            return
        if gui and hasattr(gui, "messageBox"):
            res = gui.messageBox(
                _("Are you sure you want to revert the streaming engine to the previous version?"),
                _("Confirm Revert"),
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION
            )
            if res != wx.YES:
                return

        success, msg = stream_engine.rollback_ytdlp()
        if success:
            ver = msg.split(":", 1)[1] if ":" in msg else ""
            text = _(
                "The streaming engine was successfully restored to version %s.\n"
                "Please restart NVDA to activate the changes."
            ) % ver
            caption = _("Revert Successful")
            icon = wx.ICON_INFORMATION
            if hasattr(self, "ytdlpVersionText"):
                self.ytdlpVersionText.SetLabel(
                    _("Streaming engine (yt-dlp) version: %s (restart NVDA to activate)") % ver
                )
        else:
            text = _("Failed to revert the streaming engine.\nDetails: %s") % msg
            caption = _("Revert Failed")
            icon = wx.ICON_ERROR

        self._refreshYtdlpButtons()
        if gui and hasattr(gui, "messageBox"):
            gui.messageBox(text, caption, wx.OK | icon)
        elif ui and hasattr(ui, "message"):
            try:
                ui.message(text)
            except Exception:
                pass

    def onResetBundledYtdlp(self, evt: Any) -> None:
        """Restores the original factory bundled streaming engine."""
        if not wx or not stream_engine:
            return
        if gui and hasattr(gui, "messageBox"):
            res = gui.messageBox(
                _("Are you sure you want to restore the original factory bundled streaming engine?\n"
                  "This will reset any downloaded updates."),
                _("Confirm Factory Reset"),
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING
            )
            if res != wx.YES:
                return

        success, msg = stream_engine.reset_to_bundled_ytdlp()
        if success:
            ver = msg.split(":", 1)[1] if ":" in msg else ""
            text = _(
                "The streaming engine was reset to the original bundled version %s.\n"
                "Please restart NVDA to activate the changes."
            ) % ver
            caption = _("Reset Successful")
            icon = wx.ICON_INFORMATION
            if hasattr(self, "ytdlpVersionText"):
                self.ytdlpVersionText.SetLabel(
                    _("Streaming engine (yt-dlp) version: %s (restart NVDA to activate)") % ver
                )
        else:
            text = _("Failed to restore bundled streaming engine.\nDetails: %s") % msg
            caption = _("Reset Failed")
            icon = wx.ICON_ERROR

        self._refreshYtdlpButtons()
        if gui and hasattr(gui, "messageBox"):
            gui.messageBox(text, caption, wx.OK | icon)
        elif ui and hasattr(ui, "message"):
            try:
                ui.message(text)
            except Exception:
                pass

    def onCustomizeShortcuts(self, evt: Any) -> None:
        """Opens the accessible Player Mode shortcuts customization dialog."""
        if not wx:
            return
        if gui and hasattr(gui, "mainFrame") and hasattr(gui.mainFrame, "prePopup"):
            try:
                gui.mainFrame.prePopup()
            except Exception:
                pass
        dlg = HeadlessPlayerShortcutsDialog(self)
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()
            if gui and hasattr(gui, "mainFrame") and hasattr(gui.mainFrame, "postPopup"):
                try:
                    gui.mainFrame.postPopup()
                except Exception:
                    pass

    def onCheckAddonUpdates(self, evt: Any) -> None:
        """
        Checks GitHub Releases for a newer version of the HeadlessPlayer add-on.
        If an update is found, presents the AddonUpdateDialog with changelog and live download progress.
        """
        if not wx:
            return

        self.checkAddonUpdatesBtn.Disable()
        self.checkAddonUpdatesBtn.SetLabel(_("Checking for add-on updates..."))
        if ui and hasattr(ui, "message"):
            try:
                ui.message(_("Checking for add-on updates, please wait..."))
            except Exception:
                pass

        def worker() -> None:
            try:
                if addon_updater and hasattr(addon_updater, "check_for_addon_update"):
                    available, info, status = addon_updater.check_for_addon_update()
                else:
                    available, info, status = False, None, "addon_updater unavailable"
            except Exception as e:
                available, info, status = False, None, f"error:{e}"
            wx.CallAfter(self._onAddonUpdateCheckFinished, available, info, status)

        threading.Thread(target=worker, daemon=True, name="HeadlessPlayer-AddonUpdateCheck").start()

    def _onAddonUpdateCheckFinished(self, available: bool, info: Optional[dict], status: str) -> None:
        if not wx:
            return
        if not self or not hasattr(self, "checkAddonUpdatesBtn") or not self.checkAddonUpdatesBtn:
            return
        try:
            if not getattr(self.checkAddonUpdatesBtn, "thisown", True):
                return
            self.checkAddonUpdatesBtn.Enable()
            self.checkAddonUpdatesBtn.SetLabel(_("Check for &Add-on Updates on GitHub..."))
        except Exception:
            return

        if available and info and AddonUpdateDialog:
            if gui and hasattr(gui, "mainFrame") and hasattr(gui.mainFrame, "prePopup"):
                try:
                    gui.mainFrame.prePopup()
                except Exception:
                    pass
            dlg = AddonUpdateDialog(self, info)
            try:
                dlg.ShowModal()
            finally:
                dlg.Destroy()
                if gui and hasattr(gui, "mainFrame") and hasattr(gui.mainFrame, "postPopup"):
                    try:
                        gui.mainFrame.postPopup()
                    except Exception:
                        pass
        elif status == "up_to_date" and info:
            cur_ver = info.get("current_version", "")
            text = _("You are already using the latest version of Headless Media Player (version %s).") % cur_ver
            caption = _("No Update Needed")
            if gui and hasattr(gui, "messageBox"):
                gui.messageBox(text, caption, wx.OK | wx.ICON_INFORMATION)
            elif ui and hasattr(ui, "message"):
                try:
                    ui.message(text)
                except Exception:
                    pass
        elif status == "error:rate_limit_exceeded":
            text = _(
                "GitHub API rate limit exceeded (maximum 60 requests per hour).\n"
                "Please wait a few minutes and try again."
            )
            caption = _("Rate Limit Exceeded")
            if gui and hasattr(gui, "messageBox"):
                gui.messageBox(text, caption, wx.OK | wx.ICON_WARNING)
            elif ui and hasattr(ui, "message"):
                try:
                    ui.message(text)
                except Exception:
                    pass
        else:
            text = _(
                "Could not check for add-on updates.\n"
                "Please check your internet connection and try again.\n\nDetails: %s"
            ) % status
            caption = _("Update Check Failed")
            if gui and hasattr(gui, "messageBox"):
                gui.messageBox(text, caption, wx.OK | wx.ICON_ERROR)
            elif ui and hasattr(ui, "message"):
                try:
                    ui.message(text)
                except Exception:
                    pass

    def onCopyDiagnosticsReport(self, evt: Any) -> None:
        """Runs full system diagnostics asynchronously and copies the report to Windows clipboard."""
        if hasattr(self, "copyDiagnosticsBtn") and self.copyDiagnosticsBtn:
            try:
                self.copyDiagnosticsBtn.Disable()
                self.copyDiagnosticsBtn.SetLabel(_("Generating diagnostics report..."))
            except Exception:
                pass

        if ui and hasattr(ui, "message"):
            try:
                ui.message(_("Generating system diagnostics report, please wait..."))
            except Exception:
                pass

        def worker() -> None:
            success = False
            try:
                if diagnostics and hasattr(diagnostics, "copy_diagnostic_report_to_clipboard"):
                    success = diagnostics.copy_diagnostic_report_to_clipboard()
            except Exception as e:
                logger.error("Failed to copy diagnostic report: %s", e)
                success = False
            if wx and hasattr(wx, "CallAfter"):
                try:
                    wx.CallAfter(self._onCopyDiagnosticsFinished, success)
                except Exception:
                    self._onCopyDiagnosticsFinished(success)
            else:
                self._onCopyDiagnosticsFinished(success)

        threading.Thread(target=worker, daemon=True, name="HeadlessPlayer-DiagnosticsWorker").start()

    def _onCopyDiagnosticsFinished(self, success: bool) -> None:
        if not self:
            return
        if hasattr(self, "copyDiagnosticsBtn") and self.copyDiagnosticsBtn:
            try:
                if getattr(self.copyDiagnosticsBtn, "thisown", True):
                    self.copyDiagnosticsBtn.Enable()
                    self.copyDiagnosticsBtn.SetLabel(_("&Copy System Health & Diagnostics Report to Clipboard..."))
            except Exception:
                pass

        if success:
            msg = _("System diagnostics report successfully copied to clipboard. You can now paste and share it with the developer.")
            if ui and hasattr(ui, "message"):
                try:
                    ui.message(msg)
                except Exception:
                    pass
            if gui and hasattr(gui, "messageBox"):
                flag = (wx.OK | wx.ICON_INFORMATION) if wx else 0
                gui.messageBox(
                    msg,
                    _("System Diagnostics"),
                    flag
                )
        else:
            err_msg = _("Could not generate or copy the diagnostics report to clipboard.")
            if gui and hasattr(gui, "messageBox"):
                flag = (wx.OK | wx.ICON_ERROR) if wx else 0
                gui.messageBox(
                    err_msg,
                    _("Diagnostics Error"),
                    flag
                )

    def onBrowseCookiesFile(self, evt: Any) -> None:
        if not wx:
            return
        current = self.cookiesFileCtrl.GetValue().strip().strip('"')
        start_dir = os.path.dirname(current) if current and os.path.isfile(current) else os.path.join(os.path.expanduser("~"), "Downloads")
        dlg = wx.FileDialog(
            self,
            message=_("Select Netscape format cookies.txt file"),
            defaultDir=start_dir,
            wildcard=_("Cookie files (*.txt)|*.txt|All files (*.*)|*.*"),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        )
        with dlg:
            if dlg.ShowModal() == wx.ID_OK:
                chosen_path = dlg.GetPath()
                self.cookiesFileCtrl.SetValue(chosen_path)
                self.onTestCookiesFile(None)

    def onTestCookiesFile(self, evt: Any) -> None:
        path = self.cookiesFileCtrl.GetValue().strip().strip('"')
        if stream_engine and hasattr(stream_engine, "check_youtube_cookies_validity"):
            valid, reason = stream_engine.check_youtube_cookies_validity(path)
        else:
            valid, reason = False, "stream_engine_unavailable"

        if valid:
            msg = _("The selected cookies file is valid and contains active YouTube authentication tokens.")
            caption = _("Cookies File Valid")
            icon = wx.ICON_INFORMATION
        elif reason == "expired":
            msg = _("The cookies file contains expired session tokens (LOGIN_INFO). Please export fresh cookies from an Incognito/Private window.")
            caption = _("Cookies Expired")
            icon = wx.ICON_WARNING
        elif reason == "missing_auth_tokens":
            msg = _("The cookies file does not contain necessary YouTube authentication tokens (LOGIN_INFO/SAPISID). Make sure you were logged in to YouTube when exporting.")
            caption = _("Incomplete Cookies")
            icon = wx.ICON_WARNING
        elif reason == "empty":
            msg = _("The cookies file is empty or does not contain any YouTube or Google domain cookies.")
            caption = _("Invalid Cookies")
            icon = wx.ICON_ERROR
        elif reason == "file_not_found":
            msg = _("The specified cookies file path does not exist.")
            caption = _("File Not Found")
            icon = wx.ICON_ERROR
        else:
            msg = _("No cookies file specified. Please browse for a valid cookies.txt file.")
            caption = _("No File Selected")
            icon = wx.ICON_WARNING

        if gui and hasattr(gui, "messageBox"):
            gui.messageBox(msg, caption, wx.OK | icon)
        elif ui and hasattr(ui, "message"):
            try:
                ui.message(f"{caption}: {msg}")
            except Exception:
                pass

    def onBrowseExportFolder(self, evt: Any) -> None:
        if not wx:
            return
        current = self.exportFolderCtrl.GetValue().strip()
        start_dir = current if current and os.path.isdir(current) else os.path.join(os.path.expanduser("~"), "Downloads")
        dlg = wx.DirDialog(self, message=_("Select download folder"), defaultPath=start_dir, style=wx.DD_DEFAULT_STYLE)
        with dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.exportFolderCtrl.SetValue(dlg.GetPath())

    def onSave(self) -> None:
        """
        Invoked when the user clicks OK or Apply in NVDA Settings.
        Commits all UI control values to the configuration store and informs the running engine.
        """
        if wx is None:
            return

        # Playback & Announcement settings
        for attr, key in (
            ("announceVolumeChk", "announceVolume"),
            ("announceSeekChk", "announceSeek"),
            ("announceSpeedChk", "announceSpeed"),
            ("announceTrackChk", "announceTrack"),
            ("announceLoopChk", "announceLoop"),
            ("announceChapterChk", "announceChapter"),
            ("announceChapterAutoChk", "announceChapterAuto"),
            ("announcePlaylistTotalDurationChk", "announcePlaylistTotalDuration"),
            ("remainingTimeAccountsForSpeedChk", "remainingTimeAccountsForSpeed"),
            ("elapsedTimeAccountsForSpeedChk", "elapsedTimeAccountsForSpeed"),
        ):
            if hasattr(self, attr):
                try:
                    setConfigValue(key, bool(getattr(self, attr).GetValue()))
                except Exception:
                    pass

        # Seek steps
        for attr, key in (
            ("seekStepNormalCtrl", "seekStepNormal"),
            ("seekStepSlowCtrl", "seekStepSlow"),
            ("seekStepFastCtrl", "seekStepFast"),
            ("seekStepUltrafastCtrl", "seekStepUltrafast"),
        ):
            if hasattr(self, attr):
                try:
                    setConfigValue(key, int(getattr(self, attr).GetValue()))
                except Exception:
                    pass

        # Default Speed
        if hasattr(self, "defaultSpeedChoice"):
            try:
                sel = self.defaultSpeedChoice.GetSelection()
                if 0 <= sel < len(SPEED_CHOICES):
                    spd_val = float(SPEED_CHOICES[sel][0])
                    setConfigValue("defaultSpeed", spd_val)
            except Exception:
                pass

        # Default Repeat Mode
        if hasattr(self, "defaultRepeatChoice"):
            try:
                sel = self.defaultRepeatChoice.GetSelection()
                if 0 <= sel < len(REPEAT_CHOICES):
                    mode_val = REPEAT_CHOICES[sel][0]
                    setConfigValue("defaultRepeatMode", mode_val)
            except Exception:
                pass

        if hasattr(self, "autoNextChk"):
            try:
                setConfigValue("defaultAutoNext", bool(self.autoNextChk.GetValue()))
            except Exception:
                pass

        if hasattr(self, "resumePositionChk"):
            try:
                setConfigValue("resumePosition", bool(self.resumePositionChk.GetValue()))
            except Exception:
                pass

        if hasattr(self, "rememberPlaybackStateChk"):
            try:
                val = bool(self.rememberPlaybackStateChk.GetValue())
                setConfigValue("rememberPlaybackState", val)
                if not val:
                    store = get_state_store()
                    if store and hasattr(store, "clear_last_session"):
                        store.clear_last_session()
            except Exception:
                pass
        if hasattr(self, "autoEnterPlayerModeChk"):
            try:
                setConfigValue("autoEnterPlayerMode", bool(self.autoEnterPlayerModeChk.GetValue()))
            except Exception:
                pass

        # Update recents history options
        if hasattr(self, "recentsEnabledChk"):
            try:
                setConfigValue("recentsEnabled", bool(self.recentsEnabledChk.GetValue()))
            except Exception:
                pass
        if hasattr(self, "recentsMaxEntriesCtrl"):
            try:
                setConfigValue("recentsMaxEntries", int(self.recentsMaxEntriesCtrl.GetValue()))
            except Exception:
                pass
        if hasattr(self, "recentsKeepFilesChk"):
            try:
                setConfigValue("recentsKeepFiles", bool(self.recentsKeepFilesChk.GetValue()))
            except Exception:
                pass
        if hasattr(self, "recentsKeepFoldersChk"):
            try:
                setConfigValue("recentsKeepFolders", bool(self.recentsKeepFoldersChk.GetValue()))
            except Exception:
                pass
        if hasattr(self, "recentsKeepPlaylistsChk"):
            try:
                setConfigValue("recentsKeepPlaylists", bool(self.recentsKeepPlaylistsChk.GetValue()))
            except Exception:
                pass
        if hasattr(self, "recentsKeepStreamsChk"):
            try:
                setConfigValue("recentsKeepStreams", bool(self.recentsKeepStreamsChk.GetValue()))
            except Exception:
                pass

        # Update YouTube & online streaming options
        if hasattr(self, "ytdlpChannelChoice"):
            try:
                chanSel = self.ytdlpChannelChoice.GetSelection()
                if 0 <= chanSel < len(YTDLP_CHANNEL_CHOICES):
                    setConfigValue("ytdlpUpdateChannel", YTDLP_CHANNEL_CHOICES[chanSel][0])
            except Exception:
                pass
        if hasattr(self, "streamAudioQualityChoice"):
            try:
                qualSel = self.streamAudioQualityChoice.GetSelection()
                if 0 <= qualSel < len(STREAM_QUALITY_CHOICES):
                    new_qual = STREAM_QUALITY_CHOICES[qualSel][0]
                    old_qual = getConfigValue("streamAudioQuality", "high")
                    setConfigValue("streamAudioQuality", new_qual)
                    if new_qual != old_qual:
                        if stream_engine and hasattr(stream_engine, "clear_resolve_cache"):
                            stream_engine.clear_resolve_cache()
            except Exception:
                pass
        if hasattr(self, "searchResultsCountCtrl"):
            try:
                setConfigValue("searchResultsCount", int(self.searchResultsCountCtrl.GetValue()))
            except Exception:
                pass
        if hasattr(self, "maxStreamItemsCtrl"):
            try:
                setConfigValue("maxStreamPlaylistItems", int(self.maxStreamItemsCtrl.GetValue()))
            except Exception:
                pass
        if hasattr(self, "cookiesBrowserChoice"):
            try:
                browserSel = self.cookiesBrowserChoice.GetSelection()
                if 0 <= browserSel < len(self.cookiesBrowserChoices):
                    setConfigValue("ytdlpCookiesBrowser", self.cookiesBrowserChoices[browserSel][0])
            except Exception:
                pass
        if hasattr(self, "cookiesFileCtrl"):
            try:
                setConfigValue("ytdlpCookiesFile", self.cookiesFileCtrl.GetValue().strip().strip('"'))
            except Exception:
                pass

        if hasattr(self, "exportFolderCtrl"):
            try:
                setConfigValue("exportFolder", self.exportFolderCtrl.GetValue().strip().strip('"'))
                i = self.exportFormatChoice.GetSelection()
                if 0 <= i < len(self.exportFormatChoices):
                    setConfigValue("exportFormat", self.exportFormatChoices[i][0])
                j = self.exportQualityChoice.GetSelection()
                if 0 <= j < len(self.exportQualityChoices):
                    setConfigValue("exportQuality", self.exportQualityChoices[j][0])
                setConfigValue("exportAutoCopy", bool(self.exportAutoCopyChk.GetValue()))
            except Exception:
                pass

        # Update SponsorBlock options
        if hasattr(self, "sponsorBlockEnabledChk"):
            setConfigValue("sponsorBlockEnabled", bool(self.sponsorBlockEnabledChk.GetValue()))
        if hasattr(self, "announceSponsorSkipChk"):
            setConfigValue("announceSponsorSkip", bool(self.announceSponsorSkipChk.GetValue()))
        if hasattr(self, "sbCatSponsorChk"):
            cats = []
            if self.sbCatSponsorChk.GetValue():
                cats.append("sponsor")
            if hasattr(self, "sbCatIntroChk") and self.sbCatIntroChk.GetValue():
                cats.append("intro")
            if hasattr(self, "sbCatOutroChk") and self.sbCatOutroChk.GetValue():
                cats.append("outro")
            if hasattr(self, "sbCatSelfpromoChk") and self.sbCatSelfpromoChk.GetValue():
                cats.append("selfpromo")
            if hasattr(self, "sbCatInteractionChk") and self.sbCatInteractionChk.GetValue():
                cats.append("interaction")
            if hasattr(self, "sbCatMusicOfftopicChk") and self.sbCatMusicOfftopicChk.GetValue():
                cats.append("music_offtopic")
            setConfigValue("sponsorBlockCategories", ",".join(cats))

        # Update startup add-on update check option
        if hasattr(self, "autoCheckAddonUpdateChk"):
            try:
                setConfigValue("autoCheckAddonUpdateOnStartup", bool(self.autoCheckAddonUpdateChk.GetValue()))
            except Exception:
                pass

        # Save to database store
        saveConfig()

        # Notify active player controller or engine of configuration update
        self._notifyActiveEngine(getConfig())

    def _notifyActiveEngine(self, cfg: dict) -> None:
        """
        Dispatches updated configuration to running controller or engine instances.
        """
        try:
            ctrl = get_controller()
            if ctrl is not None:
                if hasattr(ctrl, "on_config_updated"):
                    ctrl.on_config_updated(cfg)
                elif hasattr(ctrl, "onConfigUpdated"):
                    ctrl.onConfigUpdated(cfg)
        except Exception:
            pass

        try:
            engine = get_engine()
            if engine is not None:
                if hasattr(engine, "on_config_updated"):
                    engine.on_config_updated(cfg)
                elif hasattr(engine, "onConfigUpdated"):
                    engine.onConfigUpdated(cfg)
        except Exception:
            pass

    def onDiscard(self) -> None:
        """Invoked when the user cancels or discards settings changes."""
        pass
