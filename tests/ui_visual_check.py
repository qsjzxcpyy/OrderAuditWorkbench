import os
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "tests" / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
    page.goto(os.environ.get("AUDIT_TEST_URL", "http://127.0.0.1:8793"), wait_until="networkidle")
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
    assert page.locator("#manual-empty").is_hidden()
    manual_toggle = page.locator("#manual-toggle")
    assert manual_toggle.get_attribute("aria-expanded") == "true"
    assert page.locator("#manual-content").is_visible()
    manual_toggle.click()
    assert manual_toggle.get_attribute("aria-expanded") == "false"
    assert page.locator("#manual-content").is_hidden()
    assert page.locator("#manual-section-count").is_visible()
    page.locator("#search-input").fill("112")
    assert page.locator("#manual-content").is_hidden()
    page.locator("#search-input").fill("")
    assert page.locator("#manual-content").is_hidden()
    manual_toggle.click()
    assert page.locator("#manual-list .order-card").first.is_visible()
    pass_orders = page.locator("#pass-orders")
    assert pass_orders.is_hidden()
    page.locator("#pass-toggle").click()
    assert page.locator("#pass-orders .order-card").count() == 2
    assert pass_orders.is_visible()
    page.locator("#pass-toggle").click()
    assert pass_orders.is_hidden()
    first_order = page.locator("#manual-list .order-card").first
    assert first_order.locator(".order-detail").is_hidden()
    first_order.locator("summary").scroll_into_view_if_needed()
    page.evaluate("window.scrollTo({top: window.scrollY, behavior: 'instant'})")
    summary_y = first_order.locator("summary").bounding_box()["y"]
    next_order_y = page.locator("#manual-list .order-card").nth(1).bounding_box()["y"]
    first_order.locator("summary").click()
    assert first_order.locator(".order-detail").is_visible()
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    summary_box = first_order.locator("summary").bounding_box()
    detail_box = first_order.locator(".order-detail").bounding_box()
    assert detail_box["y"] + detail_box["height"] <= summary_box["y"] + 1
    assert abs(summary_box["y"] - summary_y) < 3
    assert abs(page.locator("#manual-list .order-card").nth(1).bounding_box()["y"] - next_order_y) < 3
    assert first_order.locator(".summary-sku-platform").inner_text() == "W3434P080023-ZE-HR"
    assert first_order.locator(".summary-sku-warehouse").inner_text() == "W3434P080023"
    assert first_order.locator(".sku-identity-platform strong").inner_text() == "W3434P080023-ZE-HR"
    assert first_order.locator(".sku-identity-warehouse strong").inner_text() == "W3434P080023"
    sku_font = first_order.locator(".sku-identity-warehouse strong").evaluate("e => parseFloat(getComputedStyle(e).fontSize)")
    value_font = first_order.locator(".evidence-pill strong").first.evaluate("e => parseFloat(getComputedStyle(e).fontSize)")
    assert sku_font == 13
    assert value_font == 14
    assert value_font > sku_font
    first_order.locator(".sku-identity-warehouse strong").click()
    page.wait_for_function("document.querySelector('#toast').textContent.includes('\u590d\u5236 SKU')")

    manual_toggle.click()
    assert first_order.locator(".order-detail").is_hidden()
    manual_toggle.click()
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
    # Re-rendering must not stack click handlers or toggle a row more than once.
    for query in ["112", "", "112", ""]:
        page.locator("#search-input").fill(query)
    first_order.locator("summary").click()
    assert first_order.locator(".order-detail").is_visible()
    first_order.locator("summary").press("Enter")
    assert first_order.locator(".order-detail").is_hidden()
    page.locator("#pass-toggle").click()
    pass_order = page.locator("#pass-orders .order-card").first
    pass_order.locator("summary").click()
    assert pass_order.locator(".order-detail").bounding_box()["y"] >= pass_order.locator("summary").bounding_box()["y"]

    mobile = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
    mobile.goto(os.environ.get("AUDIT_TEST_URL", "http://127.0.0.1:8793"), wait_until="networkidle")
    assert mobile.locator(".workflow-rail").is_visible()
    assert mobile.locator(".filter-bar").is_visible()
    mobile.locator("#demo-button").click()
    mobile.locator("#manual-toggle").click()
    assert mobile.locator("#manual-content").is_hidden()
    mobile.locator("#manual-toggle").click()
    assert mobile.locator("#manual-list .order-card").first.is_visible()
    mobile_order = mobile.locator("#manual-list .order-card").first
    mobile_order.locator("summary").click()
    assert mobile_order.locator(".order-detail").bounding_box()["y"] < mobile_order.locator("summary").bounding_box()["y"]
    assert mobile_order.locator(".summary-sku-warehouse").is_visible()
    assert mobile.evaluate("document.documentElement.scrollWidth <= innerWidth")
    mobile.screenshot(path=str(ARTIFACTS / "audit-workbench-mobile-expanded.png"), full_page=True)
    mobile.locator("#manual-toggle").click()
    mobile.locator("#reset-button").click()
    assert mobile.locator("#manual-toggle").get_attribute("aria-expanded") == "true"
    assert mobile.locator("#manual-empty").is_visible()
    mobile.screenshot(path=str(ARTIFACTS / "audit-workbench-mobile.png"), full_page=True)
    browser.close()

print("ui checks passed")

