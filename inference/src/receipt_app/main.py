"""FastAPIアプリ。APIと、Solid.jsのビルド成果物の静的配信を担う。"""

import io
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError

from receipt_app import pipeline
from receipt_app.schemas import AnalyzeResult

DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def create_app(
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    static_dir: Path | None = None,
) -> FastAPI:
    """アプリを組み立てる。static_dir を渡すとそこを画面として配信する。"""
    app = FastAPI(title="receipt-tagger")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/analyze")
    async def analyze(image: UploadFile) -> AnalyzeResult:
        # 上限+1バイトだけ読めば超過を判定でき、巨大ファイルを丸ごとメモリに載せずに済む
        data = await image.read(max_upload_bytes + 1)
        if len(data) > max_upload_bytes:
            raise HTTPException(status_code=413, detail="画像が大きすぎます")
        try:
            img = Image.open(io.BytesIO(data))
            img.load()
        except UnidentifiedImageError as e:
            raise HTTPException(status_code=415, detail="画像として読み込めません") from e
        # 画像はディスクに保存せず、メモリ上で処理して破棄する
        return pipeline.analyze(img.convert("RGB"))

    if static_dir is not None and static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app


def _static_dir_from_env() -> Path | None:
    value = os.environ.get("STATIC_DIR")
    return Path(value) if value else None


app = create_app(static_dir=_static_dir_from_env())
