"""ocr_vlm.py の応答に対して整合性チェックを流し、eval_parser.py と同じ形で集計する。

    uv run --project inference python ml/scripts/eval_vlm.py <応答のフォルダ> <詳細の出力先.jsonl>

- lines の応答: 行をそのまま既存のパーサに渡す（行の組み立ては VLM が済ませている）
- struct の応答: アプリと同じ変換（parse_receipt_json）で品目・合計を取り出して整合性を見る

どちらもアプリと同じ後処理（個数の検算、割引のまとめ）をかけてから数える。
後処理で直した個数と、まとめた割引の数も出す。

標準出力には件数・割合・処理時間だけを出す。レシートごとの詳細は出力先の JSONL に書くので、
出力先は ml/data/private/ 配下にすること。
"""

import argparse
import json
import statistics
from pathlib import Path

from receipt_app.stages.consistency import check_consistency
from receipt_app.stages.item_cleanup import fix_quantities, merge_discounts
from receipt_app.stages.ocr_reader.receipt_parser import parse_receipt
from receipt_app.stages.receipt import ParsedReceipt, ReadError
from receipt_app.stages.vlm_reader import parse_receipt_json


def _from_lines(content: str) -> ParsedReceipt:
    rows = [r.strip() for r in content.splitlines() if r.strip()]
    return parse_receipt(rows)


def _from_struct(content: str) -> ParsedReceipt | None:
    # 制約付き生成を使えないモデルは ```json などで囲んで返すので、最も外側の {} だけを読む
    start, end = content.find("{"), content.rfind("}")
    try:
        return parse_receipt_json(content[start : end + 1])
    except ReadError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("response_dir", type=Path)
    parser.add_argument("detail_out", type=Path)
    args = parser.parse_args()

    counts = {"receipts": 0, "has_total": 0, "consistent": 0, "has_items": 0, "has_store": 0}
    invalid_json = 0
    fixed_quantities = merged_discounts = 0
    elapsed = []
    with args.detail_out.open("w", encoding="utf-8") as out:
        for path in sorted(args.response_dir.glob("*.json")):
            response = json.loads(path.read_text(encoding="utf-8"))
            elapsed.append(response["elapsed"])
            if response["mode"] == "lines":
                parsed: ParsedReceipt | None = _from_lines(response["content"])
            else:
                parsed = _from_struct(response["content"])
            counts["receipts"] += 1
            if parsed is None:
                invalid_json += 1
                continue
            fixed = fix_quantities(parsed.items)
            fixed_quantities += sum(a.quantity != b.quantity for a, b in zip(parsed.items, fixed))
            items = merge_discounts(fixed)
            merged_discounts += len(fixed) - len(items)
            consistency = check_consistency(
                [i.amount for i in items],
                total=parsed.total,
                subtotal=parsed.subtotal,
                tax=parsed.tax,
            )
            counts["has_total"] += parsed.total is not None
            counts["consistent"] += consistency.ok is True
            counts["has_items"] += bool(items)
            counts["has_store"] += bool(parsed.store_candidates)
            detail = {
                "image": response["image"],
                "ok": consistency.ok,
                "store": parsed.store_candidates[0] if parsed.store_candidates else None,
                "items": [[i.name, i.quantity, i.unit_price, i.amount, i.discount] for i in items],
                "subtotal": parsed.subtotal,
                "tax": parsed.tax,
                "total": parsed.total,
            }
            out.write(json.dumps(detail, ensure_ascii=False) + "\n")

    n = counts["receipts"]
    for key, value in counts.items():
        print(f"{key}: {value}" + ("" if key == "receipts" else f" ({value / n:.0%})"))
    if invalid_json:
        print(f"invalid_json: {invalid_json}")
    print(f"fixed_quantities: {fixed_quantities}, merged_discounts: {merged_discounts}")
    print(f"elapsed: median {statistics.median(elapsed):.1f}s, max {max(elapsed):.1f}s")


if __name__ == "__main__":
    main()
