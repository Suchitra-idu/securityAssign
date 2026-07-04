import time


class SystemClock:
    def now(self) -> int:
        return int(time.time())
