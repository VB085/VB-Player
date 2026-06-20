# VB Player — 功能详细列表 v0.6.2

## 播放引擎

| 功能 | 详情 |
|---|---|
| GStreamer 后端 | Linux: ALSA (独占) / PipeWire+PulseAudio (共享)。Windows: WASAPI。macOS: CoreAudio。 |
| 独占模式 | ALSA `hw:X,Y` 直通。切换时重建 pipeline + 等 GStreamer 状态同步。 |
| DSD 解码 | PCM 软解 / Native 硬解 / DoP，不支持时自动回退。设置中可选。 |
| ReplayGain | 读取文件标签自动音量标准化，开关在高级设置。 |
| 无缝播放 | 曲末 2s 预加载下一首 pipeline，EOS 瞬间切换。 |
| 均衡器 | 10 段参数 EQ ±12dB。预设 6 组（Flat/Pop/Rock/Jazz/Classical/Custom）。 |
| DLNA/UPnP | SSDP 设备发现 → 设备列表 → 切换输出 → AVTransport 控制。 |
| HTTP 服务器 | 内嵌 `ThreadingHTTPServer`，127.0.0.1 随机端口，供 DLNA 串流。 |
| MPRIS2 | Linux 系统媒体控制：播放/暂停/上下曲/进度/封面。DBus 接口。 |
| 系统托盘 | 最小化到托盘，图标 + 右键菜单（播放控制、显示/退出）。 |
| 音频分析器 | `_DecoderWorker` QThread，`gst-launch` 解码 → numpy FFT 频谱 + 波形。 |

## 界面系统

### 窗口

| 功能 | 详情 |
|---|---|
| 主题 | 暗 (Adwaita-dark) / 亮，全局 QPalette + QSS 注入。`QSettings: theme_mode` |
| 强调色 | 6 种预设（purple/blue/green/orange/pink/red）+ 动态 + 系统跟随。`QSettings: accent` |
| 动态强调色 | 从专辑封面提取主色 → 12 步 QTimer 动画（600ms cubic ease-out）→ 全局 QSS + QPalette + delegate 同步。每帧更新 `_dynamic_accent` + `app.setStyleSheet()` + `app.setPalette()` + `on_anim_tick` 回调链。`QSettings: dynamic_accent_enabled` |
| 窗口材质 | 无 / 玻璃（半透明 84-100%）/ 毛玻璃（半透明 92-100% + SoftLight 噪点）。`QSettings: window_material / material_alpha / material_texture` |
| 毛玻璃噪点 | numpy `integers(0,256,(h,w))` → QImage Grayscale8 → SoftLight 混合 → 纹理强度 0-30% 可调 |
| KDE 真毛玻璃 | `_KDE_NET_WM_BLUR_BEHIND_REGION` X11 atom。KWinBlurEnabler ctypes 调 libX11。仅 KDE X11。 |
| 标题栏 | 无边框（自绘 TitleBar + 圆角遮罩）/ CSD（合成器装饰）/ 原生。`QSettings: window_titlebar` |
| 窗口圆角 | 0-20px 可调。frameless 下 QPainterPath clip + QPixmap mask。`QSettings: border_radius` |
| UI 圆角 | 0-24px，控制按钮/卡片/滑块。`QSettings: ui_radius` |
| Wayland 适配 | 自动检测 `WAYLAND_DISPLAY`，默认 CSD。frameless + WA_TranslucentBackground 在 Wayland 也可用但需合成器支持。 |

### 播控栏

| 功能 | 详情 |
|---|---|
| 完整底栏 | 84px 高，左封面 56×56 + 曲名/艺人 12pt/10pt，中控键（⏮48 ⏯56 ⏭48），右时间 11pt mono。4px 顶部进度条。左右 min-width=220 对称。 |
| 悬浮胶囊 | Apple Music 风格。72px 高，max 580px 宽，居中浮于内容区上方。玻璃背景 rgba 16px 圆角。左封面 40px，中曲名·艺人，右 ⏯40 ⏭36。顶部 4px 进度线。点空白 → HiFi。`QSettings: playback_bar_style` |
| 胶囊进度样式 | 顶边细线 / 绕边框一圈 dash。`QSettings: pill_progress_style` |
| 胶囊定位 | `_body` 内绝对定位，resizeEvent + showEvent 自动追踪。HiFi 覆盖时自动隐藏。 |
| HiFi 展开 | 底栏→全屏沉浸页，350ms slide-up 动画 (OutCubic)。收起 slide-down。 |

