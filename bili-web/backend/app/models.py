from enum import Enum
from pydantic import BaseModel, Field


class StreamKind(str, Enum):
    video = "video"
    audio = "audio"
    merged = "merged"


class ParseRequest(BaseModel):
    url: str = Field(..., min_length=2)
    page: int | None = Field(default=None, ge=1)
    bili_cookie: str | None = None


class CookieCheckRequest(BaseModel):
    bili_cookie: str | None = None


class CookieCheckResponse(BaseModel):
    is_login: bool
    uname: str = ""
    mid: int = 0
    face: str = ""
    message: str = ""


class LoginQRCodeResponse(BaseModel):
    session_id: str
    qrcode_url: str
    qrcode_image: str
    expires_in: int


class LoginPollRequest(BaseModel):
    session_id: str


class LoginPollResponse(BaseModel):
    code: int
    message: str
    is_login: bool
    bili_cookie: str = ""


class DownloadRequest(BaseModel):
    url: str = Field(..., min_length=2)
    page: int | None = Field(default=None, ge=1)
    quality: int | None = None
    kind: StreamKind = StreamKind.merged
    bili_cookie: str | None = None


class PageInfo(BaseModel):
    page: int
    cid: int
    title: str
    duration: int | None = None


class StreamInfo(BaseModel):
    id: int
    label: str
    codecs: str | None = None
    bandwidth: int | None = None


class ParsedVideo(BaseModel):
    bvid: str
    aid: int | None = None
    title: str
    owner: str | None = None
    owner_face: str | None = None
    cover: str | None = None
    duration: int | None = None
    page_count: int = 0
    selected_page_title: str = ""
    selected_page_duration: int | None = None
    quality_summary: str = ""
    requires_login_for_high_quality: bool = False
    pages: list[PageInfo]
    video_streams: list[StreamInfo]
    audio_streams: list[StreamInfo]
    selected_page: int


class TaskStatus(str, Enum):
    queued = "queued"
    parsing = "parsing"
    downloading = "downloading"
    merging = "merging"
    completed = "completed"
    failed = "failed"
    canceled = "canceled"


class DownloadTaskView(BaseModel):
    id: str
    status: TaskStatus
    title: str = ""
    message: str = ""
    progress: float = 0
    total_bytes: int = 0
    downloaded_bytes: int = 0
    file_name: str | None = None
    download_url: str | None = None
    created_at: float = 0
    updated_at: float = 0
    speed_bytes: float = 0
    eta_seconds: int | None = None
    retention_hours: int = 24


class TaskListResponse(BaseModel):
    tasks: list[DownloadTaskView]
    retention_hours: int
    download_dir: str
