"""gen_tts.py — 故事手绘风视频的旁白配音（默认免费 edge-tts，可切 MiniMax）

按场景生成旁白 mp3 + timeline.json（含每段时长，供 apply_timeline.py 回写 storyboard.json）。

后端（--backend）：
  - edge（默认，免费）：Microsoft Edge TTS，无需 API key，voice 默认
    zh-CN-XiaoyiNeural 女声。需 `pip install edge-tts`。
  - minimax：apiz speak → 失败 fallback 直连 api.minimaxi.com/v1/t2a_v2
    （从 .env 读 minimaxi=KEY，model=speech-02-hd）。音质更好但要额度，
    仅在用户明确要高质量时用。

输入 narration.yaml（id 用 s01/s02 字符串，避免 YAML 把 01 当八进制）：
  lang: zh                    # 可选：en 时默认 voice 切 en-US-JennyNeural（英文教学）
  voice: zh-CN-XiaoyiNeural   # edge 默认；minimax 用 female-shaonv；英文用 en-US-JennyNeural
  speed: 1.0
  scenes:
    - id: s01
      text: "盛唐长安，万邦来朝……"

输出：
  public/audio/narration/s01.mp3 s02.mp3 ...
  public/audio/narration/timeline.json  # [{id, file, seconds, frames_source, frames_playback}]

frames 计算：
  sourceFrames = ceil(时长秒 × 30) + 15
  playbackFrames = ceil(sourceFrames / 1.2)   # 1.2x 交付节奏（手绘日记风默认原速，用 source 即可）
"""
from __future__ import annotations
import argparse
import json
import math
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

FPS = 30
PLAYBACK_RATE = 1.2  # 交付节奏（对齐 sketch-story 系列默认）


# ============================================================================
# 路径 2：直连 MiniMax API（fallback）
# ============================================================================

def find_minimax_key() -> str:
    """从 .env 读 minimaxi=KEY（和 poem-video-template/gen_tts.py 一致）。"""
    candidates = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
        Path.cwd().parent.parent / ".env",  # video-spec-builder-main/.env
    ]
    for p in candidates:
        if p.exists():
            text = p.read_text(encoding="utf-8")
            m = re.search(r"minimaxi\s*=\s*(\S+)", text)
            if m:
                return m.group(1)
    raise RuntimeError(
        f"找不到 minimaxi=KEY，tried: {[str(p) for p in candidates]}"
    )


