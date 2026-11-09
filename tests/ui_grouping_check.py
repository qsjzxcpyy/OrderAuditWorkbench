"""Exercise SKU grouping with real workbook uploads and the local audit API."""

import io
import os
from pathlib import Path
import sys
from datetime import date, timedelta

import openpyxl
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import STORE_ALIASES


def workbook_bytes(rows):
    workbook = openpyxl.Workbook()
    for row in rows:
        workbook.active.append(row)
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def run():
    store_a, store_b = list(STORE_ALIASES.values())[:2]
    token_a, token_b = list(STORE_ALIASES)[:2]
    special_sku = 'WH-"<>&\''
    soon = str(date.today() + timedelta(days=2))
    later = str(date.today() + timedelta(days=7))
    erp_rows = [
        ['refrence_no_platform', 'platform_seller_id', 'buyer_id', 'date_latest_ship',
         'sku1', 'warehouse_sku1', 'qty1', 'sku2', 'warehouse_sku2', 'qty2'],
        ['112-DEMO-101', store_a, 'buyer-101', soon, 'PLAT-1', 'WH-SHARED', 1],
        ['112-DEMO-102', store_b, 'buyer-102', later, 'PLAT-2', 'WH-SHARED', 1],
        ['112-DEMO-103', store_a, 'buyer-103', soon, 'PLAT-3', 'WH-SHARED', 1, 'PLAT-3', 'WH-SHARED', 1],
        ['112-DEMO-104', store_a, 'buyer-104', soon, 'PLAT-PASS', 'WH-SHARED', 1],
        ['112-DEMO-201', store_a, 'buyer-201', soon, 'PLAT-SOLO', 'WH-SOLO', 1],
        ['112-DEMO-301', store_a, 'buyer-301', soon, 'PLAT-1', 'WH-SHARED', 1, 'PLAT-OTHER', 'WH-OTHER', 1],
        ['112-DEMO-302', store_a, 'buyer-302', soon, 'PLAT-OTHER', 'WH-OTHER', 1, 'PLAT-1', 'WH-SHARED', 1],
        ['112-DEMO-401', store_a, 'buyer-401', soon, 'PLAT-MISSING-1', None, 1],
        ['112-DEMO-402', store_a, 'buyer-402', soon, 'PLAT-MISSING-2', None, 1],
        ['112-DEMO-501', store_a, 'buyer-501', soon, 'PLAT-CASE', 'wh-shared', 1],
        ['112-DEMO-601', store_a, 'buyer-601', soon, 'PLAT-SPECIAL-1', special_sku, 1],
        ['112-DEMO-602', store_a, 'buyer-602', soon, 'PLAT-SPECIAL-2', special_sku, 1],
    ]
    inventory_header = ['platformsku', 'warehousesku', '圈买库存', '分销库存', '成本价', '当前分销优惠价']
    inventory_a = [inventory_header,
        ['PLAT-1', 'WH-SHARED', 0, 100, 10, 20],
        ['PLAT-3', 'WH-SHARED', 0, 100, 10, 20],
        ['PLAT-PASS', 'WH-SHARED', 100, 100, 10, 10],
        ['PLAT-SOLO', 'WH-SOLO', 0, 4, 10, 10],
        ['PLAT-OTHER', 'WH-OTHER', 0, 100, 10, 20],
        ['PLAT-CASE', 'wh-shared', 0, 100, 10, 20],
        ['PLAT-SPECIAL-1', special_sku, 0, 100, 10, 20],
        ['PLAT-SPECIAL-2', special_sku, 0, 100, 10, 20],
    ]
    inventory_b = [inventory_header, ['PLAT-2', 'WH-SHARED', 0, 100, 10, 20]]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel='chrome')
        context = browser.new_context(permissions=['clipboard-read', 'clipboard-write'], viewport={'width': 1440, 'height': 1000})
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(os.environ.get('AUDIT_TEST_URL', 'http://127.0.0.1:8793'), wait_until='networkidle')
        page.locator('#erp-file').set_input_files({'name': 'demo-orders.xlsx', 'mimeType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'buffer': workbook_bytes(erp_rows)})
        page.locator('#inventory-file').set_input_files([
            {'name': f'{token_a}-inventory.xlsx', 'mimeType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'buffer': workbook_bytes(inventory_a)},
            {'name': f'{token_b}-inventory.xlsx', 'mimeType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'buffer': workbook_bytes(inventory_b)},
        ])
        page.locator('#audit-button').click()
        expect(page.locator('#kpi-manual')).to_have_text('11')
        expect(page.locator('#kpi-pass')).to_have_text('1')
        groups = page.locator('#manual-list > .sku-group')
        expect(groups).to_have_count(2)
        group = groups.first
        expect(group.locator('.group-sku')).to_have_text('WH-SHARED')
        expect(group.locator('.group-order-count')).to_have_text('3 单')
        expect(group.locator('.group-quantity')).to_have_text('4 件')
        expect(group.locator('.group-members')).to_be_hidden()
        # Group members are neither repeated at top level nor mixed with pass orders.
        expect(page.locator('#manual-list > .order-card')).to_have_count(6)
        manual_numbers = page.locator('#manual-list .order-card').evaluate_all('cards => cards.map(card => card.dataset.orderNo)')
        assert len(manual_numbers) == len(set(manual_numbers)) == 11
        assert '112-DEMO-104' not in manual_numbers

        group.locator('[data-copy-group]').click()
        expect(page.locator('#toast')).to_contain_text('3 个订单号')
        assert page.evaluate('navigator.clipboard.readText()') == '112-DEMO-101 112-DEMO-102 112-DEMO-103'
        expect(group.locator('.group-members')).to_be_hidden()
        group.locator('.group-sku').click()
        assert page.evaluate('navigator.clipboard.readText()') == 'WH-SHARED'
        expect(group.locator('.group-members')).to_be_hidden()

        group.locator('.sku-group-summary').scroll_into_view_if_needed()
        page.evaluate("window.scrollTo({top: window.scrollY, behavior: 'instant'})")
        anchor_y = group.locator('.sku-group-summary').bounding_box()['y']
        next_y = page.locator('#manual-list > .order-card').first.bounding_box()['y']
        group.locator('.sku-group-summary').click()
        expect(group.locator('.group-members')).to_be_visible()
        page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
        group_box = group.locator('.sku-group-summary').bounding_box()
        members_box = group.locator('.group-members').bounding_box()
        assert members_box['y'] + members_box['height'] <= group_box['y'] + 1
        assert abs(group_box['y'] - anchor_y) < 3
        assert abs(page.locator('#manual-list > .order-card').first.bounding_box()['y'] - next_y) < 3
        first_order = group.locator('.order-card').first
        expect(first_order.locator('.order-detail')).to_be_hidden()
        first_order.locator('summary').click()
        expect(first_order.locator('.order-detail')).to_be_visible()
        expect(group.locator('.group-members')).to_be_visible()
        expect(first_order.locator('.reason-list')).to_contain_text('差异超过 3')
        page.locator('#manual-toggle').click()
        expect(page.locator('#manual-content')).to_be_hidden()
        page.locator('#manual-toggle').click()
        expect(group.locator('.group-members')).to_be_visible()
        group.locator('.sku-group-summary').press('Enter')
        expect(group.locator('.group-members')).to_be_hidden()
        group.locator('[data-copy-group]').press('Enter')
        assert page.evaluate('navigator.clipboard.readText()') == '112-DEMO-101 112-DEMO-102 112-DEMO-103'
        expect(group.locator('.group-members')).to_be_hidden()

        # Group membership and copied IDs follow the active filters.
        page.locator('#store-filter').select_option(store_a)
        group = page.locator('#manual-list > .sku-group').first
        expect(group.locator('.group-order-count')).to_have_text('2 单')
        expect(group.locator('.group-quantity')).to_have_text('3 件')
        group.locator('[data-copy-group]').click()
        assert page.evaluate('navigator.clipboard.readText()') == '112-DEMO-101 112-DEMO-103'
        page.locator('#store-filter').select_option('')
        page.locator('#presale-filter').select_option('presale')
        expect(page.locator('#manual-list > .sku-group')).to_have_count(0)
        expect(page.locator('#manual-list > .order-card')).to_have_count(1)
        expect(page.locator('#manual-list .order-number')).to_have_text('112-DEMO-102')
        page.locator('#presale-filter').select_option('')
        page.locator('#reason-filter').select_option(label='单个订单购买数量 ≥ 2')
        expect(page.locator('#manual-list > .sku-group')).to_have_count(0)
        expect(page.locator('#manual-list .order-number')).to_have_text('112-DEMO-103')
        page.locator('#reason-filter').select_option('')
        page.locator('#search-input').fill('WH-SHARED')
        group = page.locator('#manual-list > .sku-group').first
        expect(group.locator('.group-order-count')).to_have_text('3 单')
        expect(page.locator('#manual-list > .order-card')).to_have_count(3)
        page.locator('#search-input').fill('112-DEMO-102')
        expect(page.locator('#manual-list > .sku-group')).to_have_count(0)
        expect(page.locator('#manual-list > .order-card')).to_have_count(1)
        page.locator('#search-input').fill('no-such-order')
        expect(page.locator('#manual-empty')).to_be_visible()
        page.locator('#search-input').fill('')
        special_group = page.locator('#manual-list > .sku-group').nth(1)
        expect(special_group.locator('.group-sku')).to_have_text(special_sku)
        special_group.locator('.group-sku').click()
        assert page.evaluate('navigator.clipboard.readText()') == special_sku
        special_group.locator('[data-copy-group]').click()
        assert page.evaluate('navigator.clipboard.readText()') == '112-DEMO-601 112-DEMO-602'

        group = page.locator('#manual-list > .sku-group').first
        group.locator('.sku-group-summary').click()
        group.locator('.order-card').first.locator('summary').click()
        artifacts = ROOT / 'tests' / 'artifacts'
        artifacts.mkdir(exist_ok=True)
        page.locator('.review-panel').screenshot(path=str(artifacts / 'audit-sku-groups-desktop.png'))
        for width in [768, 390]:
            page.set_viewport_size({'width': width, 'height': 1000})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), page.evaluate(
                "[...document.querySelectorAll('body *')].filter(e => e.getBoundingClientRect().right > innerWidth + 1).map(e => ({tag:e.tagName, cls:e.className, right:e.getBoundingClientRect().right})).slice(0, 12)"
            )
            group.locator('[data-copy-group]').click()
            assert page.evaluate('navigator.clipboard.readText()') == '112-DEMO-101 112-DEMO-102 112-DEMO-103'
        page.locator('.review-panel').screenshot(path=str(artifacts / 'audit-sku-groups-mobile.png'))
        page.locator('#pass-toggle').click()
        expect(page.locator('#pass-orders > .order-card')).to_have_count(1)
        page.locator('#copy-button').click()
        expect(page.locator('#toast')).to_have_text('已复制人工订单号')
        all_copied = page.evaluate('navigator.clipboard.readText()').split(' ')
        assert len(all_copied) == len(set(all_copied)) == 11
        assert '112-DEMO-104' not in all_copied
        page.locator('#reset-button').click()
        expect(page.locator('#manual-list .sku-group')).to_have_count(0)
        expect(page.locator('#manual-list .order-card')).to_have_count(0)
        assert not errors, errors
        browser.close()
    print('SKU grouping, filtered copy, nested details, escaping and responsive checks passed')


if __name__ == '__main__':
    run()
