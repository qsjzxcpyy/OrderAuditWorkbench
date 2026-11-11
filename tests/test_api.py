from pathlib import Path
from io import BytesIO
import http.client
import json
import sys
import threading
import time

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_server, detect_seller_from_filename


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
def running_server():
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
def test_unrecognized_order_store_is_manual_without_stopping_other_orders(running_server, monkeypatch, tmp_path, seller):
    monkeypatch.setattr('app.OUTPUT', tmp_path)
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
