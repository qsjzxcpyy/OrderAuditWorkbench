# 审单工作台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Chinese order-audit workbench that accepts one ERP `.xlsx` plus the relevant store inventory workbooks, runs the agreed audit rules, presents manual-review reasons interactively, copies review order numbers, and exports a compact results workbook.

**Architecture:** A standalone Python standard-library HTTP server serves a vanilla HTML/CSS/JS frontend and exposes JSON endpoints. The backend parses `.xlsx` files with `openpyxl`, normalizes the known ERP/inventory headers, runs pure audit functions, and generates an `.xlsx` download. The frontend uses a focused operations-workbench layout inspired by the existing multi-package email tool: a compact left rail, upload tray, KPI strip, manual-review list, and detail drawer.

**Tech Stack:** Python 3, `http.server`, `openpyxl`, vanilla JavaScript, CSS.

---

### Task 1: Create project skeleton and pure audit test fixtures

**Files:**
- Create: `./app.py`
- Create: `./audit_logic.py`
- Create: `./exporter.py`
- Create: `./tests/test_audit_logic.py`
- Create: `./tests/conftest.py`

- [ ] **Step 1: Write failing tests for the agreed business rules**

Cover: SKU demand aggregation, circle-stock priority, distribution stock plus price tolerance of `<= 3`, duplicate buyer detection across sellers, quantity `>= 2`, duplicate inventory matches, and order-level aggregation of line failures.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest ./tests/test_audit_logic.py -q`
Expected: FAIL because `audit_logic.py` does not yet expose the audit functions.

- [ ] **Step 3: Implement minimal pure functions**

Define normalized records and functions:
- `normalize_number(value)`;
- `build_inventory_index(rows)`;
- `run_audit(order_rows, inventory_rows_by_store)`;
- `copyable_manual_order_numbers(results)`.

Use `abs(cost_price - discount_price) <= 3` as the price pass condition. If a SKU has more than one matching inventory row, emit `库存表存在重复匹配记录` and do not sum stock.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest ./tests/test_audit_logic.py -q`
Expected: PASS.

---

### Task 2: Add workbook parsing and result export

**Files:**
- Modify: `./app.py`
- Modify: `./exporter.py`
- Create: `./tests/test_workbooks.py`

- [ ] **Step 1: Write failing parser tests against small in-memory `.xlsx` fixtures**

Test automatic sheet/header discovery, ERP fields (`refrence_no_platform`, `platform_seller_id`, `buyer_id`, `sku1`, `warehouse_sku1`, `qty1`), inventory aliases for platform SKU/warehouse SKU/circle stock/distribution stock/cost/discount price, and a clear missing-field error.

- [ ] **Step 2: Run parser tests to verify they fail**

Run: `python -m pytest ./tests/test_workbooks.py -q`
Expected: FAIL because workbook parsing is not implemented.

- [ ] **Step 3: Implement workbook parsing**

Read the first effective sheet by default, scan the first 20 rows for a header containing the required fields, and allow the API to accept an optional `sheet` name. Normalize common header aliases without relying on Chinese console encoding. For each ERP row, collect all numbered item groups (`sku1`, `sku2`, ...), preserving one audit line per item.

- [ ] **Step 4: Implement compact `.xlsx` exporter**

Create one `审单结果` sheet with only audit-related columns and one `审单汇总` sheet with total/manual/pass counts and timestamp. Keep all reasons in one cell separated by `；`. Use Arial font and freeze the header row.

- [ ] **Step 5: Run parser/export tests**

Run: `python -m pytest ./tests/test_workbooks.py -q`
Expected: PASS.

---

### Task 3: Add local HTTP API and static frontend shell

**Files:**
- Modify: `./app.py`
- Create: `./web/index.html`
- Create: `./web/styles.css`
- Create: `./web/app.js`
- Create: `./start.bat`
- Create: `./tests/test_api.py`

- [ ] **Step 1: Write failing API tests**

Cover `GET /`, `POST /api/audit` multipart upload with one ERP plus inventory files, `POST /api/copy-orders`, `GET /api/export/<run_id>`, invalid extension, missing required file, and malformed workbook errors.

- [ ] **Step 2: Run API tests to verify they fail**

Run: `python -m pytest ./tests/test_api.py -q`
Expected: FAIL because the HTTP server and endpoints are not implemented.

- [ ] **Step 3: Implement the API**

Use a bounded in-memory run store for the local app. Enforce `.xlsx` uploads and a 120 MB per-file limit. Return structured JSON with summary, store mapping, results, and per-file warnings. Keep the upload process local; do not send files to external services.

- [ ] **Step 4: Build the frontend shell and interactions**

Implement:
- drag/drop upload zones for ERP and multiple inventory files;
- auto store-name detection with a manual mapping select when uncertain;
- “开始审单” button with busy state;
- KPI strip;
- default manual-review list with all reason tags;
- collapsible pass list;
- store/reason/SKU/order search filters;
- right-side detail drawer with demand/stock/price evidence;
- one-click copy with Clipboard API fallback and visible toast;
- Excel export button;
- reset button;
- keyboard focus styles, reduced-motion handling, and responsive mobile stacking.

Visual direction: ink navy `#13233A`, paper `#F5F7F4`, signal coral `#E86A54`, pass teal `#2C8B78`, warning gold `#C8912E`, slate `#6D7C8E`; use a restrained serif display face stack (`Georgia`, `Songti SC`) only for the title and a clean sans stack for operations text. The signature is a “review docket” card: each manual order has a thin coral status rail and a clipped row of reason tags, echoing a multi-package message thread rather than a generic dashboard.

- [ ] **Step 5: Run API tests and a smoke server check**

Run: `python -m pytest ./tests -q`
Expected: PASS.
Run: `python ./app.py --port 8793`
Expected: server listens on `http://127.0.0.1:8793`.

---

### Task 4: Run the provided sample files end-to-end

**Files:**
- Modify: `./tests/test_sample_files.py`
- Create: `./internal/sample-audit.json` only if needed for debugging; do not commit generated screenshots.

- [ ] **Step 1: Write a sample-file smoke test**

Locate `order-1788335157.xlsx` and the four `店铺*.xlsx` workbooks under `审单文件`, parse the ERP sample and at least the used inventory sheet for each relevant store, assert a nonzero order count, and assert every result has a status and a human-readable reason list when manual.

- [ ] **Step 2: Run it and inspect actual headers**

Run: `python -m pytest ./tests/test_sample_files.py -q -s`
Expected: PASS or a clear field-alias failure that can be corrected without changing the agreed rules.

- [ ] **Step 3: Fix only data-shape compatibility issues**

Do not alter the business rules. Add aliases/number parsing/sheet selection needed by the provided files, then rerun all tests.

- [ ] **Step 4: Browser verification**

Start the server and use Playwright to verify desktop and mobile layouts, upload state, filters, copy toast, detail drawer, export link, and reset behavior. Capture a screenshot for visual review, then remove the generated image.

---

### Task 5: Final verification

**Files:**
- Modify: `./README.md`

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest ./tests -q`
Expected: all tests PASS.

- [ ] **Step 2: Run a syntax check**

Run: `python -m py_compile ./app.py ./audit_logic.py ./exporter.py`
Expected: exit code 0.

- [ ] **Step 3: Write usage instructions**

Document starting the app, the upload sequence, required fields, the agreed audit rules, and where exported files are downloaded.

- [ ] **Step 4: Verify git diff and remove debug artifacts**

Run: `git diff --check; git status --short`
Expected: no whitespace errors and only intentional project files are changed.

