from __future__ import annotations

import argparse
import json
import mimetypes
import re
import tempfile
import threading
import uuid
from email.parser import BytesParser
from email.policy import default
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from audit_logic import copyable_manual_order_numbers, run_audit
from exporter import export_result
from workbooks import WorkbookDataError, parse_erp_workbook, parse_inventory_workbook

ROOT = Path(__file__).resolve().parent
WEB = ROOT / 'web'
OUTPUT = ROOT / 'outputs'
MAX_UPLOAD_BYTES = 120 * 1024 * 1024
RUNS: dict[str, dict[str, Any]] = {}

STORE_ALIASES = {
    'THRYVIX': 'THRYVIX_US_US',
    'VYNELITO': 'VYNELITO_US',
    'XOCN': 'XOCN_US',
    'ZEIINPA': 'ZEIINPA_US',
}


def detect_seller_from_filename(filename: str) -> str | None:
    upper = str(filename or '').upper()
    for token, seller in STORE_ALIASES.items():
        if token in upper:
            return seller
    return None


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode('utf-8')


def _safe_filename(filename: str) -> str:
    name = Path(str(filename or 'upload.xlsx')).name
    if not name.lower().endswith('.xlsx'):
        raise WorkbookDataError('????? .xlsx ???')
    return name


def parse_multipart(content_type: str, body: bytes) -> tuple[dict[str, str], list[tuple[str, str, bytes]]]:
    message = BytesParser(policy=default).parsebytes(
        f'Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n'.encode() + body
    )
    fields: dict[str, str] = {}
    files: list[tuple[str, str, bytes]] = []
    if not message.is_multipart():
        raise ValueError('上传格式无效。')
    for part in message.iter_parts():
        disposition = part.get('Content-Disposition', '')
        name_match = re.search(r'name="([^"]+)"', disposition)
        if not name_match:
            continue
        name = name_match.group(1)
        filename = part.get_filename()
        content = part.get_payload(decode=True) or b''
        if filename:
            files.append((name, _safe_filename(filename), content))
        else:
            charset = part.get_content_charset() or 'utf-8'
            fields[name] = content.decode(charset, errors='replace')
    return fields, files


def _order_json(order: dict[str, Any]) -> dict[str, Any]:
    return order


def process_audit_upload(fields: dict[str, str], files: list[tuple[str, str, bytes]]) -> tuple[str, dict[str, Any]]:
    if not files:
        raise WorkbookDataError('请至少上传 1 份 ERP 订单文件。')
    erp_files = [item for item in files if item[0] == 'erp']
    inventory_files = [item for item in files if item[0] == 'inventory']
    if len(erp_files) != 1:
        raise WorkbookDataError('请上传且仅上传 1 份 ERP 订单文件。')
    if any(len(content) > MAX_UPLOAD_BYTES for _, _, content in files):
        raise WorkbookDataError('上传文件不能超过 120 MB。')

    mapping = {}
    if fields.get('inventory_mapping'):
        try:
            mapping = json.loads(fields['inventory_mapping'])
        except json.JSONDecodeError as exc:
            raise WorkbookDataError('库存文件店铺匹配信息无效。') from exc

    with tempfile.TemporaryDirectory(prefix='order-audit-') as temp_dir:
        temp = Path(temp_dir)
        erp_name = erp_files[0][1]
        erp_path = temp / erp_name
        erp_path.write_bytes(erp_files[0][2])
        order_rows = parse_erp_workbook(erp_path, fields.get('erp_sheet') or None)
        required_sellers = sorted({str(row.get('seller') or '').strip() for row in order_rows if row.get('seller')})
        inventory_by_store: dict[str, list[dict[str, Any]]] = {}
        store_files: list[dict[str, Any]] = []
        unresolved: list[str] = []
        for index, (_, filename, content) in enumerate(inventory_files):
            seller = mapping.get(filename) or detect_seller_from_filename(filename)
            if not seller:
                unresolved.append(filename)
                continue
            path = temp / f'{index}-{filename}'
            path.write_bytes(content)
            inventory_rows = parse_inventory_workbook(path, seller, fields.get(f'inventory_sheet_{index}') or None)
            inventory_by_store.setdefault(seller, []).extend(inventory_rows)
            store_files.append({'filename': filename, 'seller': seller, 'rows': len(inventory_rows)})
        if unresolved:
            raise WorkbookDataError('无法识别库存文件对应店铺：' + '、'.join(unresolved))
        missing = [seller for seller in required_sellers if seller not in inventory_by_store]
        if missing:
            raise WorkbookDataError('缺少这些有订单店铺的库存文件：' + '、'.join(missing))
        result = run_audit(order_rows, inventory_by_store)

    run_id = uuid.uuid4().hex
    output = OUTPUT / f'order-audit-{run_id}.xlsx'
    export_result(result, output)
    RUNS[run_id] = {'result': result, 'output': output, 'store_files': store_files}
    response = {
        'run_id': run_id,
        'summary': result['summary'],
        'sku_groups': result['sku_groups'],
        'orders': [_order_json(order) for order in result['orders'].values()],
        'store_files': store_files,
        'copyable_orders': copyable_manual_order_numbers(result),
    }
    return run_id, response


