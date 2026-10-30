"""OCR（段2）。RapidOCR（PaddleOCR の ONNX 版）で、画像から文字列と座標を読む。

モデルは PP-OCRv6 medium（日本語）。選定の経緯は docs/devlog.md を参照。
"""

from pathlib import Path

from PIL import Image

from receipt_app.stages.ocr_reader.lines import OcrBox


class RapidOcrReader:
    """RapidOCR で画像を読む。モデルの読み込みは生成時に1回だけ行う。"""

    def __init__(self, model_dir: Path | None = None) -> None:
        # 重いライブラリなので、OCRを使うときにだけ読み込む（テストを軽くする）
        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR
        from rapidocr.utils.output import RapidOCROutput

        params: dict[str, object] = {
            "Global.log_level": "warning",
            "Rec.lang_type": LangRec.JAPAN,
            "Rec.ocr_version": OCRVersion.PPOCRV6,
            "Rec.model_type": ModelType.MEDIUM,
            # v6 の検出モデルは LangDet に無い言語（JAPAN）も受け付けるので LangRec で渡す
            "Det.lang_type": LangRec.JAPAN,
            "Det.ocr_version": OCRVersion.PPOCRV6,
            "Det.model_type": ModelType.MEDIUM,
        }
        if model_dir is not None:
            # モデルをイメージに焼かず、ボリュームに置いて再起動後も使い回す
            params["Global.model_root_dir"] = str(model_dir)
        self._engine = RapidOCR(params=params)
        self._output_type = RapidOCROutput

    def read(self, image: Image.Image) -> list[OcrBox]:
        """画像中の文字列を、座標と確信度つきで返す。"""
        result = self._engine(image)
        # 検出・認識をすべて行う呼び方なので、戻り値は常に全段の結果になる
        assert isinstance(result, self._output_type)
        boxes = [] if result.boxes is None else result.boxes.tolist()
        return [
            OcrBox(text=text, score=float(score), box=box)
            for text, score, box in zip(result.txts or [], result.scores or [], boxes, strict=True)
        ]
