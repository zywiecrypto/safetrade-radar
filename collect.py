#!/usr/bin/env python3
"""SafeTrade Radar - data collector for the SafeTrade public API.

No dependencies (standard library only). Usage:
    python3 collect.py            # full run
    python3 collect.py --quick    # tickers, order book and trades only (skips candles of inactive markets)

No API key is needed: only public endpoints are used.
"""
import json, os, sys, time, math, datetime, urllib.request, urllib.error
import ssl

# python.org builds on macOS ship without CA certificates; fall back to the system bundle.
if not os.environ.get("SSL_CERT_FILE") and ssl.get_default_verify_paths().cafile is None and os.path.exists("/etc/ssl/cert.pem"):
    os.environ["SSL_CERT_FILE"] = "/etc/ssl/cert.pem"

BASE = os.environ.get("SAFETRADE_BASE", "https://safetrade.com/api/v2/trade/public")
UA = "SafeTradeRadar/1.0 (+https://github.com/zywiecrypto/safetrade-radar)"
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
PAUSE = float(os.environ.get("SAFETRADE_PAUSE", "0.25"))
HOURLY_KEEP = 24 * 90          # 90 days of hourly candles
FLOW_KEEP = 24 * 45            # 45 days of buy/sell flow
SNAP_KEEP = 3000               # order-book snapshots kept per market
MAJORS = {"btc","eth","sol","bnb","doge","ltc","xmr","zec","trx","avax","sui","arb","pol","usdc","usdt","dai","pls","plsx","wpls","ada","xrp","dot","link","bch","etc","matic","shib","uni","atom"}
STABLE = {"usdt": 1.0, "usdc": 1.0, "dai": 1.0}
# Tickers that were renamed on the exchange: old base unit -> current one.
ALIASES = {"bip110": "xbt", "quan": "quantus"}
# Markets created in the January 2023 platform migration have no true listing date.
MIGRATION_END = "2023-02-01"
NOW = int(time.time())


class Blocked(Exception):
    pass


def get(path, tries=4):
    url = BASE + path
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=40) as r:
                body = r.read().decode("utf-8", "replace")
            time.sleep(PAUSE)
            return json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code == 403:
                raise Blocked("SafeTrade (Cloudflare) refused the connection from this IP address: HTTP 403")
            if e.code == 404:
                return None
            wait = int(e.headers.get("retry-after") or 0) or 5 * (i + 1)
            print(f"  HTTP {e.code} {path} - waiting {wait}s", flush=True)
            time.sleep(wait)
        except Exception as e:  # network, timeout, bad JSON
            print(f"  error {path}: {e}", flush=True)
            time.sleep(3 * (i + 1))
    return None


def load(rel, default):
    p = os.path.join(DATA, rel)
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return default


