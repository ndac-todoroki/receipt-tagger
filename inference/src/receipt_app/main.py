"""FastAPIアプリ。APIと、Solid.jsのビルド成果物の静的配信を担う。"""

import io
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError

from receipt_app.config import load_config
from receipt_app.schemas import AnalyzeResult

DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
REPO_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"

Analyzer = Callable[[Image.Image], AnalyzeResult]


def _load_pipeline() -> Analyzer:
    # モデルの読み込みは重いので、テストで偽の解析関数を渡す場合は読み込まない
    from receipt_app.pipeline import Pipeline

    config_dir = Path(os.environ.get("CONFIG_DIR", REPO_CONFIG_DIR))
    model_dir = os.environ.get("MODEL_DIR")
    pipeline = Pipeline.load(load_config(config_dir), Path(model_dir) if model_dir else None)
    return pipeline.analyze


def create_app(
    analyzer: Analyzer | None = None,
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    static_dir: Path | None = None,
) -> FastAPI:
    """アプリを組み立てる。analyzer を省くと、起動時に本物のパイプラインを読み込む。"""
    state: dict[str, Analyzer] = {} if analyzer is None else {"analyze": analyzer}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # モデルはリクエストごとではなく、起動時に1回だけ読み込む
        if "analyze" not in state:
            state["analyze"] = _load_pipeline()
        yield

    app = FastAPI(title="receipt-tagger", lifespan=lifespan)

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
        # スマホの写真は向きがEXIFに入っているので、画素を正しい向きに直してから読む
        upright = ImageOps.exif_transpose(img).convert("RGB")
        # 画像はディスクに保存せず、メモリ上で処理して破棄する。
        # OCRはCPUを長く使うので、イベントループを止めないよう別スレッドで動かす
        return await run_in_threadpool(state["analyze"], upright)

    if static_dir is not None and static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app


def _static_dir_from_env() -> Path | None:
    value = os.environ.get("STATIC_DIR")
    return Path(value) if value else None


app = create_app(static_dir=_static_dir_from_env())
