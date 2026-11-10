#!/usr/bin/env python3
"""Demo server (stdlib only). Run: python3 serve.py -> http://localhost:8000"""
import json, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import app

LOCK = threading.Lock()
THREAD = None
CANCEL = None
RESULT = {}

def run_loop(cancel, mode, seed, matches, ticks):
    app.PHASE = "running"; app.MODE = mode; app.LAST_ERROR = ""
    app.CURRENT_RUN[0] += 1
    teams = None
    try:
        teams = app.make_teams(seed)
        for m in range(1, matches+1):
            if cancel.is_set():
                app.PHASE = "stopping"; break
            out = app.play_match(teams, ticks, mode=="llm", m, cancel=cancel, delay=0.35)
            app.DATA.joinpath(f"match_{m}.log").write_text(out, encoding="utf-8")
            if cancel.is_set():
                app.PHASE = "stopping"; break
            app.PHASE = "reflecting"
            app.evolve_knowledge(teams, mode=="llm", cancel=cancel)
            # snapshot dopo memoria: la UI mostra prima/dopo
            try:
                app.snapshot(teams, {"x":52,"y":34,"owner":None}, ticks, [f"Match {m} finished. Memory updated."], m)
            except Exception:
                pass
            if cancel.is_set():
                app.PHASE = "stopping"; break
            app.PHASE = "running"
        if app.PHASE != "stopping":
            app.PHASE = "finished" if not cancel.is_set() else "stopping"
    except Exception as e:
        app.PHASE = "error"; app.LAST_ERROR = f"{type(e).__name__}: {e}"[:160]
    finally:
        # pubblica sempre la fase terminale (finished/error/stopping) con errori e punteggio
        try:
            if teams is not None:
                events = [f"Phase: {app.PHASE}"]
                if app.LAST_ERROR:
                    events.append(f"Error: {app.LAST_ERROR}")
                app.snapshot(teams, {"x":52,"y":34,"owner":None}, 0, events, matches)
        except Exception:
            pass

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        u = urllib.parse.urlparse(self.path); q = urllib.parse.parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            data = Path("index.html").read_bytes()
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
        elif u.path == "/state.json":
            p = app.STATE_PATH
            if not p.exists():
                self._json(200, {"tick":0,"mnum":1,"run_id":0,"phase":"idle","mode":"fast","last_error":"",
                                 "strategies":{},"sources":{},"api":{"calls":0,"succeeded":0,"failed":0,"cost_usd":0.0,"cost_partial":True,"prompt_tokens":0,"completion_tokens":0,"total_tokens":0,"latency_s":0.0},
                                 "score":[0,0],"teams":["Azzurri","Rossi"],"ball":{"x":52,"y":34,"owner":None},
                                 "players":[],"events":["Press Run with Ember or Practice without AI"],"scorers":[]})
            else:
                data = p.read_bytes()
                self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store")
                self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
        elif u.path == "/start":
            try:
                mode = q.get("mode",["fast"])[0]
                seed = int(q.get("seed",["1"])[0]); matches = int(q.get("matches",["2"])[0]); ticks = int(q.get("ticks",["15"])[0])
            except ValueError:
                return self._json(400, {"error":"Invalid numbers"})
            if mode not in ("fast","llm") or not (0 <= seed <= 999) or not (1 <= matches <= 5) or not (1 <= ticks <= 60):
                return self._json(400, {"error":"Out of range: seed 0-999, matches 1-5, ticks 1-60"})
            global THREAD, CANCEL
            with LOCK:
                if THREAD and THREAD.is_alive():
                    return self._json(409, {"error":"Already running; stop it first"})
                app.CURRENT_RUN[0] += 1
                cancel = threading.Event()
                CANCEL = cancel
                THREAD = threading.Thread(target=run_loop, args=(cancel,mode,seed,matches,ticks), daemon=True)
                THREAD.start()
            self._json(200, {"ok":True})
        elif u.path == "/stop":
            with LOCK:
                if CANCEL is not None:
                    CANCEL.set()
                    app.PHASE = "stopping"
                busy = bool(THREAD and THREAD.is_alive())
            self._json(200, {"ok":True,"busy":busy})
        else:
            self.send_response(404); self.end_headers()

if __name__ == "__main__":
    print("Open http://localhost:8000")
    ThreadingHTTPServer(("127.0.0.1", 8000), H).serve_forever()
