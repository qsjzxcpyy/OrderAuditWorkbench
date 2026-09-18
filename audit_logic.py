from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta
from numbers import Number
from typing import Any, Iterable

PRICE_TOLERANCE = 3.0
DISTRIBUTION_LOW_STOCK_LIMIT = 6.0
DISTRIBUTION_LOW_STOCK_REASON = '\u5206\u9500\u5e93\u5b58\u5c0f\u4e8e\u7b49\u4e8e 6\uff0c\u9700\u8981\u4eba\u5de5\u63d0\u524d\u4e70\u5165'
LATEST_SHIP_MANUAL_DAYS = 5
LATEST_SHIP_REASON = '\u9884\u552e\u8ba2\u5355\uff1a\u6700\u665a\u53d1\u8d27\u65e5\u671f\u8ddd\u5f53\u524d\u65e5\u671f\u8fbe 5 \u5929\u53ca\u4ee5\u4e0a'
PRESALE_REASON = '\u9884\u552e\u8ba2\u5355'
PLATFORM_SKU_EXACT_REASON = '\u5e97\u94fa SKU \u672a\u7cbe\u786e\u5339\u914d\uff0c\u9700\u8981\u4eba\u5de5\u786e\u8ba4'


def normalize_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Number):
        return float(value)
    text = str(value).strip().replace(',', '').replace('$', '').replace('￥', '').replace('¥', '')
    if not text or text in {'-', '—', 'N/A', 'None', 'null', '#REF!', '#VALUE!'}:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def clean_text(value: Any) -> str:
    return str(value or '').strip()


def parse_date_value(value: Any) -> date | None:
    """Parse common ERP date values without making invalid dates manual."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, Number):
        serial = float(value)
        if serial <= 0 or serial > 100000:
            return None
        try:
            return (datetime(1899, 12, 30) + timedelta(days=serial)).date()
        except (OverflowError, ValueError):
            return None
    text = clean_text(value)
    if not text or text.startswith('0000-00-00'):
        return None
    normalized = text.replace('T', ' ').replace('Z', '').strip()
    for candidate in (normalized, normalized.split('.')[0]):
        try:
            return datetime.fromisoformat(candidate).date()
        except ValueError:
            pass
    for fmt in ('%Y/%m/%d', '%Y.%m.%d', '\u0025Y\u5e74\u0025m\u6708\u0025d\u65e5', '%m/%d/%Y'):
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            pass
    return None


def presale_matches(record: dict[str, Any]) -> list[str]:
    """Deprecated: pre-sale status is determined only by date_latest_ship."""
    return []


def is_presale_order(record: dict[str, Any]) -> bool:
    """Deprecated: callers should use the aggregated date_latest_ship rule."""
    return False


def days_until_latest_ship(value: Any, today: date | None = None) -> int | None:
    """Return calendar days from today until the latest ship date."""
    ship_date = parse_date_value(value)
    if ship_date is None:
        return None
    current_date = today or date.today()
    return (ship_date - current_date).days


def latest_ship_age_days(value: Any, today: date | None = None) -> int | None:
    """Backward-compatible alias; the value now means days until shipment."""
    return days_until_latest_ship(value, today)

def build_inventory_index(rows: Iterable[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        seller = clean_text(row.get('seller'))
        platform_sku = clean_text(row.get('platform_sku'))
        if seller and platform_sku:
            index[(seller, platform_sku)].append(dict(row))
    return dict(index)


def _line_key(line: dict[str, Any]) -> tuple[str, str]:
    return clean_text(line.get('seller')), clean_text(line.get('platform_sku'))


def _warehouse_key(line: dict[str, Any]) -> tuple[str, str]:
    return clean_text(line.get('seller')), clean_text(line.get('warehouse_sku'))


def _warehouse_fallback_matches(line: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve SKU aliases when ERP and inventory use different platform SKU suffixes."""
    if len(candidates) <= 1:
        return candidates
    warehouse = clean_text(line.get('warehouse_sku')).lower()
    preferred = [
        row for row in candidates
        if clean_text(row.get('platform_sku')).lower().startswith(warehouse)
    ]
    return preferred if len(preferred) == 1 else candidates


