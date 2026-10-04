#include "osc_panel.h"
#include <assert.h>
#include <stdio.h>

static osc_image_t fixture(void)
{
    osc_image_t image = {0};
    for (unsigned i = 0u; i < OSC_NORMAL_COUNT; ++i)
        image.normal[i] = (osc_profile_t){7u, 60u, 8u};
    image.touch = (osc_profile_t){1u, 40u, 5u};
    image.selected_normal = 1u;
    return image;
}
static void init(osc_params_t *s, osc_panel_t *ui, uint32_t now)
{
    const osc_image_t image = fixture();
    assert(osc_params_init(s, &image, true, now));
    assert(osc_panel_init(ui, s, OSC_KEY_MASK, now));
}
static uint16_t low(uint16_t bits)
{
    return (uint16_t)(OSC_KEY_MASK & (uint16_t)~bits);
}
static void click(osc_panel_t *ui, osc_params_t *s, unsigned key, uint32_t now)
{
    const uint16_t levels = low(OSC_KEY_BIT(key));
    (void)osc_panel_poll(ui, s, levels, now);
    (void)osc_panel_poll(ui, s, levels, now + 20u);
    (void)osc_panel_poll(ui, s, OSC_KEY_MASK, now + 21u);
    (void)osc_panel_poll(ui, s, OSC_KEY_MASK, now + 41u);
}
static osc_display_frame_t frame(osc_panel_t *ui, osc_params_t *s)
{
    osc_display_frame_t out;
    assert(osc_panel_frame(ui, s, &out));
    return out;
}

static void test_sleep_wake_execute(void)
{
    osc_params_t s; osc_panel_t ui;
    init(&s, &ui, 0u);
    (void)osc_panel_poll(&ui, &s, OSC_KEY_MASK, 119999u);
    assert(frame(&ui, &s).brightness == 7u);
    (void)osc_panel_poll(&ui, &s, OSC_KEY_MASK, 120000u);
    assert(frame(&ui, &s).brightness == 0u);
    assert(frame(&ui, &s).decimal_mask == 1u);
    click(&ui, &s, OSC_KEY_WIDTH_UP, 120010u);
    assert(frame(&ui, &s).brightness == 7u);
    assert(osc_params_current(&s)->width_us == 61u);
    assert(frame(&ui, &s).decimal_mask == 0u);
    (void)osc_panel_poll(&ui, &s, OSC_KEY_MASK, 500000u);
    assert(frame(&ui, &s).brightness == 7u); /* 脏数据不能显示已保存休眠。 */
}

static void test_saved_timer_and_boundary_key(void)
{
    osc_params_t s; osc_panel_t ui;
    init(&s, &ui, 0u);
    click(&ui, &s, OSC_KEY_LEVEL_UP, 1u); /* 到8档。 */
    osc_image_t snap; uint64_t token;
    assert(osc_params_begin_save(&s, 2521u, &snap, &token));
    assert(osc_params_finish_save(&s, token, true, 2530u));
    (void)osc_panel_poll(&ui, &s, OSC_KEY_MASK, 2530u);
    (void)osc_panel_poll(&ui, &s, OSC_KEY_MASK, 122529u);
    assert(frame(&ui, &s).brightness == 7u);
    (void)osc_panel_poll(&ui, &s, OSC_KEY_MASK, 122530u);
    assert(frame(&ui, &s).brightness == 0u);
    click(&ui, &s, OSC_KEY_LEVEL_UP, 122540u);
    assert(frame(&ui, &s).brightness == 7u);
    assert(osc_params_is_saved(&s)); /* 边界按键唤醒，但不产生无效保存。 */
}

