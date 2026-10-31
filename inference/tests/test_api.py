"""推論APIの入出力の約束事を確かめるテスト。

確かめること: 画像を受け取り、進み具合と結果を1行1つの JSON（NDJSON）で順に返す、
            不正な入力を弾く、読み取りの失敗を伝える。
確かめないこと: 各段の判定の正しさ（段ごとのテストで扱う）。待ち順の数え方（キューのテストで扱う）。
"""

import io
import json
from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image

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
) -> TestClient:
    app = create_app(analyzer=analyzer or _fake_analyzer, max_upload_bytes=max_upload_bytes)
    return TestClient(app)


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
