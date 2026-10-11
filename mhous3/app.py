"""MHous3 Audio Studio - main window."""
import os
import sys
import threading
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Qt, QThread, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMainWindow, QMessageBox,
                               QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSlider, QTableWidget,
                               QTableWidgetItem, QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from . import APP_NAME, APP_VERSION, SR, dsp, engine, settings as cfg
from .paths import app_dir
from .player import ABPlayer, SD_ERROR
from .waveform import WaveformPanel

MEDIA_FILTER = ("Audio / video (*.wav *.mp3 *.m4a *.aac *.flac *.ogg *.opus *.wma *.aif *.aiff *.mp4 *.mov *.mkv "
                "*.avi *.mts *.m2ts *.mxf *.webm *.mpg *.mpeg *.wmv *.m4v);;All files (*.*)")
MEDIA_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aif", ".aiff"} | cfg.VIDEO_EXT

STYLE = """
* { font-family: 'Segoe UI', 'Inter', sans-serif; font-size: 13px; }
QMainWindow, QWidget { background: #14161b; color: #e6e8ee; }
QTabWidget::pane { border: 1px solid #262a33; top: -1px; }
QTabBar::tab { background: #1b1e25; padding: 9px 22px; border: 1px solid #262a33; border-bottom: none; margin-right: 2px; }
QTabBar::tab:selected { background: #14161b; color: #f2b84b; font-weight: 600; }
QGroupBox { border: 1px solid #2a2f3a; border-radius: 8px; margin-top: 14px; padding: 10px 8px 6px 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #f2b84b; font-weight: 600; }
QPushButton { background: #232731; border: 1px solid #343a47; border-radius: 6px; padding: 6px 14px; }
QPushButton:hover { background: #2c313e; border-color: #f2b84b; }
QPushButton:disabled { color: #5b6270; background: #1a1d24; }
QPushButton:checked { background: #f2b84b; color: #14161b; font-weight: 700; border-color: #f2b84b; }
QPushButton#primary { background: #f2b84b; color: #14161b; font-weight: 700; border: none; padding: 9px 20px; }
QPushButton#primary:hover { background: #ffd070; }
QPushButton#primary:disabled { background: #5a4a26; color: #1a1d24; }
QComboBox, QTableWidget, QTextBrowser { background: #1b1e25; border: 1px solid #2f3541; border-radius: 5px; padding: 4px 8px; }
QComboBox QAbstractItemView { background: #1b1e25; selection-background-color: #3a3220; }
QSlider::groove:horizontal { height: 4px; background: #2f3541; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #f2b84b; border-radius: 2px; }
QSlider::handle:horizontal { background: #f6f7fb; width: 14px; margin: -6px 0; border-radius: 7px; }
QProgressBar { background: #1b1e25; border: 1px solid #2f3541; border-radius: 5px; text-align: center; height: 16px; }
QProgressBar::chunk { background: #f2b84b; border-radius: 4px; }
QHeaderView::section { background: #1b1e25; border: none; border-bottom: 1px solid #2f3541; padding: 6px; }
QScrollBar:horizontal { height: 12px; background: #14161b; }
QScrollBar::handle:horizontal { background: #343a47; border-radius: 5px; min-width: 30px; }
QScrollBar:vertical { width: 12px; background: #14161b; }
QScrollBar::handle:vertical { background: #343a47; border-radius: 5px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #4a5160; border-radius: 4px; background: #1b1e25; }
QCheckBox::indicator:checked { background: #f2b84b; border-color: #f2b84b; }
QLabel#hint { color: #8f98a8; }
QLabel#info { background: #1b1e25; border: 1px solid #2a2f3a; border-radius: 6px; padding: 7px 10px; color: #cfd4df; }
QToolTip { background: #232731; color: #fff; border: 1px solid #f2b84b; }
QStatusBar { background: #101216; color: #9aa3b2; }
QMenuBar { background: #101216; } QMenuBar::item:selected { background: #2a2f3a; }
QMenu { background: #1b1e25; border: 1px solid #2f3541; } QMenu::item:selected { background: #3a3220; }
"""


# ======================================================================== shared state + bound widgets
class Store(QObject):
    changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.s = dict(cfg.DEFAULTS)

    def set(self, key, value):
        if self.s.get(key) != value:
            self.s[key] = value
            self.changed.emit(key)

    def load(self, d):
        self.s = dict(cfg.DEFAULTS)
        self.s.update(d)
        self.changed.emit("*")


class SliderRow(QWidget):
    def __init__(self, store, key, lo, hi, step=1.0, dec=0, suffix="", tip=""):
        super().__init__()
        self.store, self.key, self.step, self.dec, self.suffix = store, key, step, dec, suffix
        self.is_float = isinstance(cfg.DEFAULTS[key], float)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.sl = QSlider(Qt.Horizontal)
        self.sl.setRange(int(round(lo / step)), int(round(hi / step)))
        self.lab = QLabel()
        self.lab.setMinimumWidth(70)
        self.lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.sl, 1)
        lay.addWidget(self.lab)
        self.sl.valueChanged.connect(self._moved)
        store.changed.connect(self._refresh)
        self._refresh("*")
        if tip:
            self.setToolTip(tip)

    def _moved(self, v):
        val = round(v * self.step, 4)
        self.store.set(self.key, float(val) if self.is_float else int(round(val)))
        self._label()

    def _label(self):
        v = self.sl.value() * self.step
        self.lab.setText(f"{v:.{self.dec}f}{self.suffix}")

    def _refresh(self, key):
        if key in ("*", self.key):
            self.sl.blockSignals(True)
            self.sl.setValue(int(round(self.store.s[self.key] / self.step)))
            self.sl.blockSignals(False)
            self._label()


class ComboRow(QComboBox):
    def __init__(self, store, key, items, tip=""):
        super().__init__()
        self.store, self.key = store, key
        self.addItems(items)
        self.currentTextChanged.connect(lambda t: self.store.set(self.key, t))
        store.changed.connect(self._refresh)
        self._refresh("*")
        if tip:
            self.setToolTip(tip)

    def _refresh(self, key):
        if key in ("*", self.key):
            v = str(self.store.s[self.key])
            if self.findText(v) < 0:
                self.addItem(v)
            self.blockSignals(True)
            self.setCurrentText(v)
            self.blockSignals(False)


