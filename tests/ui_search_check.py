"""Verify partial warehouse SKU searches with fictional workbook uploads."""

import argparse
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import threading

import openpyxl
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app


def workbook_bytes(rows):
    workbook = openpyxl.Workbook()
    for row in rows:
        workbook.active.append(row)
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def verify(url):
    token, seller = next(iter(app.STORE_ALIASES.items()))
    erp = workbook_bytes([
        ['refrence_no_platform', 'platform_seller_id', 'buyer_id', 'sku1', 'warehouse_sku1', 'qty1'],
        ['DEMO-MANUAL-A', seller, 'demo-a', 'PLATFORM-A', 'W2339S00001', 2],
        ['DEMO-MANUAL-B', seller, 'demo-b', 'PLATFORM-A', 'W2339S00001', 2],
        ['DEMO-PASS-C', seller, 'demo-c', 'PLATFORM-C', 'W2339P00002', 1],
        ['DEMO-OTHER-D', seller, 'demo-d', 'PLATFORM-D', 'W8000S00003', 2],
        ['DEMO-OTHER-E', seller, 'demo-e', 'PLATFORM-E', 'W9000P00004', 1],
    ])
    inventory = workbook_bytes([
        ['platformsku', 'warehousesku', '圈买库存', '分销库存', '成本价', '当前分销优惠价'],
        ['PLATFORM-A', 'W2339S00001', 100, 100, 10, 10],
        ['PLATFORM-C', 'W2339P00002', 100, 100, 10, 10],
        ['PLATFORM-D', 'W8000S00003', 100, 100, 10, 10],
        ['PLATFORM-E', 'W9000P00004', 100, 100, 10, 10],
    ])
    mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel='chrome')
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url, wait_until='networkidle')
        page.locator('#erp-file').set_input_files({'name': 'demo-orders.xlsx', 'mimeType': mime, 'buffer': erp})
        page.locator('#inventory-file').set_input_files({'name': f'{token}-inventory.xlsx', 'mimeType': mime, 'buffer': inventory})
        with page.expect_response('**/api/audit') as response:
            page.locator('#audit-button').click()
        assert response.value.status == 200
        expect(page.locator('#kpi-total')).to_have_text('5')
        expect(page.locator('#manual-section-count')).to_have_text('3')
        expect(page.locator('#pass-section-count')).to_have_text('2')
        page.locator('#pass-toggle').click()
        search = page.locator('#search-input')
        for query in ['2339', ' w2339 ', 'S00001']:
            search.fill(query)
            expected_pass = 0 if query == 'S00001' else 1
            # Match both grouped manual orders by warehouse SKU alone, even
            # though the platform SKUs and order numbers lack the search term.
            expect(page.locator('#manual-list .order-card')).to_have_count(2)
            expect(page.locator('#manual-list .group-order-count')).to_have_text('2 单')
            expect(page.locator('#pass-orders .order-card')).to_have_count(expected_pass)
            expect(page.locator('#manual-section-count')).to_have_text('2')
            expect(page.locator('#pass-section-count')).to_have_text(str(expected_pass))
        search.fill('not-present')
        expect(page.locator('#manual-list .order-card')).to_have_count(0)
        expect(page.locator('#manual-section-count')).to_have_text('0')
        expect(page.locator('#pass-section-count')).to_have_text('0')
        search.fill('')
        expect(page.locator('#manual-section-count')).to_have_text('3')
        expect(page.locator('#pass-section-count')).to_have_text('2')
        search.fill('demo-c')
        expect(page.locator('#pass-orders .order-number')).to_have_text('DEMO-PASS-C')
        expect(page.locator('#manual-section-count')).to_have_text('0')
        expect(page.locator('#pass-section-count')).to_have_text('1')
        expect(page.locator('#kpi-total')).to_have_text('5')
        assert not errors, errors
        browser.close()
    print('PASS: partial warehouse SKU, case/whitespace, grouped orders, pass orders, counts, clear and buyer search')


def run(url=None):
    if url:
        verify(url)
        return
    with tempfile.TemporaryDirectory(prefix='audit-search-') as temp:
        app.OUTPUT = Path(temp)
        server = app.create_server(0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            verify(f'http://127.0.0.1:{server.server_address[1]}')
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url')
    run(parser.parse_args().url)
