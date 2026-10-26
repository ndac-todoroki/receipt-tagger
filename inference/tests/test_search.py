"""OSM（Nominatim）検索クライアント（FR-08, FR-14）のテスト。

確かめること: 店名だけを送る、店種別のタグだけを返す、キャッシュする、
            失敗しても例外を出さず判定不能（None）にする、利用規約の間隔を守る。
確かめないこと: 実際の Nominatim の応答（ネットワークに依存するため手動で確認する）。
"""

from urllib.parse import parse_qs, urlparse

import pytest

from receipt_app.search import NominatimClient


class FakeNominatim:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.urls: list[str] = []

    def __call__(self, url: str) -> object:
        self.urls.append(url)
        res = self.responses.pop(0)
        if isinstance(res, Exception):
            raise res
        return res


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _client(fake: FakeNominatim, clock: FakeClock | None = None) -> NominatimClient:
    clock = clock or FakeClock()
    return NominatimClient(fetch_json=fake, time=clock.time, sleep=clock.sleep)


def _hit(category: str, type_: str) -> dict[str, str]:
    return {"category": category, "type": type_, "name": "x"}


def test_問い合わせには店名以外の情報を含めない() -> None:
    fake = FakeNominatim([[]])

    _client(fake).search_tags("ローソン")

    params = parse_qs(urlparse(fake.urls[0]).query)
    assert params["q"] == ["ローソン"]
    assert set(params) <= {"q", "format", "countrycodes", "limit"}


def test_店種別のカテゴリのタグだけを返す() -> None:
    fake = FakeNominatim(
        [[_hit("shop", "convenience"), _hit("landuse", "retail"), _hit("amenity", "pharmacy")]]
    )

    assert _client(fake).search_tags("ローソン") == ["shop=convenience", "amenity=pharmacy"]


def test_同じ店名は2回目以降は問い合わせない() -> None:
    fake = FakeNominatim([[_hit("shop", "convenience")]])
    client = _client(fake)

    client.search_tags("ローソン")
    second = client.search_tags("ローソン")

    assert second == ["shop=convenience"]
    assert len(fake.urls) == 1


def test_ヒットしなかった結果もキャッシュする() -> None:
    fake = FakeNominatim([[]])
    client = _client(fake)

    client.search_tags("まるや")
    client.search_tags("まるや")

    assert len(fake.urls) == 1


def test_問い合わせに失敗したらNoneを返し次回は再び問い合わせる() -> None:
    fake = FakeNominatim([TimeoutError("timeout"), [_hit("shop", "convenience")]])
    client = _client(fake)

    assert client.search_tags("ローソン") is None
    assert client.search_tags("ローソン") == ["shop=convenience"]


def test_想定外の形の応答は失敗として扱う() -> None:
    fake = FakeNominatim([{"error": "unexpected"}])

    assert _client(fake).search_tags("ローソン") is None


def test_連続する問い合わせは1秒以上空ける() -> None:
    fake = FakeNominatim([[], []])
    clock = FakeClock()
    client = _client(fake, clock)

    client.search_tags("A")
    clock.now += 0.3
    client.search_tags("B")

    assert clock.slept == pytest.approx([0.7])
