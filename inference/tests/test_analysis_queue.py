"""解析の依頼を1件ずつ順に処理するキューのテスト。

確かめること: 空いていれば待たずに始める、先に来た依頼から1件ずつ処理する、
            待っている間は前に何件あるかと目安の時間を知らせる、処理の段階を知らせる、
            待っている依頼が取り下げられたら後ろが繰り上がる、処理の失敗を伝える。
確かめないこと: 解析そのもの（パイプラインのテストで扱う）。
"""

import asyncio
import threading
from collections.abc import Callable

import pytest

from receipt_app.analysis_queue import AnalysisQueue, QueueEvent

Work = Callable[[Callable[[str], None]], str]


async def _collect(queue: AnalysisQueue, work: Work) -> list[QueueEvent]:
    return [e async for e in queue.run(work)]


def _instant(result: str) -> Work:
    return lambda on_stage: result


class Gate:
    """テストから開けるまで処理を止めておく仕事。"""

    def __init__(self, result: str) -> None:
        self.result = result
        self.started = threading.Event()
        self._open = threading.Event()

    def work(self, on_stage: Callable[[str], None]) -> str:
        self.started.set()
        self._open.wait(timeout=5)
        return self.result

    def open(self) -> None:
        self._open.set()


async def _until(condition: Callable[[], bool]) -> None:
    for _ in range(500):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("条件が満たされなかった")


def test_空いていれば待たずに始めて結果を返す() -> None:
    events = asyncio.run(_collect(AnalysisQueue(), _instant("r1")))

    assert [e.kind for e in events] == ["started", "done"]
    assert events[-1].result == "r1"


def test_処理の段階を順に知らせる() -> None:
    def work(on_stage: Callable[[str], None]) -> str:
        on_stage("reading")
        on_stage("items")
        return "r1"

    events = asyncio.run(_collect(AnalysisQueue(), work))

    assert [(e.kind, e.stage) for e in events] == [
        ("started", None),
        ("stage", "reading"),
        ("stage", "items"),
        ("done", None),
    ]


def test_先に来た依頼が終わるまで待ち前に何件あるかを知らせ直す() -> None:
    async def run() -> tuple[list[QueueEvent], list[QueueEvent]]:
        queue = AnalysisQueue()
        first, second = Gate("r1"), Gate("r2")
        t1 = asyncio.create_task(_collect(queue, first.work))
        await _until(first.started.is_set)
        t2 = asyncio.create_task(_collect(queue, second.work))
        t3 = asyncio.create_task(_collect(queue, _instant("r3")))
        await asyncio.sleep(0.05)
        assert not second.started.is_set()
        first.open()
        await _until(second.started.is_set)
        second.open()
        await t1
        return await t2, await t3

    second_events, third_events = asyncio.run(run())

    assert [(e.kind, e.ahead) for e in second_events] == [
        ("queued", 1),
        ("started", None),
        ("done", None),
    ]
    assert [(e.kind, e.ahead) for e in third_events] == [
        ("queued", 2),
        ("queued", 1),
        ("started", None),
        ("done", None),
    ]


def test_待っている依頼が取り下げられたら後ろの待ち順が繰り上がる() -> None:
    async def run() -> list[QueueEvent]:
        queue = AnalysisQueue()
        first = Gate("r1")
        t1 = asyncio.create_task(_collect(queue, first.work))
        await _until(first.started.is_set)
        t2 = asyncio.create_task(_collect(queue, _instant("r2")))
        third: list[QueueEvent] = []

        async def collect_third() -> None:
            async for e in queue.run(_instant("r3")):
                third.append(e)

        t3 = asyncio.create_task(collect_third())
        await _until(lambda: len(third) == 1)
        t2.cancel()  # 画面を閉じるなどで接続が切れた
        await _until(lambda: len(third) == 2)
        first.open()
        await t1
        await t3
        return third

    third = asyncio.run(run())

    assert [(e.kind, e.ahead) for e in third[:2]] == [("queued", 2), ("queued", 1)]
    assert third[-1].result == "r3"


def test_目安の時間は直近の処理時間と前の件数から出す() -> None:
    async def run() -> QueueEvent:
        queue = AnalysisQueue(initial_estimate_seconds=10.0)
        first = Gate("r1")
        t1 = asyncio.create_task(_collect(queue, first.work))
        await _until(first.started.is_set)
        events = queue.run(_instant("r2"))
        queued = await anext(events)
        first.open()
        await t1
        await events.aclose()
        return queued

    queued = asyncio.run(run())

    # 前の1件が終わるまでと、自分の分
    assert queued.estimate_seconds == pytest.approx(20.0)


def test_処理に失敗したら例外を伝えて次の依頼に進む() -> None:
    def fail(on_stage: Callable[[str], None]) -> str:
        raise RuntimeError("壊れた")

    async def run() -> list[QueueEvent]:
        queue = AnalysisQueue()
        with pytest.raises(RuntimeError):
            await _collect(queue, fail)
        return await _collect(queue, _instant("r2"))

    assert asyncio.run(run())[-1].result == "r2"
