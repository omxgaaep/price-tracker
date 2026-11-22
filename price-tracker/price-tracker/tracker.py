"""
Apple price tracker — checks Australian retailers for iPhone / MacBook prices
and emails when any model hits its lowest price seen so far (across all stores).

Run locally:   python tracker.py            (needs env vars, see README)
Dry run:       python tracker.py --dry-run  (prints instead of emailing, doesn't save)
"""
import json
import os
import re
import smtplib
import sys
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from pathlib import Path
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import requests

import config

STATE_FILE = Path(__file__).parent / "data" / "state.json"
TZ = ZoneInfo(config.TIMEZONE)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# ------------------------------------------------------------------ matching

EXCLUDE = re.compile(
    r"\b(case|cover|folio|protector|screen guard|glass|film|skin|sleeve|bag|"
    r"charger|charging|cable|adapter|adaptor|dock|hub|stand|mount|holder|strap|"
    r"lens|wallet|keyboard|tripod|grip|refurb\w*|renewed|pre-?owned|used|"
    r"second hand|as new|excellent|very good|grade|plan|outright\s+on|compatible|"
    r"for iphone|for macbook|replacement|battery|decal|sticker|demo|ex-?display)\b",
    re.I)

STORAGE = {"64gb": "64GB", "128gb": "128GB", "256gb": "256GB", "512gb": "512GB",
           "1tb": "1TB", "2tb": "2TB", "4tb": "4TB", "8tb": "8TB"}
RAM = {8, 16, 18, 24, 32, 36, 48, 64, 96, 128}
_IPHONES = {m.lower().replace(" ", "") for m in config.IPHONE_MODELS}


def _sizes(t):
    """All '256GB' / '1 TB' style sizes in a title, normalised."""
    return [(int(n), u.lower()) for n, u in re.findall(r"(\d+)\s*(gb|tb)\b", t, re.I)]


def model_key(title):
    """Turn a retailer's product title into a standard model name, or None.

    'Apple iPhone 17 Pro 256GB (Deep Blue)'  -> 'iPhone 17 Pro 256GB'
    'Apple MacBook Air 13-inch with M5 Chip, 512GB/16GB (Midnight)'
                                             -> 'MacBook Air 13" M5 16GB/512GB'
    Colour is ignored on purpose: cheapest of any colour wins.
    """
    t = " ".join(title.replace("‑", "-").replace("‐", "-").split())
    if EXCLUDE.search(t):
        return None

    m = re.search(r"\biphone\s*(1[0-9])\s*(e)?\b\s*(pro\s*max|pro|plus|max)?", t, re.I)
    if m:
        gen, e, variant = m.group(1), m.group(2), (m.group(3) or "")
        variant = " ".join(w.capitalize() for w in variant.split())
        name = gen + ("e" if e else "") + (" " + variant if variant else "")
        if name.lower().replace(" ", "") not in _IPHONES:
            return None
        stores = {STORAGE[f"{n}{u}"] for n, u in _sizes(t) if f"{n}{u}" in STORAGE}
        if len(stores) != 1:
            return None
        return f"iPhone {name} {stores.pop()}"

    m = re.search(r"\bmacbook\s*(air|pro)\b", t, re.I)
    if m:
        line = m.group(1).capitalize()
        if line not in config.MACBOOK_LINES:
            return None
        size = re.search(r"\b(13|14|15|16)(?:\.\d)?\s*(?:-|\s)?(?:inch|in\b|\"|”|''|-in\b)", t, re.I)
        chip = re.search(r"\bM([1-9])(?:\s*(Pro|Max))?\b", t, re.I)
        if not size or not chip:
            return None
        chip_s = "M" + chip.group(1) + (" " + chip.group(2).capitalize() if chip.group(2) else "")
        sizes = _sizes(t)
        storage = [STORAGE[f"{n}{u}"] for n, u in sizes
                   if f"{n}{u}" in STORAGE and (u == "tb" or n >= 256)]
        ram = [n for n, u in sizes if u == "gb" and n in RAM]
        if len(set(storage)) != 1:
            return None
        ram_s = f"{ram[0]}GB/" if len(set(ram)) == 1 else ""
        return f'MacBook {line} {size.group(1)}" {chip_s} {ram_s}{storage[0]}'
    return None


