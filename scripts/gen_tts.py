"""gen_tts.py — 故事手绘风视频的旁白配音（edge-tts，免费）

按场景生成旁白 mp3 + timeline.json（含每段时长，供 gen_story_videos.py 读秒数对齐视频帧数）。

后端固定 edge-tts（Microsoft Edge TTS，免费、无需 API key），voice 默认
zh-CN-XiaoyiNeural 女声；英文教学（lang: en）默认 en-US-JennyNeural。
需 `pip install edge-tts`。

输入 narration.yaml（id 用 s01/s02 字符串，避免 YAML 把 01 当八进制）：
  lang: zh                    # 可选：en 时默认 voice 切 en-US-JennyNeural（英文教学）
  voice: zh-CN-XiaoyiNeural   # 可覆盖；英文用 en-US-JennyNeural
  speed: 1.0
  scenes:
    - id: s01
      text: "盛唐长安，万邦来朝……"

输出：
  public/audio/narration/s01.mp3 s02.mp3 ...
  public/audio/narration/timeline.json  # [{id, file, text, seconds}]

注意：seconds 字段供 gen_story_videos.py 按 24fps、8n+1 规则算 num_frames；
帧数计算完全在 gen_story_videos.py 内完成，本脚本不输出 frames_* 字段。
"""
from __future__ import annotations
import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

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
            "edge-tts 未安装。运行 `pip install edge-tts` 后重试。"
        )

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


# ============================================================================
# 主流程
# ============================================================================

def load_narration(path: Path) -> dict:
    import yaml  # type: ignore
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(
        description="故事手绘风视频旁白配音（edge-tts 免费）+ 生成 timeline.json",
    )
    parser.add_argument("narration_yaml", help="narration.yaml 路径")
    parser.add_argument(
        "--out-dir", default="public/audio/narration",
        help="输出目录（默认 public/audio/narration/）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印不生成")
    args = parser.parse_args()

    spec = load_narration(Path(args.narration_yaml))
    # voice 选择优先级：yaml 显式 voice > yaml lang 字段 > 默认
    # 英文教学故事（lang: en）默认用 en-US-JennyNeural
    yaml_lang = spec.get("lang", "zh")
    default_voice = EDGE_DEFAULT_VOICE_EN if yaml_lang == "en" else EDGE_DEFAULT_VOICE
    voice = spec.get("voice", default_voice)
    speed = float(spec.get("speed", 1.0))
    scenes = spec["scenes"]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"backend=edge, voice={voice}, speed={speed}, scenes={len(scenes)}")

    timeline = []
    for sc in scenes:
        sid = sc["id"]
        text = sc["text"].strip()
        out_path = out_dir / f"{sid}.mp3"
        print(f"[{sid}] {text[:30]}...")

        if args.dry_run:
            print(f"  (dry-run) voice={voice} speed={speed}")
            continue

        if out_path.exists():
            print(f"  已存在，跳过（删掉可重新生成）")
        else:
            call_tts_edge(text, out_path, voice=voice, speed=speed)
            print(f"  生成完成")

        seconds = ffprobe_duration(out_path)
        timeline.append({
            "id": sid,
            "file": str(out_path.relative_to(out_dir.parent.parent.parent)) if out_path.parent.parent.parent in out_path.parents else str(out_path),
            "text": text,
            "seconds": round(seconds, 2),
        })
        print(f"  时长 {seconds:.2f}s")

    timeline_path = out_dir / "timeline.json"
    timeline_path.write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\ntimeline 写入 {timeline_path}")
    print("下一步：python gen_story_videos.py ... 生成视频并写 storyboard.json")


if __name__ == "__main__":
    main()
