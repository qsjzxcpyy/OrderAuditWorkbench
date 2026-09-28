from datetime import date

from audit_logic import (
    DISTRIBUTION_LOW_STOCK_REASON,
    LATEST_SHIP_REASON,
    PLATFORM_SKU_EXACT_REASON,
    build_inventory_index,
    copyable_manual_order_numbers,
    run_audit,
)


def order(order_no, seller='THRYVIX_US_US', buyer='buyer-1', platform='AMZ-1', warehouse='WH-1', qty=1, date_latest_ship=None, **extra):
    return {
        'order_no': order_no,
        'seller': seller,
        'buyer_id': buyer,
        'platform_sku': platform,
        'warehouse_sku': warehouse,
        'qty': qty,
        'date_latest_ship': date_latest_ship,
        **extra,
    }


def stock(seller='THRYVIX_US_US', platform='AMZ-1', warehouse='WH-1', circle=0, distribution=0, cost=10, discount=10):
    return {
        'seller': seller,
        'platform_sku': platform,
        'warehouse_sku': warehouse,
        'circle_stock': circle,
        'distribution_stock': distribution,
        'cost_price': cost,
        'discount_price': discount,
    }


def test_aggregates_same_warehouse_sku_demand_and_prefers_circle_stock():
    rows = [order('A', qty=1), order('B', buyer='buyer-2', qty=1)]
    result = run_audit(rows, {'THRYVIX_US_US': [stock(circle=1, distribution=99)]})

    assert result['summary']['total_orders'] == 2
    assert result['summary']['manual_orders'] == 2
    assert result['sku_groups']['WH-1']['demand'] == 2
    assert result['sku_groups']['WH-1']['circle_stock'] == 1
    assert '圈买库存不足' in result['orders']['A']['reasons']
    assert '圈买库存不足' in result['orders']['B']['reasons']


def test_distribution_stock_uses_price_tolerance_of_three():
    rows = [order('A')]
    result = run_audit(rows, {'THRYVIX_US_US': [stock(distribution=7, cost=10, discount=13)]})
    assert result['orders']['A']['status'] == 'pass'

    result = run_audit(rows, {'THRYVIX_US_US': [stock(distribution=7, cost=10, discount=13.01)]})
    assert result['orders']['A']['status'] == 'manual'
    assert '成本价与分销优惠价差异超过 3' in result['orders']['A']['reasons']


def test_distribution_stock_at_or_below_six_requires_manual_purchase_review():
    result = run_audit(
        [order('LOW-DISTRIBUTION')],
        {'THRYVIX_US_US': [stock(distribution=6, cost=10, discount=10)]},
    )

    assert result['orders']['LOW-DISTRIBUTION']['status'] == 'manual'
    assert DISTRIBUTION_LOW_STOCK_REASON in result['orders']['LOW-DISTRIBUTION']['reasons']


def test_distribution_stock_above_six_keeps_existing_pass_logic():
    result = run_audit(
        [order('ABOVE-THRESHOLD')],
        {'THRYVIX_US_US': [stock(distribution=7, cost=10, discount=10)]},
    )

    assert result['orders']['ABOVE-THRESHOLD']['status'] == 'pass'
    assert DISTRIBUTION_LOW_STOCK_REASON not in result['orders']['ABOVE-THRESHOLD']['reasons']


def test_duplicate_buyer_is_detected_across_sellers():
    rows = [order('A', seller='THRYVIX_US_US'), order('B', seller='VYNELITO_US')]
    inventories = {
        'THRYVIX_US_US': [stock(seller='THRYVIX_US_US', circle=2)],
        'VYNELITO_US': [stock(seller='VYNELITO_US', circle=2)],
    }
    result = run_audit(rows, inventories)
    assert result['orders']['A']['status'] == 'manual'
    assert result['orders']['B']['status'] == 'manual'
    assert '同一用户重复购买' in result['orders']['A']['reasons']
    assert result['orders']['A']['duplicate_orders'] == ['B']



