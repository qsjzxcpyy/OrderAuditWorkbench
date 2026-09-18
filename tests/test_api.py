from pathlib import Path
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
    assert detect_seller_from_filename('店铺Thryvix上架产品.xlsx') == 'THRYVIX_US_US'
    assert detect_seller_from_filename('店铺ZEIINPA上架产品.xlsx') == 'ZEIINPA_US'
    assert detect_seller_from_filename('anything.xlsx') is None


def test_audit_api_returns_results(running_server):
    erp = workbook_bytes([
        ['refrence_no_platform', 'platform_seller_id', 'buyer_id', 'sku1', 'warehouse_sku1', 'qty1'],
        ['ORDER-1', 'THRYVIX_US_US', 'buyer-1', 'AMZ-1', 'WH-1', 1],
    ])
    inventory = workbook_bytes([
        ['亚马逊平台sku', '云仓发货sku', '圈买库存', '分销库存', '成本价', '当前分销优惠价价'],
        ['AMZ-1', 'WH-1', 1, 0, 10, 10],
    ])
    body, content_type = multipart([
        ('erp', 'orders.xlsx', erp),
        ('inventory', '店铺Thryvix上架产品.xlsx', inventory),
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
