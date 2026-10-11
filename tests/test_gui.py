"""Headless GUI smoke test (QT_QPA_PLATFORM=offscreen): load, preview, edit, batch, export, screenshots."""
import os, sys, time, tempfile
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import numpy as np, soundfile as sf
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop, QTimer
from mhous3 import app as A, engine
from test_engine import messy_clip

def wait(cond, timeout=60):
    t = time.time()
    while not cond() and time.time() - t < timeout:
        QApplication.processEvents(QEventLoop.AllEvents, 50)
    assert cond(), "timeout"

qa = QApplication([]); qa.setStyleSheet(A.STYLE)
w = A.MainWindow(); w.resize(1360, 860); w.show()
d = Path(tempfile.mkdtemp()); src = d / "rough.wav"; sf.write(src, messy_clip(12), 48000)
st = w.studio
st.load(str(src)); wait(lambda: st.audio is not None)
wait(lambda: st.preview is not None and st.task is None)
print("preview info:", {k: (round(v, 2) if isinstance(v, float) else v) for k, v in st.preview[1].items()})
st.wave.view.sel = (48000 * 2, 48000 * 5); st.e_fade_in(); st.e_gain.__self__  # edit calls
n0 = len(st.audio); st.e_trim(); assert len(st.audio) == 48000 * 3, len(st.audio); st.do_undo(); assert len(st.audio) == n0
st.btn_spec.setChecked(True); st.wave.view.update(); w.grab().save(str(d / "spec.png")); st.btn_spec.setChecked(False)
wait(lambda: st.task is None and st.preview is not None)
st.set_ab("A"); st.set_ab("B")
w.grab().save(str(d / "studio.png"))
w.tabs.setCurrentIndex(1); w.batch.add_paths([str(src)]); w.grab().save(str(d / "batch.png"))
w.store.set("out_channels", "Dolby Digital 5.1"); w.store.set("out_format", "Dolby Digital AC-3")
w.batch.same.setChecked(False); w.batch.out_dir = str(d / "out"); w.batch.start()
wait(lambda: w.batch.btn_start.isEnabled(), 120)
print("batch:", [w.batch.table.item(0, c).text() for c in (1, 2, 3)])
assert w.batch.table.item(0, 1).text() == "Done ✓"
w.tabs.setCurrentIndex(2); w.grab().save(str(d / "guide.png"))
import shutil; shutil.copy(d / "studio.png", "/tmp/studio.png"); shutil.copy(d / "batch.png", "/tmp/batch.png"); shutil.copy(d / "spec.png", "/tmp/spec.png")
w.close(); print("GUI OK")
