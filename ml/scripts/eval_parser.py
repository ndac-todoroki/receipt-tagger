"""OCR結果に対して、行の組み立て → レシートのパース → 整合性チェックを流し、集計する。

品目抽出（段4）の評価指標「合計整合率」を測るためのスクリプト。

    uv run --project inference python ml/scripts/eval_parser.py <OCR結果のフォルダ> <詳細の出力先.jsonl>

標準出力には件数と割合だけを出す。レシートごとの詳細（品名など実レシート由来の内容）は
出力先の JSONL に書くので、出力先は ml/data/private/ 配下にすること。
"""

import argparse
import json
from pathlib import Path

from receipt_app.stages.consistency import check_consistency
from receipt_app.stages.lines import OcrBox, group_rows
from receipt_app.stages.receipt_parser import parse_receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ocr_dir", type=Path)
    parser.add_argument("detail_out", type=Path)
    args = parser.parse_args()

    files = sorted(args.ocr_dir.glob("*.json"))
    counts = {"receipts": 0, "has_total": 0, "consistent": 0, "has_items": 0, "has_store": 0}
    with args.detail_out.open("w", encoding="utf-8") as out:
        for path in files:
            ocr = json.loads(path.read_text(encoding="utf-8"))
            boxes = [OcrBox(text=i["text"], score=i["score"], box=i["box"]) for i in ocr["items"]]
            rows = [row.text for row in group_rows(boxes)]
            receipt = parse_receipt(rows)
            consistency = check_consistency(
                [i.amount for i in receipt.items],
                total=receipt.total,
                subtotal=receipt.subtotal,
                tax=receipt.tax,
            )
            counts["receipts"] += 1
            counts["has_total"] += receipt.total is not None
            counts["consistent"] += consistency.ok is True
            counts["has_items"] += bool(receipt.items)
            counts["has_store"] += bool(receipt.store_candidates)
            detail = {
                "image": ocr["image"],
                "ok": consistency.ok,
                "items_sum": consistency.items_sum,
                "subtotal": receipt.subtotal,
                "tax": receipt.tax,
                "total": receipt.total,
                "store_candidates": receipt.store_candidates,
                "items": [[i.name, i.quantity, i.unit_price, i.amount] for i in receipt.items],
                "rows": rows,
            }
            out.write(json.dumps(detail, ensure_ascii=False) + "\n")

    n = counts["receipts"]
    for key, value in counts.items():
        print(f"{key}: {value}" + ("" if key == "receipts" else f" ({value / n:.0%})"))


if __name__ == "__main__":
    main()
