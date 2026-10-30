"""旧方式の各段をつなぎ、画像からレシートの内容を読む。"""

from typing import Protocol

from PIL import Image

from receipt_app.stages.ocr_reader.lines import OcrBox, group_rows
from receipt_app.stages.ocr_reader.receipt_parser import parse_receipt
from receipt_app.stages.receipt import ParsedReceipt


class OcrEngine(Protocol):
    def read(self, image: Image.Image) -> list[OcrBox]: ...


class OcrReceiptReader:
    """OCR → 行の組み立て → ルールのパーサ。"""

    def __init__(self, ocr: OcrEngine) -> None:
        self._ocr = ocr

    def read(self, image: Image.Image) -> ParsedReceipt:
        rows = [row.text for row in group_rows(self._ocr.read(image))]
        return parse_receipt(rows)
