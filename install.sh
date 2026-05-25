#!/usr/bin/env bash
# install.sh — 一键检测 + 装 video-transcribe skill 依赖
# 幂等: 已装的跳过, 缺的自动补
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
CACHE_DIR="$HOME/.cache/sherpa-onnx"
SV_MODEL_DIR="$CACHE_DIR/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
SV_TARBALL_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2"
VAD_ONNX="$CACHE_DIR/silero_vad.onnx"

bold() { printf "\033[1m%s\033[0m\n" "$*"; }
ok() { printf "  \033[32m✓\033[0m %s\n" "$*"; }
warn() { printf "  \033[33m⚠\033[0m %s\n" "$*"; }
err() { printf "  \033[31m✗\033[0m %s\n" "$*"; }

bold "▸ video-transcribe install"
echo

# 1. Homebrew tools
bold "1) Homebrew tools (yt-dlp + ffmpeg)"
if ! command -v brew >/dev/null 2>&1; then
  err "Homebrew not found. 装一下: https://brew.sh"
  exit 1
fi
for tool in yt-dlp ffmpeg; do
  if command -v "$tool" >/dev/null 2>&1; then
    ok "$tool ($(command -v $tool))"
  else
    warn "$tool 缺失, 装中..."
    brew install "$tool"
  fi
done
echo

# 2. Python deps
bold "2) Python deps (sherpa-onnx)"
if python3 -c "import sherpa_onnx" 2>/dev/null; then
  ok "sherpa-onnx $(python3 -c 'import sherpa_onnx; print(sherpa_onnx.__version__)')"
else
  warn "sherpa-onnx 缺失, pip 装中..."
  pip3 install sherpa-onnx
fi

if python3 -c "import mlx_whisper" 2>/dev/null; then
  ok "mlx-whisper (--engine whisper 可用)"
else
  warn "mlx-whisper 未装 (可选, 仅 --engine whisper 用)"
  echo "    跑 pip3 install mlx-whisper 启用"
fi
echo

# 3. SenseVoice model
bold "3) SenseVoice ONNX 模型 (~234 MB int8)"
mkdir -p "$CACHE_DIR"
if [ -f "$SV_MODEL_DIR/model.int8.onnx" ]; then
  ok "已就位: $SV_MODEL_DIR"
else
  warn "下载中 (~234 MB)..."
  cd "$CACHE_DIR"
  curl -L --progress-bar "$SV_TARBALL_URL" -o sv.tar.bz2
  tar xjf sv.tar.bz2
  rm sv.tar.bz2
  ok "下完: $SV_MODEL_DIR"
fi
echo

# 4. Silero VAD onnx
bold "4) Silero VAD ONNX (~2 MB, 给 --vad 用)"
if [ -f "$VAD_ONNX" ]; then
  ok "已就位: $VAD_ONNX"
else
  warn "通过 pip silero-vad 包拷出 .onnx 文件 (然后立即 uninstall pip 包)"
  pip3 install -q silero-vad 2>&1 | tail -1 || true
  SRC=$(python3 -c "
import importlib.util, pathlib
spec = importlib.util.find_spec('silero_vad')
if spec is None or spec.origin is None:
    print('')
else:
    p = pathlib.Path(spec.origin).parent / 'data' / 'silero_vad.onnx'
    print(p if p.exists() else '')
")
  if [ -n "$SRC" ] && [ -f "$SRC" ]; then
    cp "$SRC" "$VAD_ONNX"
    pip3 uninstall -y silero-vad >/dev/null 2>&1 || true
    ok "已就位: $VAD_ONNX ($(du -h "$VAD_ONNX" | cut -f1))"
  else
    err "拷出失败, 跳过 (不开 --vad 不影响)"
  fi
fi
echo

# 5. Install transcribe binary to ~/bin
bold "5) 装命令 transcribe → ~/bin/"
mkdir -p "$HOME/bin"
cp "$SKILL_DIR/scripts/transcribe.py" "$HOME/bin/transcribe"
chmod +x "$HOME/bin/transcribe"
ok "$HOME/bin/transcribe"

if ! echo "$PATH" | tr ':' '\n' | grep -qx "$HOME/bin"; then
  warn "~/bin 不在 PATH, 加到 ~/.zshrc:"
  echo '    echo '"'"'export PATH="$HOME/bin:$PATH"'"'"' >> ~/.zshrc'
fi
echo

# 6. Optional: browser-harness check
bold "6) browser-harness (可选, --up 和 yt-dlp 兜底用)"
if command -v browser-harness >/dev/null 2>&1; then
  ok "browser-harness 已装"
else
  warn "browser-harness 未装 (可选). 装法: https://github.com/browser-use/browser-harness"
fi
echo

bold "✅ 安装完成"
echo
echo "测试:"
echo "  transcribe --help"
echo "  transcribe BV1xxx"
