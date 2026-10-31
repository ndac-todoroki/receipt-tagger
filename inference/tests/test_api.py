"""推論APIの入出力の約束事を確かめるテスト。

確かめること: 画像を受け取り、進み具合と結果を1行1つの JSON（NDJSON）で順に返す、
            不正な入力を弾く、読み取りの失敗を伝える、
            同じ相手からの依頼が多すぎれば断る、待ち行列が上限なら断る、
            画像をディスクに書かずに受け取る、公開しない入口を閉じる、セキュリティ用の見出しを付ける。
確かめないこと: 各段の判定の正しさ（段ごとのテストで扱う）。待ち順の数え方（キューのテストで扱う）。
"""

import io
import json
import os
import tempfile
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from receipt_app.analysis_queue import AnalysisQueue
from receipt_app.main import create_app
from receipt_app.schemas import AnalyzeResult, ConsistencyResult, StoreResult
from receipt_app.stages.receipt import ReadError

FAKE_RESULT = AnalyzeResult(
    store=StoreResult(name="サンプルマート", genre="コンビニ", status="confirmed"),
    granularity="per_item",
    items=[],
    total=None,
    consistency=ConsistencyResult(ok=None, items_sum=0, total=None),
)


Analyzer = Callable[[Image.Image, Callable[[str], None]], AnalyzeResult]


def _fake_analyzer(image: Image.Image, on_stage: Callable[[str], None]) -> AnalyzeResult:
    on_stage("reading")
    return FAKE_RESULT


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), "white").save(buf, format="PNG")
    return buf.getvalue()


def _failing_analyzer(image: Image.Image, on_stage: Callable[[str], None]) -> AnalyzeResult:
    raise ReadError("推論サーバーに問い合わせられない")


def _client(
    max_upload_bytes: int = 10_000_000,
    analyzer: Analyzer | None = None,
    rate_limits: list[tuple[float, int]] | None = None,
    queue: AnalysisQueue | None = None,
    max_pixels: int = 50_000_000,
) -> TestClient:
    app = create_app(
        analyzer=analyzer or _fake_analyzer,
        max_upload_bytes=max_upload_bytes,
        rate_limits=rate_limits or [(60, 100)],
        queue=queue,
        max_pixels=max_pixels,
    )
    return TestClient(app)


def _post(
    client: TestClient, headers: dict[str, str] | None = None, data: bytes | None = None
) -> Any:
    return client.post(
        "/api/analyze",
        files={"image": ("r.png", data or _png_bytes(), "image/png")},
        headers=headers or {},
    )


def _image_bytes(image: Image.Image, fmt: str) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format=fmt)
    return buf.getvalue()


def test_ヘルスチェックはokを返す() -> None:
    res = _client().get("/api/health")

    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def _events(res: object) -> list[dict[str, Any]]:
    return [json.loads(line) for line in res.text.splitlines()]  # type: ignore[attr-defined]


def test_画像を送ると進み具合のあとに店と品目と整合性チェックを含む結果を返す() -> None:
    res = _client().post("/api/analyze", files={"image": ("r.png", _png_bytes(), "image/png")})

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/x-ndjson")
    events = _events(res)
    assert [e["type"] for e in events] == ["started", "stage", "result"]
    assert events[1]["stage"] == "reading"
    assert set(events[-1]["result"]) >= {"store", "granularity", "items", "total", "consistency"}


def test_画像でないファイルは415で弾く() -> None:
    res = _client().post("/api/analyze", files={"image": ("a.txt", b"not an image", "text/plain")})

    assert res.status_code == 415


def test_上限を超えるサイズは413で弾く() -> None:
    res = _client(max_upload_bytes=10).post(
        "/api/analyze", files={"image": ("r.png", _png_bytes(), "image/png")}
    )

    assert res.status_code == 413


def test_レシートを読み取れなければ最後の行で理由を返す() -> None:
    # 進み具合を送り始めた後なので、HTTP の状態コードでは伝えられない
    res = _client(analyzer=_failing_analyzer).post(
        "/api/analyze", files={"image": ("r.png", _png_bytes(), "image/png")}
    )

    last = _events(res)[-1]
    assert last == {
        "type": "error",
        "detail": "レシートを読み取れませんでした。時間をおいて試してください",
    }


def test_同じ相手からの依頼が多すぎれば429で断る() -> None:
    client = _client(rate_limits=[(60, 1)])

    assert _post(client).status_code == 200
    res = _post(client)

    assert res.status_code == 429
    assert "時間をおいて" in res.json()["detail"]


def test_Cloudflare経由では接続元のIPアドレスで相手を見分ける() -> None:
    # Cloudflare Tunnel 経由だと、接続してくるのはすべて cloudflared のコンテナになる
    client = _client(rate_limits=[(60, 1)])

    assert _post(client, {"CF-Connecting-IP": "203.0.113.1"}).status_code == 200
    assert _post(client, {"CF-Connecting-IP": "203.0.113.2"}).status_code == 200
    assert _post(client, {"CF-Connecting-IP": "203.0.113.1"}).status_code == 429


class FullQueue(AnalysisQueue):
    @property
    def full(self) -> bool:
        return True


def test_待ち行列が上限に達していれば503で断る() -> None:
    res = _post(_client(queue=FullQueue()))

    assert res.status_code == 503
    assert "混んでいます" in res.json()["detail"]


def test_1MBを超える画像もディスクに書かずに受け取る(monkeypatch: pytest.MonkeyPatch) -> None:
    # 一時ファイルがメモリからディスクに切り替わったら失敗させる
    def no_rollover(self: object) -> None:
        raise AssertionError("アップロードがディスクに書かれた")

    monkeypatch.setattr(tempfile.SpooledTemporaryFile, "rollover", no_rollover)
    noise = Image.frombytes("RGB", (800, 800), os.urandom(800 * 800 * 3))
    data = _image_bytes(noise, "PNG")
    assert len(data) > 1024 * 1024

    assert _post(_client(), data=data).status_code == 200


def test_本体が上限を大きく超えれば読み切る前に413で弾く() -> None:
    res = _client(max_upload_bytes=1000).post(
        "/api/analyze",
        content=b"x" * 200_000,
        headers={"Content-Type": "multipart/form-data; boundary=b"},
    )

    assert res.status_code == 413


@pytest.mark.parametrize("fmt", ["BMP", "GIF", "TIFF"])
def test_JPEGとPNGとWebP以外の形式は415で弾く(fmt: str) -> None:
    data = _image_bytes(Image.new("RGB", (10, 10), "white"), fmt)

    assert _post(_client(), data=data).status_code == 415


def test_途中で切れた画像は415で弾く() -> None:
    data = _image_bytes(Image.new("RGB", (200, 200), "white"), "JPEG")

    assert _post(_client(), data=data[: len(data) // 2]).status_code == 415


def test_画素数が上限を超える画像は展開せずに413で弾く() -> None:
    # 小さなファイルでも展開すると巨大になる画像（解凍爆弾）を防ぐ
    res = _post(_client(max_pixels=100), data=_image_bytes(Image.new("1", (20, 20)), "PNG"))

    assert res.status_code == 413


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_APIの説明ページは公開しない(path: str) -> None:
    assert _client().get(path).status_code == 404


def test_応答にセキュリティ用の見出しを付ける() -> None:
    headers = _client().get("/api/health").headers

    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert headers["Referrer-Policy"] == "no-referrer"