def test_duplicate_buyer_product_is_detected_across_orders_even_when_warehouse_sku_differs():
    rows = [
        order('A', platform='SAME-PRODUCT', warehouse='WH-1'),
        order('B', platform='SAME-PRODUCT', warehouse='WH-2'),
    ]
    inventories = {
        'THRYVIX_US_US': [
            stock(platform='SAME-PRODUCT', warehouse='WH-1', circle=10),
            stock(platform='SAME-PRODUCT', warehouse='WH-2', circle=10),
        ],
    }

    result = run_audit(rows, inventories)

    assert result['orders']['A']['status'] == 'manual'
    assert result['orders']['B']['status'] == 'manual'
    assert '\u540c\u4e00\u7528\u6237\u91cd\u590d\u8d2d\u4e70\u540c\u4e00\u4ea7\u54c1' in result['orders']['A']['reasons']
    assert result['orders']['A']['duplicate_orders'] == ['B']


def test_repeated_platform_product_lines_for_one_buyer_are_detected():
    rows = [
        order('A', platform='SAME-PRODUCT', warehouse='WH-1'),
        order('A', platform='SAME-PRODUCT', warehouse='WH-2'),
    ]
    inventories = {
        'THRYVIX_US_US': [
            stock(platform='SAME-PRODUCT', warehouse='WH-1', circle=10),
            stock(platform='SAME-PRODUCT', warehouse='WH-2', circle=10),
        ],
    }

    result = run_audit(rows, inventories)

    assert result['orders']['A']['status'] == 'manual'
    assert '\u540c\u4e00\u7528\u6237\u91cd\u590d\u8d2d\u4e70\u540c\u4e00\u4ea7\u54c1' in result['orders']['A']['reasons']

def test_duplicate_inventory_rows_never_get_summed():
    rows = [order('A')]
    result = run_audit(rows, {'THRYVIX_US_US': [stock(circle=1), stock(circle=1)]})
    assert result['orders']['A']['status'] == 'manual'
    assert '库存表存在重复匹配记录' in result['orders']['A']['reasons']


def test_sku_mismatch_and_missing_inventory_are_manual():
    mismatch = run_audit([order('A')], {'THRYVIX_US_US': [stock(warehouse='OTHER', circle=10)]})
    assert '云仓 SKU 不一致' in mismatch['orders']['A']['reasons']

    missing = run_audit([order('A')], {'THRYVIX_US_US': []})
    assert '找不到对应库存' in missing['orders']['A']['reasons']


def test_copyable_order_numbers_are_unique_and_space_separated():
    result = run_audit([order('A', qty=2), order('B', buyer='buyer-2')], {'THRYVIX_US_US': [stock(circle=99)]})
    assert copyable_manual_order_numbers(result) == 'A'







def test_inventory_falls_back_to_matching_warehouse_sku_for_platform_variant():
    rows = [order(
        '112-2946839-4049003',
        platform='W2339S00157-th-zy',
        warehouse='W2339S00157',
        date_latest_ship='2026-09-15 14:59:59',
    )]
    inventories = {
        'THRYVIX_US_US': [
            stock(platform='W2339S00157-VY-HR', warehouse='W2339S00157', circle=37),
            stock(platform='W1117S00354-VY-HR', warehouse='W2339S00157', circle=37),
        ]
    }

    result = run_audit(rows, inventories, today=date(2026, 9, 11))
    audited = result['orders']['112-2946839-4049003']

    assert audited['status'] == 'manual'
    assert PLATFORM_SKU_EXACT_REASON in audited['reasons']
    assert '\u627e\u4e0d\u5230\u5bf9\u5e94\u5e93\u5b58' not in audited['reasons']
    assert audited['lines'][0]['evidence']['platform_sku_exact_match'] is False
    assert audited['lines'][0]['evidence']['inventory_match_type'] == 'warehouse_fallback'
    assert audited['lines'][0]['evidence']['circle_stock'] == 37
    assert audited['lines'][0]['evidence']['matched_platform_sku'] == 'W2339S00157-VY-HR'



