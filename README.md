# video-transcribe

Claude Code Skill — 把视频转成带标点的中文文字稿和 SRT 字幕。

- **引擎**: SenseVoice (阿里 2024, 自带标点) + Whisper (mlx) 双引擎
- **覆盖**: B 站 / YouTube / Vimeo / Twitch / Patreon ... 任何 yt-dlp 支持的站
- **会员视频**: 通过 `yt-dlp --cookies-from-browser chrome` 复用本机浏览器登录态
- **VAD 切片**: 句级时间戳 (silero VAD) 做精确字幕
- **兜底**: yt-dlp 失败时由 [browser-harness](https://github.com/browser-use/browser-harness) 接管页面抓 manifest
- **速度**: M5 Max 上 24 分钟视频 5-10 秒搞定 (SenseVoice 70× 实时)

## 装

```bash
# 1. 克隆到 Claude Code 的 skill 目录
git clone https://github.com/isaac-du/video-transcribe-skill ~/.claude/skills/video-transcribe

# 2. 跑一键 install (装 yt-dlp / ffmpeg / sherpa-onnx + 下 SenseVoice 模型)
bash ~/.claude/skills/video-transcribe/install.sh
```

依赖:
- macOS (Apple Silicon 强推 — sherpa-onnx 的 CoreML/Metal 加速)
- Homebrew
- Python 3.11+
- Chrome (要登录态时)

## 用

### 在 Claude Code 里
说 "转写这个 B 站视频 BV1xxx" / "把 youtube.com/watch?v=xxx 转文字" — Claude 自动调用 skill。

### 终端直接跑
```bash
# 单个视频
transcribe BV1xxx
transcribe "https://www.youtube.com/watch?v=xxx"

# 字幕模式 (句级时间戳)
transcribe --vad BV1xxx

# B 站 UP 主热门 top-N
transcribe --up 676494894 --top 3 --vad

# 多个
transcribe BV1xxx BV1yyy "https://youtu.be/zzz"

# 切引擎
transcribe --engine whisper --vad BV1xxx

# 自定义输出目录
transcribe --out ~/Documents/notes BV1xxx
```

输出: `~/Desktop/transcripts/<video>_<title>[_vad][_whisper].{txt,srt}`

## 引擎对比

| 引擎 | 标点 | 速度 (M5 Max, 24min 视频) | 时间戳粒度 | 模型 |
|---|---|---|---|---|
| **sensevoice** (默认) | ✅ 自带 | ~5 秒 (70× 实时) | 30s 块 (加 `--vad` 句级) | 234 MB int8 |
| **whisper** | ❌ 无 | ~77 秒 (12× 实时) | 1-3s 字级 | 3 GB |

详见 [`references/engines.md`](./references/engines.md)。

## 协作 browser-harness

`yt-dlp` 90% 情况下能 cover B 站 / YouTube 的提取。失败时 (DRM / 反爬升级 / 私有站) 由 [browser-harness](https://github.com/browser-use/browser-harness) 接管:

- `--up` 列举 B 站 UP 主热度排序 (DOM 抓取)
- yt-dlp 失败 → browser-harness 打开页面 → 监听 network 抓 m3u8/mpd manifest

详见 [`references/browser-harness-integration.md`](./references/browser-harness-integration.md)。

## Files

```
video-transcribe-skill/
├── SKILL.md                                 # Claude Code skill manifest
├── scripts/
│   └── transcribe.py                        # 主脚本 (~/bin/transcribe ↔ 这里)
├── references/
│   ├── engines.md                           # SenseVoice vs Whisper
│   ├── browser-harness-integration.md       # yt-dlp 兜底流程
│   └── architecture.md                      # 全链路
├── install.sh                               # 一键装依赖
├── README.md
└── LICENSE                                  # MIT
```

## License

MIT — see [LICENSE](./LICENSE).