class FormatCombo(ComboRow):
    """Output format list depends on the chosen channel layout."""

    def __init__(self, store):
        super().__init__(store, "out_format", list(cfg.FORMATS))
        store.changed.connect(self._channels)
        self._channels("*")

    def _channels(self, key):
        if key not in ("*", "out_channels"):
            return
        ok = cfg.formats_for(self.store.s["out_channels"])
        cur = self.store.s["out_format"]
        self.blockSignals(True)
        self.clear()
        self.addItems(ok)
        if cur not in ok:
            cur = "Dolby Digital AC-3" if self.store.s["out_channels"] == "Dolby Digital 5.1" else ok[0]
            self.store.s["out_format"] = cur
        self.setCurrentText(cur)
        self.blockSignals(False)


class CheckRow(QCheckBox):
    def __init__(self, store, key, text, tip=""):
        super().__init__(text)
        self.store, self.key = store, key
        self.toggled.connect(lambda v: self.store.set(self.key, bool(v)))
        store.changed.connect(self._refresh)
        self._refresh("*")
        if tip:
            self.setToolTip(tip)

    def _refresh(self, key):
        if key in ("*", self.key):
            self.blockSignals(True)
            self.setChecked(bool(self.store.s[self.key]))
            self.blockSignals(False)


def group(title, rows):
    box = QGroupBox(title)
    f = QFormLayout(box)
    f.setLabelAlignment(Qt.AlignLeft)
    f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    for r in rows:
        if isinstance(r, tuple):
            f.addRow(r[0], r[1])
        else:
            f.addRow(r)
    return box


def hint(text):
    l = QLabel(text)
    l.setObjectName("hint")
    l.setWordWrap(True)
    return l


class PresetBar(QWidget):
    def __init__(self, store):
        super().__init__()
        self.store = store
        self.user = cfg.load_user_presets()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox()
        self.combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(22)
        self.fill()
        self.combo.activated.connect(self._pick)
        save = QPushButton("Save…")
        save.setToolTip("Save the current settings as your own preset")
        save.clicked.connect(self._save)
        dele = QPushButton("Delete")
        dele.clicked.connect(self._delete)
        lay.addWidget(QLabel("Preset"))
        lay.addWidget(self.combo, 1)
        lay.addWidget(save)
        lay.addWidget(dele)

    def names(self):
        return list(cfg.PRESETS) + list(self.user)

    def fill(self, select=None):
        self.combo.clear()
        self.combo.addItems(list(cfg.PRESETS))
        for n in self.user:
            self.combo.addItem("★ " + n)
        if select:
            self.combo.setCurrentText(select)

    def _pick(self, i):
        t = self.combo.itemText(i)
        if t.startswith("★ "):
            d = dict(cfg.DEFAULTS)
            d.update(self.user.get(t[2:], {}))
            self.store.load(d)
        else:
            self.store.load(cfg.preset_settings(t))

    def _save(self):
        name, ok = QInputDialog.getText(self, "Save preset", "Preset name:")
        if ok and name.strip():
            self.user[name.strip()] = dict(self.store.s)
            cfg.save_user_presets(self.user)
            self.fill("★ " + name.strip())

    def _delete(self):
        t = self.combo.currentText()
        if t.startswith("★ ") and t[2:] in self.user:
            del self.user[t[2:]]
            cfg.save_user_presets(self.user)
            self.fill()
        else:
            QMessageBox.information(self, "Presets", "Built-in presets can't be deleted. Only your ★ presets can.")


class OutputPanel(QGroupBox):
    def __init__(self, store):
        super().__init__("Output")
        f = QFormLayout(self)
        self.ch = ComboRow(store, "out_channels", cfg.OUT_CHANNELS,
                           "Mono, Stereo, Dolby Surround (matrix-encoded Lt/Rt stereo) or true 5.1 for Dolby Digital")
        f.addRow("Channels", self.ch)
        f.addRow("Format", FormatCombo(store))
        f.addRow(CheckRow(store, "loudness_on", "Match loudness"))
        f.addRow("Target", ComboRow(store, "loudness_target", list(cfg.LOUDNESS_TARGETS)))
        self.custom = SliderRow(store, "lufs_custom", -40, -9, 0.5, 1, " LUFS")
        f.addRow("Custom", self.custom)
        f.addRow("Peak ceiling", SliderRow(store, "ceiling", -6, 0, 0.1, 1, " dB",
                                           "Nothing in the output will go above this level"))


# ======================================================================== background tasks
class _Sig(QObject):
    progress = Signal(float, str)
    done = Signal(object)
    failed = Signal(str)


