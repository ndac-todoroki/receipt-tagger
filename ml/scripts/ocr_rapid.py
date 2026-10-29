"""RapidOCR（PaddleOCR の ONNX 版）でレシート画像を OCR し、結果を JSON で保存する。

OCR モデル選定（未決事項）のための実験スクリプト。DGX Spark 上で実行する。

    python ocr_rapid.py <画像フォルダ> <出力フォルダ> [--limit N] [--lang JAPAN] [--version PPOCRV6]
        [--model-type medium] [--det-lang JAPAN]

指定できる組み合わせは rapidocr の default_models.yaml を参照（例: v6 は JAPAN + tiny/small/medium、
v5 は CH + mobile/server + --det-lang CH。v5 の CH モデルは日本語も読める）。

出力は画像ごとに1つの JSON（文字列・座標・確信度）。実レシート由来なので、
出力フォルダはリポジトリの外か ml/data/private/ にすること。
"""

import argparse
import json
import time
from pathlib import Path

from rapidocr import LangDet, LangRec, ModelType, OCRVersion, RapidOCR


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image_dir", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--lang", default="JAPAN")
    parser.add_argument("--version", default="PPOCRV6")
    parser.add_argument("--model-type", default="medium")
    parser.add_argument("--det-lang", default="JAPAN")
    args = parser.parse_args()

    # v6 の検出モデルは LangDet に無い言語（JAPAN）も受け付けるので LangRec で渡す
    det_lang = (
        LangDet[args.det_lang] if args.det_lang in LangDet.__members__ else LangRec[args.det_lang]
    )
    engine = RapidOCR(
        params={
            "Rec.lang_type": LangRec[args.lang],
            "Rec.ocr_version": OCRVersion[args.version],
            "Rec.model_type": ModelType[args.model_type.upper()],
            "Det.lang_type": det_lang,
            "Det.ocr_version": OCRVersion[args.version],
            "Det.model_type": ModelType[args.model_type.upper()],
        }
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    images = sorted(args.image_dir.glob("*.jpg"))[: args.limit]
    for path in images:
        started = time.perf_counter()
        result = engine(str(path))
        elapsed = time.perf_counter() - started
        boxes = [] if result.boxes is None else result.boxes.tolist()
        items = [
            {"text": text, "score": float(score), "box": box}
            for text, score, box in zip(result.txts or [], result.scores or [], boxes, strict=True)
        ]
        out = {"image": path.name, "seconds": round(elapsed, 2), "items": items}
        (args.out_dir / f"{path.stem}.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"{path.name}: {len(items)} 件, {elapsed:.1f} 秒")


if __name__ == "__main__":
    main()
