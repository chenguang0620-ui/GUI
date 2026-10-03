# LinuxCNC XY 接入说明

## 控制分工

- LinuxCNC 只负责 X/Y 回零、G54 工作坐标和 XY 运动。
- STM32F407 负责 Z 轴快移/点动、增量编码器和光栅尺位置反馈、放电间隙进给及单孔穿孔循环。
- PyQt 上位机解析 `.ngc`：`G0 XY` 交给 LinuxCNC；`M200 P… D…` 由上位机等待 XY 到位后交给 STM32F407。LinuxCNC 不直接收到 `M200`。
- **不可让 LinuxCNC 和 STM32 同时向同一个 Z 驱动器输出运动信号。** 建议 LinuxCNC 机床配置只声明 XY；Z 驱动和硬件联锁由 STM32 系统独占。

接口代码：[linuxcnc_adapter.py](../src/edm_drill/linuxcnc_adapter.py)。这个文件使用 LinuxCNC 官方 Python API `linuxcnc.stat()`、`linuxcnc.command()` 和 `linuxcnc.error_channel()`；必须在安装 LinuxCNC 且其进程运行的 Linux 机床电脑上执行。云端环境没有该模块，所以当前测试使用模拟 API。

## 接入前检查

在机床电脑上运行只读探针：

```bash
/usr/bin/python3 -m edm_drill.linuxcnc_probe
```

若系统 Python 能导入 `linuxcnc`，而项目虚拟环境不能，应使用同一系统 Python 建立带系统包的虚拟环境，例如 `/usr/bin/python3 -m venv --system-site-packages .venv`。探针不会使电机运动。

适配器在发 XY 指令前核对：LinuxCNC 已上电、配置的 XY 关节已回零、机床单位为毫米、当前是 G54、XY 旋转为零、无 G92/刀具 XY 偏置、解释器空闲且轴已停稳。XY 目标还须通过上位机软限位校验。

手动页先让 STM Z 回零，再对仅配置两条 XY 关节的 LinuxCNC 发送 `home(-1)`；若机床还有其他关节，接口拒绝整组回零，需按现场轴映射另行适配。离散 XY 点动使用 `MODE_MANUAL`、轴坐标模式与 `JOG_INCREMENT`；目标快移使用 MDI `G0 XY`，要求 Z 已回零、放电关闭且 Z 读数不低于 0 mm。真实安全高度仍须现场核定。冲液、旋转及手动放电由 STM 控制器声明能力后启用，不假定 LinuxCNC 的 coolant 命令已接线。

找中页只在作业空闲、XY 停稳、Z 手动且放电关闭时记录操作者确认的碰边。按铜管实测外径和边缘方向计算原点后，`G10 L20 P1 X…`/`Y…` 将当前铜管中心位置设置为指定 G54 读数；只写选中的轴，命令完成后回读验证。G54 会保存在 LinuxCNC 的 VAR 文件中，重新装夹后须重新确认。此处是工作零点偏置，不实现 G41/G42 加工路径刀补。参考 [LinuxCNC G10 L20](https://linuxcnc.org/docs/stable/html/gcode/g-code.html#gcode:g10-l20) 与 [Python 控制接口](https://linuxcnc.org/docs/stable/html/config/python-interface.html#_code_linuxcnc_command_code_attributes)。

## 接线后组装

```python
from edm_drill.linuxcnc_adapter import LinuxCncController
from edm_drill.job_service import JobService

# stm32_controller 必须是已实现 Controller 接口的真实 STM32 通信对象。
# 不能用 SimulatedController 替代后直接进行实机加工。
controller = LinuxCncController(stm32_controller, machine_config)
job = JobService(controller, machine_config, event_log.add)
```

`move_xy()` 使用 MDI 发送 `G21 G90 G54 G0 X… Y…`，**不包含 Z**。它发起移动后立即返回；作业调度持续读取 LinuxCNC 的 `inpos`、解释器状态和 G54 实际位置。三者全部符合且误差不超过默认 0.02 mm 时，才进入 `M200`。默认 30 秒不到位则请求 LinuxCNC 中止、Z/放电急停并报故障。运动期间可通过底部“停止作业”请求中止。

放电或退刀期间，如果 LinuxCNC 停机、XY 不再到位，或解释器意外运行，接口请求中止 XY 并要求 STM32 急停。状态或错误通道通信失联同样触发该路径；界面把失效的 XY 坐标显示为“—”。硬件急停仍须直接联锁放电电源与驱动器，不能依赖 Python 或 MDI。

## 仍需实机联调

1. LinuxCNC 实际版本、INI 的 XY 关节索引及 G54 零点。
2. STM32F407 的串口/CAN/以太网协议与命令确认机制；目前项目尚无可连接真实 STM32 的通信实现。
3. LinuxCNC 与 STM32 之间的硬件联锁和故障停止时序。
4. 轴实际到位误差、超时时间和软限位；先低速、无放电验证运动，再进行带放电试验。

当前 `edm-drill` 默认仍启动离线模拟器。完成 STM32 实机通信对象后，在应用组装处替换默认模拟控制器，才可启用这套 LinuxCNC 接口。
