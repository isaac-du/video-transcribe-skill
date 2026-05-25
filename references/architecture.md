# Architecture

## 全链路

```
                                  ┌────────────────────────────────┐
                                  │ 用户: transcribe BV1xxx        │
                                  └───────────────┬────────────────┘
                                                  │
                                                  ▼
                                    ┌──────────────────────────┐
                                    │ normalize_target()        │
                                    │ BV/url → https://… URL    │
                                    └──────────────┬───────────┘
                                                  │
            ┌─────────────────────────────────────┴──────────────┐
            │ (单独路径) --up <UID> --top N                       │
            │ ──────────────────────────────────                  │
            │ fetch_up_top() 用 browser-harness                   │
            │ DOM 抓 UP 主 ?order=click 页, 取前 N 个 BV          │
            └─────────────────────────────────────┬──────────────┘
                                                  │
                                                  ▼
                            ┌────────────────────────────────────┐
                            │ download_audio(target)              │
                            │ ─────────────────────────────────── │
                            │ 1. yt-dlp --skip-download --print-json
                            │    --cookies-from-browser chrome    │
                            │    → metadata (title, duration, id) │
                            │                                     │
                            │ 2. yt-dlp -f worst                  │
                            │    --cookies-from-browser chrome    │
                            │    → <id>.mp4 (lowest res)          │
                            │                                     │
                            │ 3. ffmpeg -i <id>.mp4               │
                            │      -vn -ar 16000 -ac 1            │
                            │      -c:a pcm_s16le                 │
                            │    → <id>_<safe_title>.wav          │
                            │                                     │
                            │ 4. rm <id>.mp4                      │
                            └────────────────┬───────────────────┘
                                             │
                                             ▼
                            ┌────────────────────────────────────┐
                            │ read_wav() → numpy array, sr=16k    │
                            └────────────────┬───────────────────┘
                                             │
                          ┌──────────────────┴──────────────────┐
                          │                                     │
                          ▼ (默认)                              ▼ (--vad)
            ┌────────────────────────┐         ┌────────────────────────────┐
            │ chunk 30s 切片         │         │ silero VAD → list of      │
            │ windows = [(t0,t1)...] │         │ (start_s, end_s) 按真实   │
            │                        │         │ 停顿切, 每段 5-15s         │
            └───────────┬────────────┘         └─────────────┬──────────────┘
                        │                                    │
                        └────────────┬───────────────────────┘
                                     │
                                     ▼
                  ┌──────────────────────────────────────┐
                  │ SenseVoice OfflineRecognizer          │
                  │ ───────────────────────────────────── │
                  │ for (t0, t1) in windows:              │
                  │     s = rec.create_stream()           │
                  │     s.accept_waveform(sr, samples)    │
                  │ rec.decode_streams([all_streams])     │
                  │ for stream:                           │
                  │     part = (t0, t1, stream.result.text)│
                  └────────────────┬────────────────────┘
                                   │
                                   ▼
                  ┌──────────────────────────────────────┐
                  │ write_outputs()                       │
                  │ ───────────────────────────────────── │
                  │ TXT: "".join(p[2] for p in parts)     │
                  │ SRT: <i> <fmt(t0)> --> <fmt(t1)> <txt> │
                  └────────────────┬────────────────────┘
                                   │
                                   ▼
                  ┌──────────────────────────────────────┐
                  │ rm wav (unless --keep-wav)            │
                  └──────────────────────────────────────┘
```

## 关键决策

### 为什么 `-f worst` 不是 `-f bestaudio`

B 站绝大多数视频的 yt-dlp `formats` 是 muxed (音视频合一, 没有独立 audio 流), `bestaudio` 直接报 `Requested format is not available`. 用 `worst` 取最低画质 mp4 (~30-60 MB / 24min), ffmpeg 抽音频后立即删 mp4, 比 yt-dlp 的 `-x --audio-format wav` 更可靠.

### 为什么 16kHz mono

- SenseVoice 训练时输入是 16kHz, 上 22.05 / 44.1 不会更准
- mono 而非 stereo, 减少 50% 内存 + 推理快
- pcm_s16le 是 sherpa-onnx 期望的格式

### 为什么 sherpa-onnx 不直接用 funasr

`funasr` 拖 torch 全家桶 (~2 GB 安装), `sherpa-onnx` 是 C++ 推理, Python 包仅 ~50 MB. M5 Max 上 Metal/CoreML 加速.

### `--cookies-from-browser chrome` 怎么工作

yt-dlp 读 Chrome 的 cookies sqlite (`~/Library/Application Support/Google/Chrome/Default/Cookies`), 用 macOS Keychain API 解密 (会弹一次密码), 注入 yt-dlp 的 requests session. 之后访问 bilibili.com / youtube.com 时带着你的会员 / 登录态.

## 失败模式 + 退路

| 失败 | 怎么发现 | 退路 |
|---|---|---|
| yt-dlp 提取失败 | `RuntimeError: yt-dlp dl failed` | `brew upgrade yt-dlp`; 还失败上 browser-harness |
| ffmpeg 找不到 video | `RuntimeError: no video file` | 看 yt-dlp 输出后缀, 加到 `download_audio()` 的 suffix set |
| SenseVoice 模型缺失 | `FileNotFoundError model.int8.onnx` | 重跑 `install.sh` |
| silero_vad.onnx 缺失 (用 --vad 时) | sherpa-onnx 报错 | 重跑 `install.sh`, 它会从 pip 包拷出来 |
| Chrome 没开 9222 (用 --up 时) | browser-harness 连不上 | 启 Chrome 时加 `--remote-debugging-port=9222`, 或装 browser-harness 后用它的 CDP autostart |
| 模型推理 hang | 25+ 秒无输出 | kill, 看 wav 是否损坏 (ffprobe), 重试 |
