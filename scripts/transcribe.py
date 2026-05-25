#!/usr/bin/env python3
"""transcribe-bili — 转写视频 (B 站 / YouTube) 为带标点的中文文本.

usage:
  transcribe-bili <URL_OR_BV> [<URL_OR_BV> ...]
  transcribe-bili --up <UID> [--top N]      # UP 主热度 top-N (默认 3)
  transcribe-bili --vad                     # 句级精分时间戳 (做字幕用)
  transcribe-bili --keep-wav                # 保留 wav 不删
  transcribe-bili --out DIR                 # 输出目录, 默认 ~/Desktop/transcripts
  transcribe-bili --engine sensevoice|whisper   默认 sensevoice
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

# ----- paths -----
CACHE = Path.home() / ".cache/sherpa-onnx"
SV_DIR = CACHE / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
VAD_ONNX = CACHE / "silero_vad.onnx"
DEFAULT_OUT = Path.home() / "Desktop" / "transcripts"

# ----- utils -----
BV_RE = re.compile(r"BV[a-zA-Z0-9]+")


def safe_name(s: str) -> str:
    s = re.sub(r"[^\w一-鿿\-\.\s]", "_", s)
    return s[:80].strip()


def normalize_target(s: str) -> str:
    """BV 短码或裸 ID → 完整 URL; 其他原样返回."""
    s = s.strip()
    if s.startswith("BV"):
        return f"https://www.bilibili.com/video/{s}/"
    return s


def fmt_ts(t: float) -> str:
    h, r = divmod(int(t), 3600)
    m, s = divmod(r, 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


# ----- step 1: 拿 metadata + 下载音频 -----
def download_audio(target: str, out: Path) -> tuple[Path, str]:
    info = subprocess.run(
        [
            "yt-dlp",
            "--cookies-from-browser",
            "chrome",
            "--skip-download",
            "--print-json",
            target,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if info.returncode != 0:
        raise RuntimeError(f"yt-dlp info failed: {info.stderr[-400:]}")
    meta = json.loads(info.stdout.strip().split("\n")[0])
    title = meta.get("title", target)
    duration = meta.get("duration", 0)
    vid = meta.get("id") or meta.get("display_id") or "video"
    print(f"  📺 {title}  ({duration}s)")

    safe = safe_name(title)
    wav_path = out / f"{vid}_{safe}.wav"
    if wav_path.exists() and wav_path.stat().st_size > 1024:
        print(f"  ↳ wav 已存在, 跳过下载")
        return wav_path, title

    tmp_template = str(out / f"{vid}.%(ext)s")
    print(f"  ⬇️  下载视频 (worst format)")
    r = subprocess.run(
        [
            "yt-dlp",
            "--cookies-from-browser",
            "chrome",
            "-f",
            "worst",
            "-o",
            tmp_template,
            target,
        ],
        capture_output=True,
        text=True,
        timeout=900,
    )
    if r.returncode != 0:
        raise RuntimeError(f"yt-dlp dl failed: {r.stderr[-400:]}")

    cand = sorted(out.glob(f"{vid}.*"), key=lambda p: p.stat().st_size, reverse=True)
    video_file = next(
        (c for c in cand if c.suffix in {".mp4", ".flv", ".m4s", ".webm", ".mkv"}),
        None,
    )
    if not video_file:
        raise RuntimeError(f"no video file for {vid}")

    print(f"  🔊 ffmpeg 抽音频 16kHz mono")
    r2 = subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(video_file),
            "-vn", "-ar", "16000", "-ac", "1",
            "-c:a", "pcm_s16le",
            str(wav_path),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if r2.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r2.stderr[-400:]}")
    video_file.unlink()
    return wav_path, title


# ----- step 2: VAD 切片 -----
def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        ch = w.getnchannels()
        sw = w.getsampwidth()
        raw = w.readframes(n)
    dtype = {1: np.int8, 2: np.int16, 4: np.int32}[sw]
    samples = np.frombuffer(raw, dtype=dtype).astype(np.float32) / (2 ** (sw * 8 - 1))
    if ch == 2:
        samples = samples.reshape(-1, 2).mean(axis=1)
    return samples, sr


def vad_segments(samples: np.ndarray, sr: int) -> list[tuple[float, float]]:
    """silero VAD → list of (start_s, end_s)."""
    import sherpa_onnx

    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = str(VAD_ONNX)
    cfg.silero_vad.threshold = 0.5
    cfg.silero_vad.min_silence_duration = 0.4
    cfg.silero_vad.min_speech_duration = 0.25
    cfg.silero_vad.max_speech_duration = 15.0
    cfg.sample_rate = sr

    vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=100)
    window = cfg.silero_vad.window_size
    segs: list[tuple[float, float]] = []
    i = 0
    while i < len(samples):
        vad.accept_waveform(samples[i : i + window])
        while not vad.empty():
            seg = vad.front
            t0 = seg.start / sr
            t1 = (seg.start + len(seg.samples)) / sr
            segs.append((t0, t1))
            vad.pop()
        i += window
    vad.flush()
    while not vad.empty():
        seg = vad.front
        t0 = seg.start / sr
        t1 = (seg.start + len(seg.samples)) / sr
        segs.append((t0, t1))
        vad.pop()
    return segs


# ----- step 3: SenseVoice 转写 -----
def load_sense_voice():
    import sherpa_onnx

    return sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(SV_DIR / "model.int8.onnx"),
        tokens=str(SV_DIR / "tokens.txt"),
        num_threads=4,
        use_itn=True,
        language="zh",
        debug=False,
    )


def transcribe(samples: np.ndarray, sr: int, rec, use_vad: bool):
    """返回 list[(t0, t1, text)]."""
    if use_vad:
        windows = vad_segments(samples, sr)
        print(f"  ✂  VAD 切片: {len(windows)} 段语音")
    else:
        step = sr * 30
        windows = [(i / sr, min((i + step) / sr, len(samples) / sr))
                   for i in range(0, len(samples), step)]

    parts: list[tuple[float, float, str]] = []
    streams = []
    for t0, t1 in windows:
        clip = samples[int(t0 * sr) : int(t1 * sr)]
        if len(clip) < sr // 4:
            continue
        s = rec.create_stream()
        s.accept_waveform(sr, clip)
        streams.append((s, t0, t1))
    # batch decode 一次性
    rec.decode_streams([s for s, *_ in streams])
    for s, t0, t1 in streams:
        text = s.result.text.strip()
        if text:
            parts.append((t0, t1, text))
    return parts


# ----- step 4: 写文件 -----
def write_outputs(out: Path, base: str, parts: list[tuple[float, float, str]]):
    full = "".join(p[2] for p in parts)
    txt = out / f"{base}.txt"
    txt.write_text(full, encoding="utf-8")

    srt = out / f"{base}.srt"
    with srt.open("w", encoding="utf-8") as f:
        for i, (t0, t1, t) in enumerate(parts, 1):
            f.write(f"{i}\n{fmt_ts(t0)} --> {fmt_ts(t1)}\n{t}\n\n")
    return txt, srt, len(full)


# ----- step 5: UP 主热门 top-N -----
def fetch_up_top(uid: str, n: int) -> list[str]:
    """用 browser-harness 调浏览器拿 top-N BV (按播放量排序)."""
    bh_script = f"""