def call_tts_direct(
    text: str, out_path: Path, voice: str, speed: float,
    model: str = "speech-02-hd",
) -> Path:
    """直连 api.minimaxi.com/v1/t2a_v2（apiz 不可用时的 fallback）。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    api_key = find_minimax_key()
    payload = json.dumps({
        "model": model,
        "text": text,
        "stream": False,
        "voice_setting": {"voice_id": voice, "speed": speed, "vol": 1.0, "pitch": 0},
        "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1},
        "output_format": "url",
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.minimaxi.com/v1/t2a_v2",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("base_resp", {}).get("status_code") != 0:
        raise RuntimeError(f"MiniMax 错误: {data.get('base_resp')}")
    audio = data["data"]["audio"]
    if audio.startswith("http"):
        with urllib.request.urlopen(audio, timeout=60) as r:
            out_path.write_bytes(r.read())
    else:
        out_path.write_bytes(bytes.fromhex(audio))
    return out_path


# ============================================================================
# 路径 3：edge-tts（免费 fallback，用户明说"用免费的"时启用）
# ============================================================================

EDGE_DEFAULT_VOICE = "zh-CN-XiaoyiNeural"  # 女声清亮；男声可用 zh-CN-YunxiNeural
EDGE_DEFAULT_VOICE_EN = "en-US-JennyNeural"  # 英文教学默认女声；男声可用 en-US-GuyNeural


def call_tts_edge(
    text: str, out_path: Path, voice: str, speed: float,
) -> Path:
    """用 edge-tts（Microsoft 在线 TTS，免费、无需 API key）生成 mp3。

    需要先 `pip install edge-tts`。speed 参数对 edge-tts 是 rate 百分比，
    1.0 → +0%，1.2 → +20%，0.9 → -10%。
    """
    try:
        import edge_tts  # type: ignore
    except ImportError:
        raise RuntimeError(
            "edge-tts 未安装。运行 `pip install edge-tts` 后重试，"
            "或去掉 --backend edge 用默认 MiniMax。"
        )
    import asyncio

    out_path.parent.mkdir(parents=True, exist_ok=True)
    rate_pct = int((speed - 1.0) * 100)
    rate_str = f"{'+' if rate_pct >= 0 else ''}{rate_pct}%"

    async def _run():
        communicate = edge_tts.Communicate(text, voice, rate=rate_str)
        await communicate.save(str(out_path))

    asyncio.run(_run())
    if not out_path.exists():
        raise RuntimeError(f"edge-tts 声称成功但文件不存在: {out_path}")
    return out_path


# ============================================================================
# 公共：时长测量 + timeline
# ============================================================================

def ffprobe_duration(path: Path) -> float:
    """用 ffprobe 量音频时长（秒）。"""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {proc.stderr}")
    return float(proc.stdout.strip())


def gen_tts_with_fallback(
    text: str, out_path: Path, voice: str, speed: float,
    backend: str = "edge",
) -> str:
    """按 backend 选择 TTS 路径。返回用了哪条路径。

    - backend='edge'（默认，免费）：edge-tts，无需 API key
    - backend='minimax'：apiz speak → 失败 fallback 直连 MiniMax API
    """
    if backend == "edge":
        call_tts_edge(text, out_path, voice=voice, speed=speed)
        return "edge"

    # MiniMax 链路（lazy import：默认走 edge 的用户无需配置 apiz）
    from lib_apiz import speak as apiz_speak  # noqa: E402
    try:
        apiz_speak(text, out_path, voice=voice, speed=speed)
        return "apiz"
    except RuntimeError as e:
        print(f"  apiz speak 失败 ({e})，fallback 到直连 MiniMax API ...", file=sys.stderr)
        call_tts_direct(text, out_path, voice, speed)
        return "direct"


# ============================================================================
# 主流程
# ============================================================================

def load_narration(path: Path) -> dict:
    import yaml  # type: ignore
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(
        description="故事手绘风视频旁白配音（默认免费 edge-tts，可切 MiniMax 高质量）+ 生成 timeline.json",
    )
    parser.add_argument("narration_yaml", help="narration.yaml 路径")
    parser.add_argument(
        "--out-dir", default="public/audio/narration",
        help="输出目录（默认 public/audio/narration/）",
    )
    parser.add_argument(
        "--backend", choices=["minimax", "edge"], default="edge",
        help="TTS 后端：edge（默认，免费 edge-tts）/ minimax（apiz speak → 直连 fallback，音质更好但要额度）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印不生成")
    args = parser.parse_args()

    spec = load_narration(Path(args.narration_yaml))
    # voice 选择优先级：yaml 显式 voice > yaml lang 字段 > backend 默认
    # 英文教学故事（lang: en）默认用 en-US-JennyNeural
    yaml_lang = spec.get("lang", "zh")
    if args.backend == "edge":
        default_voice = EDGE_DEFAULT_VOICE_EN if yaml_lang == "en" else EDGE_DEFAULT_VOICE
    else:
        default_voice = "female-shaonv"  # minimax 中文女声
    voice = spec.get("voice", default_voice)
    speed = float(spec.get("speed", 1.0))
    scenes = spec["scenes"]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"backend={args.backend}, voice={voice}, speed={speed}, scenes={len(scenes)}")

    timeline = []
    for sc in scenes:
        sid = sc["id"]
        text = sc["text"].strip()
        out_path = out_dir / f"{sid}.mp3"
        print(f"[{sid}] {text[:30]}...")

        if args.dry_run:
            print(f"  (dry-run) backend={args.backend} voice={voice} speed={speed}")
            continue

        if out_path.exists():
            print(f"  已存在，跳过（删掉可重新生成）")
        else:
            path_used = gen_tts_with_fallback(
                text, out_path, voice, speed, backend=args.backend,
            )
            print(f"  生成完成 ({path_used})")

        seconds = ffprobe_duration(out_path)
        # 帧数计算（对齐 SKILL.md 公式）
        source_frames = math.ceil(seconds * FPS) + 15
        playback_frames = math.ceil(source_frames / PLAYBACK_RATE)
        timeline.append({
            "id": sid,
            "file": str(out_path.relative_to(out_dir.parent.parent.parent)) if out_path.parent.parent.parent in out_path.parents else str(out_path),
            "text": text,
            "seconds": round(seconds, 2),
            "frames_source": source_frames,
            "frames_playback": playback_frames,
        })
        print(f"  时长 {seconds:.2f}s → source {source_frames}帧 / playback {playback_frames}帧")

    timeline_path = out_dir / "timeline.json"
    timeline_path.write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\ntimeline 写入 {timeline_path}")
    print("下一步：python apply_timeline.py 把 frames_source 回写 storyboard.json 的 duration_sec")


if __name__ == "__main__":
    main()
