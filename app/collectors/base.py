"""Collector 基类和通用工具。"""

from dataclasses import dataclass, field
from datetime import datetime

import httpx
from loguru import logger

from app.exceptions import FetchError


@dataclass
class RawFetchResult:
    """原始抓取结果。"""

    url: str
    status_code: int
    text: str
    content: bytes | None = None
    headers: dict = field(default_factory=dict)
    fetched_at: datetime = field(default_factory=datetime.now)


class BaseCollector:
    """数据采集器基类。"""

    name: str = "base"

    def fetch(self) -> RawFetchResult:
        """抓取原始数据。"""
        raise NotImplementedError

    def parse(self, raw: RawFetchResult) -> list[dict]:
        """解析原始数据为半结构化 dict 列表。"""
        raise NotImplementedError


def fetch_url(
    url: str,
    headers: dict | None = None,
    timeout: int = 20,
) -> RawFetchResult:
    """通用 HTTP GET 请求。"""
    default_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.8",
    }
    if headers:
        default_headers.update(headers)

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url, headers=default_headers)
            resp.raise_for_status()
            return RawFetchResult(
                url=str(resp.url),
                status_code=resp.status_code,
                text=resp.text,
                content=resp.content,
                headers=dict(resp.headers),
                fetched_at=datetime.now(),
            )
    except httpx.TimeoutException as e:
        raise FetchError(f"Timeout fetching {url}: {e}") from e
    except httpx.HTTPStatusError as e:
        raise FetchError(f"HTTP {e.response.status_code} from {url}") from e
    except httpx.HTTPError as e:
        raise FetchError(f"HTTP error fetching {url}: {e}") from e