def save(rel, obj):
    p = os.path.join(DATA, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(tmp, p)


def save_js(rel, expr, obj):
    p = os.path.join(DATA, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        f.write(expr + "=" + json.dumps(obj, separators=(",", ":")) + ";\n")
    os.replace(tmp, p)


def fnum(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else 0.0
    except Exception:
        return 0.0


def sig(v, n=6):
    if not v:
        return 0
    return float(f"{v:.{n}g}")


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def day(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d")


def parse_iso(s):
    try:
        return int(datetime.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc).timestamp())
    except Exception:
        return 0


def klines(mid, period, old):
    """Fetch candles [ts,o,h,l,c,v] and merge them into the existing list `old`."""
    if old:
        frm = old[-1][0] - period * 60 * 3
        rows = get(f"/markets/{mid}/k-line?period={period}&time_from={frm}&time_to={NOW}&limit=2000")
    else:
        rows = get(f"/markets/{mid}/k-line?period={period}&limit=2000")
    if not isinstance(rows, list):
        return old
    d = {r[0]: r for r in old}
    for r in rows:
        try:
            d[int(r[0])] = [int(r[0]), sig(fnum(r[1])), sig(fnum(r[2])), sig(fnum(r[3])), sig(fnum(r[4])), sig(fnum(r[5]), 8)]
        except Exception:
            pass
    return [d[k] for k in sorted(d)]


def depth_metrics(dp, rate):
    """Spread and order-book capital within +-2% and +-10% of the mid price (USD)."""
    asks = sorted(([fnum(p), fnum(a)] for p, a in (dp or {}).get("asks", []) if fnum(p) > 0), key=lambda x: x[0])
    bids = sorted(([fnum(p), fnum(a)] for p, a in (dp or {}).get("bids", []) if fnum(p) > 0), key=lambda x: -x[0])
    if not asks or not bids:
        return None
    ba, bb = asks[0][0], bids[0][0]
    mid = (ba + bb) / 2
    def within(side, pct, up):
        lim = mid * (1 + pct) if up else mid * (1 - pct)
        return sum(p * a for p, a in side if (p <= lim if up else p >= lim)) * rate
    return {"bid": bb, "ask": ba, "spread": round((ba - bb) / mid * 100, 3),
            "b2": round(within(bids, .02, False)), "a2": round(within(asks, .02, True)),
            "b10": round(within(bids, .10, False)), "a10": round(within(asks, .10, True)),
            "nb": len(bids), "na": len(asks)}


def analyse(daily, rate):
    """Base / breakout / phase from daily SafeTrade candles. Prices in the quote currency."""
    out = {}
    s = [r for r in daily if r[4] > 0]
    n = len(s)
    if n < 2:
        return out
    c = [r[4] for r in s]
    out["ath"] = max(r[2] for r in s); out["ath_date"] = day(max(s, key=lambda r: r[2])[0])
    lows = [r for r in s if r[3] > 0]
    if lows:
        lo = min(lows, key=lambda r: r[3]); out["atl"] = lo[3]; out["atl_date"] = day(lo[0])
    def chg(k):
        return round((c[-1] / c[-1 - k] - 1) * 100, 2) if n > k and c[-1 - k] > 0 else None
    out["c7"], out["c30"] = chg(7), chg(30)
    vq = [r[4] * r[5] * rate for r in s]              # daily volume in USD
    prev = vq[-15:-1]
    out["v14"] = round(sum(prev) / len(prev)) if prev else 0
    if n < 20:
        out["phase"] = "new"
        return out
    w = s[-220:]; p = [r[4] for r in w]; m = len(p)
    li = min(range(m), key=lambda i: p[i]); a = b = li; lo = hi = p[li]
    while True:
        ext = False
        if b + 1 < m and max(hi, p[b + 1]) / min(lo, p[b + 1]) <= 2.5:
            b += 1; lo = min(lo, p[b]); hi = max(hi, p[b]); ext = True
        if a - 1 >= 0 and max(hi, p[a - 1]) / min(lo, p[a - 1]) <= 2.5:
            a -= 1; lo = min(lo, p[a]); hi = max(hi, p[a]); ext = True
        if not ext:
            break
    cur = p[-1]
    if b - a + 1 < 14:
        p30 = p[-31] if m > 31 else p[0]
        ch = (cur / p30 - 1) * 100 if p30 else 0
        out["phase"] = "uptrend" if ch > 30 else ("correction" if ch < -30 else "consolidation")
        return out
    out.update(acc_low=lo, acc_high=hi, acc_from=day(w[a][0]), acc_to=day(w[b][0]), acc_days=b - a + 1)
    if b == m - 1:
        out["phase"] = "accumulation"
        rng = hi / lo
        out["tight"] = round(rng, 2)
        return out
    bo = b + 1
    if p[bo] <= hi:
        out["phase"] = "correction"
        return out
    pk = max(range(bo, m), key=lambda i: w[i][2])
    peak = w[pk][2]; midp = math.sqrt(lo * hi)
    vb = [w[i][4] * w[i][5] for i in range(a, b + 1)]
    vbase = sum(vb) / len(vb) if vb else 0
    vbo = max(w[i][4] * w[i][5] for i in range(bo, min(m, bo + 3)))
    out.update(bo_date=day(w[bo][0]), bo_price=p[bo], peak=peak, peak_date=day(w[pk][0]),
               multiple=round(peak / midp, 1), bo_vol_x=round(vbo / vbase, 1) if vbase else None,
               dd=round((cur / peak - 1) * 100))
    if cur < hi:
        out["phase"] = "accumulation" if cur >= lo * 0.9 else "correction"
    elif cur >= 0.9 * peak:
        out["phase"] = "breakout" if (m - 1 - pk) <= 5 else "uptrend"
    elif cur >= 0.75 * peak:
        out["phase"] = "post_breakout"
    else:
        out["phase"] = "correction"
    return out


def main():
    quick = "--quick" in sys.argv
    t0 = time.time()
    print(f"SafeTrade Radar - start {iso(NOW)}  ({BASE})", flush=True)
    markets = get("/markets")
    tickers = get("/tickers")
    if not isinstance(markets, list) or not isinstance(tickers, dict):
        print("No data from /markets or /tickers - aborting.")
        return 2

    # --- quote-currency rates in USD
    rate = dict(STABLE)
    for q in {m["quote_unit"] for m in markets}:
        if q in rate:
            continue
        for st in ("usdt", "usdc"):
            t = tickers.get(q + st)
            if t and fnum(t.get("last")) > 0:
                rate[q] = fnum(t["last"]); break
    # currencies priced indirectly (e.g. SAFE via BTC)
    for q in {m["quote_unit"] for m in markets} - set(rate):
        for via in ("btc", "ltc", "eth"):
            t = tickers.get(q + via)
            if t and fnum(t.get("last")) > 0 and via in rate:
                rate[q] = fnum(t["last"]) * rate[via]; break

    # --- events: new markets and state changes
    prev = {m["id"]: m for m in load("markets.json", [])}
    events = load("events.json", [])
    first_run = not prev
    for m in markets:
        o = prev.get(m["id"])
        if o is None and not first_run:
            events.append({"t": NOW, "type": "new_market", "id": m["id"], "name": m["name"], "state": m["state"], "created_at": m.get("created_at")})
            print(f"  NEW MARKET: {m['name']}", flush=True)
        elif o is not None and o.get("state") != m.get("state"):
            events.append({"t": NOW, "type": "state", "id": m["id"], "name": m["name"], "from": o.get("state"), "to": m["state"]})
    save("markets.json", [{k: m.get(k) for k in ("id", "name", "base_unit", "quote_unit", "state", "created_at", "updated_at", "min_price", "min_amount")} for m in markets])
    save("events.json", events[-2000:])

    summary = []
    enabled = [m for m in markets if m.get("state") == "enabled"]
    for i, m in enumerate(enabled):
        mid = m["id"]; q = m["quote_unit"]; r = rate.get(q, 0.0)
        t = tickers.get(mid) or {}
        last = fnum(t.get("last")); vol_usd = fnum(t.get("volume")) * r
        active = vol_usd > 0
        daily = load(f"daily/{mid}.json", [])
        hourly = load(f"hourly/{mid}.json", [])
        stale = (not daily) or (NOW - (os.path.getmtime(os.path.join(DATA, f"daily/{mid}.json")) if os.path.exists(os.path.join(DATA, f"daily/{mid}.json")) else 0) > 20 * 3600)
        if active or (stale and not quick):
            daily = klines(mid, 1440, daily); save(f"daily/{mid}.json", daily)
            hourly = klines(mid, 60, hourly)[-HOURLY_KEEP:]; save(f"hourly/{mid}.json", hourly)
        dm = None; flow24 = None
        flow = load(f"flow/{mid}.json", {})
        if active:
            dm = depth_metrics(get(f"/markets/{mid}/depth?limit=1000"), r)
            trades = get(f"/markets/{mid}/trades?limit=1000") or []
            buckets = {}
            for tr in trades:
                ts = parse_iso(tr.get("created_at", "")); h = str(ts - ts % 3600)
                b = buckets.setdefault(h, [0.0, 0.0, 0, 0.0])
                usd = fnum(tr.get("total")) * r
                b[0 if tr.get("side") == "buy" else 1] += usd; b[2] += 1; b[3] = max(b[3], usd)
            if trades:
                oldest = min(parse_iso(tr.get("created_at", "")) for tr in trades)
                for h, b in buckets.items():
                    # full hours from this fetch overwrite; the partial oldest hour only if it holds more trades
                    if int(h) > oldest - oldest % 3600 or h not in flow or b[2] >= flow[h][2]:
                        flow[h] = [round(b[0], 2), round(b[1], 2), b[2], round(b[3], 2)]
            keep = sorted(flow)[-FLOW_KEEP:]
            flow = {h: flow[h] for h in keep}
            save(f"flow/{mid}.json", flow)
            if dm:
                snap = load(f"snap/{mid}.json", [])
                snap.append([NOW, sig(last), round(vol_usd), dm["spread"], dm["b2"], dm["a2"], dm["b10"], dm["a10"]])
                save(f"snap/{mid}.json", snap[-SNAP_KEEP:])
        f24 = [v for h, v in flow.items() if int(h) >= NOW - 86400]
        if f24:
            bu = sum(v[0] for v in f24); se = sum(v[1] for v in f24)
            flow24 = {"buy": round(bu), "sell": round(se), "n": sum(v[2] for v in f24), "max": round(max(v[3] for v in f24)),
                      "share": round(bu / (bu + se) * 100, 1) if bu + se > 0 else None}
        an = analyse(daily, r)
        row = {"id": mid, "name": m["name"], "base": m["base_unit"], "quote": q, "created": m.get("created_at"),
               "tier": "major" if m["base_unit"] in MAJORS else "niche", "rate": sig(r),
               "last": sig(last), "usd": sig(last * r), "vol": round(vol_usd),
               "c24": fnum(str(t.get("price_change_percent", "0")).replace("%", "")) if t else None,
               "high": sig(fnum(t.get("high"))), "low": sig(fnum(t.get("low"))),
               "depth": dm, "flow": flow24, "an": an,
               "volx": round(vol_usd / an["v14"], 1) if an.get("v14") else None,
               "spark": [sig(x[4], 4) for x in daily[-90:]], "days": len(daily),
               "first_candle": day(daily[0][0]) if daily else None}
        summary.append(row)
        snap = load(f"snap/{mid}.json", [])
        fl = sorted(flow.items())[-24 * 14:]
        save_js(f"m/{mid}.js", f'(window.RADAR_M=window.RADAR_M||{{}})["{mid}"]',
                {"daily": daily, "hourly": hourly[-24 * 30:], "flow": [[int(h)] + v for h, v in fl], "snap": snap[-700:]})
        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{len(enabled)} markets...", flush=True)

    # --- coin-level listing date: the earliest market or first candle of that coin on the exchange,
    #     not the creation date of one particular pair
    first = {}
    for m in markets:
        b = ALIASES.get(m["base_unit"], m["base_unit"])
        d = (m.get("created_at") or "")[:10]
        if d and (b not in first or d < first[b]):
            first[b] = d
    for row in summary:
        b = ALIASES.get(row["base"], row["base"])
        fc = row.pop("first_candle", None)
        if fc and (b not in first or fc < first[b]):
            first[b] = fc
    for row in summary:
        d = first.get(ALIASES.get(row["base"], row["base"]))
        row["listed"] = d
        row["legacy"] = bool(d and d < MIGRATION_END)

    summary.sort(key=lambda x: -x["vol"])
    bundle = {"generated": iso(NOW), "base": BASE, "count": len(summary),
              "total_vol": round(sum(x["vol"] for x in summary)),
              "disabled": [{"id": m["id"], "name": m["name"], "created": m.get("created_at")} for m in markets if m.get("state") != "enabled"],
              "events": events[-200:], "markets": summary}
    save_js("data.js", "window.RADAR", bundle)
    save("summary.json", bundle)
    print(f"Done: {len(summary)} markets, 24h volume {bundle['total_vol']:,} USD, {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Blocked as e:
        print("BLOCKED:", e)
        sys.exit(3)
