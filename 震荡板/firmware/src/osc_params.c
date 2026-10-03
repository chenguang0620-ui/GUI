#include "osc_params.h"
#include <stddef.h>

/* 区域A：输入校验。非法存储值必须拒绝，不能直接转成PWM。 */
bool osc_profile_valid(const osc_profile_t *p)
{
    return p != NULL && p->level >= OSC_LEVEL_MIN && p->level <= OSC_LEVEL_MAX
        && p->width_us >= OSC_WIDTH_MIN_US && p->width_us <= OSC_WIDTH_MAX_US
        && p->gap_multiplier >= OSC_GAP_MIN && p->gap_multiplier <= OSC_GAP_MAX;
}

bool osc_image_valid(const osc_image_t *image)
{
    if (image == NULL || image->selected_normal >= OSC_NORMAL_COUNT
        || !osc_profile_valid(&image->touch)) {
        return false;
    }
    for (unsigned i = 0; i < OSC_NORMAL_COUNT; ++i) {
        if (!osc_profile_valid(&image->normal[i])) {
            return false;
        }
    }
    return true;
}

bool osc_params_init(osc_params_t *s, const osc_image_t *image,
                     bool persisted, uint32_t now_ms)
{
    if (s == NULL) {
        return false;
    }
    if (!osc_image_valid(image)) {
        *s = (osc_params_t){0};
        return false;
    }
    /* 先复制到局部量：即使image引用当前s中的参数也不会被清零覆盖。 */
    const osc_image_t copy = *image;
    *s = (osc_params_t){
        .image = copy, .mode = OSC_NORMAL, .revision = 1u,
        .last_change_ms = now_ms, .initialized = true, .dirty = !persisted
    };
    return true;
}

/* 区域B：参数选择和修改。模式是临时状态，不放入持久化快照。 */
static void changed(osc_params_t *s, uint32_t now_ms)
{
    ++s->revision;
    s->last_change_ms = now_ms;
    s->dirty = true;
}

const osc_profile_t *osc_params_current(const osc_params_t *s)
{
    if (s == NULL || !s->initialized) {
        return NULL;
    }
    return s->mode == OSC_TOUCH ? &s->image.touch
        : &s->image.normal[s->image.selected_normal];
}

bool osc_params_select(osc_params_t *s, uint8_t number, uint32_t now_ms)
{
    if (s == NULL || !s->initialized || s->mode != OSC_NORMAL
        || number >= OSC_NORMAL_COUNT || number == s->image.selected_normal) {
        return false;
    }
    s->image.selected_normal = number;
    changed(s, now_ms); /* 序号本身变化也属于用户要求的延时保存范围。 */
    return true;
}

bool osc_params_toggle_mode(osc_params_t *s)
{
    if (s == NULL || !s->initialized) {
        return false;
    }
    s->mode = s->mode == OSC_NORMAL ? OSC_TOUCH : OSC_NORMAL;
    /* 不改变revision、dirty或保存倒计时，保证跨模式待保存不丢失。 */
    return true;
}

bool osc_params_adjust(osc_params_t *s, osc_field_t field,
                       int direction, uint32_t now_ms)
{
    if (s == NULL || !s->initialized || (direction != 1 && direction != -1)) {
        return false;
    }
    osc_profile_t *p = s->mode == OSC_TOUCH ? &s->image.touch
        : &s->image.normal[s->image.selected_normal];
    uint8_t *value;
    unsigned min_value, max_value;
    switch (field) {
    case OSC_LEVEL:
        value = &p->level; min_value = OSC_LEVEL_MIN; max_value = OSC_LEVEL_MAX;
        break;
    case OSC_WIDTH:
        value = &p->width_us; min_value = OSC_WIDTH_MIN_US; max_value = OSC_WIDTH_MAX_US;
        break;
    case OSC_GAP:
        value = &p->gap_multiplier; min_value = OSC_GAP_MIN; max_value = OSC_GAP_MAX;
        break;
    default:
        return false;
    }
    if ((direction < 0 && *value <= min_value)
        || (direction > 0 && *value >= max_value)) {
        return false; /* 边界停止；没有实际变化就不推迟保存。 */
    }
    *value = (uint8_t)((int)*value + direction);
    changed(s, now_ms);
    return true;
}

/* 区域C：统一时间换算，仅描述逻辑波形，不配置硬件或启动功放。 */
bool osc_profile_pulse(const osc_profile_t *p, osc_pulse_t *pulse)
{
    if (pulse == NULL || !osc_profile_valid(p)) {
        return false;
    }
    pulse->low_us = p->width_us;
    pulse->high_us = (uint32_t)p->width_us * p->gap_multiplier;
    pulse->period_us = pulse->low_us + pulse->high_us;
    pulse->channel_mask = (uint8_t)((UINT32_C(1) << p->level) - UINT32_C(1));
    return true;
}

/* 区域D：保存状态握手。毫秒计数可回绕，需以短于一次完整回绕周期轮询。 */
bool osc_params_save_due(const osc_params_t *s, uint32_t now_ms)
{
    return s != NULL && s->initialized && s->dirty && !s->saving
        && (uint32_t)(now_ms - s->last_change_ms) >= OSC_SAVE_DELAY_MS;
}

bool osc_params_begin_save(osc_params_t *s, uint32_t now_ms,
                           osc_image_t *snapshot, uint64_t *token)
{
    if (snapshot == NULL || token == NULL || !osc_params_save_due(s, now_ms)) {
        return false;
    }
    *snapshot = s->image;
    s->saving_revision = s->revision;
    s->saving = true;
    *token = s->saving_revision;
    return true;
}

bool osc_params_finish_save(osc_params_t *s, uint64_t token,
                            bool verified, uint32_t now_ms)
{
    if (s == NULL || !s->initialized || !s->saving || token != s->saving_revision) {
        return false;
    }
    s->saving = false;
    if (!verified) {
        s->dirty = true;
        s->last_change_ms = now_ms; /* 避免失败后主循环每次都重写Flash。 */
    } else if (s->revision == token) {
        s->dirty = false; /* 旧快照完成不能清除保存期间产生的新修改。 */
    }
    return true;
}

bool osc_params_is_saved(const osc_params_t *s)
{
    return s != NULL && s->initialized && !s->dirty && !s->saving;
}
