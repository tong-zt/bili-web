from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote

import httpx

from .bilibili import BiliClient, BiliError, MediaUrl
from .config import settings
from .models import DownloadTaskView, StreamKind, TaskStatus


def safe_name(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|\r\n]+', "_", value).strip(" .")
    return value[:120] or "bilibili-video"


class TaskCanceled(RuntimeError):
    pass


class DownloadTask:
    def __init__(self, task_id: str) -> None:
        self.id = task_id
        self.status = TaskStatus.queued
        self.title = ""
        self.message = ""
        self.progress = 0.0
        self.total_bytes = 0
        self.downloaded_bytes = 0
        self.file_name: str | None = None
        self.file_path: Path | None = None
        self.created_at = time.time()
        self.updated_at = self.created_at
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.cancel_requested = False
        self._lock = threading.Lock()

    def update(self, **kwargs) -> None:
        with self._lock:
            for key, value in kwargs.items():
                setattr(self, key, value)
            self.updated_at = time.time()

    def add_downloaded(self, byte_count: int) -> float:
        with self._lock:
            self.downloaded_bytes += byte_count
            self.progress = min(self.downloaded_bytes / max(self.total_bytes, 1) * 90, 90)
            self.updated_at = time.time()
            return self.progress

    def download_snapshot(self) -> tuple[int, float]:
        with self._lock:
            return self.downloaded_bytes, self.progress

    def request_cancel(self) -> None:
        self.update(cancel_requested=True, status=TaskStatus.canceled, message="已取消")

    def ensure_not_canceled(self) -> None:
        if self.cancel_requested:
            raise TaskCanceled("任务已取消")

    def view(self) -> DownloadTaskView:
        with self._lock:
            download_url = None
            if self.status == TaskStatus.completed and self.file_name:
                download_url = f"{settings.public_download_path}/{self.id}/{quote(self.file_name)}"
            elapsed = max((self.finished_at or time.time()) - (self.started_at or self.created_at), 0.1)
            speed = self.downloaded_bytes / elapsed if self.downloaded_bytes else 0
            remaining = max(self.total_bytes - self.downloaded_bytes, 0)
            eta = int(remaining / speed) if speed > 1 and self.status == TaskStatus.downloading else None

            return DownloadTaskView(
                id=self.id,
                status=self.status,
                title=self.title,
                message=self.message,
                progress=round(self.progress, 2),
                total_bytes=self.total_bytes,
                downloaded_bytes=self.downloaded_bytes,
                file_name=self.file_name,
                download_url=download_url,
                created_at=self.created_at,
                updated_at=self.updated_at,
                speed_bytes=round(speed, 2),
                eta_seconds=eta,
                retention_hours=settings.file_retention_hours,
            )


