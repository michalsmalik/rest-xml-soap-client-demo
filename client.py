#!/usr/bin/env python3
"""Fetch the same device via REST/JSON, XML and SOAP and print the three results side by side.

Usage: python3 client.py [device_id] [--url http://127.0.0.1:8000]   (start app.py first)
"""
import argparse
import json
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

SOAP_ENV = "http://schemas.xmlsoap.org/soap/envelope/"
SVC_NS = "urn:example:inventory"


def http(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:     # 4xx/5xx still carry a useful body
        with e:
            return e.code, e.read()


def via_json(base, device_id):
    status, body = http(f"{base}/devices/{device_id}")
    return status, json.loads(body)


def via_xml(base, device_id):
    status, body = http(f"{base}/devices/{device_id}", headers={"Accept": "application/xml"})
    root = ET.fromstring(body)
    return status, ({c.tag: c.text for c in root} if root.tag == "device" else {"error": root.text})


def via_soap(base, device_id):
    envelope = (f'<?xml version="1.0"?><soap:Envelope xmlns:soap="{SOAP_ENV}"><soap:Body>'
                f'<GetDevice xmlns="{SVC_NS}"><id>{int(device_id)}</id></GetDevice>'
                f'</soap:Body></soap:Envelope>').encode()
    status, body = http(f"{base}/soap", envelope,
                        {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": f"{SVC_NS}#GetDevice"})
    root = ET.fromstring(body)
    device = root.find(f".//{{{SVC_NS}}}GetDeviceResponse/device")
    if device is not None:
        return status, {c.tag: c.text for c in device}
    return status, {"fault": root.findtext(f".//{{{SOAP_ENV}}}Fault/faultstring")}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("id", nargs="?", default=1, type=int)
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    results = {name: fn(args.url, args.id) for name, fn in
               (("REST/JSON", via_json), ("XML", via_xml), ("SOAP", via_soap))}
    keys = sorted({k for _, d in results.values() for k in d})
    print(f"{'field':<10}" + "".join(f"{name:<22}" for name in results))
    print(f"{'HTTP':<10}" + "".join(f"{status:<22}" for status, _ in results.values()))
    for k in keys:
        print(f"{k:<10}" + "".join(f"{str(d.get(k, '')):<22}" for _, d in results.values()))


if __name__ == "__main__":
    main()