def _manual_reasons(line: dict[str, Any], stock_rows: list[dict[str, Any]], demand: float) -> tuple[list[str], dict[str, Any]]:
    reasons: list[str] = []
    evidence: dict[str, Any] = {
        'demand': demand,
        'circle_stock': None,
        'distribution_stock': None,
        'cost_price': None,
        'discount_price': None,
        'price_difference': None,
        'inventory_match_count': len(stock_rows),
        'matched_platform_sku': None,
        'platform_sku_exact_match': None,
        'inventory_match_type': None,
    }
    if not stock_rows:
        reasons.append('找不到对应库存')
        return reasons, evidence
    if len(stock_rows) > 1:
        reasons.append('库存表存在重复匹配记录')
        return reasons, evidence

    stock = stock_rows[0]
    order_warehouse = clean_text(line.get('warehouse_sku'))
    stock_warehouse = clean_text(stock.get('warehouse_sku'))
    evidence.update({
        'matched_warehouse_sku': stock_warehouse,
        'matched_platform_sku': clean_text(stock.get('platform_sku')),
        'inventory_title': stock.get('title') or stock.get('product_title'),
    })
    if not order_warehouse or not stock_warehouse or order_warehouse != stock_warehouse:
        reasons.append('云仓 SKU 不一致')
        return reasons, evidence

    circle = normalize_number(stock.get('circle_stock'))
    distribution = normalize_number(stock.get('distribution_stock'))
    cost = normalize_number(stock.get('cost_price'))
    discount = normalize_number(stock.get('discount_price'))
    evidence.update({
        'circle_stock': circle,
        'distribution_stock': distribution,
        'cost_price': cost,
        'discount_price': discount,
    })

    if circle is not None and circle > 0:
        if circle < demand:
            reasons.append('圈买库存不足')
        return reasons, evidence

    if distribution is None:
        reasons.append('\u5206\u9500\u5e93\u5b58\u65e0\u6cd5\u8bc6\u522b')
    elif distribution < demand:
        reasons.append('\u5206\u9500\u5e93\u5b58\u4e0d\u8db3')
    if distribution is not None and distribution <= DISTRIBUTION_LOW_STOCK_LIMIT:
        reasons.append(DISTRIBUTION_LOW_STOCK_REASON)
    if distribution is not None and distribution >= demand:
        if cost is None or discount is None:
            reasons.append('\u4ef7\u683c\u65e0\u6cd5\u8bc6\u522b')
        else:
            difference = abs(cost - discount)
            evidence['price_difference'] = difference
            if difference > PRICE_TOLERANCE:
                reasons.append('\u6210\u672c\u4ef7\u4e0e\u5206\u9500\u4f18\u60e0\u4ef7\u5dee\u5f02\u8d85\u8fc7 3')
    return reasons, evidence


