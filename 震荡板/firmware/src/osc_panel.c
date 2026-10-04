#include "osc_panel.h"
#include <stddef.h>

/* 区域A：面板初始化。上电恢复正常模式由参数模块负责。 */
bool osc_panel_init(osc_panel_t *panel, const osc_params_t *params,
                     uint16_t levels, uint32_t now_ms)
{
    if (panel == NULL) return false;
    *panel = (osc_panel_t){0};
    if (params == NULL || !params->initialized) return false;
    osc_keys_init(&panel->keys, levels, now_ms);
    panel->light = OSC_PANEL_BRIGHT;
    panel->activity_ms = now_ms;
    panel->was_saved = osc_params_is_saved(params);
    panel->initialized = true;
    return true;
}

/* 区域B：相对的一对加减键同时按下时互相抑制，其他不同参数可同时操作。 */
static bool apply_pair(osc_params_t *params, unsigned pair, int direction,
                       uint32_t now_ms)
{
    if (pair == 0u) {
        if (params->mode != OSC_NORMAL) return false;
        const int target = (int)params->image.selected_normal + direction;
        if (target < 0 || target >= (int)OSC_NORMAL_COUNT) return false;
        return osc_params_select(params, (uint8_t)target, now_ms);
    }
    return osc_params_adjust(params, (osc_field_t)(pair - 1u), direction, now_ms);
}

bool osc_panel_poll(osc_panel_t *panel, osc_params_t *params,
                     uint16_t levels, uint32_t now_ms)
{
    if (panel == NULL || !panel->initialized || params == NULL || !params->initialized)
        return false;
    const osc_key_events_t e = osc_keys_poll(&panel->keys, levels, now_ms);
    const uint16_t actions = (uint16_t)(e.pressed | e.repeated);
    bool changed = false;
    if ((e.pressed & OSC_KEY_BIT(OSC_KEY_TOUCH)) != 0u) {
        changed = osc_params_toggle_mode(params);
        /* 同一扫描模式键优先，旧模式调参键按住时不串入新模式。 */
        osc_keys_suppress(&panel->keys, UINT16_C(0x00ff), now_ms);
    } else {
        for (unsigned pair = 0u; pair < 4u; ++pair) {
            const uint16_t up = OSC_KEY_BIT(pair * 2u);
            const uint16_t down = OSC_KEY_BIT(pair * 2u + 1u);
            const uint16_t both = (uint16_t)(up | down);
            if ((e.busy & both) == both) continue;
            if ((actions & up) != 0u) changed = apply_pair(params, pair, 1, now_ms) || changed;
            if ((actions & down) != 0u) changed = apply_pair(params, pair, -1, now_ms) || changed;
        }
    }

    /* 区域C：仅显示休眠。先执行按键功能，再决定亮度，不吞掉唤醒键。 */
    const bool saved = osc_params_is_saved(params);
    if (e.busy != 0u || actions != 0u || e.released != 0u
        || !saved || !panel->was_saved || params->mode == OSC_TOUCH) {
        panel->activity_ms = now_ms;
        panel->light = OSC_PANEL_BRIGHT;
    } else if ((uint32_t)(now_ms - panel->activity_ms) >= OSC_DIM_AFTER_MS) {
        panel->light = OSC_PANEL_DIM;
    }
    panel->was_saved = saved;
    return changed;
}

/* 区域D：逻辑六位帧。保留前导零，序号第1位小数点表示全部数据已保存。 */
bool osc_panel_frame(const osc_panel_t *panel, const osc_params_t *params,
                      osc_display_frame_t *frame)
{
    if (panel == NULL || !panel->initialized || frame == NULL) return false;
    const osc_profile_t *p = osc_params_current(params);
    if (p == NULL) return false;
    frame->digit[0] = params->mode == OSC_TOUCH ? OSC_DIGIT_DASH : params->image.selected_normal;
    frame->digit[1] = p->level;
    frame->digit[2] = (uint8_t)(p->width_us / 10u);
    frame->digit[3] = (uint8_t)(p->width_us % 10u);
    frame->digit[4] = (uint8_t)(p->gap_multiplier / 10u);
    frame->digit[5] = (uint8_t)(p->gap_multiplier % 10u);
    frame->decimal_mask = osc_params_is_saved(params) ? 1u : 0u;
    frame->brightness = panel->light == OSC_PANEL_DIM ? OSC_DIM_LEVEL : OSC_BRIGHT_LEVEL;
    return true;
}
