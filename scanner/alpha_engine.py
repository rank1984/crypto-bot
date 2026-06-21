"""
CRYPTO-BOT Elite — Alpha Engine ⭐⭐⭐⭐⭐

"הלב של המערכת"

alpha_score = OI + CVD + Funding + RS_BTC + RS_ETH
            + Volume_Acceleration + Compression + Whale

0–100. זה מה שמפריד סורק רגיל ממנוע Flow מקצועי.

ההבדל מ-flow_engine:
    - flow_engine: חישוב גולמי של כל מרכיב בנפרד
    - alpha_engine: ציון אחד מנורמל עם משקלים מדויקים
                    + context awareness (regime-aware)
                    + signal quality filter
"""
from utils.logger import get_logger

log = get_logger(__name__)

# ─── משקלים ───────────────────────────────────────────────────────────────────
ALPHA_WEIGHTS = {
    "oi":           20,
    "cvd":          20,
    "funding":      10,
    "rs_btc":       10,
    "rs_eth":       10,
    "vol_accel":    10,
    "compression":  10,
    "whale":        10,
}


def calc_alpha_score(
    flow_components: dict,
    alignment_score: float = 50.0,
    regime:          str   = "RANGE",
    rs_btc_1h:       float = 0.0,
    rs_btc_4h:       float = 0.0,
) -> dict:
    """
    מחשב Alpha Score מנורמל.

    Parameters
    ----------
    flow_components : dict מ-flow_engine["components"]
        {"oi", "cvd", "funding", "rs", "vol_accel", "compression", "whale"}
    alignment_score : מ-alignment_engine
    regime          : מ-regime_engine
    rs_btc_1h/4h    : מ-relative_strength_engine

    Returns
    -------
    {
        "alpha_score":   float,   # 0–100
        "signal_quality": str,   # "STRONG" / "MODERATE" / "WEAK"
        "breakdown":     dict,   # תרומת כל מרכיב
        "edge_factors":  list,   # הגורמים הכי חזקים
    }
    """
    c = flow_components

    # ── ציונים גולמיים לכל מרכיב (0–1) ──────────────────────────────────────
    raw = {
        "oi":          min(1.0, c.get("oi",   0) / 20),
        "cvd":         min(1.0, c.get("cvd",  0) / 20),
        "funding":     min(1.0, c.get("funding", 0) / 10),
        "rs_btc":      min(1.0, max(0, rs_btc_1h) / 5),   # 5% = מלא
        "rs_eth":      min(1.0, c.get("rs",   0) / 20 * 0.5),
        "vol_accel":   min(1.0, c.get("vol_accel", 0) / 10),
        "compression": min(1.0, c.get("compression", 0) / 10),
        "whale":       min(1.0, c.get("whale", 0) / 10),
    }

    # ── Alpha Score משוקלל ───────────────────────────────────────────────────
    alpha = sum(raw[k] * ALPHA_WEIGHTS[k] for k in ALPHA_WEIGHTS)

    # ── Alignment Bonus (עד +8) ───────────────────────────────────────────────
    align_bonus = (alignment_score / 100) * 8
    alpha = min(100.0, alpha + align_bonus)

    # ── Regime Multiplier ────────────────────────────────────────────────────
    # בטרנד — אגרסיבי יותר. ב-Range — סלקטיבי.
    regime_mult = {
        "TRENDING_BULL": 1.05,
        "ALTSEASON":     1.03,
        "RANGE":         0.95,
        "RISK_OFF":      0.85,
        "TRENDING_BEAR": 0.75,
    }.get(regime, 1.0)

    alpha = min(100.0, alpha * regime_mult)

    # ── RS 4h Bonus (קונסיסטנטיות) ───────────────────────────────────────────
    if rs_btc_1h > 0 and rs_btc_4h > 0:
        alpha = min(100.0, alpha + 3)

    # ── Breakdown ─────────────────────────────────────────────────────────────
    breakdown = {
        k: round(raw[k] * ALPHA_WEIGHTS[k], 1)
        for k in ALPHA_WEIGHTS
    }

    # ── Edge Factors — הגורמים הכי חזקים ────────────────────────────────────
    edge_factors = [
        k for k, v in sorted(breakdown.items(), key=lambda x: -x[1])
        if v >= 5.0
    ]

    # ── Signal Quality ────────────────────────────────────────────────────────
    strong_signals = sum(1 for v in raw.values() if v >= 0.6)
    if alpha >= 75 and strong_signals >= 4:
        quality = "STRONG"
    elif alpha >= 55 and strong_signals >= 2:
        quality = "MODERATE"
    else:
        quality = "WEAK"

    result = {
        "alpha_score":    round(alpha, 1),
        "signal_quality": quality,
        "breakdown":      breakdown,
        "edge_factors":   edge_factors,
    }

    log.debug(
        f"Alpha: {alpha:.1f} | quality={quality} | "
        f"regime_mult={regime_mult} | edges={edge_factors[:3]}"
    )
    return result


def alpha_bonus(alpha_score: float) -> float:
    """בונוס לציון הסופי מבוסס alpha. מקסימום +10."""
    if alpha_score >= 80: return 10.0
    if alpha_score >= 65: return 6.0
    if alpha_score >= 50: return 3.0
    return 0.0
