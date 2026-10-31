"""解析の依頼を、来た順に1件ずつ処理するキュー。

推論サーバーは1台で、同時に何件も読み取らせると1件あたりが遅くなり、待ち順も分からなくなる。
依頼ごとに、待ち順・処理の段階・結果をイベントとして順に返す。
"""

import asyncio
import time
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

# 処理時間の目安を、直近の処理時間にどれだけ寄せるか（指数移動平均の重み）
ESTIMATE_WEIGHT = 0.3

EventKind = Literal["queued", "started", "stage", "done"]


@dataclass(frozen=True)
class QueueEvent:
    """依頼1件の進み具合。

    queued: 前に ahead 件ある / started: 処理を始めた / stage: 処理が stage の段階に進んだ /
    done: result が出た。estimate_seconds は、今から終わるまでの目安。
    """

    kind: EventKind
    ahead: int | None = None
    stage: str | None = None
    estimate_seconds: float | None = None
    result: Any = None


class QueueFull(Exception):
    """待っている依頼が上限に達していて、受け付けられない。"""


@dataclass(eq=False)
class _Ticket:
    changed: asyncio.Event = field(default_factory=asyncio.Event)


class AnalysisQueue:
    """依頼を来た順に1件ずつ処理する。処理は別スレッドで動かし、イベントループを止めない。"""

    def __init__(
        self, initial_estimate_seconds: float = 10.0, max_waiting: int | None = None
    ) -> None:
        # 先頭が処理中の依頼
        self._line: list[_Ticket] = []
        self._estimate = initial_estimate_seconds
        self._max_waiting = max_waiting

    @property
    def waiting(self) -> int:
        """順番を待っている依頼の数（処理中の1件は数えない）。"""
        return max(len(self._line) - 1, 0)

    @property
    def full(self) -> bool:
        """待っている依頼が上限に達しているか。"""
        return self._max_waiting is not None and self.waiting >= self._max_waiting

    async def run(self, work: Callable[[Callable[[str], None]], Any]) -> AsyncGenerator[QueueEvent]:
        """work(on_stage) を順番が来たら動かし、進み具合を返す。work の例外はそのまま伝える。

        待っている依頼が上限に達していれば QueueFull。
        """
        # 列が空でも、処理中の依頼がなければ待たずに始められるので受け付ける
        if self._line and self.full:
            raise QueueFull
        ticket = _Ticket()
        self._line.append(ticket)
        started = False
        try:
            while (ahead := self._line.index(ticket)) > 0:
                ticket.changed.clear()
                yield QueueEvent(
                    "queued", ahead=ahead, estimate_seconds=(ahead + 1) * self._estimate
                )
                await ticket.changed.wait()

            loop = asyncio.get_running_loop()
            stages: asyncio.Queue[str | None] = asyncio.Queue()

            def on_stage(stage: str) -> None:
                loop.call_soon_threadsafe(stages.put_nowait, stage)

            def run_work() -> Any:
                try:
                    return work(on_stage)
                finally:
                    loop.call_soon_threadsafe(stages.put_nowait, None)

            start = time.monotonic()
            task = asyncio.ensure_future(asyncio.to_thread(run_work))
            started = True
            # 接続が切れても処理中のスレッドは止められないので、終わるまで次の依頼を始めない
            task.add_done_callback(lambda _: self._leave(ticket, time.monotonic() - start))
            yield QueueEvent("started", estimate_seconds=self._estimate)
            while (stage := await stages.get()) is not None:
                yield QueueEvent("stage", stage=stage)
            yield QueueEvent("done", result=await task)
        finally:
            if not started:
                self._leave(ticket, None)

    def _leave(self, ticket: _Ticket, elapsed: float | None) -> None:
        if elapsed is not None:
            self._estimate += ESTIMATE_WEIGHT * (elapsed - self._estimate)
        self._line.remove(ticket)
        for waiting in self._line:
            waiting.changed.set()
