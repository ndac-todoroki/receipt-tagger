"""同じ相手（IP アドレス）からの依頼の回数制限。

公開 URL は誰でも開けるので、機械的な連打で推論サーバーを占有されないようにする。
記録はメモリにだけ置き、再起動で消える（相手の記録をディスクに残さないため）。
"""

import time
from collections import defaultdict, deque
from collections.abc import Callable


class RateLimiter:
    """期間（秒）ごとの上限回数を、相手ごとに数える。"""

    def __init__(
        self, limits: list[tuple[float, int]], clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._limits = limits
        self._clock = clock
        self._window = max(seconds for seconds, _ in limits)
        self._history: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        """受け付けてよければ記録して True。どれかの期間の上限に達していれば False。"""
        now = self._clock()
        history = self._history[key]
        while history and history[0] <= now - self._window:
            history.popleft()
        for seconds, count in self._limits:
            if sum(1 for t in history if t > now - seconds) >= count:
                return False
        history.append(now)
        return True
