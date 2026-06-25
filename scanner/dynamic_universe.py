"""
CRYPTO-BOT Elite — Dynamic Universe Builder

לא תמיד אותם מטבעות.
כל סריקה בונה Universe חדש מ-3 שכבות:
    Layer A — Base Volume (CoinGecko)
    Layer B — OI Expansion Leaders  (כסף נכנס בלי שמחיר זז)
    Layer C — Compression Leaders   (ATR squeeze)
    Layer D — Relative Strength     (מתחיל להכות BTC)
"""
import requests
import pandas as pd
import numpy as np
from utils.config import COINGECKO_BASE, MIN_DAILY_VOLUME, MIN_PRICE, MAX_SYMBOLS
from utils.logger import get_logger
from scanner.market_data import get_candles

log = get_logger(__name__)

_BLACKLIST = {
    "USDCUSDT","USDTUSDT","BUSDUSDT","TUSDUSDT","FDUSDUSDT",
    "DAIUSDT","PYUSDUSDT","USDSUSDT","EURCUSDT","FRAXUSDT",
}

_HEADERS   = {"User-Agent": "crypto-bot/1.0"}
_KUCOIN_FUT = "https://api-futures.kucoin.com"


def _kucoin_fut_sym(sym: str) -> str:
    base = sym.replace("USDT","")
    if base == "BTC": base = "XBT"
    return f"{base}USDTM"


# ─── Layer A: Base ────────────────────────────────────────────────────────────

def _base_universe() -> list[str]:
    symbols = []
    for page in range(1, 3):
        try:
            r = requests.get(
                f"{COINGECKO_BASE}/coins/markets",
                headers=_HEADERS,
                params={"vs_currency":"usd","order":"volume_desc",
                        "per_page":100,"page":page,"sparkline":"false"},
                timeout=15,
            )
            r.raise_for_status()
            for c in r.json():
                vol   = c.get("total_volume") or 0
                price = c.get("current_price") or 0
                sym   = (c.get("symbol") or "").upper()
                if vol < MIN_DAILY_VOLUME or price < MIN_PRICE or not sym:
                    continue
                s = f"{sym}USDT"
                if s not in symbols:
                    symbols.append(s)
        except Exception as e:
            log.warning(f"CoinGecko page {page}: {e}")
            break
    return symbols[:150]


# ─── Layer B: OI Leaders ──────────────────────────────────────────────────────

def _oi_leaders(base: list[str], top_n: int = 30) -> list[str]:
    """OI עולה + מחיר לא זז = צבירה שקטה."""
    candidates = []
    for sym in base[:80]:
        try:
            r = requests.get(
                f"{_KUCOIN_FUT}/api/v1/contract/stats",
                headers=_HEADERS,
                params={"symbol": _kucoin_fut_sym(sym)},
                timeout=5,
            )
            if r.status_code != 200: continue
            d = r.json().get("data", {})
            oi_chg    = float(d.get("openInterestChange24h", 0) or 0)
            price_chg = abs(float(d.get("priceChgPct", 0) or 0) * 100)
            if oi_chg > 3.0 and price_chg < 3.0:
                candidates.append((oi_chg, sym))
        except Exception:
            continue
    candidates.sort(reverse=True)
    result = [s for _, s in candidates[:top_n]]
    if result: log.info(f"OI Leaders ({len(result)}): {result[:3]}")
    return result


# ─── Layer C: Compression ─────────────────────────────────────────────────────

def _compression_leaders(base: list[str], top_n: int = 20) -> list[str]:
    """ATR squeeze — שקט לפני סערה."""
    compressed = []
    for sym in base[:60]:
        try:
            df = get_candles(sym, "5min", limit=30)
            if df is None or len(df) < 25: continue
            h, l, c = df["high"], df["low"], df["close"]
            tr = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
            atr5  = float(tr.iloc[-5:].mean())
            atr20 = float(tr.iloc[-20:].mean())
            if atr20 > 0 and atr5 / atr20 < 0.65:
                compressed.append((atr5/atr20, sym))
        except Exception:
            continue
    compressed.sort()
    result = [s for _, s in compressed[:top_n]]
    if result: log.info(f"Compression Leaders ({len(result)}): {result[:3]}")
    return result


# ─── Layer D: RS Leaders ──────────────────────────────────────────────────────

def _rs_leaders(base: list[str], btc_1h_move: float, top_n: int = 20) -> list[str]:
    """מתחיל להכות BTC ב-1h."""
    if btc_1h_move == 0: return []
    rs_candidates = []
    for sym in base[:80]:
        try:
            df = get_candles(sym, "1hour", limit=5)
            if df is None or len(df) < 2: continue
            c       = df["close"]
            coin_1h = (float(c.iloc[-1]) - float(c.iloc[-2])) / float(c.iloc[-2]) * 100
            rs      = coin_1h - btc_1h_move
            if rs > 1.5:
                rs_candidates.append((rs, sym))
        except Exception:
            continue
    rs_candidates.sort(reverse=True)
    result = [s for _, s in rs_candidates[:top_n]]
    if result: log.info(f"RS Leaders ({len(result)}): {result[:3]}")
    return result


# ─── Main ─────────────────────────────────────────────────────────────────────

def build_dynamic_universe(btc_1h_move: float = 0.0) -> list[str]:
    """
    Union של כל השכבות — OI Leaders ראשון (הכי חשוב).
    """
    log.info("Building dynamic universe...")
    base   = _base_universe()
    oi_l   = _oi_leaders(base)
    comp_l = _compression_leaders(base)
    rs_l   = _rs_leaders(base, btc_1h_move)

    seen, result = set(), []
    for sym in oi_l + comp_l + rs_l + base:
        if sym in _BLACKLIST:
            continue
        if sym not in seen:
            seen.add(sym)
            result.append(sym)
        if len(result) >= MAX_SYMBOLS:
            break

    log.info(
        f"Dynamic Universe: {len(result)} "
        f"(OI:{len(oi_l)} Comp:{len(comp_l)} RS:{len(rs_l)} Base:{len(base)})"
    )
    return result
