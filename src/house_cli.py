"""``smoothcast house ...``: drive a SmoothCast node over its documented HTTP API (#434).

Standard library only, GTK-free. The node is given with ``--host HOST:PORT`` or
``SMOOTHCAST_HOST`` (the address shown on the desktop home screen or QR code).
"""
from __future__ import annotations

import argparse
from http.client import HTTPConnection
import json
import os
import sys

TIMEOUT = 10.0


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class Client:
    def __init__(self, host: str, name: str = "Command line", pin: str = "") -> None:
        if ":" not in host:
            host += ":80"
        self.host, self.name, self.pin = host, name, pin
        self.cookie = ""
        self.csrf = ""

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        name, _, port = self.host.rpartition(":")
        conn = HTTPConnection(name, int(port), timeout=TIMEOUT)
        headers = {"Host": self.host, "Origin": f"http://{self.host}"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        if self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        try:
            conn.request(method, path, body=data, headers=headers)
            reply = conn.getresponse()
            raw = reply.read()
            cookie = reply.getheader("Set-Cookie")
            if cookie:
                self.cookie = cookie.split(";", 1)[0]
            payload = json.loads(raw) if raw else {}
        except (OSError, ValueError) as exc:
            raise ApiError(0, f"Couldn't reach SmoothCast at {self.host}: {exc}") from exc
        finally:
            conn.close()
        if reply.status >= 400:
            raise ApiError(reply.status, str(payload.get("error") or f"HTTP {reply.status}"))
        return payload

    def login(self) -> None:
        reply = self._request("POST", "/api/login", {"name": self.name, "pin": self.pin})
        self.csrf = reply["csrf"]

    def get(self, path: str) -> dict:
        return self._request("GET", path)

    def action(self, body: dict) -> dict:
        return self._request("POST", "/api/action", body)


def _items(result: dict) -> list[dict]:
    return [item for group in result.get("groups", []) if group["type"] not in ("artists", "albums")
            for item in group.get("items", [])]


def _line(item: dict) -> str:
    where = ", ".join(c.get("origin_name") or "this computer" for c in item.get("copies", [])
                      if c.get("online")) or "offline"
    detail = " - ".join(str(x) for x in (item.get("year"), item.get("artist"), item.get("album")) if x)
    return f"{item['id']}  {item.get('title') or item.get('name')}" + (f"  ({detail})" if detail else "") \
        + f"  [{where}]"


def run(client: Client, args: argparse.Namespace, out=None) -> int:
    from urllib.parse import quote
    out = out or sys.stdout
    client.login()
    if args.command == "status":
        state = client.get("/api/status").get("state", {})
        print(f"{state.get('state_label', 'Unknown')}: {state.get('title') or 'nothing playing'} "
              f"({len(state.get('queue') or [])} in Up Next)", file=out)
        return 0
    if args.command == "search":
        for item in _items(client.get(f"/api/search?q={quote(args.query)}&limit={args.limit}")):
            print(_line(item), file=out)
        return 0
    if args.command == "add":
        found = _items(client.get(f"/api/search?q={quote(args.query)}&limit=20"))
        if not found:
            print(f"Nothing in the house matches {args.query!r}.", file=sys.stderr)
            return 1
        if len(found) > 1 and not args.first:
            print("More than one match; choose one with --first or refine the search:", file=sys.stderr)
            for item in found[:10]:
                print("  " + _line(item), file=sys.stderr)
            return 1
        reply = client.action({"action": "queue_add_key", "key": found[0]["id"]})
        print(reply.get("message", "Added to Up Next."), file=out)
        return 0
    if args.command == "mesh":
        print(json.dumps(client.get("/api/mesh"), indent=2, sort_keys=True), file=out)
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="smoothcast house",
                                     description="Control a SmoothCast node on your home network.")
    parser.add_argument("--host", default=os.environ.get("SMOOTHCAST_HOST", ""),
                        help="node address as HOST:PORT (or set SMOOTHCAST_HOST)")
    parser.add_argument("--pin", default=os.environ.get("SMOOTHCAST_PIN", ""),
                        help="house PIN, only if the host turned it on")
    parser.add_argument("--name", default="Command line", help="name shown in the room")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="what is playing and how long Up Next is")
    search = sub.add_parser("search", help="search every shared library in the house")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=20)
    add = sub.add_parser("add", help="add the best match to Up Next")
    add.add_argument("query")
    add.add_argument("--first", action="store_true", help="take the first match when several")
    sub.add_parser("mesh", help="print the live mesh snapshot as JSON")
    args = parser.parse_args(argv)
    if not args.host:
        print("Tell me which SmoothCast to use: --host HOST:PORT or SMOOTHCAST_HOST.", file=sys.stderr)
        return 2
    try:
        return run(Client(args.host, args.name, args.pin), args)
    except ApiError as exc:
        print(str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
