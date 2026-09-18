from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "tests" / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
    page.goto("http://127.0.0.1:8793", wait_until="networkidle")
    assert page.locator("h1").inner_text() == "审单工作台"
    assert page.locator(".workflow-rail").is_visible()
    assert page.locator(".step-card").count() == 2
    page.screenshot(path=str(ARTIFACTS / "audit-workbench-initial.png"), full_page=True)

    page.locator("#demo-button").click()
    page.wait_for_timeout(250)
    assert page.locator("#kpi-total").inner_text() == "5"
    assert page.locator("#kpi-manual").inner_text() == "3"
    assert page.locator("#kpi-pass").inner_text() == "2"
    assert page.locator("#manual-list .order-card").count() == 3
    pass_orders = page.locator("#pass-orders")
    assert pass_orders.is_hidden()
    page.locator("#pass-toggle").click()
    assert page.locator("#pass-orders .order-card").count() == 2
    assert pass_orders.is_visible()
    page.locator("#pass-toggle").click()
    assert pass_orders.is_hidden()
    first_order = page.locator("#manual-list .order-card").first
    assert first_order.locator(".order-detail").is_hidden()
    first_order.locator("summary").click()
    assert first_order.locator(".order-detail").is_visible()
    assert first_order.locator(".reason-list li").count() == 2
    assert "\u5708\u4e70\u5e93\u5b58\u4e0d\u8db3" in first_order.locator(".reason-list").inner_text()
    copied_number = first_order.locator('.order-number')
    copied_number.click()
    page.wait_for_function("document.querySelector('#toast').textContent.includes('\u5df2\u590d\u5236\u8ba2\u5355\u53f7')")
    page.screenshot(path=str(ARTIFACTS / "audit-workbench-results.png"), full_page=True)
    second_order = page.locator("#manual-list .order-card").nth(1)
    second_order.locator("summary").click()
    assert second_order.locator(".order-detail").is_visible()
    assert first_order.locator(".order-detail").is_hidden()

    mobile = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
    mobile.goto("http://127.0.0.1:8793", wait_until="networkidle")
    assert mobile.locator(".workflow-rail").is_visible()
    assert mobile.locator(".filter-bar").is_visible()
    mobile.screenshot(path=str(ARTIFACTS / "audit-workbench-mobile.png"), full_page=True)
    browser.close()

print("ui checks passed")