### 播放列表视图

| 功能 | 详情 |
|---|---|
| 行高 | 58px。封面 40×40 (r=6) 占位或缩略图。 |
| 缩略图 | `CoverDataRole` 读取 `meta.cover_data` → QPixmap 缩放到 40px → 圆角 clip 缓存 500 条 LRU。 |
| 文本 | 曲名 12pt bold/accent，艺人·时长 10pt muted。EllideRight 截断。 |
| 当前曲目高亮 | 封面发光边框（外层 alpha=35 柔光 + 内层 alpha=80 环）/ 左侧竖线 (4px r=2)。`QSettings: current_track_highlight` |
| 全局指示同步 | 模块变量 `_current_file`，所有 PlaylistView 实例按路径匹配，跨页面同步。 |
| 拖拽排序 | `PlaylistManager.moveRows` + `PlaylistFilterProxy.moveRows` 索引映射。`InternalMove` + `DragEnabled`。收藏和歌单可用。 |
| 搜索过滤 | `QSortFilterProxyModel` → `QRegularExpression` 匹配标题/艺人/专辑。搜索框玻璃风格 200px 常显。 |
| 排序 | 默认/标题/艺人/时长。角色映射到 `PlaylistManager.*Role`。 |
| 右键菜单 | 收藏/取消收藏、添加到歌单（含新建）、播放下一首、编辑标签(单文件)。 |
| 选中清除 | 点空白 `clearSelection()` + `mousePressEvent`。 |

### 专辑

| 功能 | 详情 |
|---|---|
| 网格/列表 | 专辑卡 172px。封面 + 名称 + 艺人。右键切换视图。 |
| 详情页 | 上下分区。上：封面 170px + 名称/艺人 + 元数据 chips。下：曲目列表（PlaylistView 统一组件）。← 圆形返回键 32px。 |
| 卡片 loading | 异步读取首曲目封面 → 卡片显示。 |

### 歌单

| 功能 | 详情 |
|---|---|
| 网格/列表 | PlaylistCardWidget 同专辑卡风格。右键编辑/删除。 |
| 详情页 | 封面 + 名称 + 描述 + 元数据 chips + 曲目列表（PlaylistView）。← 圆形返回键 + 编辑按钮。 |
| 新建/编辑 | PlaylistEditDialog：名称/描述/封面。可更改。 |
| 搜索过滤 | 常显搜索框，`PlaylistGridView.filter(text)` 显示/隐藏卡片。 |

### 收藏

| 功能 | 详情 |
|---|---|
| 独立列表 | `PlaylistManager` + `PlaylistFilterProxy` + `PlaylistView`。右键收藏/取消收藏。 |
| 持久化 | `LibraryManager._favorites: set[str]` → JSON 文件。`favoritesChanged` 信号刷新。 |
| 计数 | 收藏页面标题显示歌曲数量。 |

### 沉浸播放页 (HiFi)

| 功能 | 详情 |
|---|---|
| 模糊背景 | 封面图 → `_blur_pixmap()`（80×80 缩略 → 3 遍 box blur → SmoothTransformation 放大）→ 全窗铺满 + 40% 黑色遮罩。 |
| 切歌过渡 | 旧背景存 `_old_cached_bg`，新背景重算 → `QPropertyAnimation` (500ms OutCubic) → `_bg_fade_progress` 双图混合。 |
| 封面 | 默认 380px 居中，带阴影。歌词模式缩小到 240px 左移。 |
| 进度条 | 底部圆角 groove + accent fill。可点击/拖拽 seek。 |
| 控件 | 中间播放/暂停 + 上下曲按钮 + 收藏。右上：全屏/歌词/收起。质量文字：单击弹出 `_OutputDetailDialog`。 |
| 歌词 | 当前行 accent 高亮，上下行渐变淡出。QTimer 50ms 滚动。全屏模式独立窗口。 |
| 在线歌词 | `LyricsFetchWorker` QThread 调 LRCLIB API → LRC 解析。自定义 API 支持。缓存 + 自动保存 `.lrc`。 |
| 强调色跟随 | `refresh_accent()` 每帧更新 `_accent` + `update()`。 |

### 输出详情弹窗

| 功能 | 详情 |
|---|---|
| 源文件区 | 格式/采样率/位深/声道。`QFormLayout` 标签右对齐。 |
| 解码链路 | 原始采样率 → 解码方式 (DSD Native/DoP/PCM) → 实际输出率/格式。 |
| 输出设备 | 设备名/音频 API/驱动/工作模式/延迟。 |
| 外观 | 拖拽栏 (40px) + 滚动体。frameless 圆角遮罩。QSS `#outputGroup` / `#outputLabel` / `#outputValue`。分组框边框: `@ACCENT@` 跟随。 |

