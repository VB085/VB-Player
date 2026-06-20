# 更新日志

## v0.6.2 (2026-06-20)

### 新功能
- 悬浮胶囊播控栏（Apple Music 风格），环形/线性进度可选
- 专辑和歌单详情页统一 PlaylistView（封面缩略图、发光高亮、拖拽排序）
- 当前曲目高亮风格可选：封面发光边框 / 左侧竖线
- 搜索框改为玻璃风格常显（5 页面统一）
- 排序/视图切换按钮统一 accent QSS
- HiFi 页面切歌 500ms crossfade 过渡
- 输出详情弹窗重设计（QFormLayout 对齐 + accent 边框）
- 网络页玻璃质感 + 强调色跟随
- 沉浸页点击质量文字弹出输出详情
- 关闭到托盘（设置-通用可开关）
- 强调色首次播放从灰渐入

### 修复
- 双击播放逻辑重写（消除重复加载卡顿）
- 元数据加载 20ms 节流（消除洪水卡顿）
- GStreamer pipeline 清理 50ms 上限
- 全部歌曲/专辑/收藏/歌单双击播放统一修复
- 播放指示条跨页面全局同步
- 引擎 `play()` 不再跳过状态过渡
- 侧栏高亮改为 inline style 跟随动画
- DLNA/gst-launch 日志冗长抑制

### 技术变更
- 强调色动画重写：单一路径，palette-only 每帧，QSS 仅动画结束时更新
- QThread 全部加 parent 防 GC 提前析构（最终修复 QThread 崩溃）
- `beginInsertRows` → `beginResetModel`（Qt 6.7 proxy bug 绕行）
- `_MetaLoader` 改为持久 QThread + Queue 模式
- `on_anim_tick` 回调恢复（轻量通知，不调全局 QSS）

## v0.6.1 (2026-06-20)

### 新功能
- 底栏重设计：对称布局，更大控件，进度条 4px
- 播放列表每行 40×40 封面缩略图，行高 58px
- 窗口材质系统：无/玻璃/毛玻璃，带不透明度和纹理滑块
- 动态强调色：从专辑封面提取色，600ms 渐变过渡，可开关
- 设置新增"账户"标签（头像、显示名称、资料库统计）
- KDE Plasma 真毛玻璃支持（_KDE_NET_WM_BLUR_BEHIND_REGION）

### 修复
- 标题栏/材质设置即时生效
- QThread 生命周期全部修好（不再崩溃）
- 播放指示条不灭的 bug
- 播放列表当前行重绘

### 技术变更
- QThreadPool → 持久单线程 _MetaLoader
- QThread 全部加 parent 防 GC 提前析构
- PyQt6 降级到 6.7.0（Qt 6.11 线程回归 bug）

## v0.6 (2026-06-19)

### 新功能

- 底部常驻迷你播放条，点击弹起铺满 HiFi 播放页，模糊封面背景 + 大封面 + 歌词 + 完整播放控制
- 专辑封面动态取色，切换曲目时自动提取封面主色调，界面强调色跟随变化
- 单实例锁，防止重复启动
- Wayland 下使用系统原生标题栏，不再强制无边框窗口
- 平台抽象层，代码自动适配 Linux / macOS / Windows 特性，无需手动判断系统

### 界面

- 暗色主题改用 GNOME Adwaita 配色，圆角增大，更接近系统原生应用
- 修复亮色模式下全屏歌词、波形图、均衡器等组件仍显示暗色的问题
- 移除右侧固定面板，内容区拉满全宽，播放控制移到底部播控条
- 侧边栏导航图标旁增加文字标签
- 所有弹窗使用系统原生标题栏

### 国际化

- 翻译字典从源码拆为独立 JSON 文件，非开发者可直接编辑和贡献翻译

### 修复

- 修复系统 Python 下无法自动跳转 venv 的问题
- 修复样式解析警告
- 优化歌词滚动性能

### 架构

- 主窗口拆分为 TitleBar、TrayManager、ShortcutManager 等独立模块
- Controller 不再直接依赖 Widget，改为信号驱动
- 公共工具函数和类型收归统一模块，消除重复代码

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