class TaskManager:
    def __init__(self) -> None:
        self.tasks: dict[str, DownloadTask] = {}
        self.semaphore = threading.Semaphore(settings.max_parallel_downloads)
        self._lock = threading.Lock()
        self._cleanup_lock = threading.Lock()
        self._last_cleanup = 0.0

    def create(self, url: str, page: int | None, quality: int | None, kind: StreamKind, bili_cookie: str | None = None) -> DownloadTask:
        task_id = uuid.uuid4().hex
        task = DownloadTask(task_id)
        with self._lock:
            self.tasks[task_id] = task

        thread = threading.Thread(
            target=self._run_task,
            args=(task, url, page, quality, kind, bili_cookie),
            daemon=True,
        )
        thread.start()
        return task

    def get(self, task_id: str) -> DownloadTask | None:
        return self.tasks.get(task_id)

    def list(self) -> list[DownloadTask]:
        with self._lock:
            return sorted(self.tasks.values(), key=lambda item: item.created_at, reverse=True)

    def cancel(self, task_id: str) -> DownloadTask | None:
        task = self.get(task_id)
        if task and task.status not in (TaskStatus.completed, TaskStatus.failed, TaskStatus.canceled):
            task.request_cancel()
        return task

    def cleanup_old_files(self, force: bool = False) -> int:
        now = time.time()
        if not force and now - self._last_cleanup < settings.cleanup_interval_minutes * 60:
            return 0

        with self._cleanup_lock:
            self._last_cleanup = now
            cutoff = now - settings.file_retention_hours * 3600
            removed = 0
            settings.download_dir.mkdir(parents=True, exist_ok=True)
            for path in settings.download_dir.iterdir():
                try:
                    if path.stat().st_mtime >= cutoff:
                        continue
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                    removed += 1
                except OSError:
                    continue
            return removed

    def _run_task(self, task: DownloadTask, url: str, page: int | None, quality: int | None, kind: StreamKind, bili_cookie: str | None = None) -> None:
        with self.semaphore:
            client = BiliClient(bili_cookie)
            try:
                task.ensure_not_canceled()
                self.cleanup_old_files()
                task.update(status=TaskStatus.parsing, message="正在解析视频", started_at=time.time())
                title, video, audio = client.select_media(url, page, quality)
                task.update(title=title)
                self._validate_kind(kind, video, audio)

                task_dir = settings.download_dir / task.id
                task_dir.mkdir(parents=True, exist_ok=True)

                outputs: list[Path] = []
                if kind in (StreamKind.video, StreamKind.merged) and video:
                    task.ensure_not_canceled()
                    outputs.append(self._download_media(task, client, video, task_dir / f"video.{video.ext}"))
                if kind in (StreamKind.audio, StreamKind.merged) and audio:
                    task.ensure_not_canceled()
                    outputs.append(self._download_media(task, client, audio, task_dir / f"audio.{audio.ext}"))

                if kind == StreamKind.merged and video and audio:
                    final_path = task_dir / f"{safe_name(title)}.mp4"
                    self._merge(task, outputs[0], outputs[1], final_path)
                elif kind == StreamKind.video and video and video.is_video_only:
                    final_path = task_dir / f"{safe_name(title)}.mp4"
                    self._remux(task, outputs[0], final_path)
                elif kind == StreamKind.audio and outputs:
                    final_path = task_dir / f"{safe_name(title)}.m4a"
                    if outputs[0] != final_path:
                        shutil.move(str(outputs[0]), str(final_path))
                elif outputs:
                    source = outputs[0]
                    final_path = task_dir / f"{safe_name(title)}.{source.suffix.lstrip('.')}"
                    if source != final_path:
                        shutil.move(str(source), str(final_path))
                else:
                    raise BiliError("没有可用的媒体流")

                task.update(
                    status=TaskStatus.completed,
                    message=f"已完成，文件保留 {settings.file_retention_hours} 小时",
                    progress=100,
                    file_name=final_path.name,
                    file_path=final_path,
                    finished_at=time.time(),
                )
            except TaskCanceled as exc:
                task.update(status=TaskStatus.canceled, message=str(exc), finished_at=time.time())
            except Exception as exc:
                task.update(status=TaskStatus.failed, message=str(exc), finished_at=time.time())
            finally:
                client.close()

    def _validate_kind(self, kind: StreamKind, video: MediaUrl | None, audio: MediaUrl | None) -> None:
        if kind == StreamKind.video and not video:
            raise BiliError("视频流不可用")
        if kind == StreamKind.audio and not audio:
            raise BiliError("音频流不可用")
        if kind == StreamKind.merged and not (video or audio):
            raise BiliError("没有可用的媒体流")

    def _download_media(self, task: DownloadTask, client: BiliClient, media: MediaUrl, path: Path) -> Path:
        max_bytes = settings.max_download_mb * 1024 * 1024
        if media.size > max_bytes:
            raise BiliError(f"文件超过 MAX_DOWNLOAD_MB 限制（{settings.max_download_mb} MB）")

        task.update(
            status=TaskStatus.downloading,
            total_bytes=task.total_bytes + media.size,
            message=f"正在下载 {path.name}",
        )
        headers = {
            "Referer": "https://www.bilibili.com/",
            "User-Agent": settings.user_agent,
        }
        candidates = self._rank_candidate_urls(client, media, headers)
        errors: list[str] = []
        retry_count = max(settings.download_retry_count, 1)
        for attempt in range(retry_count):
            url = candidates[attempt % len(candidates)]
            media = MediaUrl(url=url, candidates=candidates, size=media.size, ext=media.ext, stream_id=media.stream_id, codecs=media.codecs, is_video_only=media.is_video_only)
            downloaded_before, progress_before = task.download_snapshot()
            try:
                task.ensure_not_canceled()
                if media.size >= settings.chunk_download_min_mb * 1024 * 1024 and settings.chunk_download_workers > 1:
                    try:
                        self._download_media_chunked(task, client, media, path, headers)
                    except Exception as exc:
                        if isinstance(exc, TaskCanceled):
                            raise
                        path.unlink(missing_ok=True)
                        task.update(
                            downloaded_bytes=downloaded_before,
                            progress=progress_before,
                            message=f"分片下载不可用，切换单线程重试：{exc}",
                        )
                        self._download_single(task, client, media, path, headers)
                else:
                    self._download_single(task, client, media, path, headers)
                return path
            except TaskCanceled:
                path.unlink(missing_ok=True)
                raise
            except Exception as exc:
                path.unlink(missing_ok=True)
                task.update(
                    downloaded_bytes=downloaded_before,
                    progress=progress_before,
                    message=f"下载失败，正在重试 {attempt + 1}/{retry_count}",
                )
                errors.append(str(exc))
                task.ensure_not_canceled()
        raise BiliError(errors[-1] if errors else "下载失败")

    def _download_single(self, task: DownloadTask, client: BiliClient, media: MediaUrl, path: Path, headers: dict[str, str]) -> None:
        task.ensure_not_canceled()
        with client.client.stream("GET", media.url, headers=headers, timeout=120) as response:
            response.raise_for_status()
            with open(path, "wb") as file_obj:
                for chunk in response.iter_bytes(chunk_size=1024 * 512):
                    if not chunk:
                        continue
                    task.ensure_not_canceled()
                    file_obj.write(chunk)
                    task.add_downloaded(len(chunk))

    def _download_media_chunked(self, task: DownloadTask, client: BiliClient, media: MediaUrl, path: Path, headers: dict[str, str]) -> None:
        workers = max(1, min(settings.chunk_download_workers, 12))
        chunk_size = max(2 * 1024 * 1024, media.size // workers)
        ranges: list[tuple[int, int, Path]] = []
        for index, start in enumerate(range(0, media.size, chunk_size)):
            end = min(start + chunk_size - 1, media.size - 1)
            ranges.append((start, end, path.with_suffix(path.suffix + f".part{index}")))

        task.update(message=f"正在分片下载 {path.name}（{len(ranges)} 片）")
        try:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [
                    executor.submit(self._download_range, task, client, media.url, part_path, start, end, headers)
                    for start, end, part_path in ranges
                ]
                for future in as_completed(futures):
                    task.ensure_not_canceled()
                    future.result()

            with open(path, "wb") as output:
                for _, _, part_path in ranges:
                    task.ensure_not_canceled()
                    with open(part_path, "rb") as part:
                        shutil.copyfileobj(part, output, length=1024 * 1024)
        finally:
            for _, _, part_path in ranges:
                part_path.unlink(missing_ok=True)

    def _download_range(self, task: DownloadTask, client: BiliClient, url: str, path: Path, start: int, end: int, headers: dict[str, str]) -> None:
        request_headers = dict(headers)
        request_headers["Range"] = f"bytes={start}-{end}"
        if "Cookie" in client.client.headers:
            request_headers["Cookie"] = client.client.headers["Cookie"]

        with httpx.Client(timeout=httpx.Timeout(120.0, connect=settings.request_timeout), follow_redirects=True) as range_client:
            with range_client.stream("GET", url, headers=request_headers) as response:
                if response.status_code != 206:
                    raise BiliError("当前 CDN 不支持分片下载")
                response.raise_for_status()
                with open(path, "wb") as file_obj:
                    for chunk in response.iter_bytes(chunk_size=1024 * 512):
                        if not chunk:
                            continue
                        task.ensure_not_canceled()
                        file_obj.write(chunk)
                        task.add_downloaded(len(chunk))

    def _rank_candidate_urls(self, client: BiliClient, media: MediaUrl, headers: dict[str, str]) -> list[str]:
        candidates = list(dict.fromkeys([media.url, *media.candidates]))
        scores: list[tuple[float, str]] = []
        for url in candidates[:5]:
            started = time.time()
            try:
                response = client.client.head(url, headers=headers, timeout=8)
                response.raise_for_status()
                scores.append((time.time() - started, str(response.url)))
            except httpx.HTTPError:
                scores.append((999.0, url))
        ranked = [url for _, url in sorted(scores, key=lambda item: item[0])]
        return ranked or [media.url]

    def _remux(self, task: DownloadTask, source_path: Path, final_path: Path) -> None:
        self._check_ffmpeg()
        task.ensure_not_canceled()
        task.update(status=TaskStatus.merging, message="正在转换为 MP4", progress=max(task.progress, 92))
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-c",
            "copy",
            str(final_path),
        ]
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if completed.returncode != 0:
            completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if completed.returncode != 0:
                raise BiliError(completed.stderr[-1000:] or "ffmpeg 转换失败")

    def _merge(self, task: DownloadTask, video_path: Path, audio_path: Path, final_path: Path) -> None:
        self._check_ffmpeg()
        task.ensure_not_canceled()
        task.update(status=TaskStatus.merging, message="正在合并音视频", progress=max(task.progress, 92))
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(audio_path),
            "-c",
            "copy",
            str(final_path),
        ]
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if completed.returncode != 0:
            completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if completed.returncode != 0:
                raise BiliError(completed.stderr[-1000:] or "ffmpeg 合并失败")

    def _check_ffmpeg(self) -> None:
        if not shutil.which("ffmpeg"):
            raise BiliError("服务器缺少 ffmpeg，请先安装 ffmpeg 后再下载 DASH 高清视频")


task_manager = TaskManager()
