"""设置持久化及参数边界测试：包括非有限数和非整数计数。"""

from dataclasses import replace
import json
import math

import pytest

from edm_drill.domain import FeedbackConfig, FeedbackMode, MachineConfig
from edm_drill.settings_store import SettingsStore


def test_feedback_settings_round_trip(tmp_path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    assert store.load().feedback.scale_mm_per_count == 0.005
    base = MachineConfig()
    config = replace(
        base,
        feedback=replace(
            base.feedback, mode=FeedbackMode.DUAL,
            scale_mm_per_count=0.001, encoder_counts_per_rev=4000,
            screw_pitch_mm=5.0,
        ),
    )
    store.save(config)
    assert store.load() == config


@pytest.mark.parametrize("field,value", [
    ("x_max_mm", math.inf),
    ("y_min_mm", -math.inf),
    ("z_min_mm", math.nan),
    ("manual_speed_mm_s", math.nan),
    ("edm_feed_mm_s", math.inf),
    ("max_hole_depth_mm", math.nan),
    ("x_max_mm", 10 ** 1000),
])
def test_machine_config_rejects_nonfinite_values(field, value) -> None:
    with pytest.raises(ValueError, match="有限数"):
        replace(MachineConfig(), **{field: value}).validate(require_hardware=True)


@pytest.mark.parametrize("field,value", [
    ("scale_mm_per_count", math.nan),
    ("screw_pitch_mm", math.inf),
    ("max_disagreement_mm", math.inf),
])
def test_feedback_config_rejects_nonfinite_values(field, value) -> None:
    with pytest.raises(ValueError, match="有限数"):
        replace(FeedbackConfig(), **{field: value}).validate()


@pytest.mark.parametrize("count", [1.5, 4000.0, True, math.nan])
def test_encoder_count_must_be_a_positive_integer(count) -> None:
    with pytest.raises(ValueError, match="正整数"):
        replace(FeedbackConfig(), encoder_counts_per_rev=count).validate()


def test_settings_file_rejects_nonfinite_json_and_fractional_count(tmp_path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    store.path.write_text('{"feedback":{"mode":"scale","scale_mm_per_count":NaN}}', encoding="utf-8")
    with pytest.raises(ValueError, match="非有限数"):
        store.load()

    payload = {"feedback": {"mode": "encoder", "encoder_counts_per_rev": 1024.5}}
    store.path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="正整数"):
        store.load()
