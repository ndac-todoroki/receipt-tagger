"""OpenStreetMap（Nominatim）で店名を検索し、店種別タグを得る（FR-08, FR-14）。

Nominatim の利用規約に従い、問い合わせは1秒に1回までとし、User-Agent でアプリを名乗る。
https://operations.osmfoundation.org/policies/nominatim/
"""

import json
import logging
import threading
import time as time_module
import urllib.request
from collections.abc import Callable
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "receipt-tagger/0.1 (machine learning course project)"
MIN_INTERVAL_SECONDS = 1.0
TIMEOUT_SECONDS = 5.0
RESULT_LIMIT = 5

# 道路や土地利用など、店そのものではないカテゴリを除く
STORE_CATEGORIES = frozenset({"shop", "amenity", "railway", "public_transport"})


def _fetch_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as res:
        return json.load(res)


class NominatimClient:
    """店名 → OSM店種別タグ一覧の検索クライアント。結果はプロセス内にキャッシュする。"""

    def __init__(
        self,
        fetch_json: Callable[[str], object] = _fetch_json,
        time: Callable[[], float] = time_module.monotonic,
        sleep: Callable[[float], None] = time_module.sleep,
    ) -> None:
        self._fetch_json = fetch_json
        self._time = time
        self._sleep = sleep
        self._cache: dict[str, list[str]] = {}
        self._last_request_at: float | None = None
        # リクエストを並行に処理しても問い合わせ間隔を守るため、問い合わせ全体を直列化する
        self._lock = threading.Lock()

    def search_tags(self, store_name: str) -> list[str] | None:
        """店名で検索し、"shop=convenience" 形式のタグを返す。

        ヒットなしは空リスト。通信失敗や想定外の応答は None（判定不能）を返し、例外は出さない。
        """
        with self._lock:
            if store_name in self._cache:
                return self._cache[store_name]
            self._wait_for_interval()
            # 外部に送るのは店名だけ（国内に絞る指定と件数は店を特定する情報を含まない）
            params = {"q": store_name, "format": "jsonv2", "countrycodes": "jp"}
            url = f"{NOMINATIM_URL}?{urlencode({**params, 'limit': RESULT_LIMIT})}"
            try:
                body = self._fetch_json(url)
            except Exception as e:
                # 失敗はキャッシュしない（一時的な障害で判定不能が固定されるのを避ける）
                logger.warning("Nominatim への問い合わせに失敗: %s", type(e).__name__)
                return None
            finally:
                self._last_request_at = self._time()
            tags = _extract_store_tags(body)
            if tags is not None:
                self._cache[store_name] = tags
            return tags

    def _wait_for_interval(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = self._time() - self._last_request_at
        if elapsed < MIN_INTERVAL_SECONDS:
            self._sleep(MIN_INTERVAL_SECONDS - elapsed)


def _extract_store_tags(body: object) -> list[str] | None:
    if not isinstance(body, list):
        logger.warning("Nominatim の応答が想定外の形: %s", type(body).__name__)
        return None
    return [
        f"{hit['category']}={hit['type']}"
        for hit in body
        if isinstance(hit, dict) and hit.get("category") in STORE_CATEGORIES and "type" in hit
    ]
