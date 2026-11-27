from pathlib import Path
from io import BytesIO
from datetime import date, timedelta
import http.client
import json
import sys
import threading
import time

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import RUNS, create_server, detect_seller_from_filename


def workbook_bytes(rows, sheet='Data'):
    path = Path(__file__).parent / '_fixture.xlsx'
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    for row in rows:
        ws.append(row)
    wb.save(path)
    data = path.read_bytes()
    path.unlink()
    return data


def multipart(parts):
    boundary = '----order-audit-test'
    chunks = []
    for name, filename, content in parts:
        chunks.extend([
            f'--{boundary}\r\n'.encode(),
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode(),
            b'Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n',
            content,
            b'\r\n',
        ])
    chunks.append(f'--{boundary}--\r\n'.encode())
    return b''.join(chunks), f'multipart/form-data; boundary={boundary}'


@pytest.fixture
def running_server(monkeypatch, tmp_path):
    monkeypatch.setattr('app.OUTPUT', tmp_path)
    server = create_server(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    thread.join(timeout=2)


def test_detect_store_from_filename():
    assert detect_seller_from_filename('店铺DEMOA上架产品.xlsx') == 'DEMOA_US_US'
    assert detect_seller_from_filename('店铺DEMOD上架产品.xlsx') == 'DEMOD_US'
    assert detect_seller_from_filename('anything.xlsx') is None


def test_audit_api_returns_results(running_server):
    erp = workbook_bytes([
        ['refrence_no_platform', 'platform_seller_id', 'buyer_id', 'sku1', 'warehouse_sku1', 'qty1'],
        ['ORDER-1', 'DEMOA_US_US', 'buyer-1', 'AMZ-1', 'WH-1', 1],
    ])
    inventory = workbook_bytes([
        ['亚马逊平台sku', '云仓发货sku', '圈买库存', '分销库存', '成本价', '当前分销优惠价价'],
        ['AMZ-1', 'WH-1', 1, 0, 10, 10],
    ])
    body, content_type = multipart([
        ('erp', 'orders.xlsx', erp),
        ('inventory', '店铺DEMOA上架产品.xlsx', inventory),
    ])
    host, port = running_server.server_address
    connection = http.client.HTTPConnection(host, port)
    connection.request('POST', '/api/audit', body=body, headers={
        'Content-Type': content_type,
        'Content-Length': str(len(body)),
    })
    response = connection.getresponse()
    payload = json.loads(response.read())
    assert response.status == 200
    assert payload['summary']['total_orders'] == 1
    assert payload['orders'][0]['status'] == 'pass'
    assert payload['run_id']


@pytest.mark.parametrize('seller', ['NEW_STORE_US', ''])
def test_unrecognized_order_store_is_manual_without_stopping_other_orders(running_server, seller):
    erp = workbook_bytes([
        ['refrence_no_platform', 'platform_seller_id', 'buyer_id', 'sku1', 'warehouse_sku1', 'qty1'],
        ['UNKNOWN-STORE', seller, 'buyer-unknown', 'AMZ-1', 'WH-1', 1],
        ['KNOWN-PASS', 'DEMOA_US_US', 'buyer-pass', 'AMZ-1', 'WH-1', 1],
        ['KNOWN-MANUAL', 'DEMOA_US_US', 'buyer-manual', 'AMZ-2', 'WH-2', 2],
    ])
    inventory = workbook_bytes([
        ['亚马逊平台sku', '云仓发货sku', '圈买库存', '分销库存', '成本价', '当前分销优惠价价'],
        ['AMZ-1', 'WH-1', 10, 0, 10, 10],
        ['AMZ-2', 'WH-2', 10, 0, 10, 10],
    ])
    body, content_type = multipart([
        ('erp', 'orders.xlsx', erp),
        ('inventory', '店铺DEMOA上架产品.xlsx', inventory),
    ])
    host, port = running_server.server_address
    connection = http.client.HTTPConnection(host, port)
    connection.request('POST', '/api/audit', body=body, headers={'Content-Type': content_type})
    response = connection.getresponse()
    payload = json.loads(response.read())

    assert response.status == 200, payload
    assert payload['summary'] == {
        'total_orders': 3, 'manual_orders': 2, 'pass_orders': 1,
        'total_lines': 3, 'manual_lines': 2,
    }
    orders = {item['order_no']: item for item in payload['orders']}
    unknown = orders['UNKNOWN-STORE']
    assert unknown['seller'] == seller
    assert unknown['status'] == 'manual'
    assert unknown['reasons'] == ['订单所属店铺未识别，需要人工处理']
    assert unknown['lines'][0]['reasons'] == ['订单所属店铺未识别，需要人工处理']
    assert unknown['lines'][0]['evidence']['circle_stock'] is None
    assert orders['KNOWN-PASS']['status'] == 'pass'
    assert orders['KNOWN-PASS']['reasons'] == []
    assert orders['KNOWN-MANUAL']['status'] == 'manual'
    assert '单个订单购买数量 ≥ 2' in orders['KNOWN-MANUAL']['reasons']
    assert payload['copyable_orders'] == 'UNKNOWN-STORE KNOWN-MANUAL'

    connection.request('GET', f"/api/export/{payload['run_id']}")
    exported = connection.getresponse()
    assert exported.status == 200
    workbook = openpyxl.load_workbook(BytesIO(exported.read()), read_only=True, data_only=True)
    try:
        rows = list(workbook['审单结果'].iter_rows(min_row=2, values_only=True))
        unknown_row = next(row for row in rows if 'UNKNOWN-STORE' in row)
        assert any('订单所属店铺未识别，需要人工处理' in str(value) for value in unknown_row)
    finally:
        workbook.close()
        connection.close()


def test_missing_inventory_for_recognized_store_still_returns_validation_error(running_server):
    erp = workbook_bytes([
        ['refrence_no_platform', 'platform_seller_id', 'buyer_id', 'sku1', 'warehouse_sku1', 'qty1'],
        ['UNKNOWN', 'NEW_STORE_US', 'buyer-unknown', 'AMZ-1', 'WH-1', 1],
        ['KNOWN', 'DEMOA_US_US', 'buyer-1', 'AMZ-1', 'WH-1', 1],
    ])
    body, content_type = multipart([('erp', 'orders.xlsx', erp)])
    host, port = running_server.server_address
    connection = http.client.HTTPConnection(host, port)
    try:
        connection.request('POST', '/api/audit', body=body, headers={'Content-Type': content_type})
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 400
        assert payload['error']['message'] == '缺少这些有订单店铺的库存文件：DEMOA_US_US'
    finally:
        connection.close()


def test_adjusting_presale_days_updates_only_presale_and_keeps_export_in_sync(running_server):
    today = date.today()
    erp = workbook_bytes([
        ['refrence_no_platform', 'platform_seller_id', 'buyer_id', 'sku1', 'warehouse_sku1', 'qty1', 'date_latest_ship'],
        ['FIVE', 'DEMOA_US_US', 'buyer-1', 'P1', 'W1', 1, today + timedelta(days=5)],
        ['SIX', 'DEMOA_US_US', 'buyer-2', 'P1', 'W1', 1, today + timedelta(days=6)],
        ['SEVEN', 'DEMOA_US_US', 'buyer-3', 'P1', 'W1', 1, today + timedelta(days=7)],
        ['PRICE', 'DEMOA_US_US', 'buyer-4', 'P2', 'W2', 1, today + timedelta(days=5)],
        ['UNKNOWN', 'DEMO_UNKNOWN', 'buyer-5', 'P3', 'W3', 1, today + timedelta(days=6)],
    ])
    inventory = workbook_bytes([
        ['亚马逊平台sku', '云仓发货sku', '圈买库存', '分销库存', '成本价', '当前分销优惠价价'],
        ['P1', 'W1', 10, 0, 10, 10],
        ['P2', 'W2', 0, 10, 10, 16],
    ])
    body, content_type = multipart([('erp', 'orders.xlsx', erp), ('inventory', 'DEMOA.xlsx', inventory)])
    connection = http.client.HTTPConnection(*running_server.server_address)
    try:
        connection.request('POST', '/api/audit', body=body, headers={'Content-Type': content_type})
        response = connection.getresponse()
        initial = json.loads(response.read())
        assert response.status == 200, initial
        assert initial['presale_days'] == 6
        assert initial['copyable_orders'] == 'SIX SEVEN PRICE UNKNOWN'
        run_id = initial['run_id']

        def adjust(days, status=200):
            connection.request('POST', f'/api/audit/{run_id}/presale', body=json.dumps({'presale_days': days}),
                               headers={'Content-Type': 'application/json'})
            response = connection.getresponse()
            payload = json.loads(response.read())
            assert response.status == status, payload
            return payload

        assert adjust(5)['copyable_orders'] == 'FIVE SIX SEVEN PRICE UNKNOWN'
        updated = adjust(7)
        assert updated['copyable_orders'] == 'SEVEN PRICE UNKNOWN'
        assert updated['summary']['pass_orders'] == 2
        assert updated['summary']['manual_orders'] == 3
        assert updated['summary']['manual_lines'] == 3
        orders = {item['order_no']: item for item in updated['orders']}
        assert orders['FIVE']['status'] == 'pass'
        assert orders['SIX']['days_until_latest_ship'] == 6
        assert orders['SEVEN']['is_presale'] is True
        assert '7 天' in orders['SEVEN']['reasons'][0]
        assert orders['PRICE']['is_presale'] is False
        assert orders['PRICE']['reasons'] == ['成本价与分销优惠价差异超过 3']
        assert orders['UNKNOWN']['reasons'] == ['订单所属店铺未识别，需要人工处理']
        adjust(0, 400)

        connection.request('GET', f'/api/export/{run_id}')
        response = connection.getresponse()
        assert response.status == 200
        workbook = openpyxl.load_workbook(BytesIO(response.read()), read_only=True, data_only=True)
        try:
            header, *data = workbook['审单结果'].values
            rows = {row[0]: dict(zip(header, row)) for row in data}
            assert rows['FIVE']['审单状态'] == '可放行'
            assert rows['SIX']['距最晚发货天数'] == 6
            assert rows['SEVEN']['审单状态'] == '人工处理'
            assert '7 天' in rows['SEVEN']['人工处理原因']
            assert rows['PRICE']['人工处理原因'] == orders['PRICE']['reasons'][0]
        finally:
            workbook.close()

        restored = adjust(6)
        assert restored['copyable_orders'] == initial['copyable_orders']
        assert restored['orders'] == initial['orders']

        RUNS.pop(run_id)
        connection.request('GET', f'/api/export/{run_id}')
        response = connection.getresponse()
        assert response.status == 200
        assert response.read().startswith(b'PK')
    finally:
        connection.close()


@pytest.mark.parametrize("length", ["-1", "abc", "1.5", "", "9" * 5000])
def test_invalid_content_length_is_rejected_before_read(length):
    from types import SimpleNamespace
    from app import Handler

    class UnreadableBody:
        def read(self, length):
            pytest.fail("invalid length must not read the request body")

    handler = SimpleNamespace(path="/api/audit", headers={"Content-Length": length},
                              rfile=UnreadableBody(), _json=lambda status, body: status)
    assert Handler.do_POST(handler) == 400
