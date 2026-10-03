#include "osc_params.h"
#include <assert.h>
#include <stddef.h>
#include <stdio.h>

/* 仅供测试的样例，不作为出厂默认参数。 */
static osc_image_t fixture(void)
{
    osc_image_t image = {0};
    for (unsigned i = 0; i < OSC_NORMAL_COUNT; ++i) {
        image.normal[i] = (osc_profile_t){7u, (uint8_t)(20u + i), 8u};
    }
    image.normal[1] = (osc_profile_t){7u, 60u, 8u};
    image.touch = (osc_profile_t){1u, 40u, 5u};
    image.selected_normal = 1u;
    return image;
}

static void test_validation(void)
{
    osc_params_t s = {0};
    osc_image_t image = fixture();
    assert(!osc_params_is_saved(&s));
    assert(!osc_params_toggle_mode(&s));
    assert(osc_image_valid(&image));
    assert(osc_params_init(&s, &image, true, 0u));
    assert(osc_params_is_saved(&s));
    image.normal[9].width_us = 1u;
    assert(!osc_params_init(&s, &image, true, 0u));
    assert(!s.initialized);
    assert(osc_params_current(&s) == NULL);
    image = fixture();
    image.touch.gap_multiplier = 33u;
    assert(!osc_image_valid(&image));
    image = fixture();
    image.selected_normal = 10u;
    assert(!osc_image_valid(&image));
    assert(!osc_image_valid(NULL));
    assert(!osc_params_init(NULL, &image, true, 0u));
}

static void test_eleven_profiles(void)
{
    osc_params_t s;
    const osc_image_t image = fixture();
    assert(osc_params_init(&s, &image, true, 0u));
    assert(osc_params_current(&s)->width_us == 60u);
    assert(osc_params_toggle_mode(&s));
    assert(osc_params_is_saved(&s));
    assert(osc_params_current(&s)->width_us == 40u);
    assert(!osc_params_select(&s, 2u, 10u));
    assert(osc_params_adjust(&s, OSC_WIDTH, 1, 20u));
    assert(osc_params_toggle_mode(&s));
    assert(osc_params_current(&s)->width_us == 60u);
    for (uint8_t i = 0u; i < OSC_NORMAL_COUNT; ++i) {
        (void)osc_params_select(&s, i, 30u);
        assert(osc_params_adjust(&s, OSC_GAP, 1, 40u));
    }
    for (unsigned i = 0; i < OSC_NORMAL_COUNT; ++i) {
        assert(s.image.normal[i].gap_multiplier == 9u);
        assert(s.image.normal[i].width_us == image.normal[i].width_us);
    }
    assert(s.image.touch.width_us == 41u);
    assert(s.image.touch.gap_multiplier == 5u);
    assert(!osc_params_select(&s, 10u, 100u));
}

static void test_boundaries(void)
{
    osc_params_t s;
    osc_image_t image = fixture();
    image.selected_normal = 0u;
    image.normal[0] = (osc_profile_t){1u, 2u, 2u};
    assert(osc_params_init(&s, &image, true, 0u));
    assert(!osc_params_adjust(&s, OSC_LEVEL, -1, 10u));
    assert(!osc_params_adjust(&s, OSC_WIDTH, -1, 10u));
    assert(!osc_params_adjust(&s, OSC_GAP, -1, 10u));
    assert(osc_params_is_saved(&s));
    assert(!osc_params_adjust(&s, OSC_GAP, 2, 10u));
    assert(!osc_params_adjust(&s, (osc_field_t)99, 1, 10u));
    for (unsigned i = 0; i < 150u; ++i) {
        (void)osc_params_adjust(&s, OSC_LEVEL, 1, i);
        (void)osc_params_adjust(&s, OSC_WIDTH, 1, i);
        (void)osc_params_adjust(&s, OSC_GAP, 1, i);
    }
    assert(osc_params_current(&s)->level == 8u);
    assert(osc_params_current(&s)->width_us == 99u);
    assert(osc_params_current(&s)->gap_multiplier == 32u);
    const uint32_t last_change = s.last_change_ms;
    assert(!osc_params_adjust(&s, OSC_WIDTH, 1, 9000u));
    assert(s.last_change_ms == last_change);
}