static void test_touch_and_display(void)
{
    osc_params_t s; osc_panel_t ui;
    init(&s, &ui, 0u);
    osc_display_frame_t f = frame(&ui, &s);
    assert(f.digit[0] == 1u && f.digit[1] == 7u);
    assert(f.digit[2] == 6u && f.digit[3] == 0u);
    assert(f.digit[4] == 0u && f.digit[5] == 8u);
    click(&ui, &s, OSC_KEY_TOUCH, 1u);
    assert(s.mode == OSC_TOUCH && osc_params_is_saved(&s));
    f = frame(&ui, &s);
    assert(f.digit[0] == OSC_DIGIT_DASH && f.digit[1] == 1u);
    assert(f.digit[2] == 4u && f.digit[3] == 0u);
    assert(f.digit[4] == 0u && f.digit[5] == 5u);
    (void)osc_panel_poll(&ui, &s, OSC_KEY_MASK, 500000u);
    assert(frame(&ui, &s).brightness == 7u);
    click(&ui, &s, OSC_KEY_NUMBER_UP, 500010u);
    assert(s.image.selected_normal == 1u && osc_params_is_saved(&s));
    click(&ui, &s, OSC_KEY_TOUCH, 500060u);
    assert(s.mode == OSC_NORMAL && osc_params_current(&s)->width_us == 60u);
    assert(osc_params_is_saved(&s));
}

static void test_pair_and_mode_priority(void)
{
    osc_params_t s; osc_panel_t ui;
    init(&s, &ui, 0u);
    const uint16_t pair = low((uint16_t)(OSC_KEY_BIT(OSC_KEY_WIDTH_UP)
                                       | OSC_KEY_BIT(OSC_KEY_WIDTH_DOWN)));
    (void)osc_panel_poll(&ui, &s, pair, 1u);
    (void)osc_panel_poll(&ui, &s, pair, 21u);
    (void)osc_panel_poll(&ui, &s, pair, 521u);
    assert(osc_params_current(&s)->width_us == 60u && osc_params_is_saved(&s));
    (void)osc_panel_poll(&ui, &s, OSC_KEY_MASK, 530u);
    (void)osc_panel_poll(&ui, &s, OSC_KEY_MASK, 550u);
    const uint16_t mix = low((uint16_t)(OSC_KEY_BIT(OSC_KEY_WIDTH_UP)
                                      | OSC_KEY_BIT(OSC_KEY_TOUCH)));
    (void)osc_panel_poll(&ui, &s, mix, 560u);
    (void)osc_panel_poll(&ui, &s, mix, 580u);
    assert(s.mode == OSC_TOUCH && osc_params_current(&s)->width_us == 40u);
    (void)osc_panel_poll(&ui, &s, mix, 5000u);
    assert(s.mode == OSC_TOUCH && osc_params_current(&s)->width_us == 40u);
}

static void test_repeat_and_wrap(void)
{
    osc_params_t s; osc_panel_t ui;
    const uint32_t start = UINT32_MAX - 100u;
    init(&s, &ui, start);
    (void)osc_panel_poll(&ui, &s, OSC_KEY_MASK, start + UINT32_C(120000));
    assert(frame(&ui, &s).brightness == 0u);
    const uint32_t press = start + UINT32_C(120010);
    const uint16_t levels = low(OSC_KEY_BIT(OSC_KEY_GAP_UP));
    (void)osc_panel_poll(&ui, &s, levels, press);
    (void)osc_panel_poll(&ui, &s, levels, press + 20u);
    (void)osc_panel_poll(&ui, &s, levels, press + 520u);
    (void)osc_panel_poll(&ui, &s, levels, press + 600u);
    assert(osc_params_current(&s)->gap_multiplier == 11u); /* 1次单按+2次连发。 */
    assert(s.last_change_ms == press + 600u);
    assert(frame(&ui, &s).brightness == 7u);
}

int main(void)
{
    test_sleep_wake_execute();
    test_saved_timer_and_boundary_key();
    test_touch_and_display();
    test_pair_and_mode_priority();
    test_repeat_and_wrap();
    puts("PASS: 5 panel integration test groups.");
    return 0;
}
