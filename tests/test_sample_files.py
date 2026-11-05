"""End-to-end workbook checks using generated, fictional business records."""

from datetime import date

import openpyxl
import pytest

from app import detect_seller_from_filename
from audit_logic import run_audit
from workbooks import parse_erp_workbook, parse_inventory_workbook


@pytest.fixture
def synthetic_workbooks(tmp_path):
    erp_path = tmp_path / 'demo-orders.xlsx'
    erp = openpyxl.Workbook()
    sheet = erp.active
    sheet.append([
        'refrence_no_platform', 'platform_seller_id', 'buyer_id',
        'date_latest_ship', 'sku1', 'warehouse_sku1', 'qty1',
    ])
    for order_no, buyer, qty in [
        ('DEMO-ORDER-001', 'demo-buyer-001', 1),
        ('DEMO-ORDER-002', 'demo-buyer-002', 2),
    ]:
        sheet.append([
            order_no, 'DEMOA_US_US', buyer, '2030-01-03',
            'DEMO-SKU-001', 'DEMO-WH-001', qty,
        ])
    erp.save(erp_path)
    erp.close()

    inventory_path = tmp_path / 'DEMOA-inventory.xlsx'
    inventory = openpyxl.Workbook()
    inventory.active.title = 'Notes'
    inventory.active.append(['Synthetic data only; no business files required.'])
    sheet = inventory.create_sheet('Inventory')
    sheet.append([
        '产品SKU', '云仓发货sku', '圈买库存', '分销库存',
        '成本价', '当前分销优惠价', '产品名称',
    ])
    sheet.append(['DEMO-SKU-001', 'DEMO-WH-001', 4, 8, 10, 12, 'Demo item'])
    inventory.save(inventory_path)
    inventory.close()
    return erp_path, inventory_path


def test_synthetic_sample_files_end_to_end(synthetic_workbooks):
    erp_path, inventory_path = synthetic_workbooks
    seller = detect_seller_from_filename(inventory_path.name)
    assert seller == 'DEMOA_US_US'
    rows = parse_erp_workbook(erp_path)
    inventory = parse_inventory_workbook(inventory_path, seller)

    result = run_audit(rows, {seller: inventory}, today=date(2030, 1, 1))

    assert result['summary']['total_orders'] == 2
    assert result['summary']['total_lines'] == 2
    assert result['summary']['manual_orders'] == 1
    assert result['summary']['pass_orders'] == 1
    assert result['sku_groups']['DEMO-WH-001']['demand'] == 3
    assert result['orders']['DEMO-ORDER-002']['reasons'] == ['单个订单购买数量 ≥ 2']


def test_inventory_parser_keeps_platform_sku_from_multi_sheet_file(synthetic_workbooks):
    _, inventory_path = synthetic_workbooks
    rows = parse_inventory_workbook(inventory_path, 'DEMOA_US_US')

    assert len(rows) == 1
    assert rows[0]['platform_sku'] == 'DEMO-SKU-001'
    assert rows[0]['warehouse_sku'] == 'DEMO-WH-001'
    assert rows[0]['circle_stock'] == 4


def test_synthetic_order_matches_exact_inventory_platform_sku(synthetic_workbooks):
    erp_path, inventory_path = synthetic_workbooks
    rows = parse_erp_workbook(erp_path)
    inventory = parse_inventory_workbook(inventory_path, 'DEMOA_US_US')
    result = run_audit(rows, {'DEMOA_US_US': inventory}, today=date(2030, 1, 1))

    target = result['orders']['DEMO-ORDER-001']
    evidence = target['lines'][0]['evidence']
    assert target['status'] == 'pass'
    assert target['reasons'] == []
    assert evidence['platform_sku_exact_match'] is True
    assert evidence['matched_platform_sku'] == 'DEMO-SKU-001'
    assert evidence['matched_warehouse_sku'] == 'DEMO-WH-001'
    assert evidence['circle_stock'] == 4
    assert evidence['distribution_stock'] == 8

