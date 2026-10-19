#!/usr/bin/env python3
"""
Teste de corretoras a partir do servidor (Render) — Level Up Capital
Responde: as corretoras aceitam chamadas vindas deste servidor (IP / região)?

  /exchtest            → relatório em texto (para colar no chat)
  /exchtest?fmt=json   → o mesmo em JSON

Para cada corretora: dados públicos (preço) e o "caminho da conta" com uma CHAVE FALSA
("teste"). A corretora deve responder "chave inválida" — isso prova que o IP do servidor
é aceito. Nenhuma chave real é usada, nada é gravado e nenhuma ordem é enviada.
Só biblioteca padrão do Python. Também roda sozinho: python exchtest.py (porta $PORT).
"""

import json
import os
import ssl
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

UA = "Mozilla/5.0 (X11; Linux x86_64) LevelUpCapital-exchtest/1.0"
TIMEOUT = 10
_CTX = ssl.create_default_context()


def http(url, headers=None):
    """GET → dict(status, body, ms, err). Nunca levanta exceção."""
    h = {"User-Agent": UA, "Accept": "application/json,*/*"}
    h.update(headers or {})
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_CTX) as r:
            body = r.read().decode("utf-8", "replace")
            return {"status": r.status, "body": body, "ms": int((time.time() - t0) * 1000), "err": ""}
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        return {"status": e.code, "body": body, "ms": int((time.time() - t0) * 1000), "err": ""}
    except Exception as e:
        return {"status": 0, "body": "", "ms": int((time.time() - t0) * 1000), "err": f"{type(e).__name__}: {e}"}


def js(r):
    try:
        return json.loads(r["body"])
    except Exception:
        return None


def snippet(r, n=160):
    s = " ".join((r.get("body") or "").split())
    return s[:n] + ("…" if len(s) > n else "")


def blocked_reason(r):
    """Explica respostas de bloqueio comuns (CDN/geo) em vez de mostrar HTML cru."""
    b = (r.get("body") or "").lower()
    if r["status"] == 0:
        return f"sem conexão ({r['err']})"
    if r["status"] == 451 or "restricted location" in b or "eligibility" in b:
        return f"HTTP {r['status']} · bloqueio por país/região do servidor"
    if r["status"] == 403 and ("cloudfront" in b or "request blocked" in b or "<html" in b):
        return f"HTTP 403 · bloqueado na entrada (CDN) — provável bloqueio do IP/região do servidor"
    return f"HTTP {r['status']} · {snippet(r)}"


def ok(d):
    return {"st": "ok", "d": d}


def bad(d):
    return {"st": "bad", "d": d}


def warn(d):
    return {"st": "warn", "d": d}


def num(x, nd=1):
    try:
        return f"{float(x):,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "—"


# ── testes por corretora ──────────────────────────────────────────────
def t_bybit_pub():
    r = http("https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT")
    j = js(r)
    try:
        t = j["result"]["list"][0]
        return ok(f"{r['ms']} ms · último {num(t['lastPrice'])} · marcação {num(t['markPrice'])}")
    except Exception:
        return bad(blocked_reason(r))


def t_bybit_opt():
    r = http("https://api.bybit.com/v5/market/tickers?category=option&baseCoin=BTC")
    j = js(r)
    try:
        L = j["result"]["list"]
        c = sorted([x for x in L if x.get("delta") not in (None, "")], key=lambda x: abs(float(x["delta"]) - 0.5))[0]
        return ok(f"{r['ms']} ms · {len(L)} opções · ex.: {c['symbol']} delta {num(c['delta'], 3)} · IV {num(float(c['markIv']) * 100)}%")
    except Exception:
        return bad(blocked_reason(r))


def t_bybit_priv():
    r = http("https://api.bybit.com/v5/position/list?category=linear&settleCoin=USDT",
             {"X-BAPI-API-KEY": "teste", "X-BAPI-TIMESTAMP": str(int(time.time() * 1000)), "X-BAPI-RECV-WINDOW": "5000", "X-BAPI-SIGN": "0"})
    j = js(r)
    if isinstance(j, dict) and "retCode" in j:
        return ok(f"caminho aberto · {r['ms']} ms · resposta: \"{j.get('retCode')} {j.get('retMsg', '')}\" (esperado: chave inválida)")
    if r["status"] == 401 and not (r["body"] or "").strip():
        return ok(f"caminho aberto · {r['ms']} ms · HTTP 401 sem texto (a Bybit recusou a chave falsa)")
    return bad(blocked_reason(r))


