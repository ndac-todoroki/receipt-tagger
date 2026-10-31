"""品目ジャンル分類（FR-11）。LLM に、出力をジャンルの選択肢に縛った JSON で答えさせる。

読み取りと同じ vLLM（Qwen3.6-35B-A3B）に品名を1つずつ送り、JSON スキーマの enum で
ジャンルの選択肢以外を出せないようにする（制約付きデコーディング）。学習はしない。
信頼度は、ジャンル名の部分のトークンの確率の積とする。
"""

import json
import logging
import math
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from receipt_app.config import AppConfig
from receipt_app.stages.item_genre import CANDIDATE_COUNT, ItemGenreJudgement

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30.0
# vLLM は同時に来た問い合わせをまとめて処理するので、品目ごとの問い合わせを並べて送る
MAX_PARALLEL = 8

PROMPT = """レシートの品名を、次のジャンルから1つ選んで JSON で答えてください。
品名は略されていたり半角カナだったりします。各ジャンルの後ろは品名の例です。

{genres}"""


def _post_json(url: str, body: dict[str, object]) -> object:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as res:
        return json.load(res)


class LlmItemGenreClassifier:
    """推論サーバー（vLLM）の LLM に、ジャンルの選択肢から品目ジャンルを選ばせる分類器。"""

    def __init__(
        self,
        url: str,
        examples: dict[str, list[str]],
        min_confidence: float,
        model: str = "default",
        post_json: Callable[[str, dict[str, object]], object] = _post_json,
    ) -> None:
        self._url = url
        self._genres = list(examples)
        self._min_confidence = min_confidence
        self._model = model
        self._post_json = post_json
        self._prompt = PROMPT.format(
            genres="\n".join(f"- {g}: {'、'.join(e)}" for g, e in examples.items())
        )

    @classmethod
    def load(cls, config: AppConfig, url: str) -> "LlmItemGenreClassifier":
        """設定の見本と閾値で分類器を作る。"""
        return cls(
            url=url,
            examples=config.item_genre_examples,
            min_confidence=config.thresholds.item_genre_min_confidence,
        )

    def classify(self, names: list[str]) -> list[ItemGenreJudgement]:
        """品名ごとに品目ジャンルを判定する。問い合わせに失敗した品目は判定不能にする。"""
        if not names:
            return []
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
            return list(pool.map(self._classify_one, names))

    def _classify_one(self, name: str) -> ItemGenreJudgement:
        body: dict[str, object] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": self._prompt},
                {"role": "user", "content": f"品名: {name}"},
            ],
            "temperature": 0,
            "max_tokens": 64,
            "chat_template_kwargs": {"enable_thinking": False},
            "logprobs": True,
            "top_logprobs": CANDIDATE_COUNT,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "item_genre",
                    "schema": {
                        "type": "object",
                        "properties": {"genre": {"enum": self._genres}},
                        "required": ["genre"],
                    },
                },
            },
        }
        try:
            choice = self._post_json(self._url, body)["choices"][0]  # type: ignore[index]
            genre = json.loads(choice["message"]["content"])["genre"]
            tokens = choice["logprobs"]["content"]
            if genre not in self._genres:
                raise ValueError("選択肢に無いジャンル")
            confidence, alternatives = _value_probability(
                choice["message"]["content"], genre, tokens
            )
        except Exception as e:
            # 品名はレシートの内容なのでログに出さない
            logger.warning("品目ジャンルの問い合わせに失敗: %s", type(e).__name__)
            return ItemGenreJudgement(genre=None, confidence=None, status="unknown")

        candidates = [genre]
        for prefix in alternatives:
            candidates += [g for g in self._genres if g.startswith(prefix) and g not in candidates]
        return ItemGenreJudgement(
            genre=genre,
            confidence=confidence,
            status="confirmed" if confidence >= self._min_confidence else "uncertain",
            candidates=candidates[:CANDIDATE_COUNT],
        )


def _value_probability(
    content: str, genre: str, tokens: list[dict[str, Any]]
) -> tuple[float, list[str]]:
    """ジャンル名の部分のトークンの確率の積と、最初のトークンの代わりの候補（確率の高い順）。"""
    # 値の前後の記号や空白は、どのジャンルを選んでも同じなので信頼度に含めない
    start = content.index(f'"{genre}"', content.index('"genre"') + len('"genre"')) + 1
    end = start + len(genre)
    logprob = 0.0
    alternatives: list[str] = []
    offset = 0
    for token in tokens:
        text = str(token["token"])
        if offset < end and offset + len(text) > start:
            logprob += float(token["logprob"])
            if not alternatives:
                # 値の直前の記号と同じトークンにまとまっていれば、その分を除いて比べる
                skip = max(start - offset, 0)
                top = sorted(token["top_logprobs"], key=lambda t: -t["logprob"])
                alternatives = [str(t["token"])[skip:] for t in top if str(t["token"])[skip:]]
        offset += len(text)
    return math.exp(logprob), alternatives
