from pathlib import Path
import sys

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbooks import WorkbookDataError, parse_erp_workbook, parse_inventory_workbook


def make_workbook(path, rows, sheet='Data'):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    for row in rows:
        ws.append(row)
    wb.save(path)


def test_parses_numbered_erp_lines(tmp_path):
    path = tmp_path / 'orders.xlsx'
    make_workbook(path, [
        ['refrence_no_platform', 'platform_seller_id', 'buyer_id', 'sku1', 'warehouse_sku1', 'qty1', 'sku2', 'warehouse_sku2', 'qty2'],
        ['ORDER-1', 'THRYVIX_US_US', 'buyer', 'AMZ-1', 'WH-1', 1, 'AMZ-2', 'WH-2', 2],
    ])
    rows = parse_erp_workbook(path)
    assert len(rows) == 2
    assert rows[1]['warehouse_sku'] == 'WH-2'
    assert rows[1]['qty'] == 2


def test_parses_inventory_aliases(tmp_path):
    path = tmp_path / 'inventory.xlsx'
    make_workbook(path, [
        [None, '父体SKU', '亚马逊平台sku', '云仓发货sku', '圈买库存', '分销库存', '成本价', '当前分销优惠价价', '产品名称'],
        [None, 'PARENT', 'AMZ-1', 'WH-1', 4, 6, 10, 12.5, 'Desk'],
    ], sheet='产品信息表')
    rows = parse_inventory_workbook(path, 'THRYVIX_US_US')
    assert rows[0]['platform_sku'] == 'AMZ-1'
    assert rows[0]['circle_stock'] == 4
    assert rows[0]['discount_price'] == 12.5


def test_missing_required_field_is_explicit(tmp_path):
    path = tmp_path / 'bad.xlsx'
    make_workbook(path, [['sku1'], ['AMZ-1']])
    with pytest.raises(WorkbookDataError, match='ERP 文件缺少字段'):
        parse_erp_workbook(path)


def test_parses_latest_ship_date_field(tmp_path):
    path = tmp_path / 'orders.xlsx'
    make_workbook(path, [
        ['refrence_no_platform', 'platform_seller_id', 'buyer_id', 'date_latest_ship', 'sku1', 'warehouse_sku1', 'qty1'],
        ['ORDER-1', 'THRYVIX_US_US', 'buyer', '2026-09-05 14:59:59', 'AMZ-1', 'WH-1', 1],
    ])
    rows = parse_erp_workbook(path)
    assert rows[0]['date_latest_ship'] == '2026-09-05 14:59:59'


def test_parses_presale_fields_for_audit_rules(tmp_path):
    path = tmp_path / 'orders.xlsx'
    make_workbook(path, [
        ['refrence_no_platform', 'platform_seller_id', 'buyer_id', 'custom_order_type', 'order_desc', 'sku1', 'warehouse_sku1', 'qty1'],
        ['PRESALE-1', 'THRYVIX_US_US', 'buyer', 'Pre-sale', 'pre-order item', 'AMZ-1', 'WH-1', 1],
    ])
    rows = parse_erp_workbook(path)
    assert rows[0]['custom_order_type'] == 'Pre-sale'
    assert rows[0]['order_desc'] == 'pre-order item'



def test_parser_prefers_buyer_id_when_empty_platform_buyer_id_is_also_present(tmp_path):
    path = tmp_path / 'orders.xlsx'
    make_workbook(path, [
        ['refrence_no_platform', 'platform_seller_id', 'platform_buyer_id', 'buyer_id', 'sku1', 'warehouse_sku1', 'qty1'],
        ['ORDER-1', 'THRYVIX_US_US', None, 'buyer-1', 'AMZ-1', 'WH-1', 1],
    ])

    rows = parse_erp_workbook(path)

    assert rows[0]['buyer_id'] == 'buyer-1'

def test_parses_product_sku_as_platform_sku_alias(tmp_path):
    path = tmp_path / 'inventory.xlsx'
    make_workbook(path, [
        [None, '产品SKU', '云仓发货sku', '圈买库存', '分销库存', '成本价', '当前分销优惠价价', '产品名称'],
        [None, 'W2339S00157-th-zy', 'W2339S00157', 37, 67, 255, 369, 'Sofa'],
    ], sheet='Data')
    rows = parse_inventory_workbook(path, 'THRYVIX_US_US')
    assert rows[0]['platform_sku'] == 'W2339S00157-th-zy'
    assert rows[0]['warehouse_sku'] == 'W2339S00157'