class Task(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.setAutoDelete(False)
        self.fn, self.sig, self.cancel = fn, _Sig(), threading.Event()

    def run(self):
        try:
            res = self.fn(self.sig.progress.emit, self.cancel)
            msg = None
        except engine.Cancelled:
            res, msg = None, "Cancelled"
        except Exception as e:
            res, msg = None, f"{e}"
        try:  # the window may already be closed
            self.sig.failed.emit(msg) if msg is not None else self.sig.done.emit(res)
        except RuntimeError:
            pass


# ======================================================================== Basic / Advanced control panels
def basic_panel(store):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.addWidget(PresetBar(store))
    lay.addWidget(group("Fix the recording", [
        ("Noise reduction", SliderRow(store, "nr_amount", 0, 100, 1, 0, " %", "Hiss, hum, room noise, camera-mic noise")),
        ("Echo / room removal", SliderRow(store, "derev_amount", 0, 100, 1, 0, " %", "Removes reverb and boxy room sound")),
        ("Fix clipping", ComboRow(store, "declip", ["Auto", "On", "Off"], "Rebuilds peaks that were flattened by distortion")),
        ("Mains hum", ComboRow(store, "hum", ["Off", "50", "60"], "50 Hz in South Africa / Europe, 60 Hz in the Americas")),
    ]))
    lay.addWidget(group("Make it sound cinematic", [
        ("Voice clarity", SliderRow(store, "clarity", 0, 100, 1, 0, " %", "Presence and intelligibility")),
        ("Warmth", SliderRow(store, "warmth", 0, 100, 1, 0, " %", "Body and chest, the 'big movie voice' low end")),
        ("Cinema polish", SliderRow(store, "polish", 0, 100, 1, 0, " %", "Parallel compression, air and density")),
    ]))
    lay.addWidget(group("Add space (reverb)", [
        ("Room", ComboRow(store, "reverb_type", cfg.reverb_choices())),
        ("Amount", SliderRow(store, "reverb_mix", 0, 100, 1, 0, " %", "0 = completely dry")),
    ]))
    lay.addWidget(OutputPanel(store))
    lay.addStretch(1)
    return w


def advanced_panel(store):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.addWidget(group("Input and repair", [
        ("Source channels", ComboRow(store, "input_mode", ["Auto", "Mono", "Stereo"], "Auto treats identical L/R as mono")),
        ("Declip max run", SliderRow(store, "declip_max_run", 8, 200, 4, 0, " smp", "Longest clipped stretch to rebuild")),
        ("Low cut", SliderRow(store, "lowcut", 0, 300, 5, 0, " Hz", "Removes rumble, wind and handling noise")),
        ("High cut", SliderRow(store, "highcut", 0, 20000, 500, 0, " Hz", "0 = off")),
    ]))
    lay.addWidget(group("Noise and echo engines", [
        ("Noise engine", ComboRow(store, "nr_engine", ["Auto", "AI (DeepFilterNet)", "Built-in"],
                                  "Auto uses the AI denoiser when available")),
        ("Built-in sensitivity", SliderRow(store, "nr_sens", 1, 5, 0.1, 1, "x", "Higher removes more noise but can sound thin")),
        ("Room decay (RT60)", SliderRow(store, "derev_rt60", 0.2, 3.0, 0.05, 2, " s", "Roughly how long the echo in your room lasts")),
    ]))
    eq_rows = []
    names = ["Low shelf", "Low-mid", "Mid", "Presence", "Upper-mid", "High shelf"]
    for i in range(1, 7):
        eq_rows.append((f"{i}. {names[i - 1]} gain", SliderRow(store, f"eq{i}_g", -15, 15, 0.5, 1, " dB")))
        eq_rows.append((f"    frequency", SliderRow(store, f"eq{i}_f", 20, 16000, 10, 0, " Hz")))
        eq_rows.append((f"    Q", SliderRow(store, f"eq{i}_q", 0.2, 5, 0.1, 1, "")))
    lay.addWidget(group("6-band parametric EQ", eq_rows))
    lay.addWidget(group("Noise gate / expander", [
        CheckRow(store, "gate_on", "Enable (trims room tails between words)"),
        ("Threshold", SliderRow(store, "gate_thr", -80, -20, 1, 0, " dB")),
        ("Ratio", SliderRow(store, "gate_ratio", 1, 6, 0.1, 1, ":1")),
        ("Max reduction", SliderRow(store, "gate_range", -40, -3, 1, 0, " dB")),
        ("Attack", SliderRow(store, "gate_attack", 1, 50, 1, 0, " ms")),
        ("Release", SliderRow(store, "gate_release", 20, 800, 10, 0, " ms")),
    ]))
    lay.addWidget(group("De-esser", [
        CheckRow(store, "deess_on", "Enable"),
        ("Frequency", SliderRow(store, "deess_freq", 3500, 10000, 100, 0, " Hz")),
        ("Threshold", SliderRow(store, "deess_thr", -60, -15, 1, 0, " dB")),
        ("Ratio", SliderRow(store, "deess_ratio", 1, 10, 0.5, 1, ":1")),
    ]))
    lay.addWidget(group("Compressor", [
        CheckRow(store, "comp_on", "Enable"),
        ("Threshold", SliderRow(store, "comp_thr", -50, 0, 1, 0, " dB")),
        ("Ratio", SliderRow(store, "comp_ratio", 1, 10, 0.1, 1, ":1")),
        ("Attack", SliderRow(store, "comp_attack", 1, 100, 1, 0, " ms")),
        ("Release", SliderRow(store, "comp_release", 20, 800, 10, 0, " ms")),
        ("Knee", SliderRow(store, "comp_knee", 0, 24, 1, 0, " dB")),
        ("Make-up gain", SliderRow(store, "comp_makeup", 0, 18, 0.5, 1, " dB")),
    ]))
    lay.addWidget(group("Colour and width", [
        CheckRow(store, "sat_on", "Tape-style saturation"),
        ("Drive", SliderRow(store, "sat_drive", 0.5, 6, 0.1, 1, "x")),
        ("Mix", SliderRow(store, "sat_mix", 0, 100, 1, 0, " %")),
        ("Stereo width", SliderRow(store, "width", 0, 200, 1, 0, " %", "Ignored for mono output")),
    ]))
    lay.addWidget(group("Reverb details", [
        ("Pre-delay", SliderRow(store, "reverb_predelay", -1, 120, 1, 0, " ms", "-1 = use the room's default")),
        ("Damping", SliderRow(store, "reverb_damp", -1, 1, 0.05, 2, "", "-1 = default; higher = darker tail")),
        ("Decay (RT60)", SliderRow(store, "reverb_rt60", 0, 8, 0.1, 1, " s", "0 = use the room's default")),
        ("Reverb low cut", SliderRow(store, "reverb_lowcut", 20, 600, 10, 0, " Hz")),
        ("Reverb high cut", SliderRow(store, "reverb_highcut", 2000, 16000, 250, 0, " Hz")),
    ]))
    lay.addWidget(group("Dolby / 5.1 mix", [
        ("Dialogue to centre", SliderRow(store, "center_level", 0, 100, 1, 0, " %", "How much of the voice goes to the centre speaker")),
        ("Surround level", SliderRow(store, "surround_level", 0, 100, 1, 0, " %", "Reverb and ambience in the rear speakers")),
        ("LFE (subwoofer)", SliderRow(store, "lfe_level", 0, 100, 1, 0, " %")),
    ]))
    lay.addStretch(1)
    return w


def scrolled(widget):
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setWidget(widget)
    sa.setFrameShape(QScrollArea.NoFrame)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    return sa


# ======================================================================== Studio tab (single file)
class StudioTab(QWidget):
    def __init__(self, store, main):
        super().__init__()
        self.store, self.main = store, main
        self.audio = self.original = None
        self.src_path = None
        self.undo, self.redo = [], []
        self.player = ABPlayer(SR)
        self.p_off = 0
        self.preview = None
        self.task = None
        self._pending = False
        self._seek_after = None
        self.pool = QThreadPool.globalInstance()
        self.timer_debounce = QTimer(self)
        self.timer_debounce.setSingleShot(True)
        self.timer_debounce.timeout.connect(self.request_preview)
        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self.tick)
        self.tick_timer.start(33)
        self._build()
        store.changed.connect(self._settings_changed)

    # ---------- UI
    def _build(self):
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        root.addLayout(left, 3)

        top = QHBoxLayout()
        self.btn_open = QPushButton("📂  Open file…")
        self.btn_open.clicked.connect(lambda: self.main.open_dialog())
        self.title = QLabel("No file loaded")
        self.title.setObjectName("hint")
        self.btn_spec = QPushButton("Spectrogram")
        self.btn_spec.setCheckable(True)
        self.btn_spec.toggled.connect(lambda v: self.wave.view.set_mode("spec" if v else "wave"))
        top.addWidget(self.btn_open)
        top.addWidget(self.title, 1)
        top.addWidget(self.btn_spec)
        for txt, fn in (("Fit", lambda: self.wave.view.zoom_fit()), ("＋", lambda: self.wave.view.zoom(0.6)),
                        ("－", lambda: self.wave.view.zoom(1.6)), ("Zoom sel.", lambda: self.wave.view.zoom_to_selection())):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            top.addWidget(b)
        left.addLayout(top)

        self.wave = WaveformPanel()
        self.wave.view.seekRequested.connect(self.seek_global)
        self.wave.view.selectionChanged.connect(self._selection_changed)
        left.addWidget(self.wave, 1)

        tr = QHBoxLayout()
        self.btn_play = QPushButton("▶  Play")
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_stop = QPushButton("■")
        self.btn_stop.clicked.connect(self.stop)
        self.btn_a = QPushButton("A · Original")
        self.btn_b = QPushButton("B · Cleaned")
        for b in (self.btn_a, self.btn_b):
            b.setCheckable(True)
            b.setMinimumWidth(130)
        self.btn_b.setChecked(True)
        self.btn_a.clicked.connect(lambda: self.set_ab("A"))
        self.btn_b.clicked.connect(lambda: self.set_ab("B"))
        self.chk_match = QCheckBox("Match loudness")
        self.chk_match.setChecked(True)
        self.chk_match.setToolTip("Plays the original at the same loudness as the cleaned version, so you compare quality, not volume")
        self.chk_match.toggled.connect(self._apply_match)
        self.chk_loop = QCheckBox("Loop selection")
        self.chk_loop.toggled.connect(self._apply_loop)
        self.time_lbl = QLabel("0:00.0 / 0:00.0")
        self.meter = QProgressBar()
        self.meter.setRange(0, 60)
        self.meter.setTextVisible(False)
        self.meter.setFixedWidth(90)
        for wdg in (self.btn_play, self.btn_stop, self.btn_a, self.btn_b, self.chk_match, self.chk_loop):
            tr.addWidget(wdg)
        tr.addStretch(1)
        tr.addWidget(self.time_lbl)
        tr.addWidget(self.meter)
        left.addLayout(tr)

        ed = QHBoxLayout()
        ed.addWidget(QLabel("Edit:"))
        for txt, fn, tip in (
                ("Trim", self.e_trim, "Keep only the selection"), ("Cut", self.e_cut, "Delete the selection"),
                ("Silence", self.e_silence, "Mute the selection"), ("Fade in", self.e_fade_in, ""),
                ("Fade out", self.e_fade_out, ""), ("Gain…", self.e_gain, "Raise or lower volume (selection or all)"),
                ("Normalize", self.e_norm, "Peak-normalise to -1 dB"), ("Reverse", self.e_reverse, ""),
                ("↶ Undo", self.do_undo, ""), ("↷ Redo", self.do_redo, "")):
            b = QPushButton(txt)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            ed.addWidget(b)
        ed.addStretch(1)
        left.addLayout(ed)

        pr = QHBoxLayout()
        self.chk_auto = QCheckBox("Auto-update preview")
        self.chk_auto.setChecked(True)
        self.scope = QComboBox()
        self.scope.addItems(["Preview: selection, or what's on screen if long", "Preview: whole file"])
        self.btn_prev = QPushButton("Update preview")
        self.btn_prev.clicked.connect(self.request_preview)
        pr.addWidget(self.chk_auto)
        pr.addWidget(self.scope)
        pr.addWidget(self.btn_prev)
        pr.addStretch(1)
        left.addLayout(pr)
        self.prog = QProgressBar()
        self.prog.setRange(0, 1000)
        self.prog.setFormat("Ready")
        self.prog.setValue(0)
        left.addWidget(self.prog)
        self.info = QLabel("Open a file to begin. Drag & drop works too.")
        self.info.setObjectName("info")
        self.info.setWordWrap(True)
        left.addWidget(self.info)

        right = QVBoxLayout()
        root.addLayout(right, 2)
        tabs = QTabWidget()
        tabs.addTab(scrolled(basic_panel(self.store)), "Basic")
        tabs.addTab(scrolled(advanced_panel(self.store)), "Advanced editor")
        right.addWidget(tabs, 1)
        self.btn_export = QPushButton("Export…")
        self.btn_export.setObjectName("primary")
        self.btn_export.clicked.connect(self.export_dialog)
        right.addWidget(self.btn_export)
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self.toggle_play)
        QShortcut(QKeySequence(Qt.Key_A), self, activated=lambda: self.set_ab("A"))
        QShortcut(QKeySequence(Qt.Key_B), self, activated=lambda: self.set_ab("B"))

    # ---------- loading
    def load(self, path):
        self.main.busy(f"Reading {Path(path).name}…")
        t = Task(lambda prog, cancel: engine.decode(path, cancel))
        self._hold(t)
        t.sig.done.connect(lambda a: self._loaded(path, a))
        t.sig.failed.connect(lambda m: (self.main.idle(), QMessageBox.warning(self, APP_NAME, f"Could not open file:\n{m}")))
        self.pool.start(t)

    def _loaded(self, path, a):
        self.main.idle()
        self.stop()
        self.src_path, self.audio, self.original = path, a, a.copy()
        self.undo, self.redo, self.preview, self.p_off = [], [], None, 0
        self.title.setText(f"{Path(path).name}   ·   {len(a) / SR:.1f} s")
        self.wave.view.set_orig(a)
        self.player.set_audio(a, None)
        self.player.seek(0)
        self.set_ab("B" if False else "A")
        self.info.setText("Loaded. Choose a preset or move the sliders - the preview updates automatically.")
        if self.chk_auto.isChecked():
            self.request_preview()

    def _hold(self, t):
        self._tasks = getattr(self, "_tasks", [])
        self._tasks = [x for x in self._tasks if x is not t][-6:] + [t]

    # ---------- preview rendering
    def _settings_changed(self, key):
        if key == "out_format" or self.audio is None:
            return
        if self.chk_auto.isChecked():
            self.timer_debounce.start(700)

    def preview_range(self):
        n, v = len(self.audio), self.wave.view
        if v.sel and v.sel[1] - v.sel[0] > SR // 4:
            return v.sel
        if self.scope.currentIndex() == 1 or n <= 90 * SR:
            return (0, n)
        s = int(v.vs)
        return (s, min(n, s + 60 * SR))

    def request_preview(self):
        if self.audio is None:
            return
        if self.task is not None:
            self._pending = True
            self.task.cancel.set()
            return
        s, e = self.preview_range()
        seg, sett = self.audio[s:e].copy(), dict(self.store.s)
        t = self.task = Task(lambda prog, cancel: (*engine.render(seg, sett, prog, cancel), s, e, seg))
        t.sig.progress.connect(lambda f, m: (self.prog.setValue(int(f * 1000)), self.prog.setFormat(f"{m}…  %p%")))
        t.sig.done.connect(self._preview_done)
        t.sig.failed.connect(self._preview_failed)
        self.prog.setFormat("Rendering preview…")
        self.pool.start(t)

    def _preview_failed(self, msg):
        self.task = None
        self.prog.setValue(0)
        self.prog.setFormat("Ready" if msg == "Cancelled" else "Preview failed")
        if msg != "Cancelled":
            self.info.setText(f"Preview failed: {msg}")
        if self._pending:
            self._pending = False
            self.request_preview()

    def _preview_done(self, res):
        y, info, s, e, seg = res
        self.task = None
        if self._pending:
            self._pending = False
            self.request_preview()
            return
        gpos = self.p_off + self.player.pos
        was_playing = self.player.playing
        self.preview = (y, info, s, e)
        b = dsp.downmix_to_stereo(y)
        self.player.set_audio(seg, b)
        self.p_off = s
        self.player.seek(gpos - s if s <= gpos <= e else 0)
        self.wave.view.set_clean(b, s)
        self.prog.setValue(1000)
        self.prog.setFormat("Preview ready")
        self.player.playing = was_playing and self.player.available
        if self.player.loop is not None or self.chk_loop.isChecked():
            self._apply_loop()
        self._apply_match()
        self.set_ab("B" if self.btn_b.isChecked() else "A")
        w = info
        txt = (f"Loudness  {w['lufs_in']:.1f} → {w['lufs_out']:.1f} LUFS   ·   Peak {w['peak_in_db']:.1f} → "
               f"{w['peak_out_db']:.1f} dBFS   ·   {w['channels']} ch")
        if "declip_runs" in w:
            txt += f"   ·   Clipping repaired: {w['declip_runs']} spots ({w['clipped_fraction']:.2%})"
        if "nr_engine" in w:
            txt += f"   ·   Noise: {w['nr_engine']}"
        if "warning" in w:
            txt += f"\n⚠ {w['warning']}"
        if (s, e) != (0, len(self.audio)):
            txt += f"\nPreviewing {s / SR:.1f}–{e / SR:.1f} s. Export always processes the whole file."
        self.info.setText(txt)
        if self._seek_after is not None:
            self.seek_global(self._seek_after)
            self._seek_after = None

    # ---------- transport
    def toggle_play(self):
        if self.audio is None:
            return
        if self.player.playing:
            self.player.pause()
        else:
            try:
                self.player.play()
            except Exception as e:
                QMessageBox.warning(self, APP_NAME, f"Audio playback problem:\n{e}")
        self._play_label()

    def stop(self):
        self.player.stop()
        self._play_label()

    def _play_label(self):
        self.btn_play.setText("⏸  Pause" if self.player.playing else "▶  Play")

    def set_ab(self, which):
        if which == "B" and self.player.b is None:
            which = "A"
        self.player.switch(which)
        self.btn_a.setChecked(which == "A")
        self.btn_b.setChecked(which == "B")

    def _apply_match(self, *_):
        if self.preview is None:
            self.player.gain_a = 1.0
            return
        info = self.preview[1]
        g = 1.0
        if self.chk_match.isChecked() and np.isfinite(info["lufs_in"]) and np.isfinite(info["lufs_out"]):
            g = float(dsp.db2lin(np.clip(info["lufs_out"] - info["lufs_in"], -30, 30)))
            pk = float(np.max(np.abs(self.player.a))) if self.player.a is not None and self.player.a.size else 1.0
            g = min(g, 0.98 / max(pk, 1e-6))
        self.player.gain_a = g

    def _selection_changed(self):
        self._apply_loop()
        if self.chk_auto.isChecked() and self.audio is not None and self.wave.view.sel:
            self.timer_debounce.start(900)

    def _apply_loop(self, *_):
        v = self.wave.view
        if self.chk_loop.isChecked() and v.sel:
            a, b = v.sel[0] - self.p_off, v.sel[1] - self.p_off
            self.player.loop = (max(0, a), min(self.player.length(), b)) if b > 0 else None
        else:
            self.player.loop = None

    def seek_global(self, g):
        if self.audio is None:
            return
        n = self.player.length()
        if self.preview is not None and not (self.p_off <= g <= self.p_off + n):
            self._seek_after = g
            self.wave.view.playhead = g
            self.request_preview()
            return
        self.player.seek(g - self.p_off)
        self.wave.view.playhead = g
        self.wave.view.update()

    def tick(self):
        if self.audio is None:
            return
        g = self.p_off + self.player.pos
        v = self.wave.view
        if v.playhead != g:
            v.playhead = g
            if self.player.playing:
                v.ensure_visible(g)
            v.update()
        if self.btn_play.text().startswith("⏸") != self.player.playing:
            self._play_label()
        self.time_lbl.setText(f"{g / SR // 60:.0f}:{g / SR % 60:04.1f} / {len(self.audio) / SR // 60:.0f}:{len(self.audio) / SR % 60:04.1f}")
        pk = 20 * np.log10(max(self.player.peak, 1e-4))
        self.meter.setValue(int(max(0, 60 + pk)))

    # ---------- editing
    def _sel(self):
        v = self.wave.view
        if v.sel and v.sel[1] - v.sel[0] > 16:
            return int(v.sel[0]), int(v.sel[1])
        return None

    def _push(self):
        if self.audio is None:
            return False
        self.undo.append(self.audio.copy())
        self.undo = self.undo[-8:]
        self.redo.clear()
        return True

    def _edited(self, keep_sel=False):
        sel = self.wave.view.sel
        self.wave.view.set_orig(self.audio, keep_view=True)
        self.wave.view.vl = min(self.wave.view.vl, len(self.audio))
        self.wave.view._clamp()
        if keep_sel:
            self.wave.view.sel = sel
        self.preview, self.p_off = None, 0
        self.player.set_audio(self.audio, None)
        self.player.seek(0)
        self.set_ab("A")
        self.title.setText(f"{Path(self.src_path).name} (edited)   ·   {len(self.audio) / SR:.1f} s")
        if self.chk_auto.isChecked():
            self.timer_debounce.start(300)

    def _micro(self, a, n=240):
        n = min(n, len(a) // 2)
        if n > 1:
            r = np.linspace(0, 1, n)[:, None].astype(np.float32)
            a[:n] *= r
            a[-n:] *= r[::-1]
        return a

    def e_trim(self):
        sel = self._sel()
        if sel and self._push():
            self.audio = self.audio[sel[0]:sel[1]].copy()
            self.wave.view.sel = None
            self._edited()
            self.wave.view.zoom_fit()

    def e_cut(self):
        sel = self._sel()
        if sel and self._push():
            a, b = self.audio[:sel[0]].copy(), self.audio[sel[1]:].copy()
            if len(a) > 480:
                a[-240:] *= np.linspace(1, 0, 240)[:, None].astype(np.float32)
            if len(b) > 480:
                b[:240] *= np.linspace(0, 1, 240)[:, None].astype(np.float32)
            self.audio = np.vstack([a, b])
            self.wave.view.sel = None
            self._edited()

    def e_silence(self):
        sel = self._sel()
        if sel and self._push():
            seg = self.audio[sel[0]:sel[1]]
            n = min(240, len(seg) // 2)
            seg[:] = 0
            self.audio[sel[0]:sel[1]] = seg
            if sel[0] > n:
                self.audio[sel[0] - n:sel[0]] *= np.linspace(1, 0, n)[:, None].astype(np.float32)
            self._edited(True)

    def _fade(self, rising):
        if self.audio is None:
            return
        sel = self._sel() or (0, len(self.audio))
        if self._push():
            n = sel[1] - sel[0]
            ramp = np.linspace(0, 1, n, dtype=np.float32)
            self.audio[sel[0]:sel[1]] *= (ramp if rising else ramp[::-1])[:, None]
            self._edited(True)

    def e_fade_in(self):
        self._fade(True)

    def e_fade_out(self):
        self._fade(False)

    def e_gain(self):
        if self.audio is None:
            return
        db, ok = QInputDialog.getDouble(self, "Gain", "Change volume by (dB):", 3.0, -48, 48, 1)
        if ok and self._push():
            sel = self._sel() or (0, len(self.audio))
            self.audio[sel[0]:sel[1]] *= float(dsp.db2lin(db))
            self._edited(True)

    def e_norm(self):
        if self.audio is None:
            return
        sel = self._sel() or (0, len(self.audio))
        pk = float(np.max(np.abs(self.audio[sel[0]:sel[1]])))
        if pk > 1e-6 and self._push():
            self.audio[sel[0]:sel[1]] *= float(dsp.db2lin(-1.0)) / pk
            self._edited(True)

    def e_reverse(self):
        if self.audio is None:
            return
        sel = self._sel() or (0, len(self.audio))
        if self._push():
            self.audio[sel[0]:sel[1]] = self.audio[sel[0]:sel[1]][::-1].copy()
            self._edited(True)

    def do_undo(self):
        if self.undo:
            self.redo.append(self.audio.copy())
            self.audio = self.undo.pop()
            self._edited()

    def do_redo(self):
        if self.redo:
            self.undo.append(self.audio.copy())
            self.audio = self.redo.pop()
            self._edited()

    # ---------- export
    def export_dialog(self):
        if self.audio is None:
            QMessageBox.information(self, APP_NAME, "Open a file first.")
            return
        s = dict(self.store.s)
        ext = cfg.FORMATS[s["out_format"]][0]
        if ext in (".mp4", ".mkv") and Path(self.src_path).suffix.lower() not in cfg.VIDEO_EXT:
            ext = ".wav"
            s["out_format"] = "WAV 24-bit"
        default = str(engine.default_output_path(self.src_path, s, None, "_MHous3"))
        dst, _ = QFileDialog.getSaveFileName(self, "Export", default, f"{ext.upper()[1:]} (*{ext})")
        if not dst:
            return
        audio = self.audio.copy()
        self.main.busy("Exporting…")
        t = Task(lambda prog, cancel: self._do_export(audio, dst, s, prog, cancel))
        self._hold(t)
        t.sig.progress.connect(lambda f, m: self.main.status(f"Exporting: {m}  {int(f * 100)}%"))
        t.sig.done.connect(lambda info: (self.main.idle(), QMessageBox.information(
            self, APP_NAME, f"Saved:\n{dst}\n\nLoudness {info['lufs_in']:.1f} → {info['lufs_out']:.1f} LUFS, "
                            f"peak {info['peak_out_db']:.1f} dBFS")))
        t.sig.failed.connect(lambda m: (self.main.idle(), QMessageBox.warning(self, APP_NAME, f"Export failed:\n{m}")))
        self.pool.start(t)

    def _do_export(self, audio, dst, s, prog, cancel):
        y, info = engine.render(audio, s, lambda f, m: prog(f * 0.9, m), cancel)
        prog(0.92, "Encoding")
        engine.export(y, dst, s, self.src_path, cancel)
        return info

    def shutdown(self):
        self.player.close()


# ======================================================================== Batch tab
class BatchWorker(QThread):
    row = Signal(int, str, str, str)
    prog = Signal(float, str)
    finished_all = Signal(str)

    def __init__(self, jobs, s, outdir, suffix):
        super().__init__()
        self.jobs, self.s, self.outdir, self.suffix = jobs, s, outdir, suffix
        self.cancel = threading.Event()

    def run(self):
        n, ok, bad = len(self.jobs), 0, 0
        for i, (r, src) in enumerate(self.jobs):
            if self.cancel.is_set():
                break
            self.row.emit(r, "Processing…", "", "")
            try:
                dst = engine.default_output_path(src, self.s, self.outdir or None, self.suffix)
                info = engine.process_file(src, dst, self.s, lambda f, m, i=i, src=src: self.prog.emit(
                    (i + f) / n, f"{Path(src).name}: {m}"), self.cancel)
                self.row.emit(r, "Done ✓", f"{info['lufs_in']:.1f} → {info['lufs_out']:.1f} LUFS", str(dst))
                ok += 1
            except engine.Cancelled:
                self.row.emit(r, "Cancelled", "", "")
                break
            except Exception as e:
                self.row.emit(r, "Failed ✗", str(e)[:200], "")
                bad += 1
        self.finished_all.emit(f"Finished: {ok} done, {bad} failed" + (", stopped early" if self.cancel.is_set() else ""))


class BatchTab(QWidget):
    def __init__(self, store, main, presets_bar):
        super().__init__()
        self.store, self.main, self.worker = store, main, None
        self.presets_bar = presets_bar
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        root.addLayout(left, 3)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["File", "Status", "Result", "Saved as"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        left.addWidget(self.table, 1)
        bar = QHBoxLayout()
        for txt, fn in (("Add files…", self.add_files), ("Add folder…", self.add_folder),
                        ("Remove selected", self.remove), ("Clear", lambda: self.table.setRowCount(0))):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch(1)
        left.addLayout(bar)
        self.prog = QProgressBar()
        self.prog.setRange(0, 1000)
        self.prog.setFormat("Ready")
        left.addWidget(self.prog)
        self.summary = QLabel("Drag & drop files or folders anywhere on this tab.")
        self.summary.setObjectName("info")
        self.summary.setWordWrap(True)
        left.addWidget(self.summary)

        right = QVBoxLayout()
        root.addLayout(right, 2)
        box = QGroupBox("Batch settings")
        f = QFormLayout(box)
        self.which = QComboBox()
        f.addRow("Settings to use", self.which)
        self.keep_out = QCheckBox("Use my Output choices below")
        self.keep_out.setChecked(True)
        f.addRow(self.keep_out)
        self.same = QCheckBox("Save next to the original file")
        self.same.setChecked(True)
        self.same.toggled.connect(lambda v: self.folder_btn.setEnabled(not v))
        f.addRow(self.same)
        self.folder = QLabel("(not chosen)")
        self.folder.setObjectName("hint")
        self.folder_btn = QPushButton("Choose output folder…")
        self.folder_btn.setEnabled(False)
        self.folder_btn.clicked.connect(self._choose_folder)
        f.addRow(self.folder_btn)
        f.addRow(self.folder)
        self.suffix = QComboBox()
        self.suffix.setEditable(True)
        self.suffix.addItems(["_MHous3", "_clean", "_cinema", ""])
        f.addRow("File name ending", self.suffix)
        right.addWidget(box)
        right.addWidget(OutputPanel(store))
        self.btn_start = QPushButton("Start batch")
        self.btn_start.setObjectName("primary")
        self.btn_start.clicked.connect(self.start)
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(lambda: self.worker and (self.worker.cancel.set(), None))
        self.btn_open = QPushButton("Open output folder")
        self.btn_open.clicked.connect(self._open_folder)
        right.addWidget(self.btn_start)
        right.addWidget(self.btn_stop)
        right.addWidget(self.btn_open)
        right.addStretch(1)
        self.out_dir = ""
        self.refresh_choices()

    def refresh_choices(self):
        cur = self.which.currentText()
        self.which.clear()
        self.which.addItem("Current Studio settings")
        self.which.addItems(self.presets_bar.names())
        i = self.which.findText(cur)
        self.which.setCurrentIndex(max(i, 0))

    def _choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Output folder")
        if d:
            self.out_dir = d
            self.folder.setText(d)

    def add_files(self):
        fs, _ = QFileDialog.getOpenFileNames(self, "Add files", "", MEDIA_FILTER)
        self.add_paths(fs)

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Add folder")
        if d:
            self.add_paths([str(p) for p in sorted(Path(d).rglob("*")) if p.suffix.lower() in MEDIA_EXT])

    def add_paths(self, paths):
        have = {self.table.item(r, 0).data(Qt.UserRole) for r in range(self.table.rowCount())}
        for p in paths:
            pp = Path(p)
            if pp.is_dir():
                self.add_paths([str(x) for x in sorted(pp.rglob("*")) if x.suffix.lower() in MEDIA_EXT])
                continue
            if p in have or pp.suffix.lower() not in MEDIA_EXT:
                continue
            r = self.table.rowCount()
            self.table.insertRow(r)
            it = QTableWidgetItem(pp.name)
            it.setData(Qt.UserRole, str(p))
            it.setToolTip(str(p))
            self.table.setItem(r, 0, it)
            for c, t in ((1, "Waiting"), (2, ""), (3, "")):
                self.table.setItem(r, c, QTableWidgetItem(t))
        self.summary.setText(f"{self.table.rowCount()} file(s) in the queue.")

    def remove(self):
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)

    def _settings(self):
        name = self.which.currentText()
        if name == "Current Studio settings":
            return dict(self.store.s)
        if name.startswith("★ "):
            s = dict(cfg.DEFAULTS)
            s.update(self.presets_bar.user.get(name[2:], {}))
        else:
            s = cfg.preset_settings(name)
        if self.keep_out.isChecked():
            for k in ("out_channels", "out_format", "loudness_on", "loudness_target", "lufs_custom", "ceiling"):
                s[k] = self.store.s[k]
        return s

    def start(self):
        jobs = [(r, self.table.item(r, 0).data(Qt.UserRole)) for r in range(self.table.rowCount())
                if self.table.item(r, 1).text() != "Done ✓"]
        if not jobs:
            QMessageBox.information(self, APP_NAME, "Add some files first (or everything is already done).")
            return
        if not self.same.isChecked() and not self.out_dir:
            self._choose_folder()
            if not self.out_dir:
                return
        self.worker = BatchWorker(jobs, self._settings(), "" if self.same.isChecked() else self.out_dir,
                                  self.suffix.currentText())
        self.worker.row.connect(self._row)
        self.worker.prog.connect(lambda f, m: (self.prog.setValue(int(f * 1000)), self.prog.setFormat(f"{m}  %p%")))
        self.worker.finished_all.connect(self._finished)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.worker.start()

    def _row(self, r, status, result, saved):
        for c, t in ((1, status), (2, result), (3, saved)):
            if r < self.table.rowCount():
                self.table.item(r, c).setText(t)

    def _finished(self, msg):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.summary.setText(msg)
        self.prog.setFormat(msg)

    def _open_folder(self):
        for r in range(self.table.rowCount()):
            p = self.table.item(r, 3).text()
            if p:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(p).parent)))
                return
        if self.out_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.out_dir))


