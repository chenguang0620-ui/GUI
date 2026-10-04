#ifndef OSC_KEYS_H
#define OSC_KEYS_H
#include <stdbool.h>
#include <stdint.h>

/* 区域A：按键时间参数（毫秒），手感调整只改此处。 */
#define OSC_KEY_COUNT 9u
#define OSC_KEY_MASK UINT16_C(0x01ff)
#define OSC_KEY_DEBOUNCE_MS UINT32_C(20)
#define OSC_KEY_LONG_MS UINT32_C(500)
#define OSC_KEY_REPEAT_MS UINT32_C(80)

typedef enum {
    OSC_KEY_NUMBER_UP, OSC_KEY_NUMBER_DOWN,
    OSC_KEY_LEVEL_UP, OSC_KEY_LEVEL_DOWN,
    OSC_KEY_WIDTH_UP, OSC_KEY_WIDTH_DOWN,
    OSC_KEY_GAP_UP, OSC_KEY_GAP_DOWN, OSC_KEY_TOUCH
} osc_key_id_t;
#define OSC_KEY_BIT(id) ((uint16_t)(UINT16_C(1) << (id)))

/* 区域B：每个键独立状态机。LOCKED要求松开后才能再次响应。 */
typedef enum {
    OSC_KEY_UP, OSC_KEY_DEBOUNCE_DOWN, OSC_KEY_HELD,
    OSC_KEY_DEBOUNCE_UP, OSC_KEY_LOCKED, OSC_KEY_LOCKED_RELEASE
} osc_key_phase_t;
typedef struct {
    osc_key_phase_t phase;
    uint32_t edge_ms;
    uint32_t pressed_ms;
    uint32_t repeated_ms;
    bool repeating;
} osc_key_state_t;
typedef struct { osc_key_state_t key[OSC_KEY_COUNT]; } osc_keys_t;
typedef struct {
    uint16_t pressed;
    uint16_t repeated;
    uint16_t released;
    uint16_t busy; /* 包含消抖/锁定中的键，避免按住时自动变暗。 */
} osc_key_events_t;

/* 区域C：gpio_levels各位1=松开、0=按下，板级负责物理脚到逻辑位映射。 */
void osc_keys_init(osc_keys_t *keys, uint16_t gpio_levels, uint32_t now_ms);
osc_key_events_t osc_keys_poll(osc_keys_t *keys, uint16_t gpio_levels,
                               uint32_t now_ms);
void osc_keys_suppress(osc_keys_t *keys, uint16_t mask, uint32_t now_ms);
#endif
