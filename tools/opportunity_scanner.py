cat << 'EOF' > /home/claude/crypto-bot/tools/opportunity_scanner.py
"""CRYPTO-BOT Elite — Opportunity Scanner (Weekly Intelligence)
רץ פעם ביום, עונה על:
"במה כדאי להתעניין השבוע?"

מקורות (כולם חינמיים):
    CoinGecko — ביצועי 7d/30d, volume, market cap
    KuCoin Futures — OI שבועי
    CoinGecko Trending — נרטיב וסקטור

ציון Conviction 0-100:
    Narrative / Sector    20
    RS שבועי (7d)        20
    OI עולה שבועי        15
    Volume גדל           15
    Market Cap מתאים     10
    Trending              10
    Momentum 30d          10
"""

import requests
from datetime import datetime, timezone
from utils.logger import get_logger

log = get_logger(__name__)

_CG      = "https://api.coingecko.com/api/v3"
_KF      = "https://api-futures.kucoin.com"
_HEADERS = {"User-Agent": "crypto-bot/1.0"}

# נרטיבים לפי מטבע
_NARRATIVES = {
    "ai":      ["TAO","FET","RENDER","RNDR","WLD","AGIX","OCEAN","NMR","VANA","ATH"],
    "rwa":     ["ONDO","POLYX","CFG","RIO","PROPS"],
    "defi":    ["AAVE","UNI","CRV","MKR","SNX","LDO","JTO","JUP","PYTH"],
    "depin":   ["HNT","MOBILE","IOT","WIFI","MYRIA"],
    "gaming":  ["IMX","GALA","ILV","MAGIC","GODS","RON","SLP"],
    "meme":    ["PEPE","WIF","BONK","FLOKI","SHIB","DOGE","MEW","POPCAT"],
    "layer1":  ["SOL","AVAX","SUI","APT","NEAR","TON","ALGO"],
    "layer2":  ["ARB","OP","MATIC","POL","STRK","MANTA"],
    "btc_eco": ["ORDI","SATS","RATS","PIZZA","WZRD"],
    "perps":   ["HYPE","GMX","DYDX","VELA"],
}

def _get_narrative(symbol: str) -> str:
    base = symbol.replace("USDT","")
    for narr, coins in _NARRATIVES.items():
        if base in coins:
            return narr
    return ""

def _get_market_data(page: int = 1) -> list[dict]:
    try:
        r = requests.get(f"{_CG}/coins/markets", headers=_HEADERS, params={
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 100, "page": page,
            "sparkline": False,
            "price_change_percentage": "7d,30d",
        }, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"CoinGecko markets p{page}: {e}")
        return []

def _get_trending() -> set[str]:
    try:
        r = requests.get(f"{_CG}/search/trending", headers=_HEADERS, timeout=8)
        r.raise_for_status()
        return {c["item"]["symbol"].upper() for c in r.json().get("coins", [])}
    except Exception:
        return set()

def _get_oi_weekly(symbol: str) -> float:
    """OI change % בשבוע האחרון מ-KuCoin Futures."""
    try:
        kf_sym = symbol.replace("USDT","") + "USDTM"
        if symbol.replace("USDT","") == "BTC":
            kf_sym = "XBTUSDTM"
        r = requests.get(f"{_KF}/api/v1/contract/stats",
                         params={"symbol": kf_sym},
                         headers=_HEADERS, timeout=6)
        if r.status_code == 200:
            data = r.json().get("data", {})
            return float(data.get("openInterestChange24h", 0) or 0)
    except Exception:
        pass
    return 0.0

