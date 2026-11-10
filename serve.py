#!/usr/bin/env python3
"""Server demo: UI live per l'hackathon (solo stdlib).
Uso: python3 serve.py  -> aprire http://localhost:8000
"""
import json, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import app

STOP = threading.Event()
THREAD = None

def run_loop(mode, seed, matches, ticks):
    STOP.clear()
    teams = app.make_teams(seed)
    for m in range(1, matches+1):
        if STOP.is_set(): break
        out = app.play_match(teams, ticks, mode=="llm", m)
        data = app.DATA / f"match_{m}.log"
        data.write_text(out, encoding="utf-8")
        app.evolve_knowledge(teams, mode=="llm")
        if STOP.is_set(): break

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        u = urllib.parse.urlparse(self.path); q = urllib.parse.parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            data = Path("index.html").read_bytes()
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
        elif u.path == "/state.json":
            p = app.STATE_PATH
            data = p.read_bytes() if p.exists() else b'{"tick":0,"mnum":1,"score":[0,0],"teams":["Azzurri","Rossi"],"ball":{"x":52,"y":34,"owner":null},"players":[],"events":["Avvio: premi Demo veloce o Demo Live"],"scorers":[]}'
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store")
            self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
        elif u.path == "/start":
            global THREAD
            mode = q.get("mode",["fast"])[0]
            seed = int(q.get("seed",["1"])[0]); matches = int(q.get("matches",["2"])[0]); ticks = int(q.get("ticks",["15"])[0])
            STOP.set()
            if THREAD and THREAD.is_alive(): THREAD.join(timeout=2)
            STOP.clear()
            THREAD = threading.Thread(target=run_loop, args=(mode,seed,matches,ticks), daemon=True)
            THREAD.start()
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
        elif u.path == "/stop":
            STOP.set(); self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
        else:
            self.send_response(404); self.end_headers()

if __name__ == "__main__":
    print("Apri http://localhost:8000")
    ThreadingHTTPServer(("127.0.0.1", 8000), H).serve_forever()
