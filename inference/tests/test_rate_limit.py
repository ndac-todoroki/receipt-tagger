"""同じ相手からの依頼の回数制限のテスト。

確かめること: 期間ごとの上限まで受け付ける、上限を超えたら断る、期間が過ぎれば数え直す、
            相手ごとに別に数える、複数の期間の上限をすべて守る。
確かめないこと: 相手（IP アドレス）の見分け方（API のテストで扱う）。
"""

from receipt_app.rate_limit import RateLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_期間内の上限までは受け付けて超えたら断る() -> None:
    limiter = RateLimiter([(60, 2)], clock=Clock())

    assert [limiter.allow("a") for _ in range(3)] == [True, True, False]


def test_期間が過ぎれば古い依頼は数えない() -> None:
    clock = Clock()
    limiter = RateLimiter([(60, 1)], clock=clock)
    limiter.allow("a")

    clock.now += 61

    assert limiter.allow("a")


def test_相手ごとに別に数える() -> None:
    limiter = RateLimiter([(60, 1)], clock=Clock())
    limiter.allow("a")

    assert limiter.allow("b")


def test_長い期間の上限にも達していれば断る() -> None:
    clock = Clock()
    limiter = RateLimiter([(60, 10), (86400, 2)], clock=clock)
    limiter.allow("a")
    clock.now += 61
    limiter.allow("a")
    clock.now += 61

    assert not limiter.allow("a")


def test_断った依頼は数えない() -> None:
    # 断られた後に送り続けても、期間が過ぎれば使えるようにする
    clock = Clock()
    limiter = RateLimiter([(60, 1)], clock=clock)
    limiter.allow("a")
    clock.now += 30
    limiter.allow("a")
    clock.now += 31

    assert limiter.allow("a")
