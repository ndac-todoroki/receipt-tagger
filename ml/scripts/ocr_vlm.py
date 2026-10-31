"""視覚言語モデル（VLM）でレシート画像を読み、応答を JSON で保存する。

OCR を GPU の VLM に置き換えるかを決めるための実験スクリプト。DGX Spark 上で、
OpenAI 互換 API を持つ推論サーバー（SGLang 等）を立ててから実行する。

    python ocr_vlm.py <画像フォルダ> <出力フォルダ> --mode lines|struct [--url URL] [--limit N]
        [--prompt 指示文]

- lines: 文字を行ごとに書き出させる（OCR だけを置き換え、行の組み立て以降は既存のパーサを使う案）
- struct: 店名・品目・金額・合計を JSON で出させる（パーサまで置き換える案）

出力は画像ごとに1つの JSON。実レシート由来なので、出力フォルダはリポジトリの外か
ml/data/private/ にすること。評価は eval_vlm.py で行う。
"""

import argparse
import base64
import io
import json
import time
import urllib.request
from pathlib import Path

from PIL import Image, ImageOps

# 長辺をこれ以下に縮める。スマホの写真をそのまま送ると画像トークンが増えすぎて遅くなる
MAX_SIDE = 2048

LINES_PROMPT = """このレシート画像に書かれている文字を、上から順に1行ずつ書き出してください。
- 同じ高さに並んでいる文字（品名と金額など）は、左から右の順に空白で区切って1行にまとめる
- 文字は画像のとおりに書き、補ったり言い換えたりしない
- 説明や前置きは書かない"""

STRUCT_PROMPT = """このレシート画像から、次の項目を読み取って JSON で答えてください。
- store_name: 店名（読めなければ null）
- items: 購入した品目。name は品名、quantity は個数、unit_price は単価、amount はその行の金額。
  値引き・割引の行も品目として含め、amount を負の数にする。個数・単価が書かれていなければ null
  品名や金額のそばにある税区分の印（外8、軽8、※、10% など）は個数ではないので quantity に入れない
- subtotal: 小計（無ければ null）
- tax: 外税の額（税抜きの品目に合計で加算される消費税。内税のみなら null）
- total: 合計金額（支払った金額ではなく合計。読めなければ null）
金額は円単位の整数にする。画像に無い品目を補わない。"""

STRUCT_SCHEMA = {
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


def load_image(path: Path) -> Image.Image:
    """写真の向きを直し、長辺を MAX_SIDE 以下に縮めて読み込む。"""
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    return img


def _image_data_url(path: Path) -> str:
    img = load_image(path)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _request(url: str, model: str, mode: str, image_url: str, prompt: str | None) -> str:
    if prompt is None:
        prompt = LINES_PROMPT if mode == "lines" else STRUCT_PROMPT
    body: dict[str, object] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "temperature": 0,
        "max_tokens": 4096,
        # 思考を出させると1枚に数分かかるので切る
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if mode == "struct":
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "receipt", "schema": STRUCT_SCHEMA},
        }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=600) as res:
        content: str = json.load(res)["choices"][0]["message"]["content"]
    return content


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image_dir", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--mode", choices=["lines", "struct"], required=True)
    parser.add_argument("--url", default="http://localhost:30000/v1/chat/completions")
    parser.add_argument("--model", default="default")
    parser.add_argument("--limit", type=int, default=None)
    # OCR 専用モデルは決まった指示文（例: GLM-OCR の "Text Recognition:"）で学習されている
    parser.add_argument("--prompt", default=None)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    images = sorted(p for p in args.image_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg"})
    for path in images[: args.limit]:
        start = time.perf_counter()
        content = _request(args.url, args.model, args.mode, _image_data_url(path), args.prompt)
        elapsed = time.perf_counter() - start
        result = {"image": path.name, "mode": args.mode, "elapsed": elapsed, "content": content}
        out = args.out_dir / f"{path.stem}.json"
        out.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        # 画像名や内容は出さず、進み具合と時間だけを出す
        print(f"{elapsed:.1f}s", flush=True)


if __name__ == "__main__":
    main()
