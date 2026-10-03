"""内存事件日志；界面只读取，不负责生成业务事件。"""

from __future__ import annotations

from datetime import datetime


class EventLog:
    def __init__(self, max_entries: int = 1000):
        self.max_entries = max_entries
        self.entries: list[str] = []
        self.version = 0

    def add(self, message: str) -> None:
        self.entries.append(f"{datetime.now().strftime('%H:%M:%S')}  {message}")
        self.version += 1
        if len(self.entries) > self.max_entries:
            del self.entries[: len(self.entries) - self.max_entries]