PRICE_RE = re.compile(r"\$\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?")
BAD_BEFORE = re.compile(r"(was|rrp|save|saving|off|payments? of|instal+ments? of|"
                        r"deposit|up to|trade.?in|delivery|shipping|from|bonus|credit|"
                        r"gift card|cashback|reward)\W*$", re.I)
BAD_AFTER = re.compile(r"^\s*(/|per\b|p/?m\b|a month|monthly|weekly|fortnight|off\b|"
                       r"cashback|credit|gift)", re.I)


def card_price(text):
    """Pick the selling price out of a product card's text."""
    found = []
    for m in PRICE_RE.finditer(text):
        before = text[max(0, m.start() - 25):m.start()]
        after = text[m.end():m.end() + 14]
        if BAD_BEFORE.search(before) or BAD_AFTER.search(after):
            continue
        val = float(m.group(1).replace(",", "") + ("." + m.group(2) if m.group(2) else ""))
        if val >= config.MIN_PRICE:
            found.append(val)
    return min(found) if found else None


# ------------------------------------------------------------------ scraping

# Runs inside the page. Finds every element whose text looks like an iPhone /
# MacBook title, climbs up to the smallest ancestor that also shows a $ price
# (= the product card), and returns the card text + link.
EXTRACT_JS = r"""
() => {
  const titleRe = /\b(iphone|macbook)\b/i;
  const priceRe = /\$\s*\d/;
  const out = [], seen = new Set();
  const els = document.querySelectorAll('a, h1, h2, h3, h4, h5, h6, [class*="title" i], [class*="name" i], [data-testid*="title" i]');
  for (const el of els) {
    const title = (el.textContent || '').replace(/\s+/g, ' ').trim();
    if (!title || title.length > 220 || !titleRe.test(title)) continue;
    let node = el, card = null;
    for (let i = 0; i < 9 && node.parentElement; i++) {
      node = node.parentElement;
      if (priceRe.test(node.textContent || '')) { card = node; break; }
    }
    if (!card) continue;
    // Too big = contains several different products -> not a single card
    const hrefs = new Set();
    for (const a of card.querySelectorAll('a[href]')) {
      const label = (a.textContent || '') + ' ' + (a.getAttribute('title') || '') + ' ' + (a.getAttribute('aria-label') || '');
      if (titleRe.test(label)) hrefs.add(a.href.split('?')[0].split('#')[0]);
    }
    if (hrefs.size > 1) continue;
    const link = (el.closest('a') || card.querySelector('a[href]') || {}).href || '';
    const key = title + '|' + link;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({title, url: link, text: (card.innerText || card.textContent || '').replace(/\s+/g, ' ')});
  }
  return out;
}
"""


def scrape_search(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    try:
        page.wait_for_load_state("networkidle", timeout=12000)
    except Exception:
        pass
    for _ in range(4):                       # trigger lazy-loaded results
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(700)
    page.wait_for_timeout(1500)
    return page.evaluate(EXTRACT_JS)


def scrape_shopify(retailer):
    rows, session = [], requests.Session()
    session.headers["User-Agent"] = UA
    for page_no in range(1, 11):
        r = session.get(retailer["url"], params={"limit": 250, "page": page_no}, timeout=30)
        r.raise_for_status()
        products = r.json().get("products", [])
        if not products:
            break
        for p in products:
            prices = [float(v["price"]) for v in p.get("variants", [])
                      if v.get("available", True) and v.get("price")]
            if prices:
                rows.append({"title": p["title"], "price": min(prices),
                             "url": retailer["base"] + p["handle"]})
        time.sleep(1)
    return rows


def collect():
    """Return (offers, ok_by_retailer). offers: list of dicts with key/price/..."""
    from playwright.sync_api import sync_playwright

    offers, counts = [], {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA, locale="en-AU", timezone_id=config.TIMEZONE,
                                  viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
        for r in config.RETAILERS:
            name = r["name"]
            counts.setdefault(name, 0)
            try:
                if r["type"] == "shopify_collection":
                    rows = scrape_shopify(r)
                else:
                    rows = []
                    for q in r.get("only", config.SEARCHES):
                        url = r["url"].format(q=quote_plus(q))
                        try:
                            for c in scrape_search(page, url):
                                c["price"] = card_price(c["text"])
                                rows.append(c)
                        except Exception as e:
                            print(f"  ! {name} '{q}': {type(e).__name__}: {str(e)[:120]}")
                        time.sleep(2)
            except Exception as e:
                print(f"  ! {name}: {type(e).__name__}: {str(e)[:120]}")
                rows = []
            n = 0
            for row in rows:
                key = model_key(row["title"])
                if key and row.get("price"):
                    offers.append({"key": key, "price": row["price"], "retailer": name,
                                   "url": row.get("url", ""), "title": row["title"][:160]})
                    n += 1
            counts[name] += n
            print(f"  {name:14s} {r['type']:18s} {n:4d} matching offers")
        browser.close()
    return offers, counts


# ------------------------------------------------------------------ state / alerts

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"lows": {}, "current": {}, "health": {}, "last_summary": None, "initialised": False}


def save_state(state):
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=1, sort_keys=True))


