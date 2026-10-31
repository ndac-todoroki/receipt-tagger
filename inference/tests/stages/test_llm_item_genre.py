"""LLM の制約付きデコーディングによる品目ジャンル分類（FR-11）のテスト。

確かめること: 推論サーバーが選んだジャンルを返す、ジャンル名のトークンの確率を信頼度にする、
            閾値未満を未確定にして候補を出す、
            推論サーバーに送る内容（ジャンルの enum、見本、品名）、
            通信の失敗や壊れた応答をその品目だけ判定不能にする。
確かめないこと: LLM が正しく分類できるか（ml/scripts で実レシートの品名を使って測る）。
            推論サーバーは偽物を使う。
"""

import json
import math

from receipt_app.stages.llm_item_genre import LlmItemGenreClassifier

EXAMPLES = {"肉": ["鶏もも肉"], "魚介": ["生鮭 切身"], "菓子・スナック": ["ポテトチップス"]}


def _token(text: str, prob: float, alternatives: dict[str, float] | None = None) -> object:
    top = {text: prob, **(alternatives or {})}
    return {
        "token": text,
        "logprob": math.log(prob),
        "top_logprobs": [{"token": t, "logprob": math.log(p)} for t, p in top.items()],
    }


def _response(*value_tokens: object) -> object:
    """{"genre": "<value_tokens>"} の応答。値の前後の記号は確率1のトークンにする。"""
    value = "".join(t["token"] for t in value_tokens)  # type: ignore[index]
    tokens = [_token('{"genre": "', 1.0), *value_tokens, _token('"}', 1.0)]
    return {
        "choices": [
            {
                "message": {"content": json.dumps({"genre": value}, ensure_ascii=False)},
                "logprobs": {"content": tokens},
            }
        ]
    }


class FakeServer:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.bodies: list[dict[str, object]] = []

    def post_json(self, url: str, body: dict[str, object]) -> object:
        self.bodies.append(body)
        name = body["messages"][-1]["content"].removeprefix("品名: ")  # type: ignore[index]
        response = self.responses[name]
        if isinstance(response, Exception):
            raise response
        return response


def _classifier(server: FakeServer, min_confidence: float = 0.5) -> LlmItemGenreClassifier:
    return LlmItemGenreClassifier(
        url="http://vllm/v1/chat/completions",
        examples=EXAMPLES,
        min_confidence=min_confidence,
        post_json=server.post_json,
    )


def test_推論サーバーが選んだジャンルを品名ごとに返す() -> None:
    server = FakeServer(
        {
            "ﾎﾟﾃﾄﾁｯﾌﾟｽ": _response(_token("菓子", 0.9), _token("・スナック", 1.0)),
            "鶏むね": _response(_token("肉", 0.95)),
        }
    )

    judgements = _classifier(server).classify(["ﾎﾟﾃﾄﾁｯﾌﾟｽ", "鶏むね"])

    assert [j.genre for j in judgements] == ["菓子・スナック", "肉"]
    assert [j.status for j in judgements] == ["confirmed", "confirmed"]


def test_ジャンル名のトークンの確率の積を信頼度にする() -> None:
    # 値の前後の記号（{"genre": " など）の確率は信頼度に含めない
    server = FakeServer({"ﾎﾟﾃﾄﾁｯﾌﾟｽ": _response(_token("菓子", 0.9), _token("・スナック", 0.5))})

    (judgement,) = _classifier(server).classify(["ﾎﾟﾃﾄﾁｯﾌﾟｽ"])

    assert math.isclose(judgement.confidence or 0, 0.45)


def test_信頼度が閾値未満なら未確定にして確率の高い順に候補を出す() -> None:
    server = FakeServer({"ｻｹﾌﾚｰｸ": _response(_token("魚介", 0.4, {"肉": 0.35, "菓子": 0.2}))})

    (judgement,) = _classifier(server).classify(["ｻｹﾌﾚｰｸ"])

    assert judgement.status == "uncertain"
    assert judgement.candidates == ["魚介", "肉", "菓子・スナック"]


def test_推論サーバーに出力をジャンルの選択肢に縛るよう頼み見本と品名を送る() -> None:
    server = FakeServer({"鶏むね": _response(_token("肉", 0.95))})

    _classifier(server).classify(["鶏むね"])

    (body,) = server.bodies
    schema = body["response_format"]["json_schema"]["schema"]  # type: ignore[index]
    assert schema["properties"]["genre"]["enum"] == ["肉", "魚介", "菓子・スナック"]
    assert body["logprobs"] is True
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert "鶏もも肉" in body["messages"][0]["content"]  # type: ignore[index]
    assert body["messages"][-1]["content"] == "品名: 鶏むね"  # type: ignore[index]


def test_問い合わせに失敗した品目だけ判定不能にする() -> None:
    server = FakeServer({"鶏むね": _response(_token("肉", 0.95)), "ｻｹ": TimeoutError()})

    judgements = _classifier(server).classify(["鶏むね", "ｻｹ"])

    assert [(j.genre, j.status) for j in judgements] == [("肉", "confirmed"), (None, "unknown")]


def test_選択肢に無いジャンルや壊れた応答は判定不能にする() -> None:
    server = FakeServer(
        {
            "a": _response(_token("野菜", 0.9)),
            "b": {"choices": [{"message": {"content": "{"}, "logprobs": None}]},
            "c": {"error": "busy"},
        }
    )

    judgements = _classifier(server).classify(["a", "b", "c"])

    assert [j.status for j in judgements] == ["unknown", "unknown", "unknown"]


def test_品名が無ければ問い合わせずに空のリストを返す() -> None:
    server = FakeServer({})

    assert _classifier(server).classify([]) == []
    assert server.bodies == []
