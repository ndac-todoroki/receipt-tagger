"""品目ジャンル分類を、人が直した正解ラベルで評価する（docs/evaluation.md の指標）。

    python ml/scripts/eval_item_genre.py <正解.csv> <詳細の出力先.jsonl> --url <vLLM の URL>

分類器2種（embedding・llm）× 段数2種（1段: 大分類を直接選ぶ、2段: 小分類を選んで大分類に直す）
の4通りを測る。genre 列が空の行（飲食店・調剤薬局）は除く。

標準出力には指標だけを出す。品名ごとの結果は出力先の JSONL に書くので、
出力先は ml/data/private/ 配下にすること。推論サーバーは compose の内部にしかないので、
Spark の app コンテナの中で動かす（docs/evaluation.md の手順）。
"""

import argparse
import csv
import json
import time
from collections.abc import Callable
from pathlib import Path

from receipt_app.config import AppConfig, load_config
from receipt_app.stages.item_genre import (
    MODEL_NAME,
    EmbeddingItemGenreClassifier,
    ItemGenreJudgement,
    _SentenceTransformerEncoder,
)
from receipt_app.stages.llm_item_genre import LlmItemGenreClassifier

REPO_ROOT = Path(__file__).resolve().parents[2]

Classify = Callable[[list[str]], list[ItemGenreJudgement]]


def _category_examples(config: AppConfig) -> dict[str, list[str]]:
    """1段で使う見本。大分類に属する小分類の見本をまとめる。"""
    return {
        category: [e for g in genres for e in config.item_genre_examples[g]]
        for category, genres in config.labels.item_categories.items()
    }


def _classifiers(config: AppConfig, url: str) -> dict[str, tuple[Classify, bool]]:
    """名前 → (分類する関数, 2段か)。"""
    thresholds = config.thresholds
    result: dict[str, tuple[Classify, bool]] = {}
    encoder = _SentenceTransformerEncoder(MODEL_NAME)
    for two_stage, examples in (
        (False, _category_examples(config)),
        (True, config.item_genre_examples),
    ):
        stage = "2段" if two_stage else "1段"
        embedding = EmbeddingItemGenreClassifier(
            encoder=encoder,
            examples=examples,
            min_confidence=thresholds.item_genre_min_confidence,
            temperature=thresholds.item_genre_temperature,
        )
        llm = LlmItemGenreClassifier(
            url=url, examples=examples, min_confidence=thresholds.item_genre_min_confidence
        )
        result[f"embedding・{stage}"] = (embedding.classify, two_stage)
        result[f"llm・{stage}"] = (llm.classify, two_stage)
    return result


def _macro_f1(gold: list[str], predicted: list[str | None]) -> float:
    scores = []
    for label in sorted(set(gold)):
        tp = sum(g == label and p == label for g, p in zip(gold, predicted, strict=True))
        fp = sum(g != label and p == label for g, p in zip(gold, predicted, strict=True))
        fn = sum(g == label and p != label for g, p in zip(gold, predicted, strict=True))
        scores.append(2 * tp / (2 * tp + fp + fn) if tp else 0.0)
    return sum(scores) / len(scores)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("gold", type=Path)
    parser.add_argument("detail_out", type=Path)
    parser.add_argument("--url", required=True)
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config")
    args = parser.parse_args()

    config = load_config(args.config)
    with args.gold.open(encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["genre"]]
    gold_genres = [r["genre"] for r in rows]
    gold_categories = [config.labels.category_of(g) for g in gold_genres]
    unchanged = sum(r["genre"] == r["draft_genre"] for r in rows)
    print(f"items: {len(rows)}, 下書きのまま: {unchanged} ({unchanged / len(rows):.0%})")

    names = list(dict.fromkeys(r["name"] for r in rows))
    details: dict[str, dict[str, object]] = {n: {"name": n} for n in names}
    for label, (classify, two_stage) in _classifiers(config, args.url).items():
        start = time.perf_counter()
        by_name = dict(zip(names, classify(names), strict=True))
        per_item = (time.perf_counter() - start) / len(names)

        judgements = [by_name[r["name"]] for r in rows]
        if two_stage:
            categories = [
                config.labels.category_of(j.genre) if j.genre else None for j in judgements
            ]
        else:
            categories = [j.genre for j in judgements]
        correct = [p == g for p, g in zip(categories, gold_categories, strict=True)]
        confirmed = [j.status == "confirmed" for j in judgements]
        confirmed_correct = sum(c and ok for c, ok in zip(confirmed, correct, strict=True))

        line = (
            f"{label}: 大分類 {sum(correct) / len(rows):.1%}"
            f", マクロF1 {_macro_f1(gold_categories, categories):.3f}"
        )
        if two_stage:
            genre_correct = sum(j.genre == g for j, g in zip(judgements, gold_genres, strict=True))
            line += f", 小分類 {genre_correct / len(rows):.1%}"
        line += (
            f", 確定 {sum(confirmed) / len(rows):.0%}"
            f"（その中の大分類 {confirmed_correct / max(sum(confirmed), 1):.1%}）"
            f", {per_item * 1000:.0f}ms/品名"
        )
        print(line)
        for name, j in by_name.items():
            details[name][label] = [
                j.genre,
                None if j.confidence is None else round(j.confidence, 3),
            ]

    with args.detail_out.open("w", encoding="utf-8") as out:
        for r in rows:
            out.write(
                json.dumps({**details[r["name"]], "gold": r["genre"]}, ensure_ascii=False) + "\n"
            )


if __name__ == "__main__":
    main()
