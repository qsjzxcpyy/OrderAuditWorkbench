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

from audit_logic import apply_presale_threshold, copyable_manual_order_numbers, run_audit
from exporter import export_result
from workbooks import WorkbookDataError, parse_erp_workbook, parse_inventory_workbook

ROOT = Path(__file__).resolve().parent
WEB = ROOT / 'web'
OUTPUT = ROOT / 'outputs'
MAX_UPLOAD_BYTES = 120 * 1024 * 1024
RUNS: dict[str, dict[str, Any]] = {}

STORE_ALIASES = {
    'DEMOA': 'DEMOA_US_US',
    'DEMOC': 'DEMOC_US',
    'DEMOB': 'DEMOB_US',
    'DEMOD': 'DEMOD_US',
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


def audit_response(run_id: str, result: dict[str, Any], store_files: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        'run_id': run_id,
        'presale_days': result['presale_days'],
        'summary': result['summary'],
        'sku_groups': result['sku_groups'],
        'orders': list(result['orders'].values()),
        'store_files': store_files,
        'copyable_orders': copyable_manual_order_numbers(result),
    }


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
        recognized_sellers = set(STORE_ALIASES.values()) | set(inventory_by_store)
        missing = [seller for seller in required_sellers if seller in recognized_sellers and seller not in inventory_by_store]
        if missing:
            raise WorkbookDataError('缺少这些有订单店铺的库存文件：' + '、'.join(missing))
        unrecognized_sellers = {
            str(row.get('seller') or '').strip() for row in order_rows
        } - recognized_sellers
        result = run_audit(order_rows, inventory_by_store, unrecognized_sellers=unrecognized_sellers)

    run_id = uuid.uuid4().hex
    output = OUTPUT / f'order-audit-{run_id}.xlsx'
    export_result(result, output)
    RUNS[run_id] = {'result': result, 'output': output, 'store_files': store_files, 'lock': threading.Lock()}
    return run_id, audit_response(run_id, result, store_files)


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
            run_id = match.group(1)
            run = RUNS.get(run_id)
            try:
                if run:
                    with run['lock']:
                        content = run['output'].read_bytes()
                else:
                    # A saved export remains available to the original link after a restart.
                    content = (OUTPUT / f'order-audit-{run_id}.xlsx').read_bytes()
            except FileNotFoundError:
                return self._json(404, {'error': {'message': '找不到这次审单结果。'}})
            return self._send(200, content, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', {
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
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 0:
                raise ValueError('negative request length')
        except ValueError:
            return self._json(400, {'error': {'message': '无效的上传长度。'}})
        if length > MAX_UPLOAD_BYTES * 6:
            return self._json(413, {'error': {'message': '上传内容过大。'}})
        body = self.rfile.read(length)
        try:
            if parsed.path == '/api/audit':
                fields, files = parse_multipart(self.headers.get('Content-Type', ''), body)
                _, payload = process_audit_upload(fields, files)
                return self._json(200, payload)
            match = re.fullmatch(r'/api/audit/([a-f0-9]+)/presale', parsed.path)
            if match:
                return self._update_presale(match.group(1), body)
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

    def _update_presale(self, run_id: str, body: bytes):
        run = RUNS.get(run_id)
        if not run:
            return self._json(404, {'error': {'message': '找不到这次审单结果，请重新审单。'}})
        payload = json.loads(body)
        days = payload.get('presale_days') if isinstance(payload, dict) else None
        with run['lock']:
            result = apply_presale_threshold(run['result'], days)
            if days != run['result']['presale_days']:
                output = run['output']
                # Replace the previous export only after the new workbook is complete.
                with tempfile.TemporaryDirectory(dir=output.parent) as temp_dir:
                    updated_output = export_result(result, Path(temp_dir) / output.name)
                    updated_output.replace(output)
                run['result'] = result
        return self._json(200, audit_response(run_id, result, run['store_files']))


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