def test_exact_platform_sku_match_can_pass_and_is_recorded_in_evidence():
    result = run_audit(
        [order('EXACT', platform='W2339S00157-th-zy', warehouse='W2339S00157')],
        {
            'THRYVIX_US_US': [
                stock(platform='W2339S00157-th-zy', warehouse='W2339S00157', circle=37),
            ],
        },
    )
    audited = result['orders']['EXACT']

    assert audited['status'] == 'pass'
    assert PLATFORM_SKU_EXACT_REASON not in audited['reasons']
    assert audited['lines'][0]['evidence']['platform_sku_exact_match'] is True
    assert audited['lines'][0]['evidence']['inventory_match_type'] == 'exact_platform_sku'
    assert audited['lines'][0]['evidence']['matched_platform_sku'] == 'W2339S00157-th-zy'


def test_latest_ship_date_five_days_in_future_is_presale():
    rows = [
        order('FIVE_DAYS', date_latest_ship='2026-09-15'),
        order('FOUR_DAYS', buyer='buyer-2', date_latest_ship='2026-09-14'),
        order('PAST', buyer='buyer-3', date_latest_ship='2026-09-05'),
    ]
    result = run_audit(
        rows,
        {'THRYVIX_US_US': [stock(circle=99)]},
        today=date(2026, 9, 10),
    )

    assert result['orders']['FIVE_DAYS']['status'] == 'manual'
    assert result['orders']['FIVE_DAYS']['is_presale'] is True
    assert LATEST_SHIP_REASON in result['orders']['FIVE_DAYS']['reasons']
    assert result['orders']['FIVE_DAYS']['latest_ship_age_days'] == 5

    assert result['orders']['FOUR_DAYS']['status'] == 'pass'
    assert result['orders']['FOUR_DAYS']['is_presale'] is False
    assert result['orders']['PAST']['status'] == 'pass'
    assert result['orders']['PAST']['is_presale'] is False


def test_latest_ship_date_fallback_applies_to_every_order_without_short_circuiting():
    rows = [
        order('INVENTORY-MANUAL', date_latest_ship='2026-09-09'),
        order('DATE-MANUAL', buyer='buyer-2', date_latest_ship='2026-09-15'),
    ]
    result = run_audit(
        rows,
        {'THRYVIX_US_US': [stock(circle=1)]},
        today=date(2026, 9, 10),
    )

    assert '圈买库存不足' in result['orders']['INVENTORY-MANUAL']['reasons']
    assert LATEST_SHIP_REASON in result['orders']['DATE-MANUAL']['reasons']
    assert result['summary']['manual_orders'] == 2


def test_latest_ship_fallback_uses_the_furthest_future_line_date_for_one_order():
    rows = [
        order('MIXED', date_latest_ship='2026-09-11'),
        order('MIXED', platform='AMZ-2', warehouse='WH-2', date_latest_ship='2026-09-15'),
    ]
    result = run_audit(
        rows,
        {'THRYVIX_US_US': [stock(circle=99), stock(platform='AMZ-2', warehouse='WH-2', circle=99)]},
        today=date(2026, 9, 10),
    )

    assert result['orders']['MIXED']['status'] == 'manual'
    assert LATEST_SHIP_REASON in result['orders']['MIXED']['reasons']
    assert result['orders']['MIXED']['latest_ship_age_days'] == 5
    assert result['orders']['MIXED']['date_latest_ship'] == '2026-09-15'


def test_latest_ship_date_with_time_uses_calendar_day_difference():
    result = run_audit(
        [order('TIME-DATE', date_latest_ship='2026-09-15 14:59:59')],
        {'THRYVIX_US_US': [stock(circle=99)]},
        today=date(2026, 9, 10),
    )

    assert result['orders']['TIME-DATE']['is_presale'] is True
    assert result['orders']['TIME-DATE']['latest_ship_age_days'] == 5


def test_presale_fields_are_not_used_for_presale_detection():
    result = run_audit(
        [order('FIELD-ONLY', custom_order_type='Pre-sale', order_desc='pre order')],
        {'THRYVIX_US_US': [stock(circle=99)]},
        today=date(2026, 9, 10),
    )

    assert result['orders']['FIELD-ONLY']['is_presale'] is False
    assert result['orders']['FIELD-ONLY']['status'] == 'pass'
    assert '预售订单' not in result['orders']['FIELD-ONLY']['reasons']
