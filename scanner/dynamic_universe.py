"""
CRYPTO-BOT Elite — Dynamic Universe Builder

לא רשימה קבועה — Universe חדש כל 2–5 דקות.

מועמדים מגיעים מ-5 שכבות:
    Layer A: Volume Leaders   — RVOL + Volume Acceleration
    Layer B: Flow Leaders     — OI + Funding
    Layer C: RS Leaders       — מול BTC ומול ETH
    Layer D: Compression      — ATR Compression
    Layer E: Base Universe    — Top 200 מ-CoinGecko (fallback)

Universe הסופי = union של כולם
"""
import requests
import pandas as pd
from utils.config import COINGECKO_BASE, MIN_DAILY_VOLUME, MIN_PRICE, MAX_SYMBOLS
from utils.logger import get_logger

log = get_logger(__name__)

_HEADERS = {"User-Agent": "crypto-bot/1.0"}
_TIMEOUT = 10

# Blacklist
_BLACKLIST = {
    "USDCUSDT","USDTUSDT","BUSDUSDT","TUSDUSDT","DAIUSDT",
    "FRAXUSDT","PYUSDUSDT","FDUSDUSDT","EURUSDT","GBPUSDT","USDDUSDT",
}


# ─── Layer A: Volume Leaders ───────────────────────────────────────────────────

def _volume_leaders(base_universe: list[str],
                    get_candles_fn) -> list[str]:
    """
    מ-base_universe מחזיר מטבעות עם RVOL > 2.
    גרסה מהירה: בודק רק 5m candles.
    """
    leaders = []
    sample  = base_universe[:50]   # בדוק רק 50 לחיסכון בזמן

    for sym in sample:
        try:
            df = get_candles_fn(sym, "5min", limit=25)
            if df is None or len(df) < 22:
                continue
            vol_last = float(df["volume"].iloc[-1])
            vol_avg  = float(df["volume"].iloc[-21:-1].mean())
            rvol = vol_last / vol_avg if vol_avg > 0 else 0
            if rvol >= 2.0:
                leaders.append(sym)
        except Exception:
            continue

    log.info(f"Volume leaders: {len(leaders)}")
    return leaders


# ─── Layer C: RS Leaders ───────────────────────────────────────────────────────

def _rs_leaders(base_universe: list[str],
                get_candles_fn,
                btc_1h_move: float) -> list[str]:
    """
    מחזיר מטבעות שזזו יותר מ-BTC ב-1h.
    """
    leaders = []
    sample  = base_universe[:80]

    for sym in sample:
        try:
            df = get_candles_fn(sym, "1hour", limit=5)
            if df is None or len(df) < 2:
                continue
            move = (float(df["close"].iloc[-1]) - float(df["close"].iloc[-2])) / float(df["close"].iloc[-2]) * 100
            if move > btc_1h_move + 1.0:   # עולה יותר מ-BTC ב-1%+
                leaders.append(sym)
        except Exception:
            continue

    log.info(f"RS leaders: {len(leaders)}")
    return leaders


# ─── Layer D: Compression Leaders ─────────────────────────────────────────────

def _compression_leaders(base_universe: list[str],
                          get_candles_fn) -> list[str]:
    """
    מחזיר מטבעות עם ATR compression — שקט לפני סערה.
    """
    leaders = []
    sample  = base_universe[:60]

    for sym in sample:
        try:
            df = get_candles_fn(sym, "5min", limit=25)
            if df is None or len(df) < 22:
                continue
            hi, lo, cl = df["high"], df["low"], df["close"]
            tr = pd.concat([
                hi - lo,
                (hi - cl.shift()).abs(),
                (lo - cl.shift()).abs(),
            ], axis=1).max(axis=1)

            atr_5  = float(tr.iloc[-5:].mean())
            atr_20 = float(tr.iloc[-20:].mean())
            if atr_20 > 0 and atr_5 / atr_20 < 0.65:
                leaders.append(sym)
        except Exception:
            continue

    log.info(f"Compression leaders: {len(leaders)}")
    return leaders


# ─── Base Universe (CoinGecko) ────────────────────────────────────────────────

def _base_universe() -> list[str]:
    symbols = []
    for page in range(1, 4):
        try:
            r = requests.get(
                f"{COINGECKO_BASE}/coins/markets",
                headers=_HEADERS,
                params={
                    "vs_currency": "usd",
                    "order":       "volume_desc",
                    "per_page":    100,
                    "page":        page,
                    "sparkline":   "false",
                },
                timeout=12,
            )
            r.raise_for_status()
            for c in r.json():
                vol    = c.get("total_volume") or 0
                price  = c.get("current_price") or 0
                symbol = (c.get("symbol") or "").upper() + "USDT"
                if vol < MIN_DAILY_VOLUME: continue
                if price < MIN_PRICE:      continue
                if symbol in _BLACKLIST:   continue
                if symbol not in symbols:
                    symbols.append(symbol)
        except Exception as e:
            log.warning(f"CoinGecko page {page}: {e}")
            break

    log.info(f"Base universe: {len(symbols)}")
    return symbols[:MAX_SYMBOLS]


# ─── Main Entry ───────────────────────────────────────────────────────────────

def build_dynamic_universe(
    get_candles_fn,
    btc_1h_move: float = 0.0,
    use_layers:  bool  = True,
) -> list[str]:
    """
    בונה Universe דינמי.

    Parameters
    ----------
    get_candles_fn : פונקציה מ-market_data.get_candles
    btc_1h_move    : % תנועת BTC ב-1h לLayer C
    use_layers     : False = base בלבד (מהיר יותר)

    Returns
    -------
    רשימת symbols ממוינת לפי עדיפות
    """
    log.info("Building dynamic universe...")

    base = _base_universe()
    if not base:
        log.error("Base universe empty")
        return []

    if not use_layers:
        return base

    # Layer A + C + D במקביל
    vol_l  = _volume_leaders(base, get_candles_fn)
    rs_l   = _rs_leaders(base, get_candles_fn, btc_1h_move)
    cmp_l  = _compression_leaders(base, get_candles_fn)

    # Union: priority leaders ראשונים
    priority = []
    seen     = set()

    for sym in vol_l + rs_l + cmp_l:
        if sym not in seen:
            priority.append(sym)
            seen.add(sym)

    # הוסף את ה-base שנשאר
    for sym in base:
        if sym not in seen:
            priority.append(sym)
            seen.add(sym)

    result = priority[:MAX_SYMBOLS]
    log.info(
        f"Dynamic universe: {len(result)} symbols "
        f"(vol={len(vol_l)} rs={len(rs_l)} cmp={len(cmp_l)} base={len(base)})"
    )
    return result
