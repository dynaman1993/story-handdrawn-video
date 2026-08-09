# Pipeline 细节

## 总流程

```
story.txt
  ↓ splitStory（按 。！？；切，超长按 ，、和转折词再切）
scenes[] = {sid, caption}
  ↓ 写 narration.yaml（id=s01/s02，文本=caption）
edge-tts (并发)  → public/audio/narration/sXX.mp3
  ↓ ffprobe
每段 duration_sec
  ↓ 算 num_frames (24fps, 8n+1, ≤441)
每段 prompt (STYLE_HEADER + scene body + MOTION_FOOTER + NEGATIVE)
  ↓ POST /v1/videos (4 路并发)
task_id / video_id
  ↓ GET /agnesapi?video_id= 轮询（8s 间隔，最长 10min）
metadata.url
  ↓ 下载
public/assets/videos/sXX.mp4
  ↓
storyboard.json
  ↓
Remotion render:preview
  ↓
out/story-preview.mp4 (720×1280)
```

## TTS → 视频帧数的换算

```
duration_sec = ffprobe(sXX.mp3)
target_frames = round(duration_sec * 24)
num_frames = 8 * ceil((target_frames - 1) / 8) + 1   # 8n+1 向上取整
num_frames = min(num_frames, 441)                    # 上限 ≈18.3s
num_frames = max(num_frames, 41)                     # 下限 ≈1.7s
```

视频实际时长 = `num_frames / 24`。Remotion 场景时长用 `duration_sec`（音频时长）；
视频略长会被 Remotion 裁尾，略短会冻最后一帧。差通常在 1/24s 内，肉眼不可见。

旁白 >18s 时 num_frames 顶到 441，视频会比旁白早结束。**正确做法是把句子拆短**，
不要靠延长 num_frames 或塞静音。

## API 端点

| 用途 | 方法 + URL |
|---|---|
| 创建任务 | `POST https://apihub.agnes-ai.com/v1/videos` |
| 查结果 | `GET  https://apihub.agnes-ai.com/agnesapi?video_id=<VIDEO_ID>` |

请求头：
```
Authorization: Bearer $AGNES_API_KEY
Content-Type: application/json
```

API key 从 `D:/video-spec-builder-main/.env` 的 `AGNES_API_KEY=` 读，
和老 skill 共用一个 key（老的图片端点是 `api.agnes-ai.cn`，视频端点是
`apihub.agnes-ai.com`，两个 host 同一个 key）。

## 创建任务 payload

```json
{
  "model": "agnes-video-v2.0",
  "prompt": "<STYLE_HEADER>\\n<scene body>\\n<MOTION_FOOTER>",
  "negative_prompt": "text, letters, subtitles, ...",
  "width": 720,
  "height": 1280,
  "num_frames": 121,
  "frame_rate": 24
}
```

文档里列了 `480p / 720p / 1080p` 三档标准化输出；720×1280 就是 720p 9:16，
不会被映射到别的比例。1080×1920 是 1080p 9:16，会慢很多——preview 默认不渲。

## 轮询

- 初始 `status=queued`，然后 `in_progress`，最后 `completed` 或 `failed`。
- 每 8s GET 一次。
- 完成时 `metadata.url` 是 mp4 CDN URL，直接下载。
- 失败时 `error` 字段有原因；脚本抛异常，其他已完成段不受影响。

## storyboard.json schema

```json
{
  "title": "我的小猫",
  "width": 720,
  "height": 1280,
  "fps": 30,
  "scenes": [
    {
      "id": "s01",
      "caption": "下雨天，我在巷口捡到一只橘猫。",
      "narration": "下雨天，我在巷口捡到一只橘猫。",
      "narration_audio": "audio/narration/s01.mp3",
      "motion_video": "assets/videos/s01.mp4",
      "duration_sec": 4.82,
      "num_frames": 121,
      "prompt_snapshot": "..."
    }
  ]
}
```

Remotion 的 `src/storyboard.ts` 直接 `import storyboard.json`。