static void test_save_transaction(void)
{
    osc_params_t s;
    osc_image_t snapshot;
    uint64_t token;
    const osc_image_t image = fixture();
    assert(osc_params_init(&s, &image, true, 0u));
    assert(osc_params_adjust(&s, OSC_WIDTH, 1, 100u));
    assert(!osc_params_save_due(&s, 2599u));
    assert(osc_params_adjust(&s, OSC_GAP, 1, 2500u));
    assert(!osc_params_save_due(&s, 2600u)); /* 连续调整推迟保存。 */
    assert(osc_params_toggle_mode(&s)); /* 切换不推迟保存。 */
    assert(s.last_change_ms == 2500u);
    assert(!osc_params_save_due(&s, 4999u));
    assert(osc_params_begin_save(&s, 5000u, &snapshot, &token));
    assert(snapshot.normal[1].width_us == 61u);
    assert(snapshot.normal[1].gap_multiplier == 9u);
    assert(!osc_params_save_due(&s, 5000u));
    assert(!osc_params_finish_save(&s, token + 1u, true, 5001u));
    assert(osc_params_adjust(&s, OSC_LEVEL, 1, 5010u)); /* 保存期间新修改。 */
    assert(osc_params_finish_save(&s, token, true, 5020u));
    assert(!osc_params_is_saved(&s));
    assert(!osc_params_save_due(&s, 7509u));
    assert(osc_params_begin_save(&s, 7510u, &snapshot, &token));
    assert(snapshot.touch.level == 2u);
    assert(osc_params_finish_save(&s, token, false, 7520u));
    assert(!osc_params_is_saved(&s));
    assert(!osc_params_save_due(&s, 10019u));
    assert(osc_params_begin_save(&s, 10020u, &snapshot, &token));
    assert(osc_params_finish_save(&s, token, true, 10021u));
    assert(osc_params_is_saved(&s));
    assert(osc_params_toggle_mode(&s));
    assert(osc_params_is_saved(&s));
    assert(!osc_params_save_due(&s, 20000u));
    assert(osc_params_select(&s, 2u, 20001u));
    assert(!osc_params_is_saved(&s)); /* 正常序号属于持久数据。 */
}

static void test_wrap_and_defaults(void)
{
    osc_params_t s;
    const osc_image_t image = fixture();
    const uint32_t start = UINT32_MAX - 1000u;
    assert(osc_params_init(&s, &image, false, start));
    assert(!osc_params_is_saved(&s)); /* 未写入的默认值不能亮保存灯。 */
    assert(!osc_params_save_due(&s, start + UINT32_C(2499)));
    assert(osc_params_save_due(&s, start + UINT32_C(2500)));
}

static void test_all_pulse_values(void)
{
    osc_pulse_t pulse;
    osc_profile_t p = {6u, 20u, 5u};
    assert(osc_profile_pulse(&p, &pulse));
    assert(pulse.low_us == 20u && pulse.high_us == 100u && pulse.period_us == 120u);
    assert(pulse.channel_mask == 0x3fu);
    unsigned combinations = 0u;
    for (uint8_t level = 1u; level <= 8u; ++level) {
        for (uint8_t width = 2u; width <= 99u; ++width) {
            for (uint8_t gap = 2u; gap <= 32u; ++gap) {
                p = (osc_profile_t){level, width, gap};
                assert(osc_profile_pulse(&p, &pulse));
                assert(pulse.low_us == width);
                assert(pulse.high_us / width == gap);
                assert(pulse.period_us == pulse.low_us + pulse.high_us);
                unsigned bits = 0u;
                for (unsigned i = 0u; i < 8u; ++i) {
                    bits += (unsigned)((pulse.channel_mask >> i) & 1u);
                }
                assert(bits == level);
                assert(pulse.period_us >= 6u && pulse.period_us <= 3267u);
                ++combinations;
            }
        }
    }
    assert(combinations == 24304u);
    p.level = 0u;
    assert(!osc_profile_pulse(&p, &pulse));
    p = (osc_profile_t){8u, 99u, 32u};
    assert(osc_profile_pulse(&p, &pulse));
    assert(pulse.high_us == 3168u && pulse.period_us == 3267u);
    assert(pulse.channel_mask == 0xffu);
}

int main(void)
{
    test_validation();
    test_eleven_profiles();
    test_boundaries();
    test_save_transaction();
    test_wrap_and_defaults();
    test_all_pulse_values();
    puts("PASS: 6 parameter test groups; 24304 legal pulse combinations.");
    return 0;
}
