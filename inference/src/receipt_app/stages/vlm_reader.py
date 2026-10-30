"""視覚言語モデル（VLM）でレシート画像を読み取る（FR-03）。

DGX Spark 上の vLLM が配信する Qwen3.6-35B-A3B（NVFP4）に、OpenAI 互換の API で
画像を送り、店名・品目・合計を JSON で受け取る。選定の経緯は docs/devlog.md を参照。
"""

import base64
import io
import json
import logging
import urllib.request
from collections.abc import Callable

from PIL import Image

from receipt_app.stages.receipt import ParsedItem, ParsedReceipt, ReadError
from receipt_app.stages.store_name import normalize_store_name

logger = logging.getLogger(__name__)

# 長辺をこれ以下に縮める。スマホの写真をそのまま送ると画像トークンが増えすぎて遅くなる
MAX_SIDE = 2048
# 実レシート89枚で最大44秒かかった。それより長く待っても結果は変わらないとみなす
TIMEOUT_SECONDS = 120.0

# 指示文と JSON スキーマは、実レシートで測った ml/scripts/ocr_vlm.py の struct と同じにする。
# 変えるときは、同じスクリプトで測り直してから変える
PROMPT = """このレシート画像から、次の項目を読み取って JSON で答えてください。
- store_name: 店名（読めなければ null）
- items: 購入した品目。name は品名、quantity は個数、unit_price は単価、amount はその行の金額。
  値引き・割引の行も品目として含め、amount を負の数にする。個数・単価が書かれていなければ null
- subtotal: 小計（無ければ null）
- tax: 外税の額（税抜きの品目に合計で加算される消費税。内税のみなら null）
- total: 合計金額（支払った金額ではなく合計。読めなければ null）
金額は円単位の整数にする。画像に無い品目を補わない。"""

SCHEMA = {
    "type": "object",
    "properties": {
        "store_name": {"type": ["string", "null"]},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "quantity": {"type": ["integer", "null"]},
                    "unit_price": {"type": ["integer", "null"]},
                    "amount": {"type": "integer"},
                },
                "required": ["name", "quantity", "unit_price", "amount"],
            },
        },
        "subtotal": {"type": ["integer", "null"]},
        "tax": {"type": ["integer", "null"]},
        "total": {"type": ["integer", "null"]},
    },
    "required": ["store_name", "items", "subtotal", "tax", "total"],
}


def _post_json(url: str, body: dict[str, object]) -> object:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as res:
        return json.load(res)


class VlmReceiptReader:
    """推論サーバー（vLLM）の VLM でレシート画像を読む。"""

    def __init__(
        self,
        url: str,
        model: str = "default",
        post_json: Callable[[str, dict[str, object]], object] = _post_json,
    ) -> None:
        self._url = url
        self._model = model
        self._post_json = post_json

    def read(self, image: Image.Image) -> ParsedReceipt:
        """画像を読み取る。推論サーバーの障害や壊れた応答は ReadError。"""
        body: dict[str, object] = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": _image_data_url(image)}},
                        {"type": "text", "text": PROMPT},
                    ],
                }
            ],
            "temperature": 0,
            "max_tokens": 4096,
            # 思考を出させると1枚に数分かかるので切る
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "receipt", "schema": SCHEMA},
            },
        }
        try:
            response = self._post_json(self._url, body)
        except Exception as e:
            # 応答や画像の中身はログに出さない（レシートの内容を残さないため）
            logger.warning("推論サーバーへの問い合わせに失敗: %s", type(e).__name__)
            raise ReadError("推論サーバーに問い合わせられない") from e
        return parse_receipt_json(_message_content(response))


def _image_data_url(image: Image.Image) -> str:
    small = image.convert("RGB")
    small.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    small.save(buf, format="JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _message_content(response: object) -> str:
    try:
        content = response["choices"][0]["message"]["content"]  # type: ignore[index]
    except (KeyError, IndexError, TypeError) as e:
        raise ReadError("推論サーバーの応答の形が想定と違う") from e
    if not isinstance(content, str):
        raise ReadError("推論サーバーの応答に本文が無い")
    return content


def parse_receipt_json(content: str) -> ParsedReceipt:
    """VLM の応答（JSON 文字列）をレシートの内容に直す。形が違えば ReadError。"""
    # JSON スキーマで出力の形を縛っているが、サーバーの設定違いなどで外れても落ちないよう確かめる
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ReadError("応答が JSON ではない") from e
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ReadError("応答の形が想定と違う")

    store_name = data.get("store_name")
    store = normalize_store_name(store_name) if isinstance(store_name, str) else None
    return ParsedReceipt(
        store_candidates=[store] if store else [],
        items=[
            ParsedItem(
                name=str(i.get("name") or ""),
                amount=i["amount"],
                quantity=_int_or_none(i.get("quantity")) or 1,
                unit_price=_int_or_none(i.get("unit_price")),
            )
            for i in data["items"]
            if isinstance(i, dict) and _int_or_none(i.get("amount")) is not None
        ],
        subtotal=_int_or_none(data.get("subtotal")),
        tax=_int_or_none(data.get("tax")),
        total=_int_or_none(data.get("total")),
    )


def _int_or_none(value: object) -> int | None:
    # bool は int の一種なので、明示的に除く
    return value if isinstance(value, int) and not isinstance(value, bool) else None