def score_coin(coin: dict, trending: set) -> dict:
    """מחשב Conviction Score לכל מטבע."""
    symbol = coin["symbol"].upper() + "USDT"
    base   = coin["symbol"].upper()
    
    ret_7d  = float(coin.get("price_change_percentage_7d_in_currency") or 0)
    ret_30d = float(coin.get("price_change_percentage_30d_in_currency") or 0)
    vol_24h = float(coin.get("total_volume") or 0)
    mcap    = float(coin.get("market_cap") or 0)
    
    score = 0
    reasons = []
    missing = []
    
    # 1. Narrative (20)
    narr = _get_narrative(symbol)
    if narr:
        score += 20
        reasons.append(f"Narrative: {narr.upper()}")
    else:
        missing.append("אין נרטיב מזוהה")
        
    # 2. RS שבועי (20)
    if ret_7d >= 20:
        score += 20
        reasons.append(f"RS שבועי חזק: +{ret_7d:.0f}%")
    elif ret_7d >= 10:
        score += 12
        reasons.append(f"RS שבועי בינוני: +{ret_7d:.0f}%")
    elif ret_7d >= 5:
        score += 6
        reasons.append(f"RS שבועי חלש: +{ret_7d:.0f}%")
    else:
        missing.append(f"RS שבועי נמוך ({ret_7d:.0f}%)")
        
    # 3. Market Cap מתאים (10)
    if 50_000_000 < mcap < 2_000_000_000:
        score += 10
        reasons.append(f"Market Cap אידאלי (${mcap/1e6:.0f}M)")
    elif 2_000_000_000 <= mcap < 10_000_000_000:
        score += 5
    else:
        missing.append(f"Market Cap לא אידאלי (${mcap/1e6:.0f}M)")
        
    # 4. Volume גדל (15)
    if vol_24h > 50_000_000:
        score += 15
        reasons.append(f"Volume גבוה (${vol_24h/1e6:.0f}M)")
    elif vol_24h > 10_000_000:
        score += 8
        reasons.append(f"Volume בינוני (${vol_24h/1e6:.0f}M)")
    else:
        missing.append("Volume נמוך")
        
    # 5. Trending (10)
    if base in trending:
        score += 10
        reasons.append("Trending ב-CoinGecko")
    else:
        missing.append("לא Trending")
        
    # 6. Momentum 30d (10)
    if ret_30d >= 30:
        score += 10
        reasons.append(f"Momentum 30d חזק: +{ret_30d:.0f}%")
    elif ret_30d >= 10:
        score += 5
    else:
        missing.append(f"Momentum 30d חלש ({ret_30d:.0f}%)")
        
    # 7. OI שבועי (15)
    oi_chg = _get_oi_weekly(symbol)
    if oi_chg >= 10:
        score += 15
        reasons.append(f"OI עולה {oi_chg:+.0f}%")
    elif oi_chg >= 5:
        score += 8
        reasons.append(f"OI עולה מתון {oi_chg:+.0f}%")
        
    return {
        "symbol":      symbol,
        "name":        coin.get("name", base),
        "price":       float(coin.get("current_price") or 0),
        "ret_7d":      ret_7d,
        "ret_30d":     ret_30d,
        "mcap":        mcap,
        "vol_24h":     vol_24h,
        "narrative":   narr,
        "conviction":  min(100, score),
        "reasons":     reasons,
        "missing":     missing,
    }

def _stars(s: int) -> str:
    if s >= 80: return "⭐⭐⭐⭐⭐"
    if s >= 65: return "⭐⭐⭐⭐☆"
    if s >= 50: return "⭐⭐⭐☆☆"
    if s >= 35: return "⭐⭐☆☆☆"
    return "⭐☆☆☆☆"

def run_opportunity_scan(top_n: int = 10, min_conviction: int = 40) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"📈 OPPORTUNITY SCANNER",
        f"📅 {today}",
        f"🎯 Top {top_n} מטבעות לשבוע הקרוב",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    
    log.info("Fetching market data...")
    trending  = _get_trending()
    all_coins = _get_market_data(1) + _get_market_data(2)
    
    if not all_coins:
        lines.append("❌ לא הצלחתי לקבל נתוני שוק.")
        return "\n".join(lines)
        
    log.info(f"Scoring {len(all_coins)} coins...")
    scored = [score_coin(c, trending) for c in all_coins]
    scored = [c for c in scored if c["conviction"] >= min_conviction]
    scored.sort(key=lambda x: x["conviction"], reverse=True)
    
    top    = scored[:top_n]
    medals = ["🥇","🥈","🥉"] + [f"{i+1}." for i in range(3, top_n)]
    
    for i, c in enumerate(top):
        medal = medals[i] if i < len(medals) else f"{i+1}."
        lines.append(f"\n{medal} {c['symbol'].replace('USDT','')}")
        lines.append(f"{_stars(c['conviction'])}  Conviction: {c['conviction']}/100")
        lines.append(f"💰 מחיר: ${c['price']:.4f}  |  7d: {c['ret_7d']:+.0f}%")
        if c["reasons"]:
            for r in c["reasons"][:4]:
                lines.append(f"  ✓ {r}")
        if c["missing"] and i < 5:
            for m in c["missing"][:2]:
                lines.append(f"  ✗ {m}")
                
    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "💡 כשאחד מאלה יתן טריגר טכני",
        "תקבל התראת BUY נפרדת.",
    ]
    return "\n".join(lines)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--top",          type=int,   default=10)
    parser.add_argument("--min-conviction", type=int, default=40)
    parser.add_argument("--send",         action="store_true")
    args = parser.parse_args()
    
    report = run_opportunity_scan(args.top, args.min_conviction)
    print(report)
    
    if args.send:
        import requests as req
        from utils.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
        if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
            req.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                     json={"chat_id": TELEGRAM_CHAT_ID, "text": report[:4096]},
                     timeout=10)
            print("✅ נשלח לטלגרם")
EOF
