# Engines: SenseVoice vs Whisper

## 选哪个 (短决策)

| 你优先 | 选 |
|---|---|
| 可读性 / 标点 / 速度 | **sensevoice** (默认) |
| 精确字幕同步 (剪辑用) | **sensevoice + `--vad`** |
| 字级时间戳 (逐词剪辑) | **whisper** |

## SenseVoice (阿里达摩院, 2024)

- 模型: `mlx-community` 风格的 ONNX, sherpa-onnx 推理
- 多语言: 中 / 英 / 日 / 韩 / 粤
- **自带标点 + ITN** (1234 → "一千二百三十四" 这种)
- 还能识别 笑声/掌声/音乐 (本 skill 没用，但 model 支持)
- 非自回归架构 → 速度极快, M5 Max 上 70× 实时
- 量化版 int8 onnx 仅 234 MB

### 局限

- 单次最长 30s 音频, 长音频要 chunked decode
- 不开 `--vad` 时, SRT 时间戳粒度 = 30s 块
- 开 `--vad` (silero) 后, 段落按真实停顿切, 5-25s 自然变长

## Whisper (mlx-whisper, OpenAI large-v3)

- 模型: `mlx-community/whisper-large-v3-mlx`
- 自回归, 时间戳精细到 1-3 秒
- **没标点** (中文模型尤其差)
- M5 Max 上 12× 实时 (sensevoice 的 1/6)
- 模型 3 GB

### 防御已启用

为防止重复 hallucination, 本脚本的 whisper 调用预设了:

```python
temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0)   # 检测到重复就升 temperature 重试
compression_ratio_threshold=2.4               # 重复率检测
no_speech_threshold=0.6                       # 跳静音
condition_on_previous_text=False              # 不让上下文带偏
```

### Lightning-Whisper-MLX 为什么不用

`lightning-whisper-mlx` 比 `mlx-whisper` 还快 10×, 但 batched decoding 牺牲了 hallucination 防御 — 实测在低音量段会陷入重复循环 ("家里你自己的家里你自己的家里..."). 故本 skill 用 `mlx-whisper` 不用 lightning.

## 字数对比 (同样 24min 中文视频)

| 文件 | sensevoice | whisper |
|---|---|---|
| BV1Lo5a6sE9x | 3012 字 | 2893 字 |
| BV1UeLK6ME78 | 3146 字 | 2944 字 |

SenseVoice 多识别 4-7% (保留口语词如 "啊/呢/嘛" 更全)。
