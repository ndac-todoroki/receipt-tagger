"""学習なしの品目ジャンル分類（埋め込みの類似度）を、パーサが取り出した品名に試す。

    uv run --project inference python ml/scripts/try_item_genre.py <eval_parser.jsonl> <出力先.jsonl>

標準出力にはジャンルごとの件数と信頼度の分布だけを出す。品名ごとの結果は
出力先の JSONL に書くので、出力先は ml/data/private/ 配下にすること。
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from receipt_app.config import load_config
from receipt_app.stages.item_genre import EmbeddingItemGenreClassifier

REPO_ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("parsed", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()

    config = load_config(REPO_ROOT / "config")
    classifier = EmbeddingItemGenreClassifier.load(config)
    names = [
        item[0]
        for line in args.parsed.read_text(encoding="utf-8").splitlines()
        for item in json.loads(line)["items"]
        if item[3] > 0
    ]
    results = classifier.classify(names)

    genres = Counter(r.genre for r in results)
    confident = sum(r.status == "confirmed" for r in results)
    print(f"品名: {len(names)} 件, 閾値以上: {confident} 件 ({confident / len(names):.0%})")
    for genre, count in genres.most_common():
        print(f"  {genre}: {count}")
    with args.out.open("w", encoding="utf-8") as out:
        for name, r in zip(names, results, strict=True):
            row = {"name": name, "genre": r.genre, "confidence": round(r.confidence, 3)}
            out.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