def t_bingx_pub():
    r = http("https://open-api.bingx.com/openApi/swap/v2/quote/premiumIndex?symbol=BTC-USDT")
    j = js(r)
    try:
        d = j["data"][0] if isinstance(j["data"], list) else j["data"]
        return ok(f"{r['ms']} ms · marcação {num(d['markPrice'])} · índice {num(d['indexPrice'])}")
    except Exception:
        return bad(blocked_reason(r))


def t_bingx_priv():
    r = http(f"https://open-api.bingx.com/openApi/swap/v2/user/positions?timestamp={int(time.time() * 1000)}&signature=0",
             {"X-BX-APIKEY": "teste"})
    j = js(r)
    if isinstance(j, dict) and ("code" in j or "msg" in j):
        return ok(f"caminho aberto · {r['ms']} ms · resposta: \"{j.get('code')} {j.get('msg', '')}\" (esperado: chave inválida)")
    return bad(blocked_reason(r))


D = "https://www.deribit.com/api/v2"


def t_deribit_pub():
    r = http(f"{D}/public/ticker?instrument_name=BTC-PERPETUAL")
    j = js(r)
    try:
        t = j["result"]
        return ok(f"{r['ms']} ms · último {num(t['last_price'])} · marcação {num(t['mark_price'])}")
    except Exception:
        return bad(blocked_reason(r))


def t_deribit_opt():
    r = http(f"{D}/public/get_instruments?currency=BTC&kind=option&expired=false")
    j = js(r)
    try:
        L = j["result"]
        ix = js(http(f"{D}/public/get_index_price?index_name=btc_usd"))["result"]["index_price"]
        lim = (time.time() + 3 * 86400) * 1000
        calls = [x for x in L if x["option_type"] == "call" and x["expiration_timestamp"] >= lim]
        exp = min(x["expiration_timestamp"] for x in calls)
        pick = sorted([x for x in calls if x["expiration_timestamp"] == exp], key=lambda x: abs(x["strike"] - ix))[0]
        g = js(http(f"{D}/public/ticker?instrument_name={pick['instrument_name']}"))["result"]
        return ok(f"{r['ms']} ms · {len(L)} opções · ex.: {pick['instrument_name']} delta {num(g['greeks']['delta'], 3)} · IV {num(g['mark_iv'])}%")
    except Exception:
        return bad(blocked_reason(r))


def t_deribit_priv():
    r = http(f"{D}/private/get_positions?currency=BTC", {"Authorization": "Bearer teste"})
    j = js(r)
    if isinstance(j, dict) and "error" in j:
        e = j["error"]
        return ok(f"caminho aberto · {r['ms']} ms · resposta: \"{e.get('code')} {e.get('message', '')}\" (esperado: chave inválida)")
    return bad(blocked_reason(r))


def t_binance_pub():
    r = http("https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT")
    j = js(r)
    if isinstance(j, dict) and j.get("markPrice"):
        return ok(f"{r['ms']} ms · marcação {num(j['markPrice'])}")
    return bad(blocked_reason(r))


def t_binance_priv():
    r = http(f"https://fapi.binance.com/fapi/v2/positionRisk?timestamp={int(time.time() * 1000)}&signature=0", {"X-MBX-APIKEY": "teste"})
    j = js(r)
    if isinstance(j, dict) and "code" in j and "msg" in j and r["status"] != 451:
        return ok(f"caminho aberto · {r['ms']} ms · resposta: \"{j['code']} {j['msg']}\" (esperado: chave inválida)")
    return bad(blocked_reason(r))