def spec_of(key):
    """'MacBook Air 13" M5 16GB/512GB' -> ('MacBook Air 13" M5', (512, 16))
       'iPhone 17 Pro 256GB'          -> ('iPhone 17 Pro', (256, 0))
       Returns None for MacBooks whose RAM couldn't be read (can't rank them)."""
    m = re.match(r"(.+?) (?:(\d+)GB/)?(\d+)(GB|TB)$", key)
    if not m:
        return None
    family, ram, size, unit = m.groups()
    storage = int(size) * (1024 if unit == "TB" else 1)
    if key.startswith("MacBook"):
        if not ram:
            return None
        return family, (storage, int(ram))
    return family, (storage, 0)


def lowest_spec_only(offers, state):
    """Keep only the base configuration of each model (smallest storage, then
    smallest RAM). The base spec is remembered, so a store that only lists the
    512GB version can't make 512GB look like the base model."""
    base = state.setdefault("base_spec", {})
    for o in offers:
        s = spec_of(o["key"])
        if s and (s[0] not in base or tuple(s[1]) < tuple(base[s[0]])):
            base[s[0]] = list(s[1])
    keep = []
    for o in offers:
        s = spec_of(o["key"])
        if s and list(s[1]) == base[s[0]]:
            keep.append(o)
    return keep


def money(x):
    return f"${x:,.0f}" if x == int(x) else f"${x:,.2f}"


def send_email(subject, html, text):
    user, pw = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD")
    to = [a.strip() for a in os.environ.get("ALERT_TO", "").split(",") if a.strip()]
    if not (user and pw and to):
        print("  (email not configured — would have sent:)", subject)
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, f"Price Tracker <{user}>", ", ".join(to)
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    with smtplib.SMTP_SSL(host, int(os.environ.get("SMTP_PORT", "465"))) as s:
        s.login(user, pw)
        s.sendmail(user, to, msg.as_string())
    print("  email sent:", subject)


