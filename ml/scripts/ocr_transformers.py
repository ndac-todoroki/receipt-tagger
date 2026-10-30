"""推論サーバーが対応していない VLM を transformers で直接動かし、ocr_vlm.py と同じ形で保存する。

sarashina2.2-vision のように、同梱のカスタムコード（trust_remote_code）でしか動かないモデル用。
指示文と画像の前処理は ocr_vlm.py と共通にして、評価は eval_vlm.py で行う。DGX Spark 上で実行する。

    python ocr_transformers.py <モデル> <画像フォルダ> <出力フォルダ> --mode lines|struct [--limit N]

struct でも出力の形を強制する仕組み（JSON スキーマでの制約付き生成）は無いので、
指示文だけで JSON を出させる。
"""

import argparse
import json
import time
from pathlib import Path

import torch
from ocr_vlm import LINES_PROMPT, STRUCT_PROMPT, load_image
from transformers import AutoModelForCausalLM, AutoProcessor


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model")
    parser.add_argument("image_dir", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--mode", choices=["lines", "struct"], required=True)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    processor = AutoProcessor.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, device_map="cuda", torch_dtype="auto", trust_remote_code=True
    )
    prompt = LINES_PROMPT if args.mode == "lines" else STRUCT_PROMPT
    message = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt}]}]
    text_prompt = processor.apply_chat_template(message, add_generation_prompt=True)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    images = sorted(p for p in args.image_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg"})
    for path in images[: args.limit]:
        start = time.perf_counter()
        inputs = processor(
            text=[text_prompt], images=[load_image(path)], padding=True, return_tensors="pt"
        ).to(model.device)
        with torch.inference_mode():
            # 他のモデルと条件を揃えるため貪欲法にする。同じ行の繰り返しに陥るのを
            # 抑えるため、繰り返しへの罰則だけ軽くかける
            output_ids = model.generate(
                **inputs, max_new_tokens=4096, do_sample=False, repetition_penalty=1.05
            )
        generated = output_ids[0][len(inputs.input_ids[0]) :]
        content = processor.decode(generated, skip_special_tokens=True)
        elapsed = time.perf_counter() - start
        result = {"image": path.name, "mode": args.mode, "elapsed": elapsed, "content": content}
        out = args.out_dir / f"{path.stem}.json"
        out.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        # 画像名や内容は出さず、進み具合と時間だけを出す
        print(f"{elapsed:.1f}s", flush=True)


if __name__ == "__main__":
    main()
