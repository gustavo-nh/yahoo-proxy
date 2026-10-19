#!/usr/bin/env python3
"""
Proxy Level Up Capital — deploy no Render
  /quote?symbol=ES=F        → Yahoo Finance (chart 1d / 5m)
  /calendar?week=thisweek   → calendário econômico ForexFactory (semana atual)
  /calendar?week=nextweek   → semana seguinte (quando já publicada)
  /health                   → status
  /exchtest                 → teste: as corretoras aceitam este servidor? (exchtest.py, chave falsa)
O calendário fica em cache por 30 min no servidor (o ForexFactory bloqueia
quem consulta o feed muitas vezes), então o dashboard pode pedir à vontade.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import urllib.request
import urllib.parse
import threading
import json
import time
import os

PORT = int(os.environ.get("PORT", 8765))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json,text/html,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://finance.yahoo.com/",
}

CAL_FEEDS = {
    "thisweek": "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "nextweek": "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
}
CAL_TTL = 30 * 60        # cache de 30 min
CAL_ERR_TTL = 10 * 60    # depois de uma falha, espera 10 min antes de tentar de novo
_cal_cache = {}          # week -> {"ts": epoch, "data": bytes}
_cal_err = {}            # week -> {"ts": epoch, "msg": str}
_cal_lock = threading.Lock()


def fetch_calendar(week):
    """Devolve (status, bytes JSON). Usa cache; em falha devolve o último dado bom, se houver."""
    now = time.time()
    with _cal_lock:
        hit = _cal_cache.get(week)
        if hit and now - hit["ts"] < CAL_TTL:
            return 200, hit["data"]
        err = _cal_err.get(week)
        if err and now - err["ts"] < CAL_ERR_TTL:
            if hit:
                return 200, hit["data"]
            return 502, json.dumps({"error": err["msg"]}).encode()
    try:
        req = urllib.request.Request(CAL_FEEDS[week], headers={
            "User-Agent": HEADERS["User-Agent"],
            "Accept": "application/json,*/*",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, list):
            raise ValueError("formato inesperado do feed")
        data = json.dumps(parsed).encode()
        with _cal_lock:
            _cal_cache[week] = {"ts": now, "data": data}
            _cal_err.pop(week, None)
        return 200, data
    except Exception as e:
        msg = str(e)
        with _cal_lock:
            _cal_err[week] = {"ts": now, "msg": msg}
            hit = _cal_cache.get(week)
        if hit:
            return 200, hit["data"]      # dado antigo é melhor que nada
        return 502, json.dumps({"error": msg}).encode()


class ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[proxy] {args[0]} {args[1]}")

    def send_json(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/quote":
            symbol = params.get("symbol", [None])[0]
            if not symbol:
                self.send_error(400, "symbol obrigatorio")
                return

            yahoo_url = (
                f"https://query1.finance.yahoo.com/v8/finance/chart/"
                f"{urllib.parse.quote(symbol)}"
                f"?range=1d&interval=5m&includePrePost=false"
            )

            try:
                req = urllib.request.Request(yahoo_url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = resp.read()
                self.send_json(200, data)
            except Exception as e:
                self.send_json(502, json.dumps({"error": str(e)}).encode())

        elif parsed.path == "/calendar":
            week = params.get("week", ["thisweek"])[0]
            if week not in CAL_FEEDS:
                self.send_json(400, json.dumps({"error": "week deve ser thisweek ou nextweek"}).encode())
                return
            status, body = fetch_calendar(week)
            self.send_json(status, body)

        elif parsed.path == "/exchtest":
            # teste das corretoras a partir deste servidor (import só aqui: um erro não afeta as outras rotas)
            try:
                import exchtest
                status, ctype, body = exchtest.handle(params)
            except Exception as e:
                status, ctype, body = 500, "text/plain; charset=utf-8", f"erro no teste: {e}".encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        elif parsed.path == "/health":
            self.send_json(200, json.dumps({"status": "ok"}).encode())

        elif parsed.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Level Up Capital Proxy - OK (/quote, /calendar, /exchtest)")

        else:
            self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()


class ThreadingServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    server = ThreadingServer(("0.0.0.0", PORT), ProxyHandler)
    print(f"Proxy rodando na porta {PORT}")
    server.serve_forever()
