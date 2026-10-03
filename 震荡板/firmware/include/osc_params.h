#ifndef OSC_PARAMS_H
#define OSC_PARAMS_H

#include <stdbool.h>
#include <stdint.h>

/* 区域A：用户参数范围。这里没有硬件引脚；改脚入口将在板级模块建立。 */
#define OSC_NORMAL_COUNT 10u
#define OSC_LEVEL_MIN 1u
#define OSC_LEVEL_MAX 8u
#define OSC_WIDTH_MIN_US 2u
#define OSC_WIDTH_MAX_US 99u
#define OSC_GAP_MIN 2u
#define OSC_GAP_MAX 32u
#define OSC_SAVE_DELAY_MS UINT32_C(2500)

/* 区域B：10组正常参数 + 1组碰丝参数；脉间是倍数，不是微秒。 */
typedef struct {
    uint8_t level;
    uint8_t width_us;
    uint8_t gap_multiplier;
} osc_profile_t;

typedef struct {
    osc_profile_t normal[OSC_NORMAL_COUNT];
    osc_profile_t touch;
    uint8_t selected_normal;
} osc_image_t;

typedef enum { OSC_NORMAL, OSC_TOUCH } osc_mode_t;
typedef enum { OSC_LEVEL, OSC_WIDTH, OSC_GAP } osc_field_t;

typedef struct {
    uint32_t low_us;
    uint32_t high_us;
    uint32_t period_us;
    uint8_t channel_mask; /* 仅逻辑通道1～8；不是HRTIM寄存器位图。 */
} osc_pulse_t;

/* 上层不可直接改成员；只允许主循环串行调用下面的接口。 */
typedef struct {
    osc_image_t image;
    osc_mode_t mode;
    uint64_t revision;
    uint64_t saving_revision;
    uint32_t last_change_ms;
    bool initialized;
    bool dirty;
    bool saving;
} osc_params_t;

/* 区域C：参数接口。返回false表示无变化、输入非法或操作当前不可执行。 */
bool osc_profile_valid(const osc_profile_t *profile);
bool osc_image_valid(const osc_image_t *image);
/* persisted仅在存储层完成格式/CRC/范围校验后才能为true；默认值表用false。 */
bool osc_params_init(osc_params_t *state, const osc_image_t *image,
                     bool persisted, uint32_t now_ms);
const osc_profile_t *osc_params_current(const osc_params_t *state);
bool osc_params_select(osc_params_t *state, uint8_t number, uint32_t now_ms);
bool osc_params_toggle_mode(osc_params_t *state);
bool osc_params_adjust(osc_params_t *state, osc_field_t field,
                       int direction, uint32_t now_ms);
bool osc_profile_pulse(const osc_profile_t *profile, osc_pulse_t *pulse);

/* 区域D：延时保存握手。仅生成快照/确认结果，本模块不擦写Flash。 */
bool osc_params_save_due(const osc_params_t *state, uint32_t now_ms);
bool osc_params_begin_save(osc_params_t *state, uint32_t now_ms,
                           osc_image_t *snapshot, uint64_t *token);
/* verified必须表示实际写入并读回校验成功；失败保持脏并延时重试。 */
bool osc_params_finish_save(osc_params_t *state, uint64_t token,
                            bool verified, uint32_t now_ms);
bool osc_params_is_saved(const osc_params_t *state);

#endif
