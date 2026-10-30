from ingestion.ufcalendar.ratelimit import SlidingWindowLimiter


class FakeTime:
    def __init__(self) -> None:
        self.t = 0.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


def test_allows_burst_then_waits_for_window():
    ft = FakeTime()
    lim = SlidingWindowLimiter(3, period=60, clock=ft.clock, sleep=ft.sleep)
    for _ in range(3):
        assert lim.acquire() == 0
    ft.t = 10
    assert lim.acquire() == 50  # oldest call leaves the window at t=60
    assert ft.t == 60


def test_never_more_than_max_in_any_window():
    ft = FakeTime()
    lim = SlidingWindowLimiter(8, period=60, clock=ft.clock, sleep=ft.sleep)
    stamps = []
    for _ in range(40):
        lim.acquire()
        stamps.append(ft.t)
        ft.t += 0.5
    for i, start in enumerate(stamps):
        assert sum(1 for s in stamps[i:] if s < start + 60) <= 8
