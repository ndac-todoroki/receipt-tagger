"""ocr_vlm.py の応答に対して整合性チェックを流し、eval_parser.py と同じ形で集計する。

    uv run --project inference python ml/scripts/eval_vlm.py <応答のフォルダ> <詳細の出力先.jsonl>

- lines の応答: 行をそのまま既存のパーサに渡す（行の組み立ては VLM が済ませている）
- struct の応答: VLM が出した品目・合計で整合性を見る

標準出力には件数・割合・処理時間だけを出す。レシートごとの詳細は出力先の JSONL に書くので、
出力先は ml/data/private/ 配下にすること。
"""

import argparse
import json
import statistics
from pathlib import Path

from receipt_app.stages.consistency import check_consistency
from receipt_app.stages.receipt_parser import parse_receipt


def _from_lines(content: str) -> dict[str, object]:
    rows = [r.strip() for r in content.splitlines() if r.strip()]
    receipt = parse_receipt(rows)
    return {
        "store": receipt.store_candidates[0] if receipt.store_candidates else None,
        "items": [[i.name, i.quantity, i.unit_price, i.amount] for i in receipt.items],
        "subtotal": receipt.subtotal,
        "tax": receipt.tax,
        "total": receipt.total,
    }


def _from_struct(content: str) -> dict[str, object] | None:
    # 制約付き生成を使えないモデルは ```json などで囲んで返すので、最も外側の {} だけを読む
    start, end = content.find("{"), content.rfind("}")
    try:
        data = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return {
        "store": data.get("store_name"),
        "items": [
            [i.get("name"), i.get("quantity"), i.get("unit_price"), i.get("amount")]
            for i in data.get("items", [])
            if isinstance(i.get("amount"), int)
        ],
        "subtotal": data.get("subtotal"),
        "tax": data.get("tax"),
        "total": data.get("total"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("response_dir", type=Path)
    parser.add_argument("detail_out", type=Path)
    args = parser.parse_args()

    counts = {"receipts": 0, "has_total": 0, "consistent": 0, "has_items": 0, "has_store": 0}
    invalid_json = 0
    elapsed = []
    with args.detail_out.open("w", encoding="utf-8") as out:
        for path in sorted(args.response_dir.glob("*.json")):
            response = json.loads(path.read_text(encoding="utf-8"))
            elapsed.append(response["elapsed"])
            if response["mode"] == "lines":
                parsed = _from_lines(response["content"])
            else:
                parsed = _from_struct(response["content"])
            counts["receipts"] += 1
            if parsed is None:
                invalid_json += 1
                continue
            items = parsed["items"]
            assert isinstance(items, list)
            consistency = check_consistency(
                [i[3] for i in items],
                total=parsed["total"],  # type: ignore[arg-type]
                subtotal=parsed["subtotal"],  # type: ignore[arg-type]
                tax=parsed["tax"],  # type: ignore[arg-type]
            )
            counts["has_total"] += parsed["total"] is not None
            counts["consistent"] += consistency.ok is True
            counts["has_items"] += bool(items)
            counts["has_store"] += bool(parsed["store"])
            detail = {"image": response["image"], "ok": consistency.ok, **parsed}
            out.write(json.dumps(detail, ensure_ascii=False) + "\n")

    n = counts["receipts"]
    for key, value in counts.items():
        print(f"{key}: {value}" + ("" if key == "receipts" else f" ({value / n:.0%})"))
    if invalid_json:
        print(f"invalid_json: {invalid_json}")
    print(f"elapsed: median {statistics.median(elapsed):.1f}s, max {max(elapsed):.1f}s")


if __name__ == "__main__":
    main()
