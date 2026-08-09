"""gen_story_videos.py — 故事 → TTS → Agnes 文生视频 → storyboard.json

一条命令跑完整个素材生产链：
  1. 分句（中文按 。！？；，超长按 ，、 和转折词再切；英文按 . ! ? ;）
  2. 写 narration.yaml
  3. 跑 edge-tts（免费）→ public/audio/narration/sXX.mp3
  4. ffprobe 量真实时长
  5. 按 24fps、8n+1 规则算每场 num_frames（上限 441）
  6. 拼 prompt（STYLE_HEADER + scene body + MOTION_FOOTER；固定 negative）
  7. 并发提交 Agnes Video V2.0 任务 → 轮询 → 下载 public/assets/videos/sXX.mp4
  8. 写 storyboard.json（Remotion 直接 import）

硬规则：
- 已存在的 mp3/mp4 自动跳过（省钱省时间）
- 失败的单段不影响其他段；最后汇总失败列表
- prompt 里 STYLE_HEADER / MOTION_FOOTER / NEGATIVE 固定
- 没有 visual_plan 时用中文原句作为 scene body（Agnes 视频模型理解中文，
  negative_prompt 负责抑制画面里出现文字）
- 有 visual_plan 时，那场用用户写的英文 scene body（质量更高、无乱码风险）
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import lib_agnes_video as agnes  # noqa: E402

# ----------------------------------------------------------------------------
# 风格常量（三段式 prompt）
# ----------------------------------------------------------------------------

STYLE_HEADER_CRAYON = (
    "modern Q-version hand-drawn crayon illustration, vertical 9:16, solid warm-white "
    "canvas background with exact base color #F8F6EF, only extremely subtle low-contrast "
    "paper grain, thick imperfect black hand-drawn marker/crayon outlines, bold flat "
    "wax-crayon blocks in sunflower yellow, saturated cobalt blue, vivid tomato red "
    "with a small muted-green accent, natural restrained Q-version proportions, simple "
    "hand-drawn composition, 2-4 large readable visual groups, generous breathing room, "
    "no glossy rendering, no realistic lighting, no 3D, no watermark"
)

MOTION_FOOTER_CRAYON = (
    "locked flat frontal camera, rigid paper cutouts, tactile 10-12 fps paper stop-motion, "
    "one or two small object bounces or a short hinge-like hand movement, no zoom, no "
    "parallax, no camera drift, no liquid morphing, no lip sync, no new characters, "
    "no added logos or text, settle and hold the final composition naturally"
)

STYLE_HEADER_TEXTBOOK = (
    "clean educational textbook illustration for adult English learners, vertical 9:16, "
    "soft warm-white background, a narrative scene that clearly illustrates the meaning "
    "of the sentence, simple colorful flat illustration in the style of an Oxford English "
    "textbook, soft bright educational palette (cobalt blue, warm red, mustard yellow, "
    "sage green), clean confident outlines, clear readable subject and action, "
    "tasteful simple setting or landscape where the scene needs it, "
    "no text, no letters, no words, no numbers anywhere in the image, "
    "no realistic shading, no paper texture, no 3D, no watermark, "
    "no crayon texture, no painterly brush strokes"
)

MOTION_FOOTER_TEXTBOOK = (
    "locked steady camera, gentle but visible motion that supports the sentence meaning "
    "(a ship sailing, a quill writing, figures walking or gesturing, a flag waving, "
    "pages turning, light shifting), smooth 12-15 fps animation, no zoom, "
    "no parallax, no camera drift, no morphing, no lip sync, no new characters, "
    "no added logos or text, hold the final composition clearly"
)

STYLE_PRESETS = {
    "crayon": (STYLE_HEADER_CRAYON, MOTION_FOOTER_CRAYON),
    "textbook": (STYLE_HEADER_TEXTBOOK, MOTION_FOOTER_TEXTBOOK),
}

NEGATIVE_PROMPT = (
    "text, letters, subtitles, captions, Chinese characters, English words, numbers, "
    "watermark, logo, signature, border frame, photorealistic, 3D render, gradient "
    "background, vignette, black background, glossy, neon"
)

# ----------------------------------------------------------------------------
# 分句（从老 skill gen_story_images.py 精简移植）
# ----------------------------------------------------------------------------

TERMINAL_PUNCT = re.compile(r"[。！？!?；;]$")
NARRATIVE_TURN = re.compile(
    r"^(后来|然后|接着|突然|可是|但是|但|却|于是|直到|最后|没想到|第二天|那天|这时)"
)


def hard_chunk(value: str, max_length: int = 36) -> list[str]:
    chunks: list[str] = []
    remaining = value.strip()
    while len(remaining) > max_length:
        window = remaining[: max_length + 1]
        cut = max(window.rfind("，"), window.rfind("、"), window.rfind("；"))
        if cut < max_length * 0.55:
            cut = max_length
        else:
            cut += 1
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def split_long_beat(sentence: str, soft_limit: int = 36) -> list[str]:
    value = sentence.strip()
    if len(value) <= soft_limit:
        return [value]
    m = TERMINAL_PUNCT.search(value)
    ending = m.group(0) if m else ""
    body = value[: -len(ending)] if ending else value
    clauses = re.split(
        r"(?<=，|、)|(?=(?:后来|然后|接着|突然|可是|但是|但|却|于是|直到|最后|没想到|第二天|那天|这时))",
        body,
    )
    clauses = [c.strip() for c in clauses if c.strip()]
    if len(clauses) == 1:
        return hard_chunk(value, soft_limit)
    beats: list[str] = []
    current = ""
    for clause in clauses:
        candidate = f"{current}{clause}"
        starts_new = bool(NARRATIVE_TURN.match(clause)) and len(current) >= 12
        if current and (len(candidate) > soft_limit or starts_new):
            beats.append(re.sub(r"[，、]$", "。", current))
            current = clause
        else:
            current = candidate
    if current:
        beats.append(f"{re.sub(r'[，、]$', '', current)}{ending or '。'}")
    return [b for beat in beats for b in hard_chunk(beat, soft_limit)]


def split_story(text: str) -> list[str]:
    normalized = re.sub(r"\r", "", re.sub(r"[ \t]+", " ", text)).strip()
    paragraphs = [p.strip() for p in re.split(r"\n+", normalized) if p.strip()]
    beats: list[str] = []
    for para in paragraphs:
        sentences = re.findall(r"[^。！？!?；;]+[。！？!?；;]?", para)
        for sent in sentences:
            beats.extend(split_long_beat(sent))
    return [
        (b if TERMINAL_PUNCT.search(b) else f"{b}。")
        for b in map(str.strip, beats)
        if b
    ]


EN_TERMINAL_PUNCT = re.compile(r"[.!?;]$")
EN_TURN_SPLIT = re.compile(
    r"\s+(?:and|but|because|so|then|when|while|after|before|although|though|"
    r"since|unless|until|if|as|once|where|whereas)\b"
)


def split_long_beat_en(sentence: str, soft_limit: int = 120) -> list[str]:
    value = sentence.strip()
    if len(value) <= soft_limit:
        return [value]
    m = EN_TERMINAL_PUNCT.search(value)
    ending = m.group(0) if m else ""
    body = value[: -len(ending)] if ending else value
    body = body.rstrip(",;: ")
    clauses = re.split(r"(?<=[,;:])\s+", body)
    expanded: list[str] = []
    for c in clauses:
        expanded.extend(EN_TURN_SPLIT.split(c))
    clauses = [c.strip() for c in expanded if c.strip()]
    if len(clauses) == 1:
        words = body.split()
        chunks: list[str] = []
        cur: list[str] = []
        cur_len = 0
        for w in words:
            add = len(w) + (1 if cur else 0)
            if cur and cur_len + add > soft_limit:
                chunks.append(" ".join(cur))
                cur, cur_len = [w], len(w)
            else:
                cur.append(w)
                cur_len += add
        if cur:
            chunks.append(" ".join(cur))
        result = chunks
    else:
        beats: list[str] = []
        current = ""
        for clause in clauses:
            candidate = f"{current} {clause}".strip() if current else clause
            if current and len(candidate) > soft_limit:
                beats.append(current.rstrip(",;:"))
                current = clause
            else:
                current = candidate
        if current:
            beats.append(current.rstrip(",;:"))
        result = beats
    return [b if EN_TERMINAL_PUNCT.search(b) else f"{b}{ending or '.'}" for b in result]


def split_story_en(text: str) -> list[str]:
    normalized = re.sub(r"\r", "", re.sub(r"[ \t]+", " ", text)).strip()
    paragraphs = [p.strip() for p in re.split(r"\n+", normalized) if p.strip()]
    beats: list[str] = []
    for para in paragraphs:
        sentences = re.split(r"(?<=[.!?;])\s+", para)
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            if not EN_TERMINAL_PUNCT.search(sent):
                sent = f"{sent}."
            beats.extend(split_long_beat_en(sent))
    return [b for b in beats if b]


def split_paragraphs(text: str) -> list[str]:
    """每个空行段落即一拍，不再按逗号/连词拆分。

    用于 LRC 已切片的项目：story.txt 每段对应一段已切好的 mp3，
    句子再长也必须保持为一个场景（视频帧数由旁白时长决定，超长会自动截到上限）。
    """
    normalized = re.sub(r"\r", "", re.sub(r"[ \t]+", " ", text)).strip()
    return [p.strip() for p in re.split(r"\n+", normalized) if p.strip()]


# ----------------------------------------------------------------------------
# 工具：ffprobe、帧数、prompt
# ----------------------------------------------------------------------------

def ffprobe_duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {proc.stderr}")
    return float(proc.stdout.strip())


def nearest_8n_plus_1(target_frames: int, lo: int = 41, hi: int = 441) -> int:
    n = max(lo, min(hi, 8 * math.ceil((target_frames - 1) / 8) + 1))
    return n


def build_prompt(scene_body: str, style: str = "crayon") -> str:
    header, footer = STYLE_PRESETS.get(style, STYLE_PRESETS["crayon"])
    return f"{header}\n\n{scene_body.strip()}\n\n{footer}"


def load_visual_plan(path: Path | None) -> dict[str, str]:
    if not path or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in data.items()}


def load_teaching_content(path: Path | None) -> dict[str, dict]:
    """textbook 教学内容：{sid: {keyword, ipa, meaning, definition, example, visual?}}。"""
    if not path or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): dict(v) for k, v in data.items()}


def resolve_scene_body(visual_plan: dict[str, str], sid: str, idx: int, caption: str,
                       teaching: dict | None = None) -> str:
    """Look up by s01 / 01 / 1 forms.

    Priority: teaching_content[sid].visual > visual_plan[sid] > 01/1 keys > caption.
    """
    if teaching:
        t = teaching.get(sid) or teaching.get(f"{idx:02d}") or teaching.get(str(idx))
        if t and t.get("visual"):
            return str(t["visual"])
    return (
        visual_plan.get(sid)
        or visual_plan.get(f"{idx:02d}")
        or visual_plan.get(str(idx))
        or caption
    )


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------

def run_tts(narration_yaml: Path) -> None:
    """调 gen_tts.py 子进程（edge-tts 免费，无需 API key）。"""
    cmd = [
        sys.executable,
        str(Path(__file__).parent / "gen_tts.py"),
        str(narration_yaml),
        "--out-dir", "public/audio/narration",
    ]
    print("$", " ".join(cmd))
    result = subprocess.run(cmd, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"gen_tts.py 退出码 {result.returncode}")


def submit_one_video(sid: str, scene_body: str, width: int, height: int,
                     num_frames: int, frame_rate: int, out_path: Path,
                     style: str = "crayon") -> tuple[str, str, dict]:
    """提交一段视频并阻塞到下载完成。返回 (sid, status, data)。"""
    if out_path.exists() and out_path.stat().st_size > 20_000:
        print(f"[{sid}] 已存在，跳过")
        return sid, "skipped", {}
    prompt = build_prompt(scene_body, style=style)
    print(f"[{sid}] 提交视频任务（{width}x{height}, {num_frames} frames @ {frame_rate}fps）...")
    t0 = time.time()
    try:
        final = agnes.generate_video(
            prompt=prompt,
            out_path=out_path,
            negative_prompt=NEGATIVE_PROMPT,
            width=width,
            height=height,
            num_frames=num_frames,
            frame_rate=frame_rate,
        )
        dur = time.time() - t0
        size_kb = out_path.stat().st_size // 1024
        print(f"[{sid}] 完成（{dur:.0f}s, {size_kb}KB）")
        return sid, "ok", final
    except Exception as e:
        print(f"[{sid}] 失败: {e}", file=sys.stderr)
        return sid, "failed", {"error": str(e)}


def main() -> None:
    p = argparse.ArgumentParser(description="故事 → TTS → Agnes 文生视频 → storyboard.json")
    p.add_argument("story_txt", help="故事文本路径（UTF-8）")
    p.add_argument("--title", default="", help="项目标题（写入 storyboard.json）")
    p.add_argument("--visual-plan", default=None, help="visual_plan.json 路径")
    p.add_argument("--teaching-content", default=None,
                   help="teaching_content.json 路径（textbook 模式）；含 keyword/ipa/meaning/definition/example/visual")
    p.add_argument("--lang", choices=["zh", "en"], default="zh")
    p.add_argument("--width", type=int, default=720)
    p.add_argument("--height", type=int, default=1280)
    p.add_argument("--frame-rate", type=int, default=24)
    p.add_argument("--max-seconds", type=float, default=18.0)
    p.add_argument("--concurrency", type=int, default=1,
                   help="并发数。免费 Agnes Video key 限流 1 req/min，默认 1；调高会大量 429")
    p.add_argument("--style", choices=sorted(STYLE_PRESETS.keys()), default="crayon",
                   help="视觉风格：crayon=Q版蜡笔（默认，童话/生活）；textbook=牛津教材风（教学/口播/历史）")
    p.add_argument("--skip-tts", action="store_true", help="跳过 TTS（复用已有 mp3）")
    p.add_argument("--paragraph-beats", action="store_true",
                   help="每个空行段落即一拍，不按逗号/连词再拆（适合 LRC 已切片的项目）")
    p.add_argument("--skip-video", action="store_true", help="跳过视频生成（只重写 storyboard）")
    p.add_argument("--dry-run", action="store_true", help="只打印 prompt 和参数，不发任何生成请求")
    args = p.parse_args()

    project_root = Path.cwd()
    story_path = Path(args.story_txt)
    if not story_path.is_absolute():
        story_path = project_root / story_path
    text = story_path.read_text(encoding="utf-8")

    if args.paragraph_beats:
        captions = split_paragraphs(text)
    elif args.lang == "en":
        captions = split_story_en(text)
    else:
        captions = split_story(text)

    if not captions:
        raise SystemExit("分句结果为空，检查 story.txt")

    print(f"分句完成：{len(captions)} 场")
    for i, c in enumerate(captions, 1):
        print(f"  s{i:02d}: {c}")

    # 写 narration.yaml
    audio_dir = project_root / "public" / "audio" / "narration"
    video_dir = project_root / "public" / "assets" / "videos"
    audio_dir.mkdir(parents=True, exist_ok=True)
    video_dir.mkdir(parents=True, exist_ok=True)

    default_voice = "en-US-JennyNeural" if args.lang == "en" else "zh-CN-XiaoyiNeural"
    narration_yaml = project_root / "narration.yaml"
    lines = [
        f'lang: {args.lang}',
        f'voice: {default_voice}',
        "speed: 1.0",
        "scenes:",
    ]
    for i, cap in enumerate(captions, 1):
        sid = f"s{i:02d}"
        safe = cap.replace('"', '\\"')
        lines.append(f'  - id: {sid}')
        lines.append(f'    text: "{safe}"')
    narration_yaml.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"narration.yaml 写入 {narration_yaml}")

    visual_plan = load_visual_plan(Path(args.visual_plan) if args.visual_plan else None)
    teaching = load_teaching_content(Path(args.teaching_content) if args.teaching_content else None)
    if args.style == "textbook" and not teaching:
        print("⚠️ textbook 模式建议提供 --teaching-content teaching_content.json（含 keyword/ipa/meaning/definition/example/visual）")

    if args.dry_run:
        print("\n=== DRY RUN：以下为每场 prompt ===\n")
        for i, cap in enumerate(captions, 1):
            sid = f"s{i:02d}"
            body = resolve_scene_body(visual_plan, sid, i, cap, teaching)
            print(f"--- {sid} ---")
            print(build_prompt(body, style=args.style))
            print(f"[negative] {NEGATIVE_PROMPT}\n")
        return

    # TTS
    if args.skip_tts:
        print("跳过 TTS（--skip-tts）")
    else:
        run_tts(narration_yaml)

    # 读 timeline.json 拿每段时长
    timeline_path = audio_dir / "timeline.json"
    if not timeline_path.exists():
        raise SystemExit(f"找不到 {timeline_path}，先跑 TTS")
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    seconds_by_id = {item["id"]: float(item["seconds"]) for item in timeline}

    # 准备每场任务
    jobs: list[dict] = []
    max_frames = nearest_8n_plus_1(int(args.max_seconds * args.frame_rate))
    for i, cap in enumerate(captions, 1):
        sid = f"s{i:02d}"
        sec = seconds_by_id.get(sid)
        if sec is None:
            print(f"⚠️ {sid} 在 timeline.json 里找不到时长，跳过视频")
            continue
        target = max(1, int(round(sec * args.frame_rate)))
        num_frames = nearest_8n_plus_1(target, hi=max_frames)
        body = resolve_scene_body(visual_plan, sid, i, cap, teaching)
        out_path = video_dir / f"{sid}.mp4"
        jobs.append({
            "sid": sid, "caption": cap, "body": body,
            "duration_sec": round(sec, 2), "num_frames": num_frames,
            "out_path": out_path,
        })

    # 并发提交视频
    if args.skip_video:
        print("跳过视频生成（--skip-video）")
    else:
        print(f"\n开始并发生成视频（concurrency={args.concurrency}）...")
        failures: list[str] = []
        with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
            futures = {
                ex.submit(
                    submit_one_video,
                    j["sid"], j["body"], args.width, args.height,
                    j["num_frames"], args.frame_rate, j["out_path"],
                    args.style,
                ): j for j in jobs
            }
            for fut in as_completed(futures):
                sid, status, data = fut.result()
                if status == "failed":
                    failures.append(sid)
        if failures:
            print(f"\n⚠️ {len(failures)} 场失败: {', '.join(failures)}", file=sys.stderr)
            print("其他场已完成；删对应 mp4 后重跑脚本即可续跑。", file=sys.stderr)
        else:
            print("\n全部视频片段生成完成。")

    # 写 storyboard.json
    scenes_out = []
    for j in jobs:
        mp4 = j["out_path"]
        sid = j["sid"]
        scene = {
            "id": sid,
            "caption": j["caption"],
            "narration": j["caption"],
            "text": j["caption"],
            "narration_audio": "audio/narration/" + mp4.with_suffix(".mp3").name,
            "motion_video": "assets/videos/" + mp4.name,
            "duration_sec": j["duration_sec"],
            "num_frames": j["num_frames"],
            "prompt_snapshot": build_prompt(j["body"], style=args.style),
        }
        t = teaching.get(sid) if teaching else None
        if t:
            for field in ("keyword", "ipa", "meaning", "definition", "example"):
                if t.get(field):
                    scene[field] = t[field]
        scenes_out.append(scene)
    storyboard = {
        "title": args.title or story_path.stem,
        "lang": args.lang,
        "style": args.style,
        "width": args.width,
        "height": args.height,
        "fps": 30,
        "frame_rate_video": args.frame_rate,
        "scenes": scenes_out,
    }
    sb_path = project_root / "storyboard.json"
    sb_path.write_text(json.dumps(storyboard, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nstoryboard.json 写入 {sb_path}")
    print("下一步：npm run dev 检查排版，然后 npm run render:preview 出片。")


if __name__ == "__main__":
    main()
