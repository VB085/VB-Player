# VB Player

跨平台 HIFI 音乐播放器，基于 PyQt6 + GStreamer，为高解析度音频回放设计。支持 Windows、macOS、Linux。

## 功能

- **跨平台** — Windows (WASAPI/ASIO)、macOS (CoreAudio)、Linux (ALSA/PipeWire)
- **独占模式** — Windows ASIO/WASAPI 独占、macOS CoreAudio Exclusive、Linux ALSA hw: 直通 DAC，bit-perfect 输出
- **DSD 软解** — 支持 .dsf / .dff 文件，自动解码为 PCM 输出
- **10 段均衡器** — 实时调节，基于 GStreamer equalizer-nbands
- **全屏歌词** — 平滑动画歌词显示，支持 LRC 时间轴歌词
- **多语言** — 简体中文、繁體中文、English、日本語
- **明暗主题** — 纯黑/纯白双主题，6 种强调色
- **音频输出流程** — 实时显示格式、采样率、位深度、声道、SRC 状态
- **播放列表管理** — 文件夹导入、M3U 导入导出
- **专辑视图** — 网格/列表双视图，自动按专辑归类
- **频谱可视化** — 实时频谱 + 波形预览
- **歌词叠加层** — 频谱区上方半透明歌词显示

## 系统要求

- Python 3.10+
- GStreamer 1.28+（含 good/bad/ugly 插件）
- PyQt6

### Windows

```powershell
# 安装 GStreamer — 从 https://gstreamer.freedesktop.org/download/ 下载 MSVC 版
# 需安装 runtime + development 两个包

pip install pyqt6 mutagen PyGObject
```

支持 WASAPI Shared/Exclusive 和 ASIO 独占模式。ASIO 需额外安装 GStreamer ASIO 插件。

### macOS

```bash
# Intel Mac
brew install gstreamer gst-plugins-good gst-plugins-bad gst-plugins-ugly
pip install pyqt6 mutagen PyGObject

# Apple Silicon Mac（同一条命令，Homebrew 自动处理架构）
brew install gstreamer gst-plugins-good gst-plugins-bad gst-plugins-ugly
pip install pyqt6 mutagen PyGObject
```

支持 CoreAudio Shared/Exclusive 模式。如手动安装 GStreamer，请下载对应架构（x86_64 或 arm64）的 `.pkg` 安装包。

### Linux

```bash
# Ubuntu/Debian
sudo apt install python3-pyqt6 gir1.2-gst-plugins-bad-1.0 \
  gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
  gstreamer1.0-plugins-ugly gstreamer1.0-alsa

# Arch
sudo pacman -S python-pyqt6 gst-plugins-good gst-plugins-bad gst-plugins-ugly gst-plugin-alsa
```

## 运行

```bash
python main.py
```

## 支持格式

MP3, FLAC, WAV, OGG, Opus, AAC, M4A, WMA, AIFF, APE, WavPack, DSD (.dsf/.dff), Musepack, Speex

## 许可证

GNU General Public License v3.0 — 详见 [LICENSE](LICENSE)

本项目使用 PyQt6 (GPLv3) 和 GStreamer (LGPLv2+)。分发或修改须遵循 GPLv3 条款。
