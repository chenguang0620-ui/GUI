#include "osc_keys.h"
#include <stddef.h>

/* 区域A：开机按住不产生调参，先等释放。调用者必须先初始化。 */
void osc_keys_init(osc_keys_t *keys, uint16_t levels, uint32_t now_ms)
{
    if (keys == NULL) return;
    *keys = (osc_keys_t){0};
    for (unsigned i = 0; i < OSC_KEY_COUNT; ++i) {
        keys->key[i].phase = (levels & OSC_KEY_BIT(i)) != 0u
            ? OSC_KEY_UP : OSC_KEY_LOCKED;
        keys->key[i].edge_ms = now_ms;
    }
}

/* 区域B：低有效采样→事件。迟到扫描最多补一次连发，不突发追赶。 */
osc_key_events_t osc_keys_poll(osc_keys_t *keys, uint16_t levels, uint32_t now_ms)
{
    osc_key_events_t out = {0};
    if (keys == NULL) return out;
    for (unsigned i = 0; i < OSC_KEY_COUNT; ++i) {
        osc_key_state_t *k = &keys->key[i];
        const uint16_t bit = OSC_KEY_BIT(i);
        const bool down = (levels & bit) == 0u;
        switch (k->phase) {
        case OSC_KEY_UP:
            if (down) {
                k->phase = OSC_KEY_DEBOUNCE_DOWN;
                k->edge_ms = now_ms;
            }
            break;
        case OSC_KEY_DEBOUNCE_DOWN:
            if (!down) {
                k->phase = OSC_KEY_UP;
            } else if ((uint32_t)(now_ms - k->edge_ms) >= OSC_KEY_DEBOUNCE_MS) {
                k->phase = OSC_KEY_HELD;
                k->pressed_ms = now_ms;
                k->repeated_ms = now_ms;
                k->repeating = false;
                out.pressed |= bit;
            }
            break;
        case OSC_KEY_HELD:
            if (!down) {
                k->phase = OSC_KEY_DEBOUNCE_UP;
                k->edge_ms = now_ms;
            } else if (i != (unsigned)OSC_KEY_TOUCH) {
                const uint32_t since = k->repeating ? k->repeated_ms : k->pressed_ms;
                const uint32_t wait = k->repeating ? OSC_KEY_REPEAT_MS : OSC_KEY_LONG_MS;
                if ((uint32_t)(now_ms - since) >= wait) {
                    out.repeated |= bit;
                    k->repeated_ms = now_ms;
                    k->repeating = true;
                }
            }
            break;
        case OSC_KEY_DEBOUNCE_UP:
            if (down) {
                k->phase = OSC_KEY_HELD;
                k->repeated_ms = now_ms;
            } else if ((uint32_t)(now_ms - k->edge_ms) >= OSC_KEY_DEBOUNCE_MS) {
                k->phase = OSC_KEY_UP;
                out.released |= bit;
            }
            break;
        case OSC_KEY_LOCKED:
            if (!down) {
                k->phase = OSC_KEY_LOCKED_RELEASE;
                k->edge_ms = now_ms;
            }
            break;
        case OSC_KEY_LOCKED_RELEASE:
            if (down) {
                k->phase = OSC_KEY_LOCKED;
            } else if ((uint32_t)(now_ms - k->edge_ms) >= OSC_KEY_DEBOUNCE_MS) {
                k->phase = OSC_KEY_UP;
            }
            break;
        default:
            k->phase = OSC_KEY_LOCKED;
            k->edge_ms = now_ms;
            break;
        }
        if (k->phase != OSC_KEY_UP) out.busy |= bit;
    }
    return out;
}

/* 区域C：模式改变后抑制尚未释放的调参键。 */
void osc_keys_suppress(osc_keys_t *keys, uint16_t mask, uint32_t now_ms)
{
    if (keys == NULL) return;
    for (unsigned i = 0; i < OSC_KEY_COUNT; ++i) {
        if ((mask & OSC_KEY_BIT(i)) != 0u && keys->key[i].phase != OSC_KEY_UP) {
            keys->key[i].phase = OSC_KEY_LOCKED;
            keys->key[i].edge_ms = now_ms;
        }
    }
}