def table(rows, headers):
    th = "".join(f"<th style='text-align:left;padding:6px 10px;border-bottom:2px solid #333'>{h}</th>" for h in headers)
    trs = "".join("<tr>" + "".join(f"<td style='padding:6px 10px;border-bottom:1px solid #ddd'>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table style='border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px'><tr>{th}</tr>{trs}</table>"


def main(dry_run=False):
    now = datetime.now(TZ)
    print(f"Run at {now:%Y-%m-%d %H:%M} Perth")
    state = load_state()
    offers, counts = collect()

    # cheapest current offer per model, across every store
    if config.LOWEST_SPEC_ONLY:
        offers = lowest_spec_only(offers, state)

    best = {}
    for o in offers:
        if o["key"] not in best or o["price"] < best[o["key"]]["price"]:
            best[o["key"]] = o
    state["current"] = {k: {"price": v["price"], "retailer": v["retailer"], "url": v["url"]}
                        for k, v in best.items()}

    alerts = []
    for key, o in sorted(best.items()):
        low = state["lows"].get(key)
        if low is None:
            state["lows"][key] = {"price": o["price"], "retailer": o["retailer"],
                                  "url": o["url"], "date": now.strftime("%d %b")}
            continue
        if o["price"] <= low["price"] - config.MIN_DROP:
            alerts.append((key, o, low))
            state["lows"][key] = {"price": o["price"], "retailer": o["retailer"],
                                  "url": o["url"], "date": now.strftime("%d %b")}

    first_run = not state.get("initialised")
    state["initialised"] = True

    if alerts and not first_run:
        rows, lines = [], []
        for key, o, low in alerts:
            drop = low["price"] - o["price"]
            flag = " ⚠️ check this — unusually big drop" if drop / low["price"] > config.SUSPICIOUS_DROP else ""
            rows.append([f"<b>{escape(key)}</b>", f"<b>{money(o['price'])}</b>",
                         f"<a href='{escape(o['url'])}'>{escape(o['retailer'])}</a>",
                         f"{money(low['price'])} ({escape(low['retailer'])}, {low['date']})",
                         f"−{money(drop)}{flag}"])
            lines.append(f"{key}: {money(o['price'])} at {o['retailer']} (prev low {money(low['price'])} "
                         f"at {low['retailer']}, {low['date']}){flag}\n  {o['url']}")
        k0, o0, _ = alerts[0]
        subject = (f"📉 New lowest price: {k0} {money(o0['price'])} at {o0['retailer']}"
                   if len(alerts) == 1 else f"📉 {len(alerts)} new lowest prices (iPhone/MacBook)")
        html = ("<p>These hit their <b>lowest price seen so far</b> across all tracked stores:</p>"
                + table(rows, ["Model", "Now", "Store", "Previous low", "Drop"])
                + "<p style='color:#666;font-size:12px'>Tip: JB Hi-Fi, Officeworks, Harvey Norman and "
                  "The Good Guys will usually price-match each other.</p>")
        if not dry_run:
            send_email(subject, html, "\n".join(lines))
        else:
            print(subject + "\n" + "\n".join(lines))
    elif first_run:
        print(f"  First run: recorded {len(best)} models as the starting point (no email).")

    # store health: warn once if a store keeps returning nothing
    for name, n in counts.items():
        h = state["health"].setdefault(name, {"fails": 0, "warned": False})
        if n:
            h.update(fails=0, warned=False)
        else:
            h["fails"] += 1
            if h["fails"] >= config.FAIL_WARN_AFTER and not h["warned"]:
                h["warned"] = True
                msg = (f"The price tracker hasn't been able to read any prices from {name} for "
                       f"{h['fails']} checks in a row. The site may have changed or be blocking it. "
                       f"Other stores are still being checked.")
                if not dry_run:
                    send_email(f"⚠️ Price tracker can't read {name}", f"<p>{msg}</p>", msg)

    # daily summary: cheapest price right now for every model, vs yesterday
    today = now.strftime("%Y-%m-%d")
    if (config.DAILY_SUMMARY and now.hour >= config.SUMMARY_HOUR
            and state.get("last_summary") != today and best):
        prev = state.get("summary_prices", {})
        rows, lines = [], []
        for k, v in sorted(best.items()):
            p = prev.get(k)
            change = ("—" if p is None or p == v["price"] else
                      f"<span style='color:{'#0a7d29' if v['price'] < p else '#b00020'}'>"
                      f"{'▼' if v['price'] < p else '▲'} {money(abs(v['price'] - p))}</span>")
            at_low = " ⭐" if v["price"] <= state["lows"][k]["price"] else ""
            rows.append([escape(k), f"<b>{money(v['price'])}</b>{at_low}",
                         f"<a href='{escape(v['url'])}'>{escape(v['retailer'])}</a>",
                         change, money(state["lows"][k]["price"])])
            lines.append(f"{k}: {money(v['price'])} at {v['retailer']}{at_low}")
        state["last_summary"] = today
        state["summary_prices"] = {k: v["price"] for k, v in best.items()}
        if not dry_run:
            send_email(f"🗓️ Daily prices {now:%a %d %b} — cheapest iPhones & MacBooks",
                       "<p>Cheapest price right now for each model (⭐ = lowest seen so far):</p>"
                       + table(rows, ["Model", "Cheapest now", "Store", "vs yesterday", "Lowest seen"]),
                       "\n".join(lines))

    print(f"  {len(best)} models tracked, {len(alerts)} new lows")
    if not dry_run:
        save_state(state)


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