def run_audit(
    order_rows: Iterable[dict[str, Any]],
    inventory_rows_by_store: dict[str, Iterable[dict[str, Any]]],
    today: date | None = None,
) -> dict[str, Any]:
    lines = [dict(row) for row in order_rows]
    demand_by_warehouse: dict[str, float] = defaultdict(float)
    order_sku_qty: dict[tuple[str, str], float] = defaultdict(float)
    buyer_orders: dict[tuple[str, str], set[str]] = defaultdict(set)
    for line in lines:
        order_no = clean_text(line.get('order_no'))
        warehouse = clean_text(line.get('warehouse_sku'))
        qty = normalize_number(line.get('qty'))
        if qty is not None and warehouse:
            demand_by_warehouse[warehouse] += qty
            order_sku_qty[(order_no, warehouse)] += qty
        buyer_key = (clean_text(line.get('buyer_id')), warehouse)
        if buyer_key[0] and buyer_key[1] and order_no:
            buyer_orders[buyer_key].add(order_no)

    inventories: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    inventories_by_warehouse: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for seller, rows in inventory_rows_by_store.items():
        for row in rows:
            item = dict(row)
            platform_key = (clean_text(seller), clean_text(item.get('platform_sku')))
            warehouse_key = (clean_text(seller), clean_text(item.get('warehouse_sku')))
            if platform_key[0] and platform_key[1]:
                inventories[platform_key].append(item)
            if warehouse_key[0] and warehouse_key[1]:
                inventories_by_warehouse[warehouse_key].append(item)

    line_results: list[dict[str, Any]] = []
    for source in lines:
        line = deepcopy(source)
        order_no = clean_text(line.get('order_no'))
        warehouse = clean_text(line.get('warehouse_sku'))
        qty = normalize_number(line.get('qty'))
        reasons: list[str] = []
        # Pre-sale is intentionally not inferred from ERP text fields.
        # It is evaluated once per aggregated order from date_latest_ship below.
        matched_presale_values: list[str] = []
        if qty is None:
            reasons.append('订单数量无法识别')
            qty = 0
        if qty >= 2 or order_sku_qty[(order_no, warehouse)] >= 2:
            reasons.append('单个订单购买数量 ≥ 2')
        buyer_key = (clean_text(line.get('buyer_id')), warehouse)
        duplicate_orders = sorted(buyer_orders.get(buyer_key, set()) - {order_no})
        if duplicate_orders:
            reasons.append('同一用户重复购买')

        exact_platform_match = bool(inventories.get(_line_key(line), []))
        inventory_match_type = 'exact_platform_sku' if exact_platform_match else 'not_found'
        stock_rows = inventories.get(_line_key(line), [])
        if not exact_platform_match:
            stock_rows = _warehouse_fallback_matches(
                line,
                inventories_by_warehouse.get(_warehouse_key(line), []),
            )
            if stock_rows:
                inventory_match_type = 'warehouse_fallback'
        inventory_reasons, evidence = _manual_reasons(
            line,
            stock_rows,
            demand_by_warehouse.get(warehouse, 0),
        )
        for reason in inventory_reasons:
            if reason not in reasons:
                reasons.append(reason)
        evidence.update({
            'platform_sku_exact_match': exact_platform_match,
            'inventory_match_type': inventory_match_type,
        })
        if not exact_platform_match:
            reasons.append(PLATFORM_SKU_EXACT_REASON)

        line_results.append({
            **line,
            'qty': qty,
            'status': 'manual' if reasons else 'pass',
            'reasons': reasons,
            'duplicate_orders': duplicate_orders,
            'is_presale': bool(matched_presale_values),
            'presale_matches': matched_presale_values,
            'evidence': evidence,
        })

    orders: dict[str, dict[str, Any]] = {}
    for line in line_results:
        order_no = line['order_no']
        if order_no not in orders:
            orders[order_no] = {
                'order_no': order_no,
                'seller': line.get('seller', ''),
                'buyer_id': line.get('buyer_id', ''),
                'date_latest_ship': clean_text(line.get('date_latest_ship')),
                'latest_ship_age_days': None,
                'is_presale': False,
                'presale_matches': [],
                'status': 'pass',
                'reasons': [],
                'duplicate_orders': [],
                'lines': [],
            }
        order = orders[order_no]
        if not order.get('date_latest_ship') and line.get('date_latest_ship'):
            order['date_latest_ship'] = clean_text(line.get('date_latest_ship'))
        order['lines'].append(line)
        if line.get('is_presale'):
            order['is_presale'] = True
        for match in line.get('presale_matches', []):
            if match not in order['presale_matches']:
                order['presale_matches'].append(match)
        if line['status'] == 'manual':
            order['status'] = 'manual'
        for reason in line['reasons']:
            if reason not in order['reasons']:
                order['reasons'].append(reason)
        for duplicate in line['duplicate_orders']:
            if duplicate not in order['duplicate_orders']:
                order['duplicate_orders'].append(duplicate)

    # Final fallback: evaluate every aggregated order after all existing rules.
    # Pre-sale is based exclusively on date_latest_ship. For multi-line orders,
    # use the furthest latest ship date. This pass never short-circuits the
    # inventory, duplicate-order, or quantity checks above.
    for order in orders.values():
        line_dates = [
            (days_until_latest_ship(line.get('date_latest_ship'), today), line.get('date_latest_ship'))
            for line in order['lines']
        ]
        valid_dates = [(days, value) for days, value in line_dates if days is not None]
        days_until_ship, ship_date_value = max(
            valid_dates,
            key=lambda item: item[0],
            default=(days_until_latest_ship(order.get('date_latest_ship'), today), order.get('date_latest_ship')),
        )
        if ship_date_value:
            order['date_latest_ship'] = clean_text(ship_date_value)
        order['days_until_latest_ship'] = days_until_ship
        # Keep the existing response key for frontend/export compatibility while
        # correcting its meaning to "days until shipment".
        order['latest_ship_age_days'] = days_until_ship
        order['is_presale'] = bool(
            days_until_ship is not None and days_until_ship >= LATEST_SHIP_MANUAL_DAYS
        )
        if order['is_presale']:
            order['status'] = 'manual'
            if LATEST_SHIP_REASON not in order['reasons']:
                order['reasons'].append(LATEST_SHIP_REASON)

    sku_groups: dict[str, dict[str, Any]] = {}
    for sku, demand in demand_by_warehouse.items():
        group_lines = [line for line in line_results if line.get('warehouse_sku') == sku]
        evidence = next((line['evidence'] for line in group_lines if line.get('evidence')), {})
        sku_groups[sku] = {
            'warehouse_sku': sku,
            'demand': demand,
            'order_count': len({line['order_no'] for line in group_lines}),
            'circle_stock': evidence.get('circle_stock'),
            'distribution_stock': evidence.get('distribution_stock'),
            'order_numbers': sorted({line['order_no'] for line in group_lines}),
        }

    manual_orders = [order for order in orders.values() if order['status'] == 'manual']
    pass_orders = [order for order in orders.values() if order['status'] == 'pass']
    return {
        'orders': orders,
        'lines': line_results,
        'sku_groups': sku_groups,
        'summary': {
            'total_orders': len(orders),
            'manual_orders': len(manual_orders),
            'pass_orders': len(pass_orders),
            'total_lines': len(line_results),
            'manual_lines': sum(1 for line in line_results if line['status'] == 'manual'),
        },
    }


def copyable_manual_order_numbers(result: dict[str, Any]) -> str:
    return ' '.join(order_no for order_no, order in result.get('orders', {}).items() if order.get('status') == 'manual')
