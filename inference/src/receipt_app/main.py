"""FastAPIアプリ。APIと、Solid.jsのビルド成果物の静的配信を担う。"""

import io
import json
import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import get_args

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError

from receipt_app.analysis_queue import AnalysisQueue, QueueEvent, QueueFull
from receipt_app.config import load_config
from receipt_app.rate_limit import RateLimiter
from receipt_app.schemas import AnalyzeResult
from receipt_app.stages.receipt import ReadError

DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# 待っている依頼の上限。1件に約10秒かかるので、10件なら最後の人は約2分待つ
DEFAULT_MAX_WAITING = 10
# 同じ相手からの依頼の上限（期間の秒数, 回数）。1件に約10秒かかるので、
# 人が試す範囲では届かず、機械的な連打だけを止める
DEFAULT_RATE_LIMITS = [(60.0, 10), (86400.0, 1000)]
BUSY_DETAIL = "混んでいます。しばらくしてから試してください"
REPO_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"

logger = logging.getLogger(__name__)

READ_ERROR_DETAIL = "レシートを読み取れませんでした。時間をおいて試してください"

# 画像と、解析の段階を知らせる関数を受け取って解析する
Analyzer = Callable[[Image.Image, Callable[[str], None]], AnalyzeResult]


def _load_pipeline() -> Analyzer:
    # モデルの読み込みは重いので、テストで偽の解析関数を渡す場合は読み込まない
    from receipt_app.pipeline import DEFAULT_VLM_URL, ItemClassifierKind, Pipeline, ReaderKind

    config_dir = Path(os.environ.get("CONFIG_DIR", REPO_CONFIG_DIR))
    model_dir = os.environ.get("MODEL_DIR")
    reader = os.environ.get("RECEIPT_READER", "vlm")
    if reader not in get_args(ReaderKind):
        raise ValueError(f"RECEIPT_READER は vlm か ocr: {reader}")
    item_classifier = os.environ.get("ITEM_CLASSIFIER", "llm")
    if item_classifier not in get_args(ItemClassifierKind):
        raise ValueError(f"ITEM_CLASSIFIER は embedding か llm: {item_classifier}")
    pipeline = Pipeline.load(
        load_config(config_dir),
        Path(model_dir) if model_dir else None,
        reader=reader,  # type: ignore[arg-type]
        vlm_url=os.environ.get("VLM_URL", DEFAULT_VLM_URL),
        item_classifier=item_classifier,  # type: ignore[arg-type]
    )
    return pipeline.analyze


def create_app(
    analyzer: Analyzer | None = None,
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    static_dir: Path | None = None,
    rate_limits: list[tuple[float, int]] | None = None,
    queue: AnalysisQueue | None = None,
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
    queue = queue or AnalysisQueue(max_waiting=DEFAULT_MAX_WAITING)
    limiter = RateLimiter(rate_limits or DEFAULT_RATE_LIMITS)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/analyze")
    async def analyze(image: UploadFile, request: Request) -> StreamingResponse:
        if not limiter.allow(_client_ip(request)):
            raise HTTPException(
                status_code=429, detail="続けて送りすぎです。時間をおいて試してください"
            )
        if queue.full:
            raise HTTPException(status_code=503, detail=BUSY_DETAIL)
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
        # 画像はディスクに保存せず、メモリ上で処理して破棄する
        events = queue.run(lambda on_stage: state["analyze"](upright, on_stage))
        return StreamingResponse(
            _ndjson(events),
            media_type="application/x-ndjson",
            # 途中の中継（Cloudflare など）でまとめて送られると、進み具合がすぐ届かない
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    if static_dir is not None and static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app


def _client_ip(request: Request) -> str:
    """依頼してきた相手の IP アドレス。

    Cloudflare Tunnel 経由では接続元がすべて cloudflared になるので、Cloudflare が付ける
    CF-Connecting-IP を使う。アプリのポートはホストの 127.0.0.1 と compose の内部にしか
    開いていないので、外から直接この見出しを偽って送ることはできない。
    """
    forwarded = request.headers.get("CF-Connecting-IP")
    if forwarded:
        return forwarded
    return request.client.host if request.client else "unknown"


def _json_line(obj: dict[str, object]) -> str:
    return json.dumps(obj, ensure_ascii=False) + "\n"


async def _ndjson(events: AsyncIterator[QueueEvent]) -> AsyncIterator[str]:
    """キューのイベントを、1行1つの JSON にして送る。"""
    try:
        async for e in events:
            if e.kind == "done":
                line: dict[str, object] = {"type": "result", "result": e.result.model_dump()}
            else:
                line = {"type": e.kind}
                if e.ahead is not None:
                    line["ahead"] = e.ahead
                if e.stage is not None:
                    line["stage"] = e.stage
                if e.estimate_seconds is not None:
                    line["estimate_seconds"] = round(e.estimate_seconds, 1)
            yield _json_line(line)
    except QueueFull:
        # 上限の確かめと列に並ぶまでの間に、他の依頼が先に並んだ
        yield _json_line({"type": "error", "detail": BUSY_DETAIL})
    except ReadError:
        # 進み具合を送り始めた後なので、HTTP の状態コードではなく最後の行で伝える
        yield _json_line({"type": "error", "detail": READ_ERROR_DETAIL})
    except Exception as e:
        # レシートの内容が含まれうるので、例外の中身はログに出さない
        logger.error("解析に失敗: %s", type(e).__name__)
        yield _json_line({"type": "error", "detail": "解析に失敗しました"})


def _static_dir_from_env() -> Path | None:
    value = os.environ.get("STATIC_DIR")
    return Path(value) if value else None


app = create_app(static_dir=_static_dir_from_env())
