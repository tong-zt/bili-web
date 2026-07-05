from __future__ import annotations

import base64
import io
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlencode

import httpx
import qrcode

from .config import settings


QR_STATUS_MESSAGES = {
    0: "登录成功",
    86038: "二维码已失效",
    86090: "已扫码，等待确认",
    86101: "等待扫码",
}


@dataclass
class LoginSession:
    session_id: str
    qrcode_key: str
    qrcode_url: str
    client: httpx.Client
    created_at: float = field(default_factory=time.time)
    cookie: str = ""


class LoginManager:
    def __init__(self) -> None:
        self.sessions: dict[str, LoginSession] = {}

    def create(self) -> dict:
        client = self._create_client()
        params = {
            "source": "main-fe-header",
            "go_url": "https://www.bilibili.com/",
            "web_location": "333.1007",
        }
        response = client.get(
            f"https://passport.bilibili.com/x/passport-login/web/qrcode/generate?{urlencode(params)}"
        )
        payload = response.json()
        self._check_payload(payload)

        data = payload["data"]
        session_id = uuid.uuid4().hex
        qrcode_url = self._absolute_login_url(data["url"])
        session = LoginSession(
            session_id=session_id,
            qrcode_key=data["qrcode_key"],
            qrcode_url=qrcode_url,
            client=client,
        )
        self.sessions[session_id] = session

        return {
            "session_id": session_id,
            "qrcode_url": session.qrcode_url,
            "qrcode_image": self._make_qrcode_data_url(session.qrcode_url),
            "expires_in": 180,
        }

    def poll(self, session_id: str) -> dict:
        session = self._get_session(session_id)
        response = session.client.get(
            "https://passport.bilibili.com/x/passport-login/web/qrcode/poll",
            params={"qrcode_key": session.qrcode_key},
        )
        payload = response.json()
        self._check_payload(payload)

        data = payload["data"]
        code = int(data.get("code", -1))
        is_login = code == 0
        if is_login:
            session.cookie = self._cookie_header(session.client)

        return {
            "code": code,
            "message": QR_STATUS_MESSAGES.get(code, data.get("message") or ""),
            "is_login": is_login,
            "bili_cookie": session.cookie if is_login else "",
        }

    def _create_client(self) -> httpx.Client:
        return httpx.Client(
            timeout=settings.request_timeout,
            follow_redirects=True,
            headers={
                "User-Agent": settings.user_agent,
                "Referer": "https://www.bilibili.com/",
            },
        )

    def _get_session(self, session_id: str) -> LoginSession:
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError("登录会话不存在或已过期")
        if time.time() - session.created_at > 300:
            session.client.close()
            self.sessions.pop(session_id, None)
            raise ValueError("二维码已过期，请重新生成")
        return session

    def _check_payload(self, payload: dict) -> None:
        if payload.get("code") != 0:
            raise ValueError(payload.get("message") or "Bilibili login request failed")

    def _absolute_login_url(self, url: str) -> str:
        if url.startswith("//"):
            return f"https:{url}"
        if url.startswith("/"):
            return f"https://passport.bilibili.com{url}"
        return url

    def _cookie_header(self, client: httpx.Client) -> str:
        values = []
        for cookie in client.cookies.jar:
            if cookie.domain.endswith("bilibili.com"):
                values.append(f"{cookie.name}={cookie.value}")
        return "; ".join(values)

    def _make_qrcode_data_url(self, value: str) -> str:
        image = qrcode.make(value)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"


login_manager = LoginManager()
