# 更新日志

## v0.3 (2026-05-29)

### 新功能

- **标签编辑** — 右键菜单"编辑标签"，弹出对话框修改标题/艺术家/专辑/年份/流派/曲目号等元数据，支持 MP3 (ID3)、FLAC/OGG/Opus (Vorbis)、M4A/AAC (MP4) 格式
- **歌单浏览** — 全新歌单管理页面，网格/列表视图切换，新建、编辑、删除歌单，歌单详情页
- **在线歌词** — LRCLIB 歌词搜索，自定义 API 接口，歌词自动保存到本地，翻译歌词显示
- **歌词解析** — LRC 文件解析器，支持逐行同步歌词
- **系统媒体控制** — Linux: MPRIS2 集成，Windows: SMTC 集成
- **macOS 支持** — CoreAudio 引擎 (osxaudiosink)
- **网络页面框架** — SMB 网络扫描器，网络音乐浏览页面
- **启动引导** — bootstrap 模块，自动检测并配置运行环境

### UI 改进

- 统一全部歌曲/收藏/专辑详情/歌单详情的曲目列表布局（MARGIN、竖杠、编号、文字位置）
- 编号右对齐，视觉居中于主题色竖杠与歌曲名称之间
- 无边框窗口拖拽调整大小 (FramelessResizeMixin)
- 搜索过滤组件
- 主题辅助工具模块 (theme_helpers)，统一菜单和按钮样式
- 图标模块 (icons)
- 全屏歌词窗口优化
- 歌词覆盖层动画
- 输出规格栏增强
- 侧边栏改进

### 架构重构

- 提取 PlaybackController / LibraryController / SettingsController，MainWindow 瘦身
- 歌曲库管理器 (LibraryManager)：JSON 持久化收藏夹与歌单
- 元数据写入支持 (write_tags)，LRU 缓存自动失效
- 均衡器模块独立 (EqualizerManager)
- 音频分析器增强：歌词提取、波形 FFT、频谱分析
- 歌词提供者架构 (LyricsProvider / LyricsFetcher)
- 移除废弃的 SlidePanel 和 animations 模块

### 测试

- 新增 write_tags 测试套件（12 个测试覆盖 MP3 写入/清除/错误处理/缓存驱逐）
- 新增 album_manager、equalizer、library、playlist、types 测试
- 总计 92 个测试全部通过

### 国际化

- 完整四语言支持：简体中文、繁體中文、English、日本語
- 标签编辑、歌单管理、在线歌词等新功能全部纳入 i18n

## v0.2 (2026-05-15)

- 跨平台支持：Linux (ALSA/PipeWire)、Windows (WASAPI/ASIO)
- DSD 原生解码与 DoP 支持
- 可视化增强：柱状图/折线图/圆形频谱
- QSS 主题系统与强调色
- 专辑网格视图与封面管理
- 均衡器预设
- 元数据面板
- 窗口圆角与透明背景

## v0.1 (2026-05-01)

- 初始版本 — GStreamer 音频播放器
- 基础播放/暂停/上下曲
- 播放列表管理
- 深色主题
