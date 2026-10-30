"""視覚言語モデル（VLM）でレシート画像を読み取る（FR-03）。

DGX Spark 上の vLLM が配信する Qwen3.6-35B-A3B（NVFP4）に、OpenAI 互換の API で
画像を送り、店名・品目・合計を JSON で受け取る。選定の経緯は docs/devlog.md を参照。
"""

import json

from receipt_app.stages.receipt import ParsedItem, ParsedReceipt, ReadError
from receipt_app.stages.store_name import normalize_store_name


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
