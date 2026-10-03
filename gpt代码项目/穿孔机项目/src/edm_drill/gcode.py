"""v0.1 G 代码白名单解析及静态校验。未知指令一律报错。"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re

from .domain import MachineConfig, Recipe


class GCodeError(ValueError):
    """带源文件行号的程序错误。"""


@dataclass(frozen=True)
class Step:
    kind: str  # move_xy / hole / pause / end
    line: int
    x_mm: float | None = None
    y_mm: float | None = None
    recipe_id: int | None = None
    depth_mm: float | None = None


@dataclass(frozen=True)
class Program:
    steps: tuple[Step, ...]
    source: str

    @property
    def hole_count(self) -> int:
        return sum(step.kind == "hole" for step in self.steps)


_WORD = re.compile(r"([A-Z])([+-]?(?:\d+(?:\.\d*)?|\.\d+))")
_COMMENT = re.compile(r"\([^()]*\)")


def _words(source: str, line_number: int) -> dict[str, float]:
    """读取无注释代码，拒绝额外字符和重复参数。"""
    compact = "".join(source.upper().split())
    words: dict[str, float] = {}
    pos = 0
    while pos < len(compact):
        match = _WORD.match(compact, pos)
        if not match:
            raise GCodeError(f"第 {line_number} 行：无效或不支持的代码：{source.strip()}")
        letter, number = match.groups()
        if letter in words:
            raise GCodeError(f"第 {line_number} 行：参数 {letter} 重复")
        value = float(number)
        if not math.isfinite(value):
            raise GCodeError(f"第 {line_number} 行：参数 {letter} 不是有限数")
        words[letter] = value
        pos = match.end()
    return words


def _integer(value: float, name: str, line_number: int) -> int:
    if not value.is_integer():
        raise GCodeError(f"第 {line_number} 行：{name} 必须为整数")
    return int(value)


def parse_program(source: str) -> Program:
    """解析上位机作业格式；不向真实控制器转发原始文本。"""
    lines = source.splitlines()
    if len(lines) > 20000:
        raise GCodeError("程序行数超过 20000 行上限")
    visible = [(i, line.strip()) for i, line in enumerate(lines, 1) if line.strip()]
    if len(visible) < 3 or visible[0][1] != "%" or visible[-1][1] != "%":
        raise GCodeError("程序必须以独立的 % 行开始和结束")
    flags: set[str] = set()
    steps: list[Step] = []
    have_xy = False
    ended = False
    for line_number, raw in visible[1:-1]:
        code = _COMMENT.sub("", raw)
        if "(" in code or ")" in code:
            raise GCodeError(f"第 {line_number} 行：注释括号不匹配或嵌套")
        if not code.strip():
            continue
        words = _words(code, line_number)
        if "N" in words:
            _integer(words.pop("N"), "N 行号", line_number)
        if ended:
            raise GCodeError(f"第 {line_number} 行：M2 后不能有指令")
        command_words = [key for key in ("G", "M") if key in words]
        if len(command_words) != 1:
            raise GCodeError(f"第 {line_number} 行：每行必须恰有一条 G 或 M 指令")
        command_letter = command_words[0]
        command = f"{command_letter}{_integer(words.pop(command_letter), command_letter, line_number)}"
        if command in ("G21", "G90", "G54"):
            if words or steps or command in flags:
                raise GCodeError(f"第 {line_number} 行：{command} 必须在程序开头声明一次且不能带参数")
            flags.add(command)
            continue
        if flags != {"G21", "G90", "G54"}:
            raise GCodeError(f"第 {line_number} 行：运动前必须声明 G21、G90、G54")
        if command == "G0":
            if set(words) != {"X", "Y"}:
                raise GCodeError(f"第 {line_number} 行：G0 必须同时包含 X 和 Y")
            steps.append(Step("move_xy", line_number, x_mm=words["X"], y_mm=words["Y"]))
            have_xy = True
        elif command == "M200":
            if set(words) != {"P", "D"} or not have_xy:
                raise GCodeError(f"第 {line_number} 行：M200 需要当前孔位及 P、D 参数")
            recipe_id = _integer(words["P"], "P 配方号", line_number)
            if recipe_id <= 0 or words["D"] <= 0:
                raise GCodeError(f"第 {line_number} 行：P 与 D 必须大于 0")
            steps.append(Step("hole", line_number, recipe_id=recipe_id, depth_mm=words["D"]))
        elif command == "M0":
            if words:
                raise GCodeError(f"第 {line_number} 行：M0 不接受参数")
            steps.append(Step("pause", line_number))
        elif command == "M2":
            if words:
                raise GCodeError(f"第 {line_number} 行：M2 不接受参数")
            steps.append(Step("end", line_number))
            ended = True
        else:
            raise GCodeError(f"第 {line_number} 行：不支持 {command}")
    if not ended:
        raise GCodeError("程序缺少 M2")
    if not any(step.kind == "hole" for step in steps):
        raise GCodeError("程序至少需要一个 M200 穿孔指令")
    return Program(tuple(steps), source)


def validate_program(program: Program, config: MachineConfig, recipes: dict[int, Recipe]) -> None:
    """运行前校验所有孔位、深度及配方。"""
    config.validate()
    for step in program.steps:
        if step.kind == "move_xy":
            assert step.x_mm is not None and step.y_mm is not None
            if not config.x_min_mm <= step.x_mm <= config.x_max_mm:
                raise GCodeError(f"第 {step.line} 行：X 超出工作范围")
            if not config.y_min_mm <= step.y_mm <= config.y_max_mm:
                raise GCodeError(f"第 {step.line} 行：Y 超出工作范围")
        if step.kind == "hole":
            assert step.recipe_id is not None and step.depth_mm is not None
            if step.recipe_id not in recipes:
                raise GCodeError(f"第 {step.line} 行：配方 P{step.recipe_id} 不存在")
            if step.depth_mm > config.max_hole_depth_mm or step.depth_mm > -config.z_min_mm:
                raise GCodeError(f"第 {step.line} 行：穿孔深度超出允许范围")
