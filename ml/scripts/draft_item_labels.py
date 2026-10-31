"""品目ジャンルの正解ラベルの下書きを、LLM の分類器（小分類）で作る。

    python ml/scripts/draft_item_labels.py <eval_vlm の詳細.jsonl> <下書き.csv> --url <vLLM の URL>

下書きの CSV は人が genre 列を直して正解にする。draft_genre 列は直さずに残し、
直す前後の差分を見られるようにする（CLAUDE.md の「LLMで事前ラベル付けした場合」）。
CSV には品名が入るので、出力先は ml/data/private/ 配下にすること。
標準出力には件数と処理時間だけを出す。

推論サーバーは compose の内部にしかないので、Spark の app コンテナの中で動かす
（docs/evaluation.md の手順）。
"""

import argparse
import csv
import json
import time
from collections import Counter
from pathlib import Path

from receipt_app.config import load_config
from receipt_app.stages.llm_item_genre import LlmItemGenreClassifier

REPO_ROOT = Path(__file__).resolve().parents[2]
COLUMNS = ["image", "store", "name", "amount", "draft_genre", "draft_confidence", "genre"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("detail", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--url", required=True)
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config")
    args = parser.parse_args()

    config = load_config(args.config)
    classifier = LlmItemGenreClassifier(
        url=args.url, examples=config.item_genre_examples, min_confidence=0.0
    )
    rows = []
    for line in args.detail.read_text(encoding="utf-8").splitlines():
        receipt = json.loads(line)
        for name, _quantity, _unit_price, amount, discount in receipt["items"]:
            # 値引きの行は品物ではないので、アプリと同じく分類しない
            if amount + discount > 0:
                rows.append(
                    {
                        "image": receipt["image"],
                        "store": receipt["store"],
                        "name": name,
                        "amount": amount,
                    }
                )

    start = time.perf_counter()
    judgements = classifier.classify([r["name"] for r in rows])
    elapsed = time.perf_counter() - start

    # Excel で開いても文字化けしないよう BOM 付きにする
    with args.out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for row, j in zip(rows, judgements, strict=True):
            confidence = "" if j.confidence is None else f"{j.confidence:.3f}"
            draft = j.genre or ""
            writer.writerow(
                {**row, "draft_genre": draft, "draft_confidence": confidence, "genre": draft}
            )

    categories = Counter(
        config.labels.category_of(j.genre) if j.genre else "判定不能" for j in judgements
    )
    print(f"items: {len(rows)}, elapsed: {elapsed:.1f}s")
    for category, count in categories.most_common():
        print(f"  {category}: {count}")


if __name__ == "__main__":
    main()
