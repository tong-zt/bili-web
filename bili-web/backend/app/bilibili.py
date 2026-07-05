from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from functools import reduce
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlencode

import httpx

from .config import settings
from .models import PageInfo, ParsedVideo, StreamInfo


MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]

VIDEO_QUALITY_LABELS = {
    6: "240P",
    16: "360P",
    32: "480P",
    64: "720P",
    74: "720P60",
    80: "1080P",
    112: "1080P+",
    116: "1080P60",
    120: "4K",
    125: "HDR",
    126: "Dolby Vision",
    127: "8K",
}

AUDIO_QUALITY_LABELS = {
    30216: "64K",
    30232: "132K",
    30280: "192K",
    30250: "Dolby",
    30251: "Hi-Res",
}


@dataclass
class MediaUrl:
    url: str
    candidates: list[str]
    size: int
    ext: str
    stream_id: int
    codecs: str = ""
    is_video_only: bool = False


class BiliError(RuntimeError):
    pass


class BiliClient:
    def __init__(self, bili_cookie: str | None = None) -> None:
        self.client = httpx.Client(
            timeout=settings.request_timeout,
            follow_redirects=True,
            headers={
                "User-Agent": settings.user_agent,
                "Referer": "https://www.bilibili.com/",
            },
        )
        cookie = bili_cookie or settings.bili_cookie
        if cookie:
            self.client.headers["Cookie"] = cookie
        self._wbi_keys: tuple[str, str] | None = None

    def close(self) -> None:
        self.client.close()

    def _check_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("code") != 0:
            raise BiliError(payload.get("message") or "Bilibili API request failed")
        return payload

    def check_login(self) -> dict[str, Any]:
        payload = self._check_response(
            self.client.get("https://api.bilibili.com/x/web-interface/nav").json()
        )
        data = payload.get("data") or {}
        return {
            "is_login": bool(data.get("isLogin")),
            "uname": data.get("uname") or "",
            "mid": data.get("mid") or 0,
            "face": data.get("face") or "",
            "message": "" if data.get("isLogin") else "Cookie 无效、复制不完整，或已过期。",
        }

    def _get_wbi_keys(self) -> tuple[str, str]:
        if self._wbi_keys:
            return self._wbi_keys

        payload = self._check_response(
            self.client.get("https://api.bilibili.com/x/web-interface/nav").json()
        )
        wbi_img = payload["data"]["wbi_img"]
        img_key = Path(wbi_img["img_url"]).stem
        sub_key = Path(wbi_img["sub_url"]).stem
        self._wbi_keys = (img_key, sub_key)
        return self._wbi_keys

    def _signed_query(self, params: dict[str, Any]) -> str:
        img_key, sub_key = self._get_wbi_keys()
        mixin_key = reduce(lambda s, i: s + (img_key + sub_key)[i], MIXIN_KEY_ENC_TAB, "")[:32]
        signed = {**params, "wts": round(time.time())}
        signed = dict(sorted(signed.items()))
        cleaned = {
            key: "".join(ch for ch in str(value) if ch not in "!'()*")
            for key, value in signed.items()
        }
        query = urlencode(cleaned)
        cleaned["w_rid"] = hashlib.md5((query + mixin_key).encode()).hexdigest()
        return urlencode(cleaned)

    def resolve_url(self, value: str) -> str:
        value = value.strip()
        link = self._extract_first_url(value) or value
        parsed = urlparse(link if re.match(r"^https?://", link, re.I) else f"https://{link}")
        if self._is_short_link(parsed.netloc):
            try:
                response = self.client.get(str(parsed.geturl()), headers={"Referer": "https://www.bilibili.com/"})
                response.raise_for_status()
                return str(response.url)
            except httpx.HTTPError as exc:
                raise BiliError("短链接解析失败，请复制完整视频链接再试") from exc
        return link

    def _extract_first_url(self, value: str) -> str | None:
        match = re.search(r"https?://[^\s]+|(?:b23\.tv|bili2233\.cn|bili22\.cn|bili33\.cn)/[^\s]+", value, re.I)
        if not match:
            return None
        return match.group(0).rstrip("，。,.!！?？)")

    def _is_short_link(self, host: str) -> bool:
        host = host.lower().split(":")[0]
        return host in {"b23.tv", "bili2233.cn", "bili22.cn", "bili33.cn"}

    def extract_bvid(self, url: str) -> str:
        bvid = re.search(r"(BV[a-zA-Z0-9]{10})", url)
        if bvid:
            return bvid.group(1)

        aid = re.search(r"(?:av|AV)(\d+)", url)
        if aid:
            return self.aid_to_bvid(int(aid.group(1)))

        raise BiliError("Please enter a valid Bilibili BV, AV, or video URL")

    def extract_page(self, url: str, fallback: int | None = None) -> int:
        page = fallback or 1
        match = re.search(r"[?&]p=(\d+)", url)
        if match:
            page = int(match.group(1))
        return max(page, 1)

    def aid_to_bvid(self, aid: int) -> str:
        xor_code = 23442827791579
        max_aid = 1 << 51
        alphabet = "FcwAPNKTMug3GV5Lj7EJnHpWsx4tb8haYeviqBz6rkCy12mUSDQX9RdoZf"
        encode_map = (8, 7, 0, 5, 1, 3, 2, 4, 6)
        chars = [""] * 9
        value = (max_aid | aid) ^ xor_code
        for index in encode_map:
            chars[index] = alphabet[value % len(alphabet)]
            value //= len(alphabet)
        return "BV1" + "".join(chars)

    def get_video_view(self, url: str) -> tuple[dict[str, Any], int]:
        resolved_url = self.resolve_url(url)
        bvid = self.extract_bvid(resolved_url)
        selected_page = self.extract_page(resolved_url)
        query = self._signed_query({"bvid": bvid})
        payload = self._check_response(
            self.client.get(f"https://api.bilibili.com/x/web-interface/wbi/view?{query}").json()
        )
        return payload["data"], selected_page

    def _request_playurl(self, bvid: str, cid: int, quality: int, fnval: int) -> dict[str, Any]:
        params = {
            "bvid": bvid,
            "cid": cid,
            "qn": quality,
            "fnver": 0,
            "fnval": fnval,
            "fourk": 1,
        }
        payload = self._check_response(
            self.client.get(
                f"https://api.bilibili.com/x/player/wbi/playurl?{self._signed_query(params)}"
            ).json()
        )
        return payload["data"]

    def get_playurl(self, bvid: str, cid: int, quality: int | None = None) -> dict[str, Any]:
        try:
            return self._request_playurl(bvid, cid, quality or 127, 4048)
        except BiliError:
            # Unauthenticated requests may fail for DASH/high-quality streams.
            # Fall back to the regular MP4 endpoint so public videos remain usable.
            fallback_quality = min(quality or 64, 64)
            return self._request_playurl(bvid, cid, fallback_quality, 1)

    def parse(self, url: str, page: int | None = None) -> ParsedVideo:
        view, page_from_url = self.get_video_view(url)
        selected_page = page or page_from_url
        pages = [
            PageInfo(
                page=item["page"],
                cid=item["cid"],
                title=item.get("part") or view["title"],
                duration=item.get("duration"),
            )
            for item in view.get("pages", [])
        ]
        if not pages:
            raise BiliError("No video pages found")

        current = next((item for item in pages if item.page == selected_page), pages[0])
        playurl = self.get_playurl(view["bvid"], current.cid)
        dash = playurl.get("dash") or {}

        video_streams = self._make_video_streams(dash.get("video", []))
        audio_streams = [
            StreamInfo(
                id=item["id"],
                label=AUDIO_QUALITY_LABELS.get(item["id"], str(item["id"])),
                codecs=item.get("codecs"),
                bandwidth=item.get("bandwidth"),
            )
            for item in dash.get("audio", [])
        ]
        if not video_streams and playurl.get("durl"):
            quality_id = playurl.get("quality") or 64
            video_streams = [
                StreamInfo(
                    id=quality_id,
                    label=f"{VIDEO_QUALITY_LABELS.get(quality_id, str(quality_id))} MP4",
                    codecs=playurl.get("format"),
                    bandwidth=None,
                )
            ]

        return ParsedVideo(
            bvid=view["bvid"],
            aid=view.get("aid"),
            title=view["title"],
            owner=(view.get("owner") or {}).get("name"),
            owner_face=(view.get("owner") or {}).get("face"),
            cover=view.get("pic"),
            duration=view.get("duration"),
            page_count=len(pages),
            selected_page_title=current.title,
            selected_page_duration=current.duration,
            quality_summary=" / ".join(item.label for item in video_streams[:5]) or "自动",
            requires_login_for_high_quality=not self.check_login().get("is_login") and any(item.id >= 80 for item in video_streams),
            pages=pages,
            video_streams=video_streams,
            audio_streams=audio_streams,
            selected_page=current.page,
        )

    def _candidate_urls(self, item: dict[str, Any]) -> list[str]:
        urls: list[str] = []
        for key in ("baseUrl", "base_url", "backupUrl", "backup_url", "url"):
            value = item.get(key)
            if isinstance(value, str):
                urls.append(value)
            elif isinstance(value, list):
                urls.extend(value)
        for entry in item.get("url_entry_list", []):
            if not isinstance(entry, dict):
                continue
            for key in ("url", "backup_url", "backupUrl"):
                value = entry.get(key)
                if isinstance(value, str):
                    urls.append(value)
                elif isinstance(value, list):
                    urls.extend(value)
        return urls

    def _make_video_streams(self, videos: list[dict[str, Any]]) -> list[StreamInfo]:
        stream_map: dict[int, dict[str, Any]] = {}
        for item in videos:
            quality_id = item.get("id")
            if not quality_id:
                continue
            current = stream_map.get(quality_id)
            if current is None or self._codec_rank(item) > self._codec_rank(current):
                stream_map[quality_id] = item

        return [
            StreamInfo(
                id=quality_id,
                label=VIDEO_QUALITY_LABELS.get(quality_id, str(quality_id)),
                codecs=None,
                bandwidth=item.get("bandwidth"),
            )
            for quality_id, item in sorted(stream_map.items(), reverse=True)
        ]

    def _codec_rank(self, item: dict[str, Any]) -> tuple[int, int]:
        codecs = (item.get("codecs") or "").lower()
        if codecs.startswith("avc"):
            codec_score = 3
        elif codecs.startswith("hev") or codecs.startswith("hvc"):
            codec_score = 2
        elif codecs.startswith("av01"):
            codec_score = 1
        else:
            codec_score = 0
        return codec_score, int(item.get("bandwidth") or 0)

    def _probe_url(self, urls: list[str]) -> tuple[str, int]:
        for url in urls:
            try:
                response = self.client.head(url, headers={"Referer": "https://www.bilibili.com/"})
                response.raise_for_status()
            except httpx.HTTPError:
                continue

            content_type = response.headers.get("content-type", "")
            size = int(response.headers.get("content-length") or 0)
            if size > 1024 and "text" not in content_type:
                return str(response.url), size

        raise BiliError("Could not resolve a usable media URL")

    def select_media(self, url: str, page: int | None, quality: int | None) -> tuple[str, MediaUrl | None, MediaUrl | None]:
        view, page_from_url = self.get_video_view(url)
        selected_page = page or page_from_url
        pages = view.get("pages", [])
        current = next((item for item in pages if item["page"] == selected_page), pages[0])
        playurl = self.get_playurl(view["bvid"], current["cid"], quality)
        dash = playurl.get("dash") or {}

        video_item = self._choose_video(dash.get("video", []), quality)
        audio_item = self._choose_audio(dash.get("audio", []))

        if not video_item and playurl.get("durl"):
            video_item = {
                "id": playurl.get("quality") or quality or 64,
                "codecs": playurl.get("format") or "mp4",
                "url_entry_list": playurl["durl"],
            }

        video_ext = "mp4" if video_item and video_item.get("url_entry_list") else "m4s"
        video = self._media_url(video_item, video_ext) if video_item else None
        if video and video.ext == "m4s":
            video.is_video_only = True
        audio = self._media_url(audio_item, "m4a") if audio_item else None
        title = current.get("part") if len(pages) > 1 else view["title"]
        return title or view["title"], video, audio

    def _choose_video(self, videos: list[dict[str, Any]], quality: int | None) -> dict[str, Any] | None:
        if not videos:
            return None
        if quality:
            selected = [item for item in videos if item.get("id") == quality]
            if selected:
                return max(selected, key=self._codec_rank)
        return max(videos, key=lambda item: (item.get("id", 0), *self._codec_rank(item)))

    def _choose_audio(self, audios: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not audios:
            return None
        return max(audios, key=lambda item: item.get("bandwidth", 0))

    def _media_url(self, item: dict[str, Any], ext: str) -> MediaUrl:
        candidates = self._candidate_urls(item)
        url, size = self._probe_url(candidates)
        return MediaUrl(
            url=url,
            candidates=candidates,
            size=size,
            ext=ext,
            stream_id=item.get("id", 0),
            codecs=item.get("codecs", ""),
        )
