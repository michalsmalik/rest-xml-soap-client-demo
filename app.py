#!/usr/bin/env python3
"""A tiny inventory service that serves the same data three ways: REST/JSON, XML and SOAP 1.1.

Standard library only (http.server, sqlite3, xml.etree). Run:  python3 app.py [--port 8000]

  GET  /devices            list devices          (JSON, or XML with "Accept: application/xml")
  GET  /devices/<id>       one device            (JSON or XML)
  POST /devices            add a device (JSON body) -> 201 Created + Location header
  POST /soap               SOAP 1.1 endpoint, operation GetDevice(id)
"""
import argparse
import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SOAP_ENV = "http://schemas.xmlsoap.org/soap/envelope/"
SVC_NS = "urn:example:inventory"
MAX_BODY = 64 * 1024          # refuse larger request bodies (simple protection)
FIELDS = ("id", "hostname", "type", "ip", "owner")

SAMPLE = [
    ("pc-reception-01", "desktop", "192.168.10.21", "Reception"),
    ("nb-sales-07", "laptop", "192.168.10.57", "Sales"),
    ("prn-floor2", "printer", "192.168.10.200", "Floor 2"),
]


def open_db(path=":memory:"):
    db = sqlite3.connect(path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS devices (
        id INTEGER PRIMARY KEY, hostname TEXT NOT NULL UNIQUE, type TEXT NOT NULL, ip TEXT, owner TEXT)""")
    if db.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 0:
        db.executemany("INSERT INTO devices (hostname, type, ip, owner) VALUES (?, ?, ?, ?)", SAMPLE)
        db.commit()
    return db


# ---- data access: always parameterized queries (?), never string formatting -> no SQL injection
def get_device(db, device_id):
    row = db.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    return dict(row) if row else None


def list_devices(db):
    return [dict(r) for r in db.execute("SELECT * FROM devices ORDER BY id")]


def add_device(db, data):
    missing = [f for f in ("hostname", "type") if not str(data.get(f, "")).strip()]
    if missing:
        raise ValueError(f"missing field(s): {', '.join(missing)}")
    cur = db.execute("INSERT INTO devices (hostname, type, ip, owner) VALUES (?, ?, ?, ?)",
                     (data["hostname"], data["type"], data.get("ip"), data.get("owner")))
    db.commit()
    return get_device(db, cur.lastrowid)


# ---- XML / SOAP helpers
def device_xml(parent, device):
    el = ET.SubElement(parent, "device")
    for f in FIELDS:
        ET.SubElement(el, f).text = "" if device[f] is None else str(device[f])
    return el


def soap_envelope(build_body):
    ET.register_namespace("soap", SOAP_ENV)
    ET.register_namespace("inv", SVC_NS)
    env = ET.Element(f"{{{SOAP_ENV}}}Envelope")
    build_body(ET.SubElement(env, f"{{{SOAP_ENV}}}Body"))
    return ET.tostring(env, encoding="utf-8", xml_declaration=True)


def soap_fault(code, message):
    def body(b):
        fault = ET.SubElement(b, f"{{{SOAP_ENV}}}Fault")
        ET.SubElement(fault, "faultcode").text = f"soap:{code}"
        ET.SubElement(fault, "faultstring").text = message
    return soap_envelope(body)


def handle_soap(db, payload):
    """Returns (http_status, xml_bytes). SOAP 1.1 sends faults with HTTP 500."""
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return 500, soap_fault("Client", "request is not well-formed XML")
    request = root.find(f"{{{SOAP_ENV}}}Body/{{{SVC_NS}}}GetDevice")
    if request is None:
        return 500, soap_fault("Client", "unknown operation (expected GetDevice in the soap:Body)")
    id_text = (request.findtext(f"{{{SVC_NS}}}id") or "").strip()
    if not id_text.isdigit():
        return 500, soap_fault("Client", "id must be a positive integer")
    device = get_device(db, int(id_text))
    if device is None:
        return 500, soap_fault("Client", f"device {id_text} not found")

    def body(b):
        resp = ET.SubElement(b, f"{{{SVC_NS}}}GetDeviceResponse")
        device_xml(resp, device)
    return 200, soap_envelope(body)


class Handler(BaseHTTPRequestHandler):
    db = None  # set in make_server()
    server_version = "InventoryDemo/1.0"

    def log_message(self, fmt, *args):   # keep test output quiet
        pass

    def send(self, status, body, content_type, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def wants_xml(self):
        return "xml" in self.headers.get("Accept", "")

    def reply(self, status, data, headers=None):
        """Send data as JSON, or as XML when the client asked for it."""
        if self.wants_xml():
            if isinstance(data, list):
                root = ET.Element("devices")
                for d in data:
                    device_xml(root, d)
            elif "error" in data:
                root = ET.Element("error")
                root.text = data["error"]
            else:
                root = device_xml(ET.Element("x"), data)
            body = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            self.send(status, body, "application/xml; charset=utf-8", headers)
        else:
            self.send(status, json.dumps(data).encode(), "application/json", headers)

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return None
        return self.rfile.read(length)

    def do_GET(self):
        if self.path == "/devices":
            return self.reply(200, list_devices(self.db))
        m = re.fullmatch(r"/devices/(\d+)", self.path)
        if m:
            device = get_device(self.db, int(m.group(1)))
            return self.reply(200, device) if device else self.reply(404, {"error": "device not found"})
        self.reply(404, {"error": "no such endpoint"})

    def do_POST(self):
        body = self.read_body()
        if body is None:
            return self.reply(413, {"error": f"request body larger than {MAX_BODY} bytes"})
        if self.path == "/soap":
            status, xml = handle_soap(self.db, body)
            return self.send(status, xml, "text/xml; charset=utf-8")
        if self.path == "/devices":
            try:
                data = json.loads(body or b"{}")
                if not isinstance(data, dict):
                    raise ValueError("JSON body must be an object")
                device = add_device(self.db, data)
            except json.JSONDecodeError:
                return self.reply(400, {"error": "body is not valid JSON"})
            except ValueError as e:
                return self.reply(400, {"error": str(e)})
            except sqlite3.IntegrityError:
                return self.reply(409, {"error": "hostname already exists"})
            return self.reply(201, device, {"Location": f"/devices/{device['id']}"})
        self.reply(404, {"error": "no such endpoint"})


class InventoryServer(ThreadingHTTPServer):
    def server_close(self):
        super().server_close()
        self.RequestHandlerClass.db.close()   # close the SQLite connection with the server


def make_server(port=8000, host="127.0.0.1", db_path=":memory:"):
    handler = type("BoundHandler", (Handler,), {"db": open_db(db_path)})
    return InventoryServer((host, port), handler)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--db", default=":memory:", help="SQLite file (default: in memory)")
    args = ap.parse_args()
    srv = make_server(args.port, db_path=args.db)
    print(f"Inventory demo on http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
