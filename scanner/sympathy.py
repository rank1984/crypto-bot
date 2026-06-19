"""
CRYPTO-BOT Elite — Sympathy / Leader→Followers Engine

הלוגיקה:
    אם TAO זז +8% בשעה האחרונה → FET, RENDER, AKT עשויים לזוז אחריו.
    הסורק מוצא Leaders שכבר זזו, ומחזיר את ה-Followers שעדיין לא.

מבנה:
    SECTORS — קבוצות מטבעות קשורים
    find_leaders() — מי זז חזק עכשיו
    find_sympathy_plays() — מי בקבוצה שלו עדיין לא זז
"""
from scanner.market_data import get_candles
from utils.logger import get_logger

log = get_logger(__name__)

# ─── Sector Map ───────────────────────────────────────────────────────────────
# קבוצות מטבעות שנעים יחד היסטורית

SECTORS: dict[str, list[str]] = {
    "AI": [
        "FETUSDT", "TAOUSDT", "RENDERUSDT", "AKTUSDT",
        "AGIXUSDT", "OCEANUSDT", "NEIROUSDT", "WLDUSDT",
    ],
    "L1": [
        "SOLUSDT", "AVAXUSDT", "NEARUSDT", "APTUSDT",
        "SUIUSDT",  "SEIUSDT",  "INJUSDT",  "TONUSDT",
    ],
    "DeFi": [
        "UNIUSDT", "AAVEUSDT", "MKRUSDT", "CRVUSDT",
        "LDOUSDT",  "JUPUSDT",  "DYDXUSDT", "STRKUSDT",
    ],
    "Meme": [
        "PEPEUSDT", "WIFUSDT", "BONKUSDT", "FLOKIUSDT",
        "DOGEUSDT", "SHIBUSDT", "BOMEUSDT", "MEWUSDT",
    ],
    "Gaming": [
        "AXSUSDT", "SANDUSDT", "MANAUSDT", "IMXUSDT",
        "GALAUSDT", "YGGUSDT",  "RONUSDT",  "PIXELUSDT",
    ],
    "BTC_Eco": [
        "ORDIUSDT", "SATSUSDT", "RUNEUSDT", "STXUSDT",
    ],
    "RWA": [
        "ONDO usdt", "POLIXUSDT", "CFGUSDT", "TBTCUSDT",
    ],
}

# Leader threshold: כמה % עלייה נחשבת "Leader move"
LEADER_THRESHOLD_1H  = 3.0   # +3% ב-1h
LEADER_THRESHOLD_4H  = 6.0   # +6% ב-4h

# Follower threshold: עד כמה % הfollower כבר זז (אם זז יותר — כבר לא הזדמנות)
FOLLOWER_MAX_MOVE_1H = 2.0


# ─── helpers ──────────────────────────────────────────────────────────────────

def _get_move(symbol: str, n_candles: int, interval: str = "1hour") -> float:
    """% שינוי של n נרות אחורה."""
    df = get_candles(symbol, interval, limit=max(n_candles + 5, 20))
    if df is None or len(df) < n_candles + 1:
        return 0.0
    current = float(df["close"].iloc[-1])
    past    = float(df["close"].iloc[-(n_candles + 1)])
    return round((current - past) / past * 100, 2) if past != 0 else 0.0


# ─── Main Functions ───────────────────────────────────────────────────────────

def find_leaders(universe: list[str]) -> list[dict]:
    """
    מוצא מטבעות שזזו חזק ב-1h.
    מחזיר: [{"symbol": ..., "sector": ..., "move_1h": ..., "move_4h": ...}]
    """
    leaders = []

    # בנה מיפוי symbol→sector
    sym_to_sector = {}
    for sector, symbols in SECTORS.items():
        for sym in symbols:
            sym_to_sector[sym] = sector

    # סרוק רק מטבעות שנמצאים ב-Sectors
    sector_syms = {s for syms in SECTORS.values() for s in syms}
    candidates  = [s for s in universe if s in sector_syms]

    for sym in candidates:
        move_1h = _get_move(sym, 1, "1hour")
        if move_1h < LEADER_THRESHOLD_1H:
            continue
        move_4h = _get_move(sym, 4, "1hour")
        leaders.append({
            "symbol":  sym,
            "sector":  sym_to_sector.get(sym, "Unknown"),
            "move_1h": move_1h,
            "move_4h": move_4h,
        })
        log.info(f"Leader found: {sym} +{move_1h:.1f}% 1h (sector: {sym_to_sector.get(sym)})")

    leaders.sort(key=lambda x: x["move_1h"], reverse=True)
    return leaders


def find_sympathy_plays(leaders: list[dict],
                        universe: list[str]) -> list[dict]:
    """
    לכל Leader — מוצא את ה-Followers בסקטור שלו שעדיין לא זזו.

    מחזיר:
    [
        {
            "symbol":      "FETUSDT",
            "sector":      "AI",
            "leader":      "TAOUSDT",
            "leader_move": +10.2,
            "own_move_1h": +0.8,
            "sympathy_score": 85,
        }
    ]
    """
    if not leaders:
        return []

    plays = []
    seen  = set()

    for leader in leaders:
        sector   = leader["sector"]
        followers = SECTORS.get(sector, [])

        for sym in followers:
            if sym == leader["symbol"]: continue
            if sym in seen:             continue
            if sym not in universe:     continue

            own_move = _get_move(sym, 1, "1hour")

            # אם כבר זז יותר מדי — לא הזדמנות
            if own_move > FOLLOWER_MAX_MOVE_1H:
                continue

            # Sympathy Score: כמה "פיגור" יש לו ביחס ל-Leader
            lag  = leader["move_1h"] - own_move
            score = min(100.0, 50 + lag * 5)

            plays.append({
                "symbol":          sym,
                "sector":          sector,
                "leader":          leader["symbol"],
                "leader_move_1h":  leader["move_1h"],
                "own_move_1h":     own_move,
                "sympathy_score":  round(score, 1),
            })
            seen.add(sym)
            log.info(
                f"Sympathy play: {sym} (lag={lag:.1f}% behind {leader['symbol']})"
            )

    plays.sort(key=lambda x: x["sympathy_score"], reverse=True)
    return plays


def sympathy_bonus(symbol: str, plays: list[dict]) -> float:
    """
    מחזיר בונוס (0–15) לציון הסופי אם המטבע הוא Sympathy Play.
    """
    for p in plays:
        if p["symbol"] == symbol:
            return min(15.0, p["sympathy_score"] / 100 * 15)
    return 0.0