new_tab("https://space.bilibili.com/{uid}/upload/video?order=click")
wait_for_load()
import time; time.sleep(4)
r = js('''
const cards = document.querySelectorAll('[class*="upload-video-card"]');
const seen = new Set();
const items = [];
cards.forEach(c => {{
    const a = c.querySelector("a[href*='/video/BV']");
    if (!a) return;
    const m = a.href.match(/\\\\/video\\\\/(BV[a-zA-Z0-9]+)/);
    if (!m || seen.has(m[1])) return;
    seen.add(m[1]);
    items.push(m[1]);
}});
return JSON.stringify(items.slice(0, {n}));
''')
print(r)
"""
    r = subprocess.run(
        ["browser-harness", "-c", bh_script],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        raise RuntimeError(f"browser-harness failed: {r.stderr[-300:]}")
    last_line = [l for l in r.stdout.strip().splitlines() if l.startswith("[")][-1]
    bvs = json.loads(last_line)
    print(f"  ✓ UP {uid} 热度 top-{n}: {bvs}")
    return bvs


# ----- main -----
def main():
    p = argparse.ArgumentParser()
    p.add_argument("targets", nargs="*")
    p.add_argument("--up", help="B站 UP 主 UID, 自动取热度 top-N")
    p.add_argument("--top", type=int, default=3)
    p.add_argument("--vad", action="store_true", help="句级时间戳 (做字幕)")
    p.add_argument("--keep-wav", action="store_true")
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--engine", default="sensevoice", choices=["sensevoice", "whisper"])
    args = p.parse_args()

    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)

    targets = list(args.targets)
    if args.up:
        targets += fetch_up_top(args.up, args.top)
    if not targets:
        p.print_help()
        sys.exit(1)

    print(f"输出: {out}")
    print(f"引擎: {args.engine}  VAD: {args.vad}")

    if args.engine == "sensevoice":
        print("加载 SenseVoice int8 模型...")
        rec = load_sense_voice()
    else:
        rec = None

    for i, t in enumerate(targets, 1):
        target = normalize_target(t)
        print(f"\n[{i}/{len(targets)}] {target}")
        try:
            wav, title = download_audio(target, out)
            samples, sr = read_wav(wav)
            print(f"  ⏱  {len(samples)/sr:.1f}s 音频")

            t0 = time.time()
            if args.engine == "sensevoice":
                parts = transcribe(samples, sr, rec, args.vad)
            else:
                import mlx_whisper
                res = mlx_whisper.transcribe(
                    str(wav),
                    path_or_hf_repo="mlx-community/whisper-large-v3-mlx",
                    language="zh",
                    temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
                    condition_on_previous_text=False,
                    verbose=False,
                )
                parts = [
                    (s["start"], s["end"], s["text"].strip())
                    for s in res.get("segments", [])
                ]
            elapsed = time.time() - t0

            base = wav.stem + ("_vad" if args.vad else "")
            if args.engine == "whisper":
                base += "_whisper"
            txt, srt, chars = write_outputs(out, base, parts)
            print(f"  ✓ TXT: {txt.name} ({chars} 字)")
            print(f"  ✓ SRT: {srt.name} ({len(parts)} 段)")
            print(f"  ⚡ {elapsed:.1f}s ({len(samples)/sr/elapsed:.0f}x 实时)")

            if not args.keep_wav:
                wav.unlink()
                print(f"  🗑  删 wav")
        except Exception as e:
            print(f"  ❌ {e}")

    print(f"\n✅ 全部完成. 打开: open {out}")


if __name__ == "__main__":
    main()
