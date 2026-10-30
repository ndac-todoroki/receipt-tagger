"""旧方式の読み取り: OCR（RapidOCR）→ 行の組み立て → ルールのパーサ。

2026-10-30 に視覚言語モデル（stages/vlm_reader.py）へ置き換えた。比較の材料にするため、
コードと評価スクリプト（ml/scripts/eval_parser.py）を残している。
アプリの読み取りは、環境変数 RECEIPT_READER=ocr でこちらに戻せる。
"""
