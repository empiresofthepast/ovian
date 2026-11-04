import time


class Clock:
    """Wall clock in epoch milliseconds. Tests replace it with a manual clock."""

    def now(self) -> int:
        return int(time.time() * 1000)


class ManualClock(Clock):
    def __init__(self, start: int = 1_800_000_000_000):
        self.value = start

    def now(self) -> int:
        return self.value

    def advance(self, seconds: float) -> int:
        self.value += int(seconds * 1000)
        return self.value