class Handler(BaseHTTPRequestHandler):
    server_version = 'OrderAuditWorkbench/1.0'

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send(self, status: int, body: bytes, content_type: str = 'application/json; charset=utf-8', extra: dict[str, str] | None = None):
        headers = {
            'Content-Type': content_type,
            'Content-Length': str(len(body)),
            'Cache-Control': 'no-store',
        }
        if extra:
            headers.update(extra)
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: Any):
        self._send(status, _json_bytes(payload))

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/':
            return self._static('index.html', 'text/html; charset=utf-8')
        if parsed.path in {'/app.js', '/styles.css'}:
            return self._static(parsed.path[1:], mimetypes.guess_type(parsed.path)[0] or 'text/plain; charset=utf-8')
        match = re.fullmatch(r'/api/export/([a-f0-9]+)', parsed.path)
        if match:
            run = RUNS.get(match.group(1))
            if not run or not run['output'].exists():
                return self._json(404, {'error': {'message': '找不到这次审单结果。'}})
            return self._send(200, run['output'].read_bytes(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', {
                'Content-Disposition': 'attachment; filename="order-audit-result.xlsx"',
            })
        return self._json(404, {'error': {'message': '页面不存在。'}})

    def _static(self, name: str, content_type: str):
        path = WEB / name
        if not path.exists():
            return self._json(404, {'error': {'message': '页面资源不存在。'}})
        self._send(200, path.read_bytes(), content_type)

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get('Content-Length', '0'))
        if length > MAX_UPLOAD_BYTES * 6:
            return self._json(413, {'error': {'message': '上传内容过大。'}})
        body = self.rfile.read(length)
        try:
            if parsed.path == '/api/audit':
                fields, files = parse_multipart(self.headers.get('Content-Type', ''), body)
                _, payload = process_audit_upload(fields, files)
                return self._json(200, payload)
            if parsed.path == '/api/copy-orders':
                payload = json.loads(body.decode('utf-8'))
                numbers = []
                for item in payload.get('order_numbers', []):
                    text = str(item).strip()
                    if text and text not in numbers:
                        numbers.append(text)
                return self._json(200, {'text': ' '.join(numbers)})
        except (WorkbookDataError, ValueError, json.JSONDecodeError) as exc:
            return self._json(400, {'error': {'message': str(exc)}})
        except Exception as exc:
            return self._json(500, {'error': {'message': f'审单失败：{exc}'}})
        return self._json(404, {'error': {'message': '接口不存在。'}})


def create_server(port: int = 8793, host: str = '127.0.0.1') -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description='Local order audit workbench')
    parser.add_argument('--port', type=int, default=8793)
    args = parser.parse_args()
    OUTPUT.mkdir(exist_ok=True)
    server = create_server(args.port)
    print(f'OrderAuditWorkbench running at http://127.0.0.1:{args.port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
