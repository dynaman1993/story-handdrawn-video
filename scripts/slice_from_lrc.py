"""slice_from_lrc.py — 用 LRC 时间戳把现成 mp3 切成每场一段，并写 timeline.json。

用于"原始 mp3 + LRC 歌词"的工作流（英语教学/播客/已有旁白），跳过 TTS。

用法：
  python slice_from_lrc.py <source.mp3> <source.lrc> \
      --out-dir public/audio/narration \
      [--pass-end 04:30.58]   # 只取第一遍到该时间戳（用于 CQ 类"讲解+复述"结构）
      [--pass-end-seconds 270.58]

输出：
  <out-dir>/s01.mp3 ... sNN.mp3   （libmp3lame 重编码）
  <out-dir>/timeline.json          [{id, seconds}, ...]
  stdout 打印分句结果
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

LINE_RE = re.compile(r"\[(\d{2}):(\d{2})\.(\d{2})\](.*)")


def ts_to_seconds(mm: str, ss: str, cs: str) -> float:
    return int(mm) * 60 + int(ss) + int(cs) / 100.0


def parse_end(value: str | None) -> float | None:
    if not value:
        return None
    m = re.match(r"^(?:(\d{1,2}):)?(\d{1,2})[:.](\d{2})$", value)
    if not m:
        raise SystemExit(f"无法解析时间戳 {value!r}，用 MM:SS.cs 或 SS.cs")
    return (int(m.group(1) or 0)) * 60 + int(m.group(2)) + int(m.group(3)) / 100.0


def parse_lrc(path: Path, pass_end: float | None) -> list[tuple[float, str, str]]:
    entries: list[tuple[float, str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        m = LINE_RE.match(raw.strip())
        if not m:
            continue
        ts = ts_to_seconds(m.group(1), m.group(2), m.group(3))
        rest = m.group(4).strip()
        if "|" in rest:
            en, zh = rest.split("|", 1)
        else:
            en, zh = rest, ""
        entries.append((ts, en.strip(), zh.strip()))
    if pass_end is not None:
        entries = [(t, e, z) for (t, e, z) in entries if t < pass_end and e]
    return entries


def ffprobe_duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {proc.stderr}")
    return float(proc.stdout.strip())


def main() -> None:
    p = argparse.ArgumentParser(description="按 LRC 切原始 mp3，写 timeline.json")
    p.add_argument("source_mp3")
    p.add_argument("source_lrc")
    p.add_argument("--out-dir", default="public/audio/narration")
    p.add_argument("--pass-end", default=None,
                   help="只取该时间戳之前的行（MM:SS.cs），用于跳过复述段")
    p.add_argument("--pass-end-seconds", type=float, default=None)
    args = p.parse_args()

    src_mp3 = Path(args.source_mp3)
    src_lrc = Path(args.source_lrc)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pass_end = args.pass_end_seconds
    if args.pass_end:
        pass_end = parse_end(args.pass_end)

    entries = parse_lrc(src_lrc, pass_end)
    if not entries:
        raise SystemExit("LRC 解析为空")

    print(f"共 {len(entries)} 段")
    timeline = []
    for i, (ts, en, zh) in enumerate(entries, 1):
        sid = f"s{i:02d}"
        nxt = entries[i][0] if i < len(entries) else (pass_end or ts + 10)
        dur = nxt - ts
        out = out_dir / f"{sid}.mp3"
        cmd = [
            "ffmpeg", "-y", "-ss", f"{ts:.3f}", "-t", f"{dur:.3f}",
            "-i", str(src_mp3), "-c:a", "libmp3lame", "-q:a", "4", str(out),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            print(r.stderr[-500:], file=sys.stderr)
            raise SystemExit(1)
        actual = ffprobe_duration(out)
        timeline.append({"id": sid, "seconds": round(actual, 2)})
        print(f"  {sid} {ts:7.2f}  {actual:6.2f}s  {en[:60]}")

    (out_dir / "timeline.json").write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out_dir / 'timeline.json'}")


if __name__ == "__main__":
    main()
