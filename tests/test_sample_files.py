from pathlib import Path
import sys
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_logic import run_audit
from app import detect_seller_from_filename
from workbooks import parse_erp_workbook, parse_inventory_workbook


def _sample_dir():
    for path in Path.cwd().rglob('order-1789089972.xlsx'):
        return path.parent
    raise AssertionError('sample ERP workbook not found')


def test_provided_sample_files_end_to_end():
    sample_dir = _sample_dir()
    order_rows = parse_erp_workbook(sample_dir / 'order-1789089972.xlsx')
    sellers = sorted({row['seller'] for row in order_rows if row.get('seller')})
    inventory_by_store = {}
    for path in sample_dir.glob('*.xlsx'):
        seller = detect_seller_from_filename(path.name)
        if seller and seller in sellers:
            inventory_by_store[seller] = parse_inventory_workbook(path, seller)
    assert order_rows
    assert set(inventory_by_store) == set(sellers)
    result = run_audit(order_rows, inventory_by_store)
    assert result['summary']['total_orders'] > 0
    assert result['summary']['total_lines'] > 0
    assert all(order['status'] in {'manual', 'pass'} for order in result['orders'].values())
    assert all(order['reasons'] for order in result['orders'].values() if order['status'] == 'manual')


def test_inventory_parser_keeps_current_platform_sku_from_multi_sheet_store_file():
    sample_dir = _sample_dir()
    inventory_path = next(sample_dir.glob('*Thryvix*.xlsx'))
    rows = parse_inventory_workbook(inventory_path, 'THRYVIX_US_US')
    target = [row for row in rows if row.get('platform_sku') == 'W2339S00157-th-zy']
    assert target, '???????????????????? SKU????????????'
    assert target[0]['warehouse_sku'] == 'W2339S00157'
    assert target[0]['circle_stock'] == 37

def test_provided_target_order_matches_exact_inventory_platform_sku():
    sample_dir = _sample_dir()
    order_rows = parse_erp_workbook(sample_dir / 'order-1789089972.xlsx')
    sellers = sorted({row['seller'] for row in order_rows if row.get('seller')})
    inventory_by_store = {}
    for path in sample_dir.glob('*.xlsx'):
        seller = detect_seller_from_filename(path.name)
        if seller and seller in sellers:
            inventory_by_store[seller] = parse_inventory_workbook(path, seller)

    result = run_audit(order_rows, inventory_by_store, today=date(2026, 9, 11))
    target = result['orders']['112-2946839-4049003']
    evidence = target['lines'][0]['evidence']
    assert target['status'] == 'pass'
    assert '???????' not in target['reasons']
    assert evidence['matched_platform_sku'] == 'W2339S00157-th-zy'
    assert evidence['matched_warehouse_sku'] == 'W2339S00157'
    assert evidence['circle_stock'] == 37
    assert evidence['distribution_stock'] == 67

