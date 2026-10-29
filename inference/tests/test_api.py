"""推論APIの入出力の約束事を確かめるテスト。

確かめること: 画像を受け取って結果JSONを返す、不正な入力を弾く。
確かめないこと: 各段の判定の正しさ（段ごとのテストで扱う）。
"""

import io

from fastapi.testclient import TestClient
from PIL import Image

from receipt_app.main import create_app
from receipt_app.schemas import AnalyzeResult, ConsistencyResult, StoreResult

FAKE_RESULT = AnalyzeResult(
    store=StoreResult(name="サンプルマート", genre="コンビニ", status="confirmed"),
    granularity="per_item",
    items=[],
    total=None,
    consistency=ConsistencyResult(ok=None, items_sum=0, total=None),
)


def _fake_analyzer(image: Image.Image) -> AnalyzeResult:
    return FAKE_RESULT


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), "white").save(buf, format="PNG")
    return buf.getvalue()


def _client(max_upload_bytes: int = 10_000_000) -> TestClient:
    return TestClient(create_app(analyzer=_fake_analyzer, max_upload_bytes=max_upload_bytes))


def test_ヘルスチェックはokを返す() -> None:
    res = _client().get("/api/health")

    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_画像を送ると店と品目と整合性チェックを含む結果を返す() -> None:
    res = _client().post("/api/analyze", files={"image": ("r.png", _png_bytes(), "image/png")})

    assert res.status_code == 200
    body = res.json()
    assert set(body) >= {"store", "granularity", "items", "total", "consistency"}


def test_画像でないファイルは415で弾く() -> None:
    res = _client().post("/api/analyze", files={"image": ("a.txt", b"not an image", "text/plain")})

    assert res.status_code == 415


def test_上限を超えるサイズは413で弾く() -> None:
    res = _client(max_upload_bytes=10).post(
        "/api/analyze", files={"image": ("r.png", _png_bytes(), "image/png")}
    )

    assert res.status_code == 413
