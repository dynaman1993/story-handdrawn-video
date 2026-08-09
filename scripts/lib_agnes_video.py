"""lib_agnes_video.py — Agnes Video V2.0 HTTP 客户端

直连 https://api.agnes-ai.cn/v1/videos 创建任务，
GET /agnesapi?video_id= 轮询结果，下载最终 mp4。

模型：agnes-video-v2.0
当前 $0/秒（促销价），未来恢复 $0.005/秒。

设计要点：
- 纯文生视频（本 skill 不传 image / extra_body.image）
- 异步：create 返回 task_id + video_id，轮询 video_id
- 500/502/503/504 指数退避重试（和 lib_agnes.py 一致）
- API key 查找顺序：环境变量 AGNES_API_KEY > 当前目录 .env
  > 父目录 .env > 父父目录 .env（兼容项目根 / monorepo 布局）
- 同一 key 在 api.agnes-ai.cn（图片端点同 host）可用
"""
from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_MODEL = "agnes-video-v2.0"
# 注意：文档写的是 apihub.agnes-ai.com，但该 host 对中国站 key 返回 401。
# 实测同一把 AGNES_API_KEY 在 api.agnes-ai.cn（图片端点同 host）可用。
DEFAULT_BASE_URL = "https://api.agnes-ai.cn"
DEFAULT_CREATE_TIMEOUT = 60
DEFAULT_POLL_TIMEOUT = 30
DEFAULT_DOWNLOAD_TIMEOUT = 300
MAX_RETRIES = 6
POLL_INTERVAL_SEC = 8
POLL_MAX_WAIT_SEC = 900  # 单段视频最多等 15 分钟（长片段 14s 实测 150s+）
# 视频端点 create 请求限流：免费 key 1 次/分钟。429 时等 65s 再试。
RATE_LIMIT_WAIT_SEC = 65


def _load_env_file() -> None:
    """从候选路径读 .env，注入 AGNES_* 变量。

    查找顺序：当前目录 .env → 父目录 .env → 父父目录 .env。
    找到 AGNES_API_KEY 即停止（不覆盖已存在的环境变量）。
    """
    if os.environ.get("AGNES_API_KEY"):
        return
    candidates = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
        Path.cwd().parent.parent / ".env",
    ]
    for env_path in candidates:
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k.startswith("AGNES_"):
                os.environ.setdefault(k, v)
        if os.environ.get("AGNES_API_KEY"):
            return


_load_env_file()


def _resolve_api_key() -> str:
    key = os.environ.get("AGNES_API_KEY")
    if not key:
        raise RuntimeError(
            "AGNES_API_KEY 未设置。请在以下任一位置创建 .env 并加一行：\n"
            "  ./（项目根目录）/.env\n"
            "  AGNES_API_KEY=sk-...\n"
            "或直接设置环境变量 AGNES_API_KEY。"
        )
    return key


