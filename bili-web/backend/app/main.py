from pathlib import Path
from urllib.parse import quote, urlparse

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .bilibili import BiliClient, BiliError
from .config import settings
from .login import login_manager
from .models import CookieCheckRequest, CookieCheckResponse, DownloadRequest, DownloadTaskView, LoginPollRequest, LoginPollResponse, LoginQRCodeResponse, ParsedVideo, ParseRequest, TaskListResponse
from .tasks import task_manager


app = FastAPI(title=settings.app_name)


@app.on_event("startup")
def on_startup() -> None:
    settings.download_dir.mkdir(parents=True, exist_ok=True)
    task_manager.cleanup_old_files(force=True)


@app.get("/api/health")
def health() -> dict[str, str | int]:
    return {"status": "ok", "retention_hours": settings.file_retention_hours}


@app.get("/api/image/proxy")
def proxy_image(url: str, download: bool = False, filename: str = "cover") -> Response:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc.endswith(("hdslb.com", "bilibili.com")):
        raise HTTPException(status_code=400, detail="Invalid image url")

    safe_url = parsed._replace(scheme="https").geturl()
    try:
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            response = client.get(
                safe_url,
                headers={
                    "User-Agent": settings.user_agent,
                    "Referer": "https://www.bilibili.com/",
                },
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=400, detail="Image fetch failed") from exc

    content_type = response.headers.get("content-type", "image/jpeg")
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Not an image")
    headers = {}
    if download:
        ext = content_type.split("/")[-1].split(";")[0] or "jpg"
        safe_name = "".join(char if char not in '\\/:*?"<>|\r\n' else "_" for char in filename).strip(" .") or "cover"
        headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(safe_name)}.{ext}"
    return Response(content=response.content, media_type=content_type, headers=headers)


@app.post("/api/parse", response_model=ParsedVideo)
def parse_video(request: ParseRequest) -> ParsedVideo:
    client = BiliClient(request.bili_cookie)
    try:
        return client.parse(request.url, request.page)
    except BiliError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        client.close()


@app.post("/api/cookie/check", response_model=CookieCheckResponse)
def check_cookie(request: CookieCheckRequest) -> CookieCheckResponse:
    client = BiliClient(request.bili_cookie)
    try:
        return CookieCheckResponse(**client.check_login())
    except BiliError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        client.close()


@app.post("/api/login/qrcode", response_model=LoginQRCodeResponse)
def create_login_qrcode() -> LoginQRCodeResponse:
    try:
        return LoginQRCodeResponse(**login_manager.create())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/login/poll", response_model=LoginPollResponse)
def poll_login(request: LoginPollRequest) -> LoginPollResponse:
    try:
        return LoginPollResponse(**login_manager.poll(request.session_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/download", response_model=DownloadTaskView)
def create_download(request: DownloadRequest) -> DownloadTaskView:
    task = task_manager.create(
        request.url,
        request.page,
        request.quality,
        request.kind,
        request.bili_cookie,
    )
    return task.view()


@app.get("/api/tasks/{task_id}", response_model=DownloadTaskView)
def get_task(task_id: str) -> DownloadTaskView:
    task = task_manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.view()


@app.get("/api/tasks", response_model=TaskListResponse)
def list_tasks() -> TaskListResponse:
    return TaskListResponse(
        tasks=[task.view() for task in task_manager.list()],
        retention_hours=settings.file_retention_hours,
        download_dir=str(settings.download_dir),
    )


@app.post("/api/tasks/{task_id}/cancel", response_model=DownloadTaskView)
def cancel_task(task_id: str) -> DownloadTaskView:
    task = task_manager.cancel(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.view()


@app.post("/api/tasks/cleanup")
def cleanup_tasks() -> dict[str, int]:
    return {"removed": task_manager.cleanup_old_files(force=True)}


@app.get("/api/files/{task_id}")
def get_file(task_id: str) -> FileResponse:
    task = task_manager.get(task_id)
    if not task or not task.file_path or not task.file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(task.file_path, filename=task.file_name)


frontend_dir = settings.frontend_dir
if Path(frontend_dir).exists():
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
