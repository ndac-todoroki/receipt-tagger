"""FastAPIアプリ。APIと、Solid.jsのビルド成果物の静的配信を担う。"""

import io
import json
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, get_args

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from receipt_app.analysis_queue import AnalysisQueue, QueueEvent, QueueFull
from receipt_app.config import load_config
from receipt_app.rate_limit import RateLimiter
from receipt_app.schemas import AnalyzeResult
from receipt_app.stages.receipt import ReadError

DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# multipart の区切りや見出しの分として、画像の上限に足して受け取る量
MULTIPART_OVERHEAD_BYTES = 64 * 1024
# 画素数の上限。5000万画素のスマホの写真まで受け付ける。小さなファイルでも展開すると
# 巨大になる画像（解凍爆弾）を、展開する前に弾く
DEFAULT_MAX_PIXELS = 52_000_000
# スマホのブラウザが送ってくる形式に限り、珍しい形式の解析コードを外から呼ばせない
ALLOWED_IMAGE_FORMATS = ["JPEG", "PNG", "WEBP"]
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    # 他のサイトに埋め込ませない（埋め込んで誤操作を誘う手口を防ぐ）
    "Content-Security-Policy": "frame-ancestors 'none'; base-uri 'none'; object-src 'none'",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
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
    max_pixels: int = DEFAULT_MAX_PIXELS,
) -> FastAPI:
    """アプリを組み立てる。analyzer を省くと、起動時に本物のパイプラインを読み込む。"""
    state: dict[str, Analyzer] = {} if analyzer is None else {"analyze": analyzer}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # モデルはリクエストごとではなく、起動時に1回だけ読み込む
        if "analyze" not in state:
            state["analyze"] = _load_pipeline()
        yield

    # API の説明ページは公開しない（使うのは自前の画面だけなので）
    app = FastAPI(
        title="receipt-tagger", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )

    @app.middleware("http")
    async def add_security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    queue = queue or AnalysisQueue(max_waiting=DEFAULT_MAX_WAITING)
    limiter = RateLimiter(rate_limits or DEFAULT_RATE_LIMITS)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/analyze")
    async def analyze(request: Request) -> StreamingResponse:
        if not limiter.allow(_client_ip(request)):
            raise HTTPException(
                status_code=429, detail="続けて送りすぎです。時間をおいて試してください"
            )
        if queue.full:
            raise HTTPException(status_code=503, detail=BUSY_DETAIL)
        upright = _decode_image(await _read_upload(request, max_upload_bytes), max_pixels)
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


class _InMemoryMultiPartParser(MultiPartParser):
    """受け取ったファイルを一時ファイルに書かず、メモリにだけ置く multipart のパーサ。

    Starlette の既定では 1MB を超えるファイルをディスクの一時ファイルに書く。
    受け取る本体の大きさを先に spool_max_size 以下に抑えておけば、ディスクに切り替わらない。
    """

    def __init__(self, *args: Any, spool_max_size: int, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.spool_max_size = spool_max_size


async def _read_upload(request: Request, max_upload_bytes: int) -> bytes:
    """フォームの image を、ディスクに書かずにメモリへ読む。上限を超えた時点で 413。"""
    too_large = HTTPException(status_code=413, detail="画像が大きすぎます")
    limit = max_upload_bytes + MULTIPART_OVERHEAD_BYTES
    if not request.headers.get("content-type", "").startswith("multipart/form-data"):
        raise HTTPException(status_code=415, detail="画像をフォームで送ってください")
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > limit:
        raise too_large
    # Content-Length が無い・偽っている場合に備え、読みながら数えて打ち切る
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise too_large

    async def replay() -> AsyncIterator[bytes]:
        yield bytes(body)

    parser = _InMemoryMultiPartParser(
        request.headers, replay(), max_files=1, max_fields=1, spool_max_size=limit
    )
    try:
        form = await parser.parse()
    except MultiPartException as e:
        raise HTTPException(status_code=400, detail="フォームの形が正しくありません") from e
    image = form.get("image")
    if not isinstance(image, UploadFile):
        raise HTTPException(status_code=400, detail="画像がありません")
    data = await image.read()
    if len(data) > max_upload_bytes:
        raise too_large
    return data


def _decode_image(data: bytes, max_pixels: int) -> Image.Image:
    """画像を展開し、向きを直した RGB にする。形式の違いや壊れた画像は 415。"""
    unreadable = HTTPException(status_code=415, detail="画像として読み込めません")
    try:
        # open は見出しだけを読む。画素の展開は画素数を確かめてから行う
        img = Image.open(io.BytesIO(data), formats=ALLOWED_IMAGE_FORMATS)
    except Image.DecompressionBombError as e:
        raise HTTPException(status_code=413, detail="画像の画素数が多すぎます") from e
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise unreadable from e
    if img.width * img.height > max_pixels:
        raise HTTPException(status_code=413, detail="画像の画素数が多すぎます")
    try:
        img.load()
        # スマホの写真は向きがEXIFに入っているので、画素を正しい向きに直してから読む
        return ImageOps.exif_transpose(img).convert("RGB")
    except (OSError, ValueError, SyntaxError) as e:
        raise unreadable from e


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