### 网络页

| 功能 | 详情 |
|---|---|
| 流媒体 | URL 输入 → Enter 或播放按钮。http/https 自动补齐。历史列表双击回放。 |
| 输出设备 | 设备列表，当前设备 ✓ 标记，单击切换。`DeviceRegistry` 自动发现。 |
| NAS | SMB 服务器/用户名/密码 → 连接 → 共享文件夹树。双击浏览。 |
| UI | 分组框玻璃 bg + accent 边框 10px 圆角。输入/列表 rgba 底。`refresh_theme()` 注册到 `on_anim_tick`。 |

### 设置对话框

| 标签 | 内容 |
|---|---|
| 通用 | 语言选择（简中/繁中/英/日）。确定按钮 (accent 色)。 |
| 账户 | 头像（点击选图 → 128px base64 存 QSettings）。显示名称（标题栏显示 "VB Player — 名字"）。资料库统计（歌曲/专辑/歌单数，来自 MainWindow）。 |
| 外观 | 主题模式（暗/亮）。强调色（6 色圆形 Swatch）。动态强调色开关。窗口/UI 圆角 SpinBox。标题栏风格（ComboBox + 重启提示）。窗口材质（ComboBox + 不透明度滑块 + 纹理滑块）。播控栏样式（完整底栏/悬浮胶囊）。胶囊进度样式（顶线/绕圈）。当前曲目高亮风格（封面发光/左侧竖线）。专辑封面圆角开关。 |
| 歌词 | 启用开关。行间距/全屏行间距。全屏字号/字间距。音频规格信息开关。在线歌词开关 + LRCLIB/自定义 API/Token。自动保存开关。测试连接按钮。 |
| 播放 | 可视化模式（柱状图/折线图/圆形）。默认音量 (0-100%)。均衡器（10 段滑块 + 预设菜单 + 启用开关）。独占模式开关 + 设备选择。DSD 解码模式。ReplayGain 开关。无缝播放开关。 |
| 高级 | 运行日志开关。 |
| 关于 | 版本号 + 应用完整性检查。 |

### 侧栏

| 功能 | 详情 |
|---|---|
| 导航 | 7 项：歌曲/专辑/收藏/歌单/网络/管理/设置。图标+文字行，当前项 accent 背景。 |
| 折叠 | 52px ↔ 200px，200ms QTimer 动画。展开/收起按钮 ↻。 |
| 统计 | 曲目数/专辑数。`sidebar.update_stats(tracks, albums)`。 |
| 日志 | QTextEdit 120px max，`append_log(msg)` 实时输出。`QSettings: sidebar_log` 开关。 |
| 强调色跟随 | `refresh_accent()` 注册到 `on_anim_tick`，nav 高亮即时变色。 |

### 国际化

| 语言 | 覆盖率 |
|---|---|
| 简体中文 | 100% |
| English | 100% |
| 繁體中文 | ~90% |
| 日本語 | ~90% |

`QSettings: language`。`set_language(code)` → `languageChanged` 信号 → 所有界面 `_refresh_language()` 刷新。JSON 翻译文件 `audio_player/i18n/{code}.json`。

### 元数据

| 功能 | 详情 |
|---|---|
| 读取 | mutagen → `TrackMetadata`（标题/艺人/专辑/封面/时长/采样率/位深/声道/格式/年代/流派/文件大小）。mutagen 异常时回退扩展名推断。 |
| 写入 | mutagen 标签写入（ID3/Vorbis/MP4）。`TagEditorDialog` 编辑单曲。 |
| 持久加载 | `_MetaLoader` QThread + Queue，单线程逐文件读取。`loaded` 信号 → `dataChanged` 更新 view。 |
| 线程安全 | 所有 QThread 子类加 `parent` 防 Python GC 提前析构。`_cancel` 用 request_id 忽略过期结果。 |

### 构建与分发

| 平台 | 方式 |
|---|---|
| Linux | PyInstaller → .deb (dpkg-deb) / AppImage / portable .tar.gz |
| 依赖 | GStreamer 插件 (base/good/bad/ugly + alsa)，python3-gi，gir1.2-gstreamer-1.0 |
| 版本 | pyproject.toml: 0.6.1。package.sh/build.sh 同步。 |
