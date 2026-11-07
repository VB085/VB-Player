# VB Player — ASIO 开发笔记

## 架构

```
GStreamer decodebin → appsink → Python 线程 → asio_write → ring buffer → ASIO COM 回调 → 驱动
```

## ASIO COM 接口

### VTable 索引
| 索引 | 函数 |
|------|------|
| 2 | Release |
| 3 | Init |
| 7 | Start |
| 8 | Stop |
| 9 | GetChannels |
| 11 | GetBufferSize |
| 14 | SetSampleRate |
| 18 | GetChannelInfo |
| 19 | CreateBuffers |
| 20 | DisposeBuffers |

### CoCreateInstance
- 用驱动自身的 CLSID 作为 IID（不是标准 IID_IASIO）
- FiiO、FL Studio ASIO 都适用
- `ctypes.byref()` 需要 ctypes 实例，不能传 `bytes`

### 回调 struct
- 必须存为模块级全局变量（`_cbs`）——局部变量会 GC
- 回调中避免 Python 循环——用 bulk memmove

## 采样格式

### ASIO SDK 常量
```
ASIOSTInt16MSB   = 0     (已废弃)
ASIOSTInt24MSB   = 1
ASIOSTInt32MSB   = 2
ASIOSTFloat32MSB = 3
ASIOSTFloat64MSB = 4
ASIOSTInt32MSB16 = 8
ASIOSTInt32MSB18 = 9
ASIOSTInt32MSB20 = 10
ASIOSTInt32MSB24 = 11
ASIOSTInt16LSB   = 16
ASIOSTInt24LSB   = 17
ASIOSTInt32LSB   = 18    ← FiiO 用这个
ASIOSTFloat32LSB = 19
ASIOSTFloat64LSB = 20
ASIOSTInt32LSB16 = 24
ASIOSTInt32LSB18 = 25
ASIOSTInt32LSB20 = 26
ASIOSTInt32LSB24 = 27
```
常量不是连续值，不能推算——必须查 asio.h。

### 格式转换
- 通过 `GetChannelInfo` (vtable 18) 查询驱动期望格式
- ring buffer 始终存 F32LE
- 回调里根据 `_sample_type` 做 F32LE→INT32/INT24/INT16 转换
- 未知格式 fallback 到 INT32LSB

## 32位/64位兼容性

| 驱动 | 位数 | 状态 |
|------|------|------|
| FiiO ASIO | 64-bit | ✅ 可用 |
| FL Studio ASIO | 64-bit | ✅ 可用 |
| Realtek ASIO | 32-bit | ❌ 不支持 |

- 64 位 Python 无法加载 32 位 COM DLL
- `REGDB_E_CLASSNOTREG` (0x80040154) 可能是位数不匹配
- 检查：`HKEY_CLASSES_ROOT\WOW6432Node\CLSID\{...}` 存在 = 32 位

## 并发问题

- Ring buffer 被主线程写、ASIO 驱动线程读
- MSYS2 Python 3.14 下 ctypes 数组不是线程安全的
- 解决：`array.array` 切片 de-interleave + bulk `memmove`

## 进度条

- 最初用字节计数 → 写入不均匀 → 卡顿
- GStreamer `query_position` → 平滑

## MSYS2 Python 3.14 已知问题

| 问题 | 解决 |
|------|------|
| `wintypes.HRESULT` 不存在 | 用 `wintypes.LONG` 替代 |
| QThread 访问冲突 | 禁用 AudioAnalyzer、LyricsFetcher、_MetaLoader |
| `mutagen` ValueError | 扩展名回退 |
| `from X import int_var` 值拷贝 | 用 `import module as _a` + `_a._var` |
| ctypes 数组并发写崩溃 | 用 array.array + memmove |
| `app.setStyleSheet` 崩溃 | 已修复(ASIO 回调 GC bug)，动态强调色恢复 |

## 调试技巧

1. 验证数据→验证格式：dump WAV 文件干净≠ASIO 出声干净
2. 回调是否触发：加 `sys.stderr.flush()` 打印，QTimer 可能吞异常
3. `_cbs` 要全局：局部变量 GC 后回调不触发
4. 独立进程测试：`asio_worker.py` 隔离 Qt/GIL 影响

## WASAPI 暂停恢复切碎问题

### 现象
WASAPI 独占模式暂停后播放，音频断续（几秒才放一段），进度条跳。

### 根因
`wasapi2sink` 的 `buffer-time=10000` (10ms) 太小，配合 `low-latency=True`。
暂停时管道停止，音频 buffer 排空。恢复时 10ms buffer 来不及填满，
导致连续 underrun → 声音"切碎"。

### 解决
```python
sink.set_property("low-latency", False)    # 关闭低延迟
sink.set_property("buffer-time", 50000)    # 10ms → 50ms
sink.set_property("latency-time", 10000)   # 3ms → 10ms
```
更大的 buffer 给管道更多时间在恢复时填充。暂停/恢复完全使用 GStreamer
基类的标准逻辑，不做任何自定义覆盖。
