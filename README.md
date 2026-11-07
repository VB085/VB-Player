# VB Player

[![Version](https://img.shields.io/badge/version-0.7.0-7c3aed)](https://github.com/VB085/VB-Player)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Linux-10b981)]()

Linux HiFi 音乐播放器，基于 PyQt6 + GStreamer，为高解析度音频回放设计。

<p align="center">
  <img src="https://github.com/VB085/VB-Player/raw/main/assets/screenshot.png" alt="screenshot" width="800"/>
</p>

## 功能亮点

### 音频引擎
- **Linux 原生后端** — ALSA / PipeWire，bit-perfect 直通
- **独占模式** — DAC 直通，无重采样
- **DSD 解码** — .dsf / .dff 支持，PCM 软解 / Native 硬解 / DoP
- **10 段参数均衡器** — 6 组预设，实时调节
- **ReplayGain** — 音量标准化
- **无缝播放** — 曲末预加载，零间隔过渡
- **DLNA/UPnP** — 局域网设备发现与串流

### 界面
- **沉浸式播放页** — 封面模糊背景 + 切歌 crossfade 过渡
- **动态强调色** — 从专辑封面提取主色，800ms 渐变扩散到全界面（可开关）
- **悬浮胶囊播控栏** — 环形/线性进度可选
- **窗口材质** — 玻璃半透明 / 毛玻璃噪点纹理，不透明度+纹理强度可调
- **暗/亮双主题** — 6 种强调色，标题栏风格可选
- **多语言** — 简体中文 / 繁體中文 / English / 日本語

### 播放列表
- 40×40 封面缩略图 + 发光高亮
- 拖拽排序（收藏 / 歌单）
- 搜索过滤 + 多字段排序
- 右键菜单：收藏、添加到歌单、编辑标签

### 专辑 & 歌单
- 网格/列表双视图，自动按专辑归类
- 详情页：封面、元数据、完整曲目列表
- 歌单：新建/编辑/删除/搜索

### 歌词
- LRC 时间轴 + 滚动动画
- 在线搜索 (LRCLIB + 自定义 API），自动保存 .lrc
- 全屏歌词模式（独立窗口）
- 双语翻译显示

### 系统集成
- MPRIS2 系统媒体控制
- 系统托盘，关闭到托盘可选
- DLNA 设备发现与输出切换
- 内嵌 HTTP 服务器（局域网串流）

## 快速开始

### Linux

```bash
# Ubuntu/Debian
sudo apt install python3-pyqt6 python3-gi gir1.2-gstreamer-1.0 \
  gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
  gstreamer1.0-plugins-ugly gstreamer1.0-alsa

pip install pyqt6 mutagen numpy
python main.py
```

```bash
# Arch
sudo pacman -S python-pyqt6 gst-plugins-good gst-plugins-bad gst-plugins-ugly
pip install pyqt6 mutagen numpy
python main.py
```

## 从源码构建

```bash
git clone https://github.com/VB085/VB-Player.git
cd VB-Player

# 创建 venv 并安装依赖
python3 -m venv --system-site-packages .venv
.venv/bin/pip install pyqt6 mutagen numpy pyinstaller Pillow

# 直接运行
.venv/bin/python main.py

# PyInstaller 打包（目录模式，约 585M）
./build.sh

# 生成 .deb 和 .AppImage
./package.sh
```

**构建输出：**
- `dist/VB Player/` — PyInstaller 目录包，可直接运行
- `dist/vb-player_<version>_<arch>.deb` — Debian/Ubuntu 安装包
- `dist/VB_Player-v<version>-<arch>.AppImage` — 通用 Linux 便携包（需 `appimagetool`）

**AppImage 工具安装：**
```bash
wget https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x appimagetool-x86_64.AppImage
sudo mv appimagetool-x86_64.AppImage /usr/local/bin/appimagetool
```

## 直接安装

下载 [Releases](https://github.com/VB085/VB-Player/releases) 中的 `.deb` 或便携 `.tar.gz` 即可运行。

## 支持格式

MP3 · FLAC · WAV · OGG · Opus · AAC · M4A · ALAC · WMA · AIFF · APE · WavPack · DSD (.dsf/.dff) · Musepack · Speex

## 许可证

GNU General Public License v3.0 — 详见 [LICENSE](LICENSE)

本项目使用 PyQt6 (GPLv3) 和 GStreamer (LGPLv2+)。分发或修改须遵循 GPLv3 条款。