# ======================================================================== Guide
GUIDE = f"""
<h2 style='color:#f2b84b'>Welcome to {APP_NAME}</h2>
<p>Free, offline audio rescue and cinema-style finishing. Nothing is uploaded anywhere.</p>
<h3>Quick start</h3>
<ol>
<li><b>Studio → Open file…</b> (or drag a file onto the window). Video files work too.</li>
<li>Pick a <b>Preset</b>. <i>Camera Mic Rescue</i> and <i>Clipped Recorder Rescue</i> are made for rough recordings; <i>Cinema Dialogue</i> is the film look.</li>
<li>Press <b>Play</b>, and press <b>A</b> / <b>B</b> on the keyboard to flip between original and cleaned instantly. "Match loudness" keeps the comparison fair.</li>
<li>Nudge <b>Noise reduction</b>, <b>Echo / room removal</b>, <b>Clarity</b>, <b>Warmth</b>. Less is often better - stop when it sounds natural.</li>
<li><b>Export…</b> to save. For lots of files use the <b>Batch</b> tab.</li>
</ol>
<h3>Tips for rough audio</h3>
<ul>
<li><b>Clipped audio:</b> leave <i>Fix clipping</i> on Auto. It rebuilds the flattened peaks. Very heavy clipping can only be improved, not fully restored.</li>
<li><b>Echoey room:</b> raise <i>Echo / room removal</i> and set <i>Room decay</i> (Advanced) to roughly how long the echo lasts. Then add a little reverb back with <i>Add space</i> so the voice sits naturally, like a film mix.</li>
<li><b>Hiss and camera noise:</b> raise <i>Noise reduction</i>. If it sounds watery, lower it - the AI engine is gentler than the built-in one.</li>
<li><b>Hum:</b> choose 50 Hz (South Africa, Europe) or 60 Hz (Americas).</li>
<li>Drag across the waveform to select a region. You can loop it, trim, cut, fade, silence or gain it, and the preview focuses on it.</li>
</ul>
<h3>Output modes</h3>
<ul>
<li><b>Mono / Stereo</b> - standard.</li>
<li><b>Dolby Surround (Lt/Rt stereo)</b> - a matrix-encoded stereo file that Dolby Surround / Pro Logic style decoders can open into surround.</li>
<li><b>Dolby Digital 5.1</b> - real 6-channel mix: dialogue in the centre, room and reverb in the rear speakers. Save as AC-3 or E-AC-3, or as video with the new audio.</li>
</ul>
<h3>Loudness</h3>
<p>Measured with the ITU-R BS.1770 method (LUFS). Presets: cinema/streaming -27, broadcast -24 / -23, podcast -16, loud online -14. A look-ahead limiter keeps peaks under your ceiling.</p>
<h3>Keyboard</h3>
<p>Space = play/pause · A / B = original / cleaned · Ctrl+O = open · Ctrl+E = export · Ctrl+Z / Ctrl+Y = undo / redo · Mouse wheel = zoom · Shift+wheel = scroll · Double-click waveform = select all</p>
<p style='color:#8f98a8'>Version {APP_VERSION}. Uses ffmpeg and DeepFilterNet (both open source) which ship inside this app.</p>
"""


