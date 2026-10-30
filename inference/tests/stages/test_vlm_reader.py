"""視覚言語モデル（VLM）による読み取り（FR-03）のテスト。

確かめること: VLM の応答 JSON をレシートの内容に直す、壊れた応答を読み取り失敗にする、
            推論サーバーに送る内容（縮めた画像、出力の形の指定）、通信の失敗を読み取り失敗にする。
確かめないこと: VLM が正しく読めるか（ml/scripts/eval_vlm.py で実レシートを使って測る）。
            推論サーバーは偽物を使う。
"""

import base64
import io
import json

import pytest
from PIL import Image

from receipt_app.stages.receipt import ParsedItem, ReadError
from receipt_app.stages.vlm_reader import VlmReceiptReader, parse_receipt_json


def _content(**overrides: object) -> str:
    data: dict[str, object] = {
        "store_name": "サンプルマート",
        "items": [{"name": "ポテチ", "quantity": 1, "unit_price": None, "amount": 150}],
        "subtotal": None,
        "tax": None,
        "total": 150,
    }
    return json.dumps({**data, **overrides}, ensure_ascii=False)


def test_店名と品目と小計と税と合計を受け取る() -> None:
    content = _content(
        items=[
            {"name": "ポテチ", "quantity": 2, "unit_price": 150, "amount": 300},
            {"name": "値引", "quantity": None, "unit_price": None, "amount": -20},
        ],
        subtotal=280,
        tax=22,
        total=302,
    )

    receipt = parse_receipt_json(content)

    assert receipt.store_candidates == ["サンプルマート"]
    assert receipt.items == [
        ParsedItem(name="ポテチ", amount=300, quantity=2, unit_price=150),
        ParsedItem(name="値引", amount=-20),
    ]
    assert (receipt.subtotal, receipt.tax, receipt.total) == (280, 22, 302)


def test_店名は法人格を除いて検索用に整える() -> None:
    receipt = parse_receipt_json(_content(store_name="株式会社サンプルマート"))

    assert receipt.store_candidates == ["サンプルマート"]


@pytest.mark.parametrize("store_name", [None, "", "株式会社"])
def test_店名が読めなければ候補は空にする(store_name: str | None) -> None:
    receipt = parse_receipt_json(_content(store_name=store_name))

    assert receipt.store_candidates == []


@pytest.mark.parametrize("content", ["", "合計は150円です", "[]", '{"items": "x"}'])
def test_形の違う応答は読み取り失敗にする(content: str) -> None:
    with pytest.raises(ReadError):
        parse_receipt_json(content)


def test_金額が整数でない品目は捨てる() -> None:
    content = _content(
        items=[
            {"name": "ポテチ", "quantity": 1, "unit_price": None, "amount": 150},
            {"name": "読めない", "quantity": 1, "unit_price": None, "amount": None},
            {"name": "真偽値", "quantity": 1, "unit_price": None, "amount": True},
            "品目ではない",
        ]
    )

    receipt = parse_receipt_json(content)

    assert [i.name for i in receipt.items] == ["ポテチ"]


def test_小計と税と合計が整数でなければ無いものとする() -> None:
    receipt = parse_receipt_json(_content(subtotal="150", tax=1.5, total=False))

    assert (receipt.subtotal, receipt.tax, receipt.total) == (None, None, None)


class FakeServer:
    def __init__(self, response: object) -> None:
        self.response = response
        self.requests: list[tuple[str, dict[str, object]]] = []

    def __call__(self, url: str, body: dict[str, object]) -> object:
        self.requests.append((url, body))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _chat_response(content: str) -> dict[str, object]:
    return {"choices": [{"message": {"content": content}}]}


def _read(server: FakeServer, image: Image.Image | None = None) -> object:
    reader = VlmReceiptReader(url="http://vllm:8000/v1/chat/completions", post_json=server)
    return reader.read(image or Image.new("RGB", (10, 10)))


def _sent_image(body: dict[str, object]) -> Image.Image:
    messages = body["messages"]
    assert isinstance(messages, list)
    url = next(c["image_url"]["url"] for c in messages[0]["content"] if c["type"] == "image_url")
    header, data = url.split(",", 1)
    assert header == "data:image/jpeg;base64"
    return Image.open(io.BytesIO(base64.b64decode(data)))


def test_画像と出力の形を指定して推論サーバーに送り応答を読む() -> None:
    server = FakeServer(_chat_response(_content()))

    receipt = _read(server)

    url, body = server.requests[0]
    assert url == "http://vllm:8000/v1/chat/completions"
    response_format = body["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"
    # 思考を出させると1枚に数分かかるので切る
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["temperature"] == 0
    assert _sent_image(body).size == (10, 10)
    assert receipt == parse_receipt_json(_content())


def test_大きな画像は長辺を2048画素に縮めて送る() -> None:
    server = FakeServer(_chat_response(_content()))

    _read(server, Image.new("RGB", (3000, 4000)))

    assert _sent_image(server.requests[0][1]).size == (1536, 2048)


def test_推論サーバーとの通信に失敗したら読み取り失敗にする() -> None:
    with pytest.raises(ReadError):
        _read(FakeServer(TimeoutError()))


@pytest.mark.parametrize("response", [{}, {"choices": []}, [], {"choices": [{"message": {}}]}])
def test_推論サーバーの応答の形が違えば読み取り失敗にする(response: object) -> None:
    with pytest.raises(ReadError):
        _read(FakeServer(response))