def _resolve_base_url() -> str:
    return os.environ.get("AGNES_VIDEO_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _request(method: str, url: str, payload: dict | None = None,
             timeout: int = DEFAULT_POLL_TIMEOUT) -> dict:
    key = _resolve_api_key()
    data = None
    headers = {"Authorization": f"Bearer {key}"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            # 429 是免费 key 的创建限流（1 req/min），等 65s 再试
            if e.code == 429 and attempt < MAX_RETRIES - 1:
                print(f"  ⚠️ agnes-video HTTP 429 限流（attempt {attempt+1}/{MAX_RETRIES}），{RATE_LIMIT_WAIT_SEC}s 后重试")
                time.sleep(RATE_LIMIT_WAIT_SEC)
                last_err = RuntimeError(f"HTTP 429: {err_body[:200]}")
                continue
            if e.code in (500, 502, 503, 504) and attempt < MAX_RETRIES - 1:
                wait = 5 * (2 ** attempt)
                print(f"  ⚠️ agnes-video HTTP {e.code}（attempt {attempt+1}/{MAX_RETRIES}），{wait}s 后重试")
                time.sleep(wait)
                last_err = RuntimeError(f"HTTP {e.code}: {err_body[:200]}")
                continue
            raise RuntimeError(f"agnes-video HTTP {e.code}: {err_body[:500]}") from None
        except (urllib.error.URLError, TimeoutError,
                http.client.RemoteDisconnected, http.client.BadStatusLine,
                ConnectionResetError, ConnectionAbortedError) as e:
            if attempt < MAX_RETRIES - 1:
                wait = 5 * (2 ** attempt)
                print(f"  ⚠️ agnes-video 网络错 ({type(e).__name__})，{wait}s 后重试")
                time.sleep(wait)
                last_err = e
                continue
            raise RuntimeError(f"agnes-video 网络失败: {type(e).__name__}: {e}") from None
    raise RuntimeError(f"agnes-video 重试 {MAX_RETRIES} 次仍失败: {last_err}")


def create_task(
    prompt: str,
    *,
    negative_prompt: str | None = None,
    width: int = 720,
    height: int = 1280,
    num_frames: int = 121,
    frame_rate: int = 24,
    model: str = DEFAULT_MODEL,
    seed: int | None = None,
) -> dict:
    """创建视频生成任务，返回 {task_id, video_id, ...}。"""
    if num_frames > 441:
        raise ValueError(f"num_frames 必须 ≤ 441，收到 {num_frames}")
    if (num_frames - 1) % 8 != 0:
        raise ValueError(f"num_frames 必须满足 8n+1，收到 {num_frames}")

    payload: dict = {
        "model": model,
        "prompt": prompt,
        "width": width,
        "height": height,
        "num_frames": num_frames,
        "frame_rate": frame_rate,
    }
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt
    if seed is not None:
        payload["seed"] = seed

    data = _request("POST", f"{_resolve_base_url()}/v1/videos", payload,
                    timeout=DEFAULT_CREATE_TIMEOUT)
    video_id = data.get("video_id") or data.get("task_id") or data.get("id")
    if not video_id:
        raise RuntimeError(f"agnes-video 创建响应缺 video_id: {json.dumps(data)[:500]}")
    return data


def _extract_url(data: dict) -> str | None:
    """从任务响应取 mp4 URL。兼容国际站 metadata.url 和中国站顶层 url。"""
    url = data.get("url")
    if url:
        return url
    meta = data.get("metadata") or {}
    return meta.get("url")


def poll_video(video_id: str,
               interval: int = POLL_INTERVAL_SEC,
               max_wait: int = POLL_MAX_WAIT_SEC) -> dict:
    """轮询直到 completed/failed。返回最终任务对象（含顶层 url 或 metadata.url）。"""
    url = f"{_resolve_base_url()}/agnesapi?video_id={video_id}"
    start = time.time()
    while True:
        data = _request("GET", url, timeout=DEFAULT_POLL_TIMEOUT)
        status = data.get("status") or data.get("internal_status") or "unknown"
        progress = data.get("progress") or data.get("internal_progress") or 0
        elapsed = int(time.time() - start)
        print(f"  [{video_id[:16]}…] {status} {progress}% ({elapsed}s)")

        if status == "completed":
            if not _extract_url(data):
                raise RuntimeError(f"任务 completed 但缺 url: {json.dumps(data)[:500]}")
            return data
        if status == "failed":
            err = data.get("error")
            raise RuntimeError(f"视频任务失败: {json.dumps(err, ensure_ascii=False)[:500]}")
        if elapsed > max_wait:
            raise RuntimeError(f"视频任务超时（{max_wait}s），最后状态: {status} {progress}%")
        time.sleep(interval)


def download(url: str, out_path: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "story-handdrawn-video"})
            with urllib.request.urlopen(req, timeout=DEFAULT_DOWNLOAD_TIMEOUT) as resp:
                out_path.write_bytes(resp.read())
            if out_path.stat().st_size < 20_000:
                raise RuntimeError(f"下载文件过小 ({out_path.stat().st_size}B)，疑似损坏")
            return out_path
        except (http.client.IncompleteRead, http.client.RemoteDisconnected,
                ConnectionResetError, ConnectionAbortedError,
                urllib.error.URLError, TimeoutError, RuntimeError) as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                wait = 5 * (2 ** attempt)
                print(f"  ⚠️ 下载失败 ({type(e).__name__}: {e})，{wait}s 后重试")
                time.sleep(wait)
                continue
            raise RuntimeError(f"下载失败 {MAX_RETRIES} 次: {type(e).__name__}: {e}") from None
    raise RuntimeError(f"下载失败: {last_err}")


def generate_video(
    prompt: str,
    out_path: str | Path,
    *,
    negative_prompt: str | None = None,
    width: int = 720,
    height: int = 1280,
    num_frames: int = 121,
    frame_rate: int = 24,
    seed: int | None = None,
) -> dict:
    """一站式：创建 → 轮询 → 下载。返回最终任务 data。"""
    created = create_task(
        prompt,
        negative_prompt=negative_prompt,
        width=width, height=height,
        num_frames=num_frames, frame_rate=frame_rate,
        seed=seed,
    )
    video_id = created.get("video_id") or created.get("task_id") or created.get("id")
    final = poll_video(video_id)  # type: ignore[arg-type]
    out = _extract_url(final)
    if not out:
        raise RuntimeError("最终响应缺 url")
    download(out, Path(out_path))
    return final


if __name__ == "__main__":
    key = _resolve_api_key()
    print(f"AGNES_API_KEY: {key[:8]}...{key[-4:]}")
    print(f"BASE_URL: {_resolve_base_url()}")
    print("OK（未发测试请求，节省配额）")
