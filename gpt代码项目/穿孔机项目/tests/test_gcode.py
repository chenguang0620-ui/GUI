"""解析器测试：验证实际作业文件及必须拒绝的危险输入。"""

from pathlib import Path

import pytest

from edm_drill.domain import DEFAULT_RECIPES, MachineConfig
from edm_drill.gcode import GCodeError, parse_program, validate_program


EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "three_holes.ngc"


def test_example_program_is_valid() -> None:
    program = parse_program(EXAMPLE.read_text(encoding="utf-8"))
    validate_program(program, MachineConfig(), DEFAULT_RECIPES)
    assert program.hole_count == 3
    assert [step.kind for step in program.steps][-1] == "end"


@pytest.mark.parametrize("line", ["G0 X10", "G1 X10 Y20", "M200 P1 D-1", "M200 P99 D1"])
def test_invalid_or_unsafe_lines_are_rejected(line: str) -> None:
    source = f"%\nG21\nG90\nG54\nG0 X10 Y10\n{line}\nM2\n%"
    with pytest.raises(GCodeError):
        program = parse_program(source)
        validate_program(program, MachineConfig(), DEFAULT_RECIPES)


def test_out_of_bounds_hole_position_is_rejected() -> None:
    source = "%\nG21\nG90\nG54\nG0 X500 Y10\nM200 P1 D1\nM2\n%"
    with pytest.raises(GCodeError, match="X 超出工作范围"):
        validate_program(parse_program(source), MachineConfig(), DEFAULT_RECIPES)
