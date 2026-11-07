# 沉浸页 QML 化移植参数规格

> 决策：沉浸页以 QML 实现为主线（歌词滚动由场景图线程渲染，结构性解决卡顿）。
> 本文记录从 widget 版（本会话验收过的状态）提取的全部参数，移植时逐项对齐。
> 回退点：`backup/widget-immersive` 分支（QML 移植前的完整 widget 状态）。

## 一、几何与布局（QML 已有一致的公式，逐项核对过）

| 项 | widget 版取值 | QML 现值 | 移植取用 |
|---|---|---|---|
| 封面尺寸（歌曲模式） | `min(h*0.38, w*0.35, 380)` | 同公式 | QML 公式 ✓ |
| 封面尺寸（歌词模式） | `min(h*0.22, w*0.18, 240)` | 同公式 | QML 公式 ✓ |
| 封面 X（歌曲/歌词） | 居中 / `w*0.08` | 同公式 | ✓ |
| 封面 Y（歌曲/歌词） | `h*0.15` / `h*0.08` | 同公式 | ✓ |
| 标题/歌手/专辑 Y 起点 | `cover_y + cover_size + 32` | Column `y:_coverY+_coverH+32` | ✓ |
| 文本块宽（歌曲/歌词） | `500` / `cover_size` | `min(_w*0.7,500)` / `_coverW` | ✓ |
| 布局形变时长 | 400ms InOutCubic | 400ms InOutCubic | ✓ |
| 进度条宽 | `min(w*0.5, 500)` → cover_size | 同 | ✓ |
| 进度条高/圆角 | 12 / 6 | 12 / 6 | ✓ |
| 进度条槽色 alpha | 70（widget 本地） | 40（`0.157`） | **QML 40（v0.7.6 打磨版，用户在 Windows 验收过）** |
| 进度条 Y | `h - bottom_margin - play_size/2 - 24 - 12` | `_h-168+40*_p`（等价：60+72/2+24+12=132 → 168-36=132 ✓） | ✓ |
| 播放键尺寸 | 72 → 52 | 72 → 52 | ✓ |
| 两侧键尺寸 | 56 → 40 | 56 → 40 | ✓ |
| 键间距 | 16 → 10 | `_gap: 16→10` | ✓ |
| 底部边距 | 60 → 40 | `_btnMargin: 60→40` | ✓ |
| 右上角按钮 | 36px 圆、间距 8、边距 12/16 | 同 | ✓ |

## 二、字体字号（widget 版为验收基准）

| 项 | widget 版 | QML 现值 | 移植取用 |
|---|---|---|---|
| 标题 | 22pt 粗体 白色 | 22pt bold #fff | ✓ |
| 歌手 | 14pt `accent.lighter(1.3)` | 14pt Qt.lighter(accent,1.3) | ✓ |
| 专辑 | 11pt `#8899aa` | 11pt #8899aa | ✓ |
| 音质条 | 10pt letterSpacing 1 `accent.lighter(1.2)` | 同 | ✓ |
| 时间标签 | 10pt（widget 用 #94a3b8，后改 accent.lighter(1.3)） | accent.lighter(1.3) | QML 值 |
| 歌词基准字号 | `max(20, min(34, w*0.038))`，**统一字号** | **18pt 活跃 / 14pt 非活跃（非统一）** | **widget：统一字号随窗宽缩放** |
| 歌词当前行区分 | 仅加粗 + 强调色（不缩放） | 字号动画 14↔18 | **widget：加粗+强调色** |
| 歌词非当前行色 | `#8899aa` 系 | #8899aa | ✓ |
| 歌词换行 | QTextLayout 词形换行 + 边缘 alpha 淡出 | WordWrap，无边缘淡出 | 需补边缘淡出 |
| 歌词滚动 | 亚像素整体滚动 + 缓存 | ListView StrictlyEnforceRange + Snap | QML 场景图原生 |

## 三、Hero 过渡动画（widget 版为本移植的基准实现）

| 项 | 值 |
|---|---|
| 进入时长 / 缓动 | 560ms / OutExpo |
| 退出时长 / 缓动 | 460ms / InCubic |
| 进入背景淡化 | 墙钟前 40%：alpha 0→1 smoothstep（底层为切换瞬间 UI 快照） |
| 退出背景淡化 | alpha 1→0 smoothstep(travel)，与封面下降同步 |
| 快照来源 | `_body.grab()`（进场：底栏可见时抓；退场：先按风格恢复底栏再抓） |
| 封面飞行 | bar 缩略图全局矩形 → 页面封面矩形插值；圆角 6→12；阴影同步 |
| 错峰淡入 | 标题 20% / 歌手专辑 28% / 播控+进度+音质 38%，上浮 16px，smoothstep |
| 退场镜像淡出 | 按钮 t=0.62 前消失、标题 t=0.8 前，下沉 16px，与背景淡化同节奏 |
| 右上角按钮 | 过渡期隐藏（退场 200ms 淡出），进场结束恢复 |
| 歌词预览 | 形变期间 `layoutProgress × enter_alpha(0.25)` |
| 进度条局部重绘 | widget 特有优化；QML 场景图原生，不需要 |

## 四、其他保持项

- 封面/背景到达渐入：QML 已有（450ms 背景 / 350ms 封面，OutCubic）— 保留
- 切歌背景交叉淡化：QML `_bgFade` Behavior 覆盖（widget 的 `_bg_fade_progress` 不再需要）
- 封面后台处理：_CoverWorker 线程（解码→80×80 模糊→放大→JPG 临时文件），复用 widget 的 `_blur_qimage`
- 自动隐藏：播控 3s、右上角 3s（QML Timer 已有）
- 音质条点击 → 输出详情弹窗（widget 有、QML 缺失——补 MouseArea 发 outputDetailRequested）
- seek 仅在释放时执行（QML 已有，防 EOF 竞态）— 保留
- 全屏收起时同时退出全屏（main_window 已合并该行为）— 保留

## 五、main_window 接线（QML API 面）

`set_track_info / set_cover / set_quality / set_position / set_duration /
set_playing / set_lyrics / set_lyrics_position / set_lyrics_visible /
refresh_accent / begin_enter_transition / begin_exit_transition /
toggle_lyrics / 信号：collapseRequested fullscreenRequested playPauseClicked
nextClicked prevClicked seekRequested lyricsToggled outputDetailRequested`

滚动/位置等信号由 QML 场景图接管，widget 版的
`_progress_region` / `_LyricsLayer` / `_enter_alpha` 数学仅保留在
Python 侧过渡驱动器中（计算逐帧推送给 QML 属性，保证与验收参数逐位一致）。