# ======================================================================== main window
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}")
        self.resize(1360, 860)
        self.setAcceptDrops(True)
        ico = app_dir() / "assets" / "icon.png"
        if ico.exists():
            self.setWindowIcon(QIcon(str(ico)))
        self.store = Store()
        self.store.load(cfg.preset_settings("Cinema Dialogue (Hollywood)"))
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.studio = StudioTab(self.store, self)
        presets_bar = PresetBar(self.store)
        self.batch = BatchTab(self.store, self, presets_bar)
        self.tabs.addTab(self.studio, "🎚  Studio")
        self.tabs.addTab(self.batch, "📦  Batch")
        guide = QTextBrowser()
        guide.setHtml(GUIDE)
        guide.setOpenExternalLinks(True)
        self.tabs.addTab(guide, "❓  Guide")
        self._menus()
        self.tool_label = QLabel()
        self.statusBar().addPermanentWidget(self.tool_label)
        self._tools()
        self.statusBar().showMessage("Ready")

    def _menus(self):
        mb = self.menuBar()
        f = mb.addMenu("&File")
        for txt, key, fn in (("Open file…", "Ctrl+O", self.open_dialog), ("Export…", "Ctrl+E", self.studio.export_dialog),
                             ("Add files to batch…", "", lambda: (self.tabs.setCurrentIndex(1), self.batch.add_files())),
                             ("Quit", "Ctrl+Q", self.close)):
            a = QAction(txt, self)
            if key:
                a.setShortcut(key)
            a.triggered.connect(lambda _=False, fn=fn: fn())
            f.addAction(a)
        e = mb.addMenu("&Edit")
        for txt, key, fn in (("Undo", "Ctrl+Z", self.studio.do_undo), ("Redo", "Ctrl+Y", self.studio.do_redo)):
            a = QAction(txt, self)
            a.setShortcut(key)
            a.triggered.connect(lambda _=False, fn=fn: fn())
            e.addAction(a)
        h = mb.addMenu("&Help")
        a = QAction("Quick guide", self)
        a.triggered.connect(lambda: self.tabs.setCurrentIndex(2))
        h.addAction(a)
        a = QAction("About", self)
        a.triggered.connect(lambda: QMessageBox.about(self, APP_NAME, f"{APP_NAME} {APP_VERSION}\n\nFree, offline audio "
                                                                      "cleanup and cinema finishing.\nPowered by ffmpeg and DeepFilterNet."))
        h.addAction(a)

    def _tools(self):
        st = engine.tool_status()
        ai = "AI denoiser ready" if st["deepfilter"] else "AI denoiser not found (built-in used)"
        au = "audio output ready" if self.studio.player.available else "audio output unavailable"
        self.tool_label.setText(f"{ai}   ·   ffmpeg {'ready' if st['ffmpeg'] else 'MISSING'}   ·   {au}   ")

    def open_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open audio or video", "", MEDIA_FILTER)
        if p:
            self.tabs.setCurrentIndex(0)
            self.studio.load(p)

    def busy(self, msg):
        self.statusBar().showMessage(msg)
        QApplication.setOverrideCursor(Qt.BusyCursor)

    def idle(self):
        QApplication.restoreOverrideCursor()
        self.statusBar().showMessage("Ready")

    def status(self, msg):
        self.statusBar().showMessage(msg)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if not paths:
            return
        if self.tabs.currentIndex() == 1 or len(paths) > 1 or Path(paths[0]).is_dir():
            self.tabs.setCurrentIndex(1)
            self.batch.add_paths(paths)
        else:
            self.tabs.setCurrentIndex(0)
            self.studio.load(paths[0])

    def closeEvent(self, e):
        self.studio.shutdown()
        super().closeEvent(e)


def run():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(STYLE)
    w = MainWindow()
    w.show()
    if len(sys.argv) > 1 and Path(sys.argv[1]).exists():
        w.studio.load(sys.argv[1])
    sys.exit(app.exec())
