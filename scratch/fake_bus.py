#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fake_bus.py — stand-in for the agent's context bus, for testing the extension.

Run this on your Windows machine INSTEAD of the full agent. It listens on
127.0.0.1:7321/context (the same address the extension posts to) and prints
every payload it receives. Load the extension unpacked in Edge/Chrome, browse
around, and watch the URLs land here in real time.

This proves the extension works end-to-end WITHOUT running the desktop agent.

  python fake_bus.py

Then in Edge:  edge://extensions  -> Developer mode ON -> Load unpacked ->
pick the tt_url_reporter folder. Browse. Watch this console.

Ctrl+C to stop.
"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime

PORT = 7321


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence default noise
        pass

    def _cors(self):
        # The extension posts cross-origin from the browser; allow it.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        if self.path != "/context":
            self.send_response(404)
            self._cors()
            self.end_headers()
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw or b"{}")
            now = datetime.now().strftime("%H:%M:%S")
            src = data.get("source", "?")
            url = data.get("url", "")
            title = (data.get("title", "") or "")[:50]
            focused = data.get("window_focused")
            print(f"[{now}] src={src} focused={focused}")
            print(f"          url   = {url}")
            print(f"          title = {title}")
            print("-" * 60)
            self.send_response(200)
            self._cors()
            self.end_headers()
        except Exception as e:
            print(f"[ERR] {e}")
            self.send_response(400)
            self._cors()
            self.end_headers()


if __name__ == "__main__":
    print(f"Fake context bus listening on http://127.0.0.1:{PORT}/context")
    print("Load the extension in Edge/Chrome and browse. Ctrl+C to stop.")
    print("=" * 60)
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
