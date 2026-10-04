#include "osc_keys.h"
#include <assert.h>
#include <stdio.h>

static uint16_t held(unsigned id)
{
    return (uint16_t)(OSC_KEY_MASK & (uint16_t)~OSC_KEY_BIT(id));
}

static void test_bounce_and_repeat(void)
{
    osc_keys_t keys;
    osc_keys_init(&keys, OSC_KEY_MASK, 0u);
    const uint16_t low = held(OSC_KEY_WIDTH_UP);
    assert(osc_keys_poll(&keys, low, 1u).pressed == 0u);
    assert(osc_keys_poll(&keys, OSC_KEY_MASK, 5u).pressed == 0u);
    assert(osc_keys_poll(&keys, low, 10u).pressed == 0u);
    assert(osc_keys_poll(&keys, low, 29u).pressed == 0u);
    assert(osc_keys_poll(&keys, low, 30u).pressed == OSC_KEY_BIT(OSC_KEY_WIDTH_UP));
    assert(osc_keys_poll(&keys, low, 529u).repeated == 0u);
    assert(osc_keys_poll(&keys, low, 530u).repeated == OSC_KEY_BIT(OSC_KEY_WIDTH_UP));
    assert(osc_keys_poll(&keys, low, 609u).repeated == 0u);
    assert(osc_keys_poll(&keys, low, 610u).repeated == OSC_KEY_BIT(OSC_KEY_WIDTH_UP));
    assert(osc_keys_poll(&keys, OSC_KEY_MASK, 620u).released == 0u);
    (void)osc_keys_poll(&keys, low, 625u); /* 释放抖动，不产生第二次单按。 */
    (void)osc_keys_poll(&keys, OSC_KEY_MASK, 630u);
    assert(osc_keys_poll(&keys, OSC_KEY_MASK, 650u).released == OSC_KEY_BIT(OSC_KEY_WIDTH_UP));
    assert(osc_keys_poll(&keys, OSC_KEY_MASK, 1000u).busy == 0u);
}

static void test_touch_once(void)
{
    osc_keys_t keys;
    osc_keys_init(&keys, OSC_KEY_MASK, 0u);
    (void)osc_keys_poll(&keys, held(OSC_KEY_TOUCH), 1u);
    assert(osc_keys_poll(&keys, held(OSC_KEY_TOUCH), 21u).pressed == OSC_KEY_BIT(OSC_KEY_TOUCH));
    for (uint32_t t = 22u; t < 10000u; ++t) {
        const osc_key_events_t e = osc_keys_poll(&keys, held(OSC_KEY_TOUCH), t);
        assert(e.pressed == 0u && e.repeated == 0u);
    }
    (void)osc_keys_poll(&keys, OSC_KEY_MASK, 10000u);
    (void)osc_keys_poll(&keys, OSC_KEY_MASK, 10020u);
    (void)osc_keys_poll(&keys, held(OSC_KEY_TOUCH), 10021u);
    assert(osc_keys_poll(&keys, held(OSC_KEY_TOUCH), 10041u).pressed == OSC_KEY_BIT(OSC_KEY_TOUCH));
}

static void test_startup_and_suppression(void)
{
    osc_keys_t keys;
    const uint16_t low = held(OSC_KEY_LEVEL_UP);
    osc_keys_init(&keys, low, 0u);
    assert(osc_keys_poll(&keys, low, 1000u).pressed == 0u);
    (void)osc_keys_poll(&keys, OSC_KEY_MASK, 1001u);
    (void)osc_keys_poll(&keys, OSC_KEY_MASK, 1021u);
    (void)osc_keys_poll(&keys, low, 1030u);
    assert(osc_keys_poll(&keys, low, 1050u).pressed == OSC_KEY_BIT(OSC_KEY_LEVEL_UP));
    osc_keys_suppress(&keys, OSC_KEY_BIT(OSC_KEY_LEVEL_UP), 1060u);
    assert(osc_keys_poll(&keys, low, 9000u).repeated == 0u);
    /* 扫描延迟后只松开1ms又按下，不应被误认为已稳定释放。 */
    (void)osc_keys_poll(&keys, OSC_KEY_MASK, 10000u);
    (void)osc_keys_poll(&keys, low, 10001u);
    assert(osc_keys_poll(&keys, low, 10021u).pressed == 0u);
}

static void test_wrap_and_all_keys(void)
{
    osc_keys_t keys;
    const uint32_t start = UINT32_MAX - 10u;
    osc_keys_init(&keys, OSC_KEY_MASK, start);
    (void)osc_keys_poll(&keys, 0u, start);
    assert(osc_keys_poll(&keys, 0u, start + UINT32_C(20)).pressed == OSC_KEY_MASK);
    const osc_key_events_t e = osc_keys_poll(&keys, 0u, start + UINT32_C(520));
    assert(e.repeated == UINT16_C(0x00ff)); /* 碰丝是第9键，不连发。 */
    assert(osc_keys_poll(&keys, 0u, start + UINT32_C(521)).repeated == 0u);
}

int main(void)
{
    test_bounce_and_repeat();
    test_touch_once();
    test_startup_and_suppression();
    test_wrap_and_all_keys();
    puts("PASS: 4 keyboard test groups.");
    return 0;
}
