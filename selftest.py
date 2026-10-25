"""Full user-path self-test: launch via main.py semantics, screenshot at
each stage, verify splash/overlay/fullscreen/borders with pixel evidence."""
import os, sys, time, ctypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["PATH"] = r"D:\ffmpeg\bin" + os.pathsep + os.environ["PATH"]

# replicate main.py run() exactly (import as module to share code path)
t0 = time.time()
from PyQt6.QtWidgets import QApplication, QSplashScreen
from audio_player.app import create_app
app = create_app()
t_app = time.time() - t0

from audio_player.ui.tooltip_gate import install_tooltip_gate
install_tooltip_gate(app)

from PyQt6.QtCore import Qt as _Qt
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont
_sp = QPixmap(360, 200)
_sp.fill(_Qt.GlobalColor.transparent)
_p = QPainter(_sp); _p.setRenderHint(QPainter.RenderHint.Antialiasing)
_p.setPen(_Qt.PenStyle.NoPen); _p.setBrush(QColor(24,24,27,245))
_p.drawRoundedRect(0,0,360,200,14,14); _p.end()
splash = QSplashScreen(_sp)
splash.setAttribute(_Qt.WidgetAttribute.WA_TranslucentBackground, True)
splash.show(); app.processEvents()
splash_shown_at = time.time() - t0

from audio_player.main_window import MainWindow
t_mw0 = time.time()
window = MainWindow()
t_mw = time.time() - t_mw0
window.show()
splash.finish(window)

SHOT = r"C:\Users\vb085\Desktop\VBP"
def shot(name):
    app.processEvents(); time.sleep(0.2); app.processEvents()
    window.grab().save(os.path.join(SHOT, name))

def pump(s):
    end = time.time() + s
    while time.time() < end:
        app.processEvents(); time.sleep(0.02)

shot("st_01_splash_moment.png")   # right after show
pump(2)
lines = [
    f"create_app: {t_app:.2f}s | MainWindow ctor: {t_mw:.2f}s | splash shown at {splash_shown_at:.2f}s",
]
# 1. did initial load need overlay? (warm store → correctly skipped)
lines.append(f"initial_load_done: {window._initial_load_done} at {round(time.time()-t0,2)}s")
pump(2)
shot("st_02_main.png")

# 2. immersive + fullscreen: corners + border lines
real = r"D:/1音乐/Alan walker/Different World/04. Alan Walker - Lily.flac"
window._playlist.add_files([real])
window._playback_ctrl.play_track_at(window._playlist.count - 1)
pump(2)
window._show_np_page(); pump(1.5)
shot("st_03_hifi_windowed.png")
window._toggle_fullscreen(); pump(2)
shot("st_04_fullscreen.png")
img = window.grab().toImage()
w, h = img.width(), img.height()
corners = [img.pixelColor(2,2).getRgb()[:3], img.pixelColor(w-3,2).getRgb()[:3],
           img.pixelColor(2,h-3).getRgb()[:3], img.pixelColor(w-3,h-3).getRgb()[:3]]
edges = [img.pixelColor(w//2, 0).getRgb()[:3], img.pixelColor(0, h//2).getRgb()[:3],
         img.pixelColor(w-1, h//2).getRgb()[:3], img.pixelColor(w//2, h-1).getRgb()[:3]]
lines.append(f"fullscreen corners: {corners}")
lines.append(f"fullscreen edge-mids: {edges}")
# 3. collapse from fullscreen
window._collapse_hifi(); pump(1.5)
shot("st_05_after_collapse.png")
lines.append(f"after collapse: fullscreen={window.isFullScreen()} stack={window._hifi_overlay.currentIndex()}")
open("st.log", "w", encoding="utf-8").write("\n".join(lines))
window.close()
print("SELFTEST DONE")
