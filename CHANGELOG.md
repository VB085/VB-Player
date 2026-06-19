# 更新日志

## v0.6 (2026-06-19)

### 重大重构

- **平台抽象层** — 新增 `platform/` 模块，`CapabilityMatrix` + `UIBehaviorPolicy` 数据驱动平台决策，替代硬编码 `sys.platform`
  - Linux: Wayland CSD 支持、gsettings 系统主题追踪、AppIndicator 托盘、D-Bus 通知
  - macOS/Windows: 预留 vibrancy/Mica 材质、系统 accent 跟随等 stubs
- **主窗口瘦身** — 拆出 `TitleBar`、`TrayManager`、`ShortcutManager` 独立模块，`main_window.py` 从 1721 行降至 ~1550 行
- **Controller 解耦** — `SettingsController` 不再直接导入 widget 类，改为信号驱动
- **消除重复代码** — `format_duration`、`format_size`、`is_light_mode`、`FlowLayout`、`AlbumTrackModel` 等收归 `ui/utils.py` 和 `ui/shared.py`

### 新功能

- **Apple Music 风格播放界面** — 底部常驻迷你播放条，点击弹起铺满 HiFi 播放页（模糊封面背景 + 大封面 + 歌词 + 完整控制）
- **专辑封面动态取色** — 切换曲目时自动提取封面主色调，界面强调色跟随变化
- **单实例锁** — fcntl 内核级文件锁，防止重复启动
- **原生窗口装饰** — Wayland 下使用 compositor 标题栏（CSD），不再强制 frameless

### UI 改进

- **暗色主题现代化** — 纯黑 `#000` → GNOME Adwaita-dark 色系 `#242424`，圆角增大，接近系统原生应用
- **亮色主题适配** — 修复全屏歌词、波形、均衡器在亮色模式下仍显示暗色的问题
- **布局重排** — 移除右侧固定面板，内容区拉满全宽；播放控制移到底部播控条
- **侧边栏加文字标签** — 导航图标旁显示文字
- 所有弹窗在 CSD 平台使用系统原生标题栏（设置、标签编辑、歌单编辑、输出详情）
- 进度条回归底部播控条，支持迷你拖动

### 国际化

- i18n 翻译字典从 Python 源码拆为独立 JSON 文件（zh_CN/zh_TW/en/ja），非开发者可直接编辑

### 修复

- bootstrap venv 检测改用 `sys.prefix`，修复 Python 符号链接导致的跳转失败
- QSS `@ACCENT_DARKER@` 占位符缺失导致样式解析警告
- 主窗口关闭后 tray_quit 方法命名不一致
- 沉浸界面歌词滚动性能优化（背景缓存、局部刷新、按钮样式移出 paintEvent）

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