TESTS = [
    ("Bybit", [("REST público · BTCUSDT", t_bybit_pub), ("Opções · gregas (público)", t_bybit_opt), ("Conta · caminho REST (chave falsa)", t_bybit_priv)]),
    ("BingX", [("REST público · BTC-USDT", t_bingx_pub), ("Conta · caminho REST (chave falsa)", t_bingx_priv)]),
    ("Deribit", [("REST público · BTC-PERPETUAL", t_deribit_pub), ("Opções · gregas (público)", t_deribit_opt), ("Conta · caminho REST (chave falsa)", t_deribit_priv)]),
    ("Binance", [("REST público · BTCUSDT", t_binance_pub), ("Conta · caminho REST (chave falsa)", t_binance_priv)]),
]


def where():
    """IP de saída e localização do servidor (mostra a região do Render)."""
    r = http("https://ipinfo.io/json")
    j = js(r)
    if isinstance(j, dict) and j.get("ip"):
        return {"ip": j.get("ip"), "local": ", ".join(x for x in [j.get("city"), j.get("region"), j.get("country")] if x), "rede": j.get("org", "")}
    r2 = http("https://api.ipify.org?format=json")
    j2 = js(r2)
    return {"ip": (j2 or {}).get("ip", "?"), "local": "?", "rede": ""}


_lock = threading.Lock()
_last = {"ts": 0, "data": None}


def run_all():
    with _lock:                                  # evita rodar duas vezes ao mesmo tempo / em sequência rápida
        if _last["data"] and time.time() - _last["ts"] < 20:
            return _last["data"]
        jobs = [(ex, k, fn) for ex, L in TESTS for k, fn in L]
        with ThreadPoolExecutor(max_workers=8) as pool:
            wf = pool.submit(where)
            futs = [pool.submit(fn) for _, _, fn in jobs]
            res = []
            for (ex, k, _), f in zip(jobs, futs):
                try:
                    v = f.result(timeout=TIMEOUT + 15)
                except Exception as e:
                    v = warn(f"erro no teste: {e}")
                res.append({"ex": ex, "teste": k, "st": v["st"], "d": v["d"]})
            loc = wf.result(timeout=TIMEOUT + 5)
        render = {k: v for k, v in os.environ.items() if k.startswith("RENDER_") and k in ("RENDER_SERVICE_NAME", "RENDER_REGION", "RENDER_INSTANCE_ID", "RENDER_GIT_COMMIT")}
        brt = datetime.now(timezone.utc) - timedelta(hours=3)
        data = {"quando_brt": brt.strftime("%d/%m/%Y %H:%M"), "servidor": loc, "render": render, "resultados": res}
        _last.update(ts=time.time(), data=data)
        return data


def as_text(data):
    sym = {"ok": "✓", "bad": "✕", "warn": "!"}
    s = data["servidor"]
    lines = [f"Teste de APIs pelo servidor · {data['quando_brt']} (BRT)",
             f"servidor: IP {s.get('ip')} · {s.get('local')} · {s.get('rede')}"]
    if data["render"]:
        lines.append("render: " + " · ".join(f"{k}={v}" for k, v in data["render"].items()))
    cur = None
    for r in data["resultados"]:
        if r["ex"] != cur:
            cur = r["ex"]
            lines += ["", f"{cur}:"]
        lines.append(f"  {sym.get(r['st'], '?')} {r['teste']} — {r['d']}")
    lines += ["", "✓ = este servidor é aceito · ✕ = bloqueado (detalhe ao lado) · chave falsa: o esperado é \"chave inválida\""]
    return "\n".join(lines)


def handle(params):
    """Usado pelo proxy_server.py: devolve (status, content-type, bytes)."""
    data = run_all()
    if (params.get("fmt") or [""])[0] == "json":
        return 200, "application/json; charset=utf-8", json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")
    return 200, "text/plain; charset=utf-8", as_text(data).encode("utf-8")


if __name__ == "__main__":                       # serviço separado (ex.: um teste em outra região)
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from socketserver import ThreadingMixIn
    import urllib.parse

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            p = urllib.parse.urlparse(self.path)
            if p.path not in ("/", "/exchtest"):
                self.send_error(404)
                return
            st, ct, body = handle(urllib.parse.parse_qs(p.query))
            self.send_response(st)
            self.send_header("Content-Type", ct)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    class S(ThreadingMixIn, HTTPServer):
        daemon_threads = True

    port = int(os.environ.get("PORT", 8766))
    print(f"exchtest na porta {port}")
    S(("0.0.0.0", port), H).serve_forever()
