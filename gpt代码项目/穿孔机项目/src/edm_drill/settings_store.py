"""设备设置持久化；写入临时文件后原子替换，避免断电留下半份 JSON。"""

from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile

from .domain import FeedbackConfig, FeedbackMode, MachineConfig


class SettingsStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> MachineConfig:
        if not self.path.exists():
            return MachineConfig()
        def reject_nonfinite(value: str) -> None:
            raise ValueError(f"设置文件包含非有限数：{value}")

        data = json.loads(self.path.read_text(encoding="utf-8"), parse_constant=reject_nonfinite)
        feedback = data.pop("feedback")
        feedback["mode"] = FeedbackMode(feedback["mode"])
        config = MachineConfig(feedback=FeedbackConfig(**feedback), **data)
        config.validate()
        return config

    def save(self, config: MachineConfig) -> None:
        config.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(config), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        fd, temp_path = tempfile.mkstemp(prefix=".settings-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                file.write(payload)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_path, self.path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
