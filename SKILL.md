---
name: video-transcribe
description: This skill should be used when the user wants to 转写视频 / 视频转文字 / 提取字幕 / 视频字幕 / 视频转写 / 把视频变成文字 / get transcript / transcribe video / make subtitles / SRT 字幕, for B 站 / bilibili / YouTube / Vimeo / Patreon / 网课 / 教程视频 / 会员视频 / 充电视频 / 付费视频 or any video URL or BV id (BV1xxx). Routes through yt-dlp with browser cookies for paywalled content, transcribes via SenseVoice (fast, with punctuation) or Whisper, and outputs both .txt and .srt. Falls back to the browser skill (browser-harness) when yt-dlp cannot extract a stream (DRM, novel sites, broken extractors). Mention "transcribe-video" / "转写" / "字幕" / "video to text" / "视频转写" / "提取字幕" to trigger.
---

# video-transcribe

把视频转成带标点的中文文本和 SRT 字幕。默认引擎 **SenseVoice** (阿里 2024, 自带标点, M5 上比实时快 30-70×)；视频流抓取通过 `yt-dlp --cookies-from-browser chrome` 复用浏览器登录态；yt-dlp 抽取失败时由 **browser skill (browser-harness)** 接管页面抓 manifest 兜底。

## When to use

- "帮我转写这个 B 站视频" / "把这视频变文字" / "拉个 SRT 字幕"
- "C喵这个 UP 主热度 top-3 视频都转写一下"
- "YouTube 这条会员视频做笔记"
- 任何 URL / `BV1xxx...` / `https://www.youtube.com/...` / `https://www.bilibili.com/video/BV...`

## When NOT to use

- 实时转写（直播流） — 这个 skill 只做离线
- 视频内容**理解**（不是文字稿） — 用 `claude-video-vision` 或者拿到 txt 后让 Claude 总结
- 录系统/桌面音频（不来自视频文件 URL） — 用 Claude Voice MCP

## Usage

```bash
# 一行命令 (默认 SenseVoice 引擎, 不开 VAD)
transcribe BV1xxx
transcribe "https://www.youtube.com/watch?v=xxx"
transcribe https://www.bilibili.com/video/BV1xxx/

# 字幕模式 (silero VAD 按自然停顿切句, 出精细时间戳)
transcribe --vad BV1xxx

# B 站 UP 主热度 top-N (走 browser-harness 拿排序)
transcribe --up 676494894 --top 3 --vad

# 多个并跑
transcribe BV1xxx BV1yyy "https://youtu.be/zzz"

# 切引擎 (whisper 时间戳更细但慢, 无标点)
transcribe --engine whisper --vad BV1xxx

# 保留下载的 wav (默认转完删)
transcribe --keep-wav BV1xxx

# 指定输出目录 (默认 ~/Desktop/transcripts/)
transcribe --out ~/Documents/notes BV1xxx
```

## Output

`<out_dir>/<video_id>_<safe_title>[_vad][_whisper].{txt,srt}`

- `.txt` — 全文，带标点（SenseVoice）或无标点（Whisper）
- `.srt` — 标准字幕，可直接 import Premiere/FCP/剪映

## Engine matrix

| 引擎 | 标点 | 速度 (M5 Max) | 时间戳粒度 | 模型大小 |
|---|---|---|---|---|
| **sensevoice** (默认) | ✅ 自带 | ~70× 实时 | 段级 (30s 块, 加 `--vad` 句级) | 234 MB int8 |
| **whisper** (`mlx-whisper`) | ❌ 无 | ~12× 实时 | 字级 (1-3s 段) | 3 GB |

短决策：要可读性 → SenseVoice；要精确字幕同步 → SenseVoice + `--vad`；要逐字时间戳剪辑 → Whisper。

## Architecture (read on demand)

```
URL / BV / UP UID
   │
   ▼
[1] yt-dlp --cookies-from-browser chrome  (90% 路径)
   │           ↳ 失败时:
   │           [1b] browser-harness 接管页面, 监听 network 抓 manifest
   ▼
[2] yt-dlp -f worst → mp4 → ffmpeg 抽 16kHz mono wav
   ▼
[3] (可选) silero VAD 切片
   ▼
[4] SenseVoice / Whisper 转写
   ▼
[5] 写 .txt + .srt, 删 wav (除非 --keep-wav)
```

详见 `references/architecture.md`、`references/engines.md`、`references/browser-harness-integration.md`。

## Configuration assumptions

脚本假设以下环境已配置 — `install.sh` 装到位:

- `yt-dlp` (Homebrew)
- `ffmpeg` (Homebrew)
- `sherpa-onnx` (pip) + SenseVoice int8 ONNX 模型 (auto-fetch)
- `silero_vad.onnx` (~/.cache/sherpa-onnx/)
- (可选) `mlx-whisper` for `--engine whisper`
- (可选) `browser-harness` for `--up` 或 yt-dlp 兜底
- Chrome 在跑 + 已开 9222 debug 端口（仅当用到 browser-harness 时）

跑 `bash install.sh` 一键检测+补装。

## Gotchas

- **B 站充电视频**: yt-dlp 只能拿到非会员视频；充电视频要 browser-harness 兜底（见 references）。
- **B 站 muxed only**: B 站绝大多数视频 yt-dlp 看到的是 muxed (无独立 audio 流), 故 `-f worst` 取最低画质 mp4 然后 ffmpeg 抽音频, 比 `-f bestaudio` 更可靠。
- **`--cookies-from-browser chrome` 首次弹 Keychain 密码**: macOS 安全机制, 输一次后记住。
- **yt-dlp 自更新**: B 站/YT 反爬升级时 extractor 会失效, 跑 `brew upgrade yt-dlp` 通常解决。
- **模型首次下载 234MB**: `install.sh` 已处理。
- **首次启动 silero VAD onnx 模型**: 通过 pip 的 `silero-vad` 包内置文件拷出（不直接联 github raw）。

## Trigger keywords

转写视频 / 视频转文字 / 提取字幕 / 视频字幕 / 视频转写 / 字幕生成 / SRT 字幕 / transcribe video / video to text / get transcript / make subtitles / 把视频变成文字 / B站 转写 / YouTube 转写 / 会员视频 转写 / 付费视频 转写 / 视频笔记 / 视频文字稿

## See also

- `references/engines.md` — SenseVoice vs Whisper 详细对比
- `references/browser-harness-integration.md` — yt-dlp 失败时的兜底流程
- `references/architecture.md` — 全链路细节
