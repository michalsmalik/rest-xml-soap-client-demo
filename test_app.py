"""End-to-end tests: start the server on a free port and call it over real HTTP."""
import json
import threading
import unittest
import urllib.request

import app
import client


class InventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = app.make_server(port=0)            # port 0 = any free port
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def post_json(self, path, obj):
        return client.http(self.base + path, json.dumps(obj).encode(), {"Content-Type": "application/json"})

    # --- REST / JSON
    def test_list_devices(self):
        status, body = client.http(self.base + "/devices")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(json.loads(body)), 3)

    def test_get_device_json(self):
        status, device = client.via_json(self.base, 1)
        self.assertEqual(status, 200)
        self.assertEqual(device["hostname"], "pc-reception-01")

    def test_create_device_returns_201_and_location(self):
        req = urllib.request.Request(self.base + "/devices", json.dumps({"hostname": "srv-new", "type": "server"}).encode())
        with urllib.request.urlopen(req) as r:
            self.assertEqual(r.status, 201)
            created = json.loads(r.read())
            self.assertEqual(r.headers["Location"], f"/devices/{created['id']}")
        self.assertEqual(client.via_json(self.base, created["id"])[1]["hostname"], "srv-new")

    def test_errors(self):
        self.assertEqual(client.via_json(self.base, 999)[0], 404)
        self.assertEqual(client.http(self.base + "/nope")[0], 404)
        self.assertEqual(client.http(self.base + "/devices", b"not json")[0], 400)
        self.assertEqual(client.http(self.base + "/devices", b"[1, 2]")[0], 400)
        self.assertEqual(self.post_json("/devices", {"hostname": "only-name"})[0], 400)
        self.assertEqual(self.post_json("/devices", {"hostname": "nb-sales-07", "type": "laptop"})[0], 409)

    def test_body_size_limit(self):
        self.assertEqual(client.http(self.base + "/devices", b"x" * (app.MAX_BODY + 1))[0], 413)

    def test_sql_injection_is_stored_as_plain_text(self):
        evil = "x'); DROP TABLE devices; --"
        status, body = self.post_json("/devices", {"hostname": evil, "type": "laptop"})
        self.assertEqual(status, 201)
        self.assertEqual(json.loads(body)["hostname"], evil)                 # stored literally
        self.assertEqual(client.http(self.base + "/devices")[0], 200)         # table still exists

    # --- XML
    def test_get_device_xml_matches_json(self):
        status, device = client.via_xml(self.base, 2)
        self.assertEqual(status, 200)
        self.assertEqual(device, {k: str(v) for k, v in client.via_json(self.base, 2)[1].items()})

    def test_xml_error_and_list(self):
        self.assertEqual(client.via_xml(self.base, 999), (404, {"error": "device not found"}))
        status, body = client.http(self.base + "/devices", headers={"Accept": "application/xml"})
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b"<?xml") and b"<devices>" in body)

    # --- SOAP
    def test_soap_get_device_matches_json(self):
        status, device = client.via_soap(self.base, 3)
        self.assertEqual(status, 200)
        self.assertEqual(device, {k: str(v) for k, v in client.via_json(self.base, 3)[1].items()})

    def test_soap_faults(self):
        self.assertEqual(client.via_soap(self.base, 999), (500, {"fault": "device 999 not found"}))
        status, body = client.http(self.base + "/soap", b"<broken")
        self.assertEqual(status, 500)
        self.assertIn(b"not well-formed", body)
        wrong_op = (b'<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>'
                    b'<DeleteEverything xmlns="urn:example:inventory"/></soap:Body></soap:Envelope>')
        self.assertIn(b"unknown operation", client.http(self.base + "/soap", wrong_op)[1])

    def test_external_entities_are_not_resolved(self):
        # XXE attempt: Python's XML parser does not fetch external entities.
        xxe = (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
               b'<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>'
               b'<GetDevice xmlns="urn:example:inventory"><id>&e;</id></GetDevice></soap:Body></soap:Envelope>')
        status, body = client.http(self.base + "/soap", xxe)
        self.assertEqual(status, 500)
        self.assertNotIn(b"root:", body)


if __name__ == "__main__":
    unittest.main()
