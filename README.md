# rest-xml-soap-client-demo

One small inventory service that serves the **same data three ways: REST/JSON, XML and SOAP 1.1**, plus a client
that calls all three and prints the results side by side. It's a hands-on comparison of the integration styles
you still meet in real systems. Standard library only (`http.server`, `sqlite3`, `xml.etree`).

## Run

```bash
python3 app.py               # server on http://127.0.0.1:8000 (in-memory SQLite with 3 sample devices)
python3 client.py 2          # in another terminal: fetch device 2 via all three styles
python3 -m unittest -v       # 11 end-to-end tests over real HTTP
```

```text
field     REST/JSON             XML                   SOAP
HTTP      200                   200                   200
hostname  nb-sales-07           nb-sales-07           nb-sales-07
id        2                     2                     2
ip        192.168.10.57         192.168.10.57         192.168.10.57
owner     Sales                 Sales                 Sales
type      laptop                laptop                laptop
```

## Endpoints

| Style | Request | Response |
|---|---|---|
| REST/JSON | `GET /devices`, `GET /devices/<id>` | `200` JSON, `404 {"error": …}` |
| REST/JSON | `POST /devices` with `{"hostname", "type", "ip"?, "owner"?}` | `201 Created` + `Location: /devices/<id>`; `400` invalid, `409` duplicate, `413` too large |
| XML | same `GET`s with header `Accept: application/xml` | `200` `<device>…</device>` (content negotiation) |
| SOAP 1.1 | `POST /soap`, operation `GetDevice` in namespace `urn:example:inventory` | `200` envelope, or a `soap:Fault` with HTTP `500` |

```bash
curl -s localhost:8000/devices/1
curl -s -H 'Accept: application/xml' localhost:8000/devices/1
curl -s -X POST localhost:8000/devices -d '{"hostname": "srv-backup", "type": "server"}' -i
curl -s localhost:8000/soap -H 'Content-Type: text/xml' -d '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body><GetDevice xmlns="urn:example:inventory"><id>3</id></GetDevice></soap:Body></soap:Envelope>'
```

## REST vs SOAP: what I noticed building both

- **Errors.** REST uses the HTTP status code itself (404, 409, …). SOAP 1.1 always answers `500` with a
  `soap:Fault` inside the XML body, so a client has to parse the body to know what went wrong.
- **Addressing.** In REST the URL names the resource (`/devices/3`). In SOAP every call goes to one URL
  (`/soap`) and the operation is named inside the envelope (`GetDevice`).
- **Contract.** SOAP messages are strict XML with namespaces, so typos in the namespace mean "unknown operation".
  JSON is looser and easier to read, but nothing enforces the shape unless you validate it yourself.

## Safety

- All SQL uses `?` placeholders. A test stores `x'); DROP TABLE devices; --` as a hostname and checks
  it's saved as plain text and the table survives.
- Request bodies over 64 KB are refused (`413`). Malformed JSON or XML gets a clean error, never a crash.
- XML external entities (XXE) are not resolved by Python's parser. A test sends one pointing at `/etc/passwd`.

## License

[MIT](LICENSE)
