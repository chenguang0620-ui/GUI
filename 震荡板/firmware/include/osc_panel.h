#ifndef OSC_PANEL_H
#define OSC_PANEL_H
#include "osc_keys.h"
#include "osc_params.h"

/* 区域A：亮度/休眠设置；0是最低亮度而非熄灭。 */
#define OSC_DIM_AFTER_MS UINT32_C(120000)
#define OSC_BRIGHT_LEVEL 7u
#define OSC_DIM_LEVEL 0u
#define OSC_DIGIT_DASH 10u

typedef enum { OSC_PANEL_BRIGHT, OSC_PANEL_DIM } osc_panel_light_t;
typedef struct {
    osc_keys_t keys;
    osc_panel_light_t light;
    uint32_t activity_ms;
    bool was_saved;
    bool initialized;
} osc_panel_t;
typedef struct {
    uint8_t digit[6]; /* 0～9数字，10横杠；物理段码映射交给显示驱动。 */
    uint8_t decimal_mask;
    uint8_t brightness;
} osc_display_frame_t;

/* 区域B：主循环接口。参数上下文须先成功初始化，均非中断安全。 */
bool osc_panel_init(osc_panel_t *panel, const osc_params_t *params,
                     uint16_t gpio_levels, uint32_t now_ms);
/* 返回参数或模式是否改变；亮度改变不意味着重新启动PWM。 */
bool osc_panel_poll(osc_panel_t *panel, osc_params_t *params,
                     uint16_t gpio_levels, uint32_t now_ms);
bool osc_panel_frame(const osc_panel_t *panel, const osc_params_t *params,
                      osc_display_frame_t *frame);
#endif
