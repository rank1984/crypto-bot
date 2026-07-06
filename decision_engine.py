"""
CRYPTO-BOT Elite — Decision Engine v2

4 רמות במקום "הכל או כלום":
    ELITE_BUY    (95+) — A+, פוזיציה מלאה
    BUY          (85+) — A,  פוזיציה מלאה
    SPECULATIVE  (70+) — B+, רבע פוזיציה
    WATCH        (50+) — B,  מעקב בלבד
    IGNORE       (<50) — C,  לא רלוונטי

Quality Gate מדורג: ניקוד במקום תנאים בינאריים.
RVOL דינמי לפי regime.
"""
from utils.logger import get_logger
log = get_logger(__name__)

# ─── Dynamic RVOL threshold ───────────────────────────────────────────────────

_RVOL_BY_REGIME = {
    "TRENDING_BULL": 1.2,
    "ALTSEASON":     1.0,
    "RANGE":         1.0,
    "RISK_OFF":      1.5,
    "TRENDING_BEAR": 2.0,
}

_RATING_ORDER = ["C","B","B+","A","A+"]


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _score(coin: dict, regime: str) -> tuple[int, list[str], list[str]]:
    """
    מחשב ציון איכות 0-100.
    מחזיר (score, positives, missing).
    """
    flow       = coin.get("flow_score", 0)
    pre        = coin.get("pre_score", 0)
    rvol       = coin.get("rvol", 0)
    oi         = coin.get("oi_change", 0)
    compressed = coin.get("is_compressed", False)
    rs_1h      = coin.get("rs_1h", 0)
    whale      = coin.get("whale_detected", False)
    vol_exp    = coin.get("vol_explosion", False)
    entry_dec  = coin.get("entry_decision", "NO")
    catalyst   = coin.get("has_catalyst", False)

    rvol_min = _RVOL_BY_REGIME.get(regime, 1.0)

    sc = 0
    pos, miss = [], []

    # Flow (25 נקודות)
    if flow >= 75:   sc += 25; pos.append(f"Flow חזק ({flow:.0f})")
    elif flow >= 60: sc += 18; pos.append(f"Flow ({flow:.0f})")
    elif flow >= 45: sc += 10; pos.append(f"Flow בינוני ({flow:.0f})")
    elif flow >= 30: sc += 4
    else:            miss.append(f"Flow חלש ({flow:.0f})")

    # OI (20 נקודות) — פחות קשיח: 0.5% מספיק
    if oi >= 5:      sc += 20; pos.append(f"OI חזק {oi:+.1f}%")
    elif oi >= 2:    sc += 14; pos.append(f"OI עולה {oi:+.1f}%")
    elif oi >= 0.5:  sc += 7;  pos.append(f"OI {oi:+.1f}%")
    else:            miss.append("OI לא עולה")

    # RVOL דינמי (20 נקודות)
    if rvol >= rvol_min * 2:  sc += 20; pos.append(f"💥 RVOL {rvol:.1f}x")
    elif rvol >= rvol_min:    sc += 13; pos.append(f"RVOL {rvol:.1f}x")
    elif rvol >= rvol_min*0.7:sc += 6
    else:                      miss.append(f"RVOL נמוך ({rvol:.1f}x, נדרש {rvol_min})")

    # Compression (15 → בונוס, לא חובה)
    if compressed:  sc += 15; pos.append("Compression")
    # else לא miss — רק בונוס

    # RS (10 נקודות)
    if rs_1h >= 2:   sc += 10; pos.append(f"חזק מ-BTC {rs_1h:+.1f}%")
    elif rs_1h >= 0: sc += 5;  pos.append("חוזק מ-BTC")
    else:             miss.append(f"חולשה מ-BTC ({rs_1h:.1f}%)")

    # Whale + Catalyst (10 נקודות)
    if whale:    sc += 5;  pos.append("פעילות לווייתנים")
    if catalyst: sc += 5;  pos.append("Catalyst")

    # Vol explosion (בונוס)
    if vol_exp:  sc += 5;  pos.append("💥 פיצוץ נפח")

    # Entry bonus
    if entry_dec == "BUY": sc += 5

    # Regime penalty
    if regime == "TRENDING_BEAR": sc = int(sc * 0.65)
    elif regime == "RISK_OFF":    sc = int(sc * 0.80)

    return min(100, sc), pos[:5], miss[:3]


# ─── Decision ─────────────────────────────────────────────────────────────────

def decide(coin: dict) -> dict:
    regime = coin.get("regime", "RANGE")
    sc, pos, miss = _score(coin, regime)

    # Rating
    if sc >= 90:   rating, decision = "A+", "ELITE_BUY"
    elif sc >= 80: rating, decision = "A",  "BUY"
    elif sc >= 65: rating, decision = "B+", "SPECULATIVE"
    elif sc >= 45: rating, decision = "B",  "WATCH"
    else:          rating, decision = "C",  "IGNORE"

    # Bear/Risk-Off: רק A+ עוברים
    if regime in ("TRENDING_BEAR", "RISK_OFF") and rating not in ("A+",):
        decision = "IGNORE"
        miss.append(f"נדרש A+ ב-{regime} (יש {rating})")

    # גודל פוזיציה מומלץ
    pos_size = {
        "ELITE_BUY":   "פוזיציה מלאה (5%)",
        "BUY":         "פוזיציה מלאה (3%)",
        "SPECULATIVE": "רבע פוזיציה (1%)",
        "WATCH":       "ללא פוזיציה",
        "IGNORE":      "ללא פוזיציה",
    }.get(decision, "")

    # Signal למיפוי עם שאר המערכת
    signal_map = {
        "ELITE_BUY": "BUY", "BUY": "BUY",
        "SPECULATIVE": "PREPARE", "WATCH": "WATCH", "IGNORE": "IGNORE"
    }

    reason = f"ציון {sc}/100 — {rating}"

    return {
        "decision":   decision,
        "rating":     rating,
        "confidence": sc,
        "reason":     reason,
        "missing":    miss,
        "positives":  pos,
        "pos_size":   pos_size,
        "signal":     signal_map[decision],
    }


def decide_batch(coins: list[dict]) -> list[dict]:
    for c in coins:
        r = decide(c)
        c.update({
            "decision":   r["decision"],
            "rating":     r["rating"],
            "confidence": r["confidence"],
            "reason":     r["reason"],
            "missing":    r["missing"],
            "positives":  r["positives"],
            "pos_size":   r["pos_size"],
            "signal":     r["signal"],
        })
    return coins"""
CRYPTO-BOT Elite — Decision Engine v2

4 רמות במקום "הכל או כלום":
    ELITE_BUY    (95+) — A+, פוזיציה מלאה
    BUY          (85+) — A,  פוזיציה מלאה
    SPECULATIVE  (70+) — B+, רבע פוזיציה
    WATCH        (50+) — B,  מעקב בלבד
    IGNORE       (<50) — C,  לא רלוונטי

Quality Gate מדורג: ניקוד במקום תנאים בינאריים.
RVOL דינמי לפי regime.
"""
from utils.logger import get_logger
log = get_logger(__name__)

# ─── Dynamic RVOL threshold ───────────────────────────────────────────────────

_RVOL_BY_REGIME = {
    "TRENDING_BULL": 1.2,
    "ALTSEASON":     1.0,
    "RANGE":         1.0,
    "RISK_OFF":      1.5,
    "TRENDING_BEAR": 2.0,
}

_RATING_ORDER = ["C","B","B+","A","A+"]


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _score(coin: dict, regime: str) -> tuple[int, list[str], list[str]]:
    """
    מחשב ציון איכות 0-100.
    מחזיר (score, positives, missing).
    """
    flow       = coin.get("flow_score", 0)
    pre        = coin.get("pre_score", 0)
    rvol       = coin.get("rvol", 0)
    oi         = coin.get("oi_change", 0)
    compressed = coin.get("is_compressed", False)
    rs_1h      = coin.get("rs_1h", 0)
    whale      = coin.get("whale_detected", False)
    vol_exp    = coin.get("vol_explosion", False)
    entry_dec  = coin.get("entry_decision", "NO")
    catalyst   = coin.get("has_catalyst", False)

    rvol_min = _RVOL_BY_REGIME.get(regime, 1.0)

    sc = 0
    pos, miss = [], []

    # Flow (25 נקודות)
    if flow >= 75:   sc += 25; pos.append(f"Flow חזק ({flow:.0f})")
    elif flow >= 60: sc += 18; pos.append(f"Flow ({flow:.0f})")
    elif flow >= 45: sc += 10; pos.append(f"Flow בינוני ({flow:.0f})")
    elif flow >= 30: sc += 4
    else:            miss.append(f"Flow חלש ({flow:.0f})")

    # OI (20 נקודות) — פחות קשיח: 0.5% מספיק
    if oi >= 5:      sc += 20; pos.append(f"OI חזק {oi:+.1f}%")
    elif oi >= 2:    sc += 14; pos.append(f"OI עולה {oi:+.1f}%")
    elif oi >= 0.5:  sc += 7;  pos.append(f"OI {oi:+.1f}%")
    else:            miss.append("OI לא עולה")

    # RVOL דינמי (20 נקודות)
    if rvol >= rvol_min * 2:  sc += 20; pos.append(f"💥 RVOL {rvol:.1f}x")
    elif rvol >= rvol_min:    sc += 13; pos.append(f"RVOL {rvol:.1f}x")
    elif rvol >= rvol_min*0.7:sc += 6
    else:                      miss.append(f"RVOL נמוך ({rvol:.1f}x, נדרש {rvol_min})")

    # Compression (15 → בונוס, לא חובה)
    if compressed:  sc += 15; pos.append("Compression")
    # else לא miss — רק בונוס

    # RS (10 נקודות)
    if rs_1h >= 2:   sc += 10; pos.append(f"חזק מ-BTC {rs_1h:+.1f}%")
    elif rs_1h >= 0: sc += 5;  pos.append("חוזק מ-BTC")
    else:             miss.append(f"חולשה מ-BTC ({rs_1h:.1f}%)")

    # Whale + Catalyst (10 נקודות)
    if whale:    sc += 5;  pos.append("פעילות לווייתנים")
    if catalyst: sc += 5;  pos.append("Catalyst")

    # Vol explosion (בונוס)
    if vol_exp:  sc += 5;  pos.append("💥 פיצוץ נפח")

    # Entry bonus
    if entry_dec == "BUY": sc += 5

    # Regime penalty
    if regime == "TRENDING_BEAR": sc = int(sc * 0.65)
    elif regime == "RISK_OFF":    sc = int(sc * 0.80)

    return min(100, sc), pos[:5], miss[:3]


# ─── Decision ─────────────────────────────────────────────────────────────────

def decide(coin: dict) -> dict:
    regime = coin.get("regime", "RANGE")
    sc, pos, miss = _score(coin, regime)

    # Rating
    if sc >= 90:   rating, decision = "A+", "ELITE_BUY"
    elif sc >= 80: rating, decision = "A",  "BUY"
    elif sc >= 65: rating, decision = "B+", "SPECULATIVE"
    elif sc >= 45: rating, decision = "B",  "WATCH"
    else:          rating, decision = "C",  "IGNORE"

    # Bear/Risk-Off: רק A+ עוברים
    if regime in ("TRENDING_BEAR", "RISK_OFF") and rating not in ("A+",):
        decision = "IGNORE"
        miss.append(f"נדרש A+ ב-{regime} (יש {rating})")

    # גודל פוזיציה מומלץ
    pos_size = {
        "ELITE_BUY":   "פוזיציה מלאה (5%)",
        "BUY":         "פוזיציה מלאה (3%)",
        "SPECULATIVE": "רבע פוזיציה (1%)",
        "WATCH":       "ללא פוזיציה",
        "IGNORE":      "ללא פוזיציה",
    }.get(decision, "")

    # Signal למיפוי עם שאר המערכת
    signal_map = {
        "ELITE_BUY": "BUY", "BUY": "BUY",
        "SPECULATIVE": "PREPARE", "WATCH": "WATCH", "IGNORE": "IGNORE"
    }

    reason = f"ציון {sc}/100 — {rating}"

    return {
        "decision":   decision,
        "rating":     rating,
        "confidence": sc,
        "reason":     reason,
        "missing":    miss,
        "positives":  pos,
        "pos_size":   pos_size,
        "signal":     signal_map[decision],
    }


def decide_batch(coins: list[dict]) -> list[dict]:
    for c in coins:
        r = decide(c)
        c.update({
            "decision":   r["decision"],
            "rating":     r["rating"],
            "confidence": r["confidence"],
            "reason":     r["reason"],
            "missing":    r["missing"],
            "positives":  r["positives"],
            "pos_size":   r["pos_size"],
            "signal":     r["signal"],
        })
    return coins"""
CRYPTO-BOT Elite — Decision Engine v2

4 רמות במקום "הכל או כלום":
    ELITE_BUY    (95+) — A+, פוזיציה מלאה
    BUY          (85+) — A,  פוזיציה מלאה
    SPECULATIVE  (70+) — B+, רבע פוזיציה
    WATCH        (50+) — B,  מעקב בלבד
    IGNORE       (<50) — C,  לא רלוונטי

Quality Gate מדורג: ניקוד במקום תנאים בינאריים.
RVOL דינמי לפי regime.
"""
from utils.logger import get_logger
log = get_logger(__name__)

# ─── Dynamic RVOL threshold ───────────────────────────────────────────────────

_RVOL_BY_REGIME = {
    "TRENDING_BULL": 1.2,
    "ALTSEASON":     1.0,
    "RANGE":         1.0,
    "RISK_OFF":      1.5,
    "TRENDING_BEAR": 2.0,
}

_RATING_ORDER = ["C","B","B+","A","A+"]


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _score(coin: dict, regime: str) -> tuple[int, list[str], list[str]]:
    """
    מחשב ציון איכות 0-100.
    מחזיר (score, positives, missing).
    """
    flow       = coin.get("flow_score", 0)
    pre        = coin.get("pre_score", 0)
    rvol       = coin.get("rvol", 0)
    oi         = coin.get("oi_change", 0)
    compressed = coin.get("is_compressed", False)
    rs_1h      = coin.get("rs_1h", 0)
    whale      = coin.get("whale_detected", False)
    vol_exp    = coin.get("vol_explosion", False)
    entry_dec  = coin.get("entry_decision", "NO")
    catalyst   = coin.get("has_catalyst", False)

    rvol_min = _RVOL_BY_REGIME.get(regime, 1.0)

    sc = 0
    pos, miss = [], []

    # Flow (25 נקודות)
    if flow >= 75:   sc += 25; pos.append(f"Flow חזק ({flow:.0f})")
    elif flow >= 60: sc += 18; pos.append(f"Flow ({flow:.0f})")
    elif flow >= 45: sc += 10; pos.append(f"Flow בינוני ({flow:.0f})")
    elif flow >= 30: sc += 4
    else:            miss.append(f"Flow חלש ({flow:.0f})")

    # OI (20 נקודות) — פחות קשיח: 0.5% מספיק
    if oi >= 5:      sc += 20; pos.append(f"OI חזק {oi:+.1f}%")
    elif oi >= 2:    sc += 14; pos.append(f"OI עולה {oi:+.1f}%")
    elif oi >= 0.5:  sc += 7;  pos.append(f"OI {oi:+.1f}%")
    else:            miss.append("OI לא עולה")

    # RVOL דינמי (20 נקודות)
    if rvol >= rvol_min * 2:  sc += 20; pos.append(f"💥 RVOL {rvol:.1f}x")
    elif rvol >= rvol_min:    sc += 13; pos.append(f"RVOL {rvol:.1f}x")
    elif rvol >= rvol_min*0.7:sc += 6
    else:                      miss.append(f"RVOL נמוך ({rvol:.1f}x, נדרש {rvol_min})")

    # Compression (15 → בונוס, לא חובה)
    if compressed:  sc += 15; pos.append("Compression")
    # else לא miss — רק בונוס

    # RS (10 נקודות)
    if rs_1h >= 2:   sc += 10; pos.append(f"חזק מ-BTC {rs_1h:+.1f}%")
    elif rs_1h >= 0: sc += 5;  pos.append("חוזק מ-BTC")
    else:             miss.append(f"חולשה מ-BTC ({rs_1h:.1f}%)")

    # Whale + Catalyst (10 נקודות)
    if whale:    sc += 5;  pos.append("פעילות לווייתנים")
    if catalyst: sc += 5;  pos.append("Catalyst")

    # Vol explosion (בונוס)
    if vol_exp:  sc += 5;  pos.append("💥 פיצוץ נפח")

    # Entry bonus
    if entry_dec == "BUY": sc += 5

    # Regime penalty
    if regime == "TRENDING_BEAR": sc = int(sc * 0.65)
    elif regime == "RISK_OFF":    sc = int(sc * 0.80)

    return min(100, sc), pos[:5], miss[:3]


# ─── Decision ─────────────────────────────────────────────────────────────────

def decide(coin: dict) -> dict:
    regime = coin.get("regime", "RANGE")
    sc, pos, miss = _score(coin, regime)

    # Rating
    if sc >= 90:   rating, decision = "A+", "ELITE_BUY"
    elif sc >= 80: rating, decision = "A",  "BUY"
    elif sc >= 65: rating, decision = "B+", "SPECULATIVE"
    elif sc >= 45: rating, decision = "B",  "WATCH"
    else:          rating, decision = "C",  "IGNORE"

    # Bear/Risk-Off: רק A+ עוברים
    if regime in ("TRENDING_BEAR", "RISK_OFF") and rating not in ("A+",):
        decision = "IGNORE"
        miss.append(f"נדרש A+ ב-{regime} (יש {rating})")

    # גודל פוזיציה מומלץ
    pos_size = {
        "ELITE_BUY":   "פוזיציה מלאה (5%)",
        "BUY":         "פוזיציה מלאה (3%)",
        "SPECULATIVE": "רבע פוזיציה (1%)",
        "WATCH":       "ללא פוזיציה",
        "IGNORE":      "ללא פוזיציה",
    }.get(decision, "")

    # Signal למיפוי עם שאר המערכת
    signal_map = {
        "ELITE_BUY": "BUY", "BUY": "BUY",
        "SPECULATIVE": "PREPARE", "WATCH": "WATCH", "IGNORE": "IGNORE"
    }

    reason = f"ציון {sc}/100 — {rating}"

    return {
        "decision":   decision,
        "rating":     rating,
        "confidence": sc,
        "reason":     reason,
        "missing":    miss,
        "positives":  pos,
        "pos_size":   pos_size,
        "signal":     signal_map[decision],
    }


def decide_batch(coins: list[dict]) -> list[dict]:
    for c in coins:
        r = decide(c)
        c.update({
            "decision":   r["decision"],
            "rating":     r["rating"],
            "confidence": r["confidence"],
            "reason":     r["reason"],
            "missing":    r["missing"],
            "positives":  r["positives"],
            "pos_size":   r["pos_size"],
            "signal":     r["signal"],
        })
    return coins"""
CRYPTO-BOT Elite — Decision Engine v2

4 רמות במקום "הכל או כלום":
    ELITE_BUY    (95+) — A+, פוזיציה מלאה
    BUY          (85+) — A,  פוזיציה מלאה
    SPECULATIVE  (70+) — B+, רבע פוזיציה
    WATCH        (50+) — B,  מעקב בלבד
    IGNORE       (<50) — C,  לא רלוונטי

Quality Gate מדורג: ניקוד במקום תנאים בינאריים.
RVOL דינמי לפי regime.
"""
from utils.logger import get_logger
log = get_logger(__name__)

# ─── Dynamic RVOL threshold ───────────────────────────────────────────────────

_RVOL_BY_REGIME = {
    "TRENDING_BULL": 1.2,
    "ALTSEASON":     1.0,
    "RANGE":         1.0,
    "RISK_OFF":      1.5,
    "TRENDING_BEAR": 2.0,
}

_RATING_ORDER = ["C","B","B+","A","A+"]


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _score(coin: dict, regime: str) -> tuple[int, list[str], list[str]]:
    """
    מחשב ציון איכות 0-100.
    מחזיר (score, positives, missing).
    """
    flow       = coin.get("flow_score", 0)
    pre        = coin.get("pre_score", 0)
    rvol       = coin.get("rvol", 0)
    oi         = coin.get("oi_change", 0)
    compressed = coin.get("is_compressed", False)
    rs_1h      = coin.get("rs_1h", 0)
    whale      = coin.get("whale_detected", False)
    vol_exp    = coin.get("vol_explosion", False)
    entry_dec  = coin.get("entry_decision", "NO")
    catalyst   = coin.get("has_catalyst", False)

    rvol_min = _RVOL_BY_REGIME.get(regime, 1.0)

    sc = 0
    pos, miss = [], []

    # Flow (25 נקודות)
    if flow >= 75:   sc += 25; pos.append(f"Flow חזק ({flow:.0f})")
    elif flow >= 60: sc += 18; pos.append(f"Flow ({flow:.0f})")
    elif flow >= 45: sc += 10; pos.append(f"Flow בינוני ({flow:.0f})")
    elif flow >= 30: sc += 4
    else:            miss.append(f"Flow חלש ({flow:.0f})")

    # OI (20 נקודות) — פחות קשיח: 0.5% מספיק
    if oi >= 5:      sc += 20; pos.append(f"OI חזק {oi:+.1f}%")
    elif oi >= 2:    sc += 14; pos.append(f"OI עולה {oi:+.1f}%")
    elif oi >= 0.5:  sc += 7;  pos.append(f"OI {oi:+.1f}%")
    else:            miss.append("OI לא עולה")

    # RVOL דינמי (20 נקודות)
    if rvol >= rvol_min * 2:  sc += 20; pos.append(f"💥 RVOL {rvol:.1f}x")
    elif rvol >= rvol_min:    sc += 13; pos.append(f"RVOL {rvol:.1f}x")
    elif rvol >= rvol_min*0.7:sc += 6
    else:                      miss.append(f"RVOL נמוך ({rvol:.1f}x, נדרש {rvol_min})")

    # Compression (15 → בונוס, לא חובה)
    if compressed:  sc += 15; pos.append("Compression")
    # else לא miss — רק בונוס

    # RS (10 נקודות)
    if rs_1h >= 2:   sc += 10; pos.append(f"חזק מ-BTC {rs_1h:+.1f}%")
    elif rs_1h >= 0: sc += 5;  pos.append("חוזק מ-BTC")
    else:             miss.append(f"חולשה מ-BTC ({rs_1h:.1f}%)")

    # Whale + Catalyst (10 נקודות)
    if whale:    sc += 5;  pos.append("פעילות לווייתנים")
    if catalyst: sc += 5;  pos.append("Catalyst")

    # Vol explosion (בונוס)
    if vol_exp:  sc += 5;  pos.append("💥 פיצוץ נפח")

    # Entry bonus
    if entry_dec == "BUY": sc += 5

    # Regime penalty
    if regime == "TRENDING_BEAR": sc = int(sc * 0.65)
    elif regime == "RISK_OFF":    sc = int(sc * 0.80)

    return min(100, sc), pos[:5], miss[:3]


# ─── Decision ─────────────────────────────────────────────────────────────────

def decide(coin: dict) -> dict:
    regime = coin.get("regime", "RANGE")
    sc, pos, miss = _score(coin, regime)

    # Rating
    if sc >= 90:   rating, decision = "A+", "ELITE_BUY"
    elif sc >= 80: rating, decision = "A",  "BUY"
    elif sc >= 65: rating, decision = "B+", "SPECULATIVE"
    elif sc >= 45: rating, decision = "B",  "WATCH"
    else:          rating, decision = "C",  "IGNORE"

    # Bear/Risk-Off: רק A+ עוברים
    if regime in ("TRENDING_BEAR", "RISK_OFF") and rating not in ("A+",):
        decision = "IGNORE"
        miss.append(f"נדרש A+ ב-{regime} (יש {rating})")

    # גודל פוזיציה מומלץ
    pos_size = {
        "ELITE_BUY":   "פוזיציה מלאה (5%)",
        "BUY":         "פוזיציה מלאה (3%)",
        "SPECULATIVE": "רבע פוזיציה (1%)",
        "WATCH":       "ללא פוזיציה",
        "IGNORE":      "ללא פוזיציה",
    }.get(decision, "")

    # Signal למיפוי עם שאר המערכת
    signal_map = {
        "ELITE_BUY": "BUY", "BUY": "BUY",
        "SPECULATIVE": "PREPARE", "WATCH": "WATCH", "IGNORE": "IGNORE"
    }

    reason = f"ציון {sc}/100 — {rating}"

    return {
        "decision":   decision,
        "rating":     rating,
        "confidence": sc,
        "reason":     reason,
        "missing":    miss,
        "positives":  pos,
        "pos_size":   pos_size,
        "signal":     signal_map[decision],
    }


def decide_batch(coins: list[dict]) -> list[dict]:
    for c in coins:
        r = decide(c)
        c.update({
            "decision":   r["decision"],
            "rating":     r["rating"],
            "confidence": r["confidence"],
            "reason":     r["reason"],
            "missing":    r["missing"],
            "positives":  r["positives"],
            "pos_size":   r["pos_size"],
            "signal":     r["signal"],
        })
    return coins"""
CRYPTO-BOT Elite — Decision Engine v2

4 רמות במקום "הכל או כלום":
    ELITE_BUY    (95+) — A+, פוזיציה מלאה
    BUY          (85+) — A,  פוזיציה מלאה
    SPECULATIVE  (70+) — B+, רבע פוזיציה
    WATCH        (50+) — B,  מעקב בלבד
    IGNORE       (<50) — C,  לא רלוונטי

Quality Gate מדורג: ניקוד במקום תנאים בינאריים.
RVOL דינמי לפי regime.
"""
from utils.logger import get_logger
log = get_logger(__name__)

# ─── Dynamic RVOL threshold ───────────────────────────────────────────────────

_RVOL_BY_REGIME = {
    "TRENDING_BULL": 1.2,
    "ALTSEASON":     1.0,
    "RANGE":         1.0,
    "RISK_OFF":      1.5,
    "TRENDING_BEAR": 2.0,
}

_RATING_ORDER = ["C","B","B+","A","A+"]


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _score(coin: dict, regime: str) -> tuple[int, list[str], list[str]]:
    """
    מחשב ציון איכות 0-100.
    מחזיר (score, positives, missing).
    """
    flow       = coin.get("flow_score", 0)
    pre        = coin.get("pre_score", 0)
    rvol       = coin.get("rvol", 0)
    oi         = coin.get("oi_change", 0)
    compressed = coin.get("is_compressed", False)
    rs_1h      = coin.get("rs_1h", 0)
    whale      = coin.get("whale_detected", False)
    vol_exp    = coin.get("vol_explosion", False)
    entry_dec  = coin.get("entry_decision", "NO")
    catalyst   = coin.get("has_catalyst", False)

    rvol_min = _RVOL_BY_REGIME.get(regime, 1.0)

    sc = 0
    pos, miss = [], []

    # Flow (25 נקודות)
    if flow >= 75:   sc += 25; pos.append(f"Flow חזק ({flow:.0f})")
    elif flow >= 60: sc += 18; pos.append(f"Flow ({flow:.0f})")
    elif flow >= 45: sc += 10; pos.append(f"Flow בינוני ({flow:.0f})")
    elif flow >= 30: sc += 4
    else:            miss.append(f"Flow חלש ({flow:.0f})")

    # OI (20 נקודות) — פחות קשיח: 0.5% מספיק
    if oi >= 5:      sc += 20; pos.append(f"OI חזק {oi:+.1f}%")
    elif oi >= 2:    sc += 14; pos.append(f"OI עולה {oi:+.1f}%")
    elif oi >= 0.5:  sc += 7;  pos.append(f"OI {oi:+.1f}%")
    else:            miss.append("OI לא עולה")

    # RVOL דינמי (20 נקודות)
    if rvol >= rvol_min * 2:  sc += 20; pos.append(f"💥 RVOL {rvol:.1f}x")
    elif rvol >= rvol_min:    sc += 13; pos.append(f"RVOL {rvol:.1f}x")
    elif rvol >= rvol_min*0.7:sc += 6
    else:                      miss.append(f"RVOL נמוך ({rvol:.1f}x, נדרש {rvol_min})")

    # Compression (15 → בונוס, לא חובה)
    if compressed:  sc += 15; pos.append("Compression")
    # else לא miss — רק בונוס

    # RS (10 נקודות)
    if rs_1h >= 2:   sc += 10; pos.append(f"חזק מ-BTC {rs_1h:+.1f}%")
    elif rs_1h >= 0: sc += 5;  pos.append("חוזק מ-BTC")
    else:             miss.append(f"חולשה מ-BTC ({rs_1h:.1f}%)")

    # Whale + Catalyst (10 נקודות)
    if whale:    sc += 5;  pos.append("פעילות לווייתנים")
    if catalyst: sc += 5;  pos.append("Catalyst")

    # Vol explosion (בונוס)
    if vol_exp:  sc += 5;  pos.append("💥 פיצוץ נפח")

    # Entry bonus
    if entry_dec == "BUY": sc += 5

    # Regime penalty
    if regime == "TRENDING_BEAR": sc = int(sc * 0.65)
    elif regime == "RISK_OFF":    sc = int(sc * 0.80)

    return min(100, sc), pos[:5], miss[:3]


# ─── Decision ─────────────────────────────────────────────────────────────────

def decide(coin: dict) -> dict:
    regime = coin.get("regime", "RANGE")
    sc, pos, miss = _score(coin, regime)

    # Rating
    if sc >= 90:   rating, decision = "A+", "ELITE_BUY"
    elif sc >= 80: rating, decision = "A",  "BUY"
    elif sc >= 65: rating, decision = "B+", "SPECULATIVE"
    elif sc >= 45: rating, decision = "B",  "WATCH"
    else:          rating, decision = "C",  "IGNORE"

    # Bear/Risk-Off: רק A+ עוברים
    if regime in ("TRENDING_BEAR", "RISK_OFF") and rating not in ("A+",):
        decision = "IGNORE"
        miss.append(f"נדרש A+ ב-{regime} (יש {rating})")

    # גודל פוזיציה מומלץ
    pos_size = {
        "ELITE_BUY":   "פוזיציה מלאה (5%)",
        "BUY":         "פוזיציה מלאה (3%)",
        "SPECULATIVE": "רבע פוזיציה (1%)",
        "WATCH":       "ללא פוזיציה",
        "IGNORE":      "ללא פוזיציה",
    }.get(decision, "")

    # Signal למיפוי עם שאר המערכת
    signal_map = {
        "ELITE_BUY": "BUY", "BUY": "BUY",
        "SPECULATIVE": "PREPARE", "WATCH": "WATCH", "IGNORE": "IGNORE"
    }

    reason = f"ציון {sc}/100 — {rating}"

    return {
        "decision":   decision,
        "rating":     rating,
        "confidence": sc,
        "reason":     reason,
        "missing":    miss,
        "positives":  pos,
        "pos_size":   pos_size,
        "signal":     signal_map[decision],
    }


def decide_batch(coins: list[dict]) -> list[dict]:
    for c in coins:
        r = decide(c)
        c.update({
            "decision":   r["decision"],
            "rating":     r["rating"],
            "confidence": r["confidence"],
            "reason":     r["reason"],
            "missing":    r["missing"],
            "positives":  r["positives"],
            "pos_size":   r["pos_size"],
            "signal":     r["signal"],
        })
    return coins"""
CRYPTO-BOT Elite — Decision Engine v2

4 רמות במקום "הכל או כלום":
    ELITE_BUY    (95+) — A+, פוזיציה מלאה
    BUY          (85+) — A,  פוזיציה מלאה
    SPECULATIVE  (70+) — B+, רבע פוזיציה
    WATCH        (50+) — B,  מעקב בלבד
    IGNORE       (<50) — C,  לא רלוונטי

Quality Gate מדורג: ניקוד במקום תנאים בינאריים.
RVOL דינמי לפי regime.
"""
from utils.logger import get_logger
log = get_logger(__name__)

# ─── Dynamic RVOL threshold ───────────────────────────────────────────────────

_RVOL_BY_REGIME = {
    "TRENDING_BULL": 1.2,
    "ALTSEASON":     1.0,
    "RANGE":         1.0,
    "RISK_OFF":      1.5,
    "TRENDING_BEAR": 2.0,
}

_RATING_ORDER = ["C","B","B+","A","A+"]


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _score(coin: dict, regime: str) -> tuple[int, list[str], list[str]]:
    """
    מחשב ציון איכות 0-100.
    מחזיר (score, positives, missing).
    """
    flow       = coin.get("flow_score", 0)
    pre        = coin.get("pre_score", 0)
    rvol       = coin.get("rvol", 0)
    oi         = coin.get("oi_change", 0)
    compressed = coin.get("is_compressed", False)
    rs_1h      = coin.get("rs_1h", 0)
    whale      = coin.get("whale_detected", False)
    vol_exp    = coin.get("vol_explosion", False)
    entry_dec  = coin.get("entry_decision", "NO")
    catalyst   = coin.get("has_catalyst", False)

    rvol_min = _RVOL_BY_REGIME.get(regime, 1.0)

    sc = 0
    pos, miss = [], []

    # Flow (25 נקודות)
    if flow >= 75:   sc += 25; pos.append(f"Flow חזק ({flow:.0f})")
    elif flow >= 60: sc += 18; pos.append(f"Flow ({flow:.0f})")
    elif flow >= 45: sc += 10; pos.append(f"Flow בינוני ({flow:.0f})")
    elif flow >= 30: sc += 4
    else:            miss.append(f"Flow חלש ({flow:.0f})")

    # OI (20 נקודות) — פחות קשיח: 0.5% מספיק
    if oi >= 5:      sc += 20; pos.append(f"OI חזק {oi:+.1f}%")
    elif oi >= 2:    sc += 14; pos.append(f"OI עולה {oi:+.1f}%")
    elif oi >= 0.5:  sc += 7;  pos.append(f"OI {oi:+.1f}%")
    else:            miss.append("OI לא עולה")

    # RVOL דינמי (20 נקודות)
    if rvol >= rvol_min * 2:  sc += 20; pos.append(f"💥 RVOL {rvol:.1f}x")
    elif rvol >= rvol_min:    sc += 13; pos.append(f"RVOL {rvol:.1f}x")
    elif rvol >= rvol_min*0.7:sc += 6
    else:                      miss.append(f"RVOL נמוך ({rvol:.1f}x, נדרש {rvol_min})")

    # Compression (15 → בונוס, לא חובה)
    if compressed:  sc += 15; pos.append("Compression")
    # else לא miss — רק בונוס

    # RS (10 נקודות)
    if rs_1h >= 2:   sc += 10; pos.append(f"חזק מ-BTC {rs_1h:+.1f}%")
    elif rs_1h >= 0: sc += 5;  pos.append("חוזק מ-BTC")
    else:             miss.append(f"חולשה מ-BTC ({rs_1h:.1f}%)")

    # Whale + Catalyst (10 נקודות)
    if whale:    sc += 5;  pos.append("פעילות לווייתנים")
    if catalyst: sc += 5;  pos.append("Catalyst")

    # Vol explosion (בונוס)
    if vol_exp:  sc += 5;  pos.append("💥 פיצוץ נפח")

    # Entry bonus
    if entry_dec == "BUY": sc += 5

    # Regime penalty
    if regime == "TRENDING_BEAR": sc = int(sc * 0.65)
    elif regime == "RISK_OFF":    sc = int(sc * 0.80)

    return min(100, sc), pos[:5], miss[:3]


# ─── Decision ─────────────────────────────────────────────────────────────────

def decide(coin: dict) -> dict:
    regime = coin.get("regime", "RANGE")
    sc, pos, miss = _score(coin, regime)

    # Rating
    if sc >= 90:   rating, decision = "A+", "ELITE_BUY"
    elif sc >= 80: rating, decision = "A",  "BUY"
    elif sc >= 65: rating, decision = "B+", "SPECULATIVE"
    elif sc >= 45: rating, decision = "B",  "WATCH"
    else:          rating, decision = "C",  "IGNORE"

    # Bear/Risk-Off: רק A+ עוברים
    if regime in ("TRENDING_BEAR", "RISK_OFF") and rating not in ("A+",):
        decision = "IGNORE"
        miss.append(f"נדרש A+ ב-{regime} (יש {rating})")

    # גודל פוזיציה מומלץ
    pos_size = {
        "ELITE_BUY":   "פוזיציה מלאה (5%)",
        "BUY":         "פוזיציה מלאה (3%)",
        "SPECULATIVE": "רבע פוזיציה (1%)",
        "WATCH":       "ללא פוזיציה",
        "IGNORE":      "ללא פוזיציה",
    }.get(decision, "")

    # Signal למיפוי עם שאר המערכת
    signal_map = {
        "ELITE_BUY": "BUY", "BUY": "BUY",
        "SPECULATIVE": "PREPARE", "WATCH": "WATCH", "IGNORE": "IGNORE"
    }

    reason = f"ציון {sc}/100 — {rating}"

    return {
        "decision":   decision,
        "rating":     rating,
        "confidence": sc,
        "reason":     reason,
        "missing":    miss,
        "positives":  pos,
        "pos_size":   pos_size,
        "signal":     signal_map[decision],
    }


def decide_batch(coins: list[dict]) -> list[dict]:
    for c in coins:
        r = decide(c)
        c.update({
            "decision":   r["decision"],
            "rating":     r["rating"],
            "confidence": r["confidence"],
            "reason":     r["reason"],
            "missing":    r["missing"],
            "positives":  r["positives"],
            "pos_size":   r["pos_size"],
            "signal":     r["signal"],
        })
    return coins"""
CRYPTO-BOT Elite — Decision Engine v2

4 רמות במקום "הכל או כלום":
    ELITE_BUY    (95+) — A+, פוזיציה מלאה
    BUY          (85+) — A,  פוזיציה מלאה
    SPECULATIVE  (70+) — B+, רבע פוזיציה
    WATCH        (50+) — B,  מעקב בלבד
    IGNORE       (<50) — C,  לא רלוונטי

Quality Gate מדורג: ניקוד במקום תנאים בינאריים.
RVOL דינמי לפי regime.
"""
from utils.logger import get_logger
log = get_logger(__name__)

# ─── Dynamic RVOL threshold ───────────────────────────────────────────────────

_RVOL_BY_REGIME = {
    "TRENDING_BULL": 1.2,
    "ALTSEASON":     1.0,
    "RANGE":         1.0,
    "RISK_OFF":      1.5,
    "TRENDING_BEAR": 2.0,
}

_RATING_ORDER = ["C","B","B+","A","A+"]


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _score(coin: dict, regime: str) -> tuple[int, list[str], list[str]]:
    """
    מחשב ציון איכות 0-100.
    מחזיר (score, positives, missing).
    """
    flow       = coin.get("flow_score", 0)
    pre        = coin.get("pre_score", 0)
    rvol       = coin.get("rvol", 0)
    oi         = coin.get("oi_change", 0)
    compressed = coin.get("is_compressed", False)
    rs_1h      = coin.get("rs_1h", 0)
    whale      = coin.get("whale_detected", False)
    vol_exp    = coin.get("vol_explosion", False)
    entry_dec  = coin.get("entry_decision", "NO")
    catalyst   = coin.get("has_catalyst", False)

    rvol_min = _RVOL_BY_REGIME.get(regime, 1.0)

    sc = 0
    pos, miss = [], []

    # Flow (25 נקודות)
    if flow >= 75:   sc += 25; pos.append(f"Flow חזק ({flow:.0f})")
    elif flow >= 60: sc += 18; pos.append(f"Flow ({flow:.0f})")
    elif flow >= 45: sc += 10; pos.append(f"Flow בינוני ({flow:.0f})")
    elif flow >= 30: sc += 4
    else:            miss.append(f"Flow חלש ({flow:.0f})")

    # OI (20 נקודות) — פחות קשיח: 0.5% מספיק
    if oi >= 5:      sc += 20; pos.append(f"OI חזק {oi:+.1f}%")
    elif oi >= 2:    sc += 14; pos.append(f"OI עולה {oi:+.1f}%")
    elif oi >= 0.5:  sc += 7;  pos.append(f"OI {oi:+.1f}%")
    else:            miss.append("OI לא עולה")

    # RVOL דינמי (20 נקודות)
    if rvol >= rvol_min * 2:  sc += 20; pos.append(f"💥 RVOL {rvol:.1f}x")
    elif rvol >= rvol_min:    sc += 13; pos.append(f"RVOL {rvol:.1f}x")
    elif rvol >= rvol_min*0.7:sc += 6
    else:                      miss.append(f"RVOL נמוך ({rvol:.1f}x, נדרש {rvol_min})")

    # Compression (15 → בונוס, לא חובה)
    if compressed:  sc += 15; pos.append("Compression")
    # else לא miss — רק בונוס

    # RS (10 נקודות)
    if rs_1h >= 2:   sc += 10; pos.append(f"חזק מ-BTC {rs_1h:+.1f}%")
    elif rs_1h >= 0: sc += 5;  pos.append("חוזק מ-BTC")
    else:             miss.append(f"חולשה מ-BTC ({rs_1h:.1f}%)")

    # Whale + Catalyst (10 נקודות)
    if whale:    sc += 5;  pos.append("פעילות לווייתנים")
    if catalyst: sc += 5;  pos.append("Catalyst")

    # Vol explosion (בונוס)
    if vol_exp:  sc += 5;  pos.append("💥 פיצוץ נפח")

    # Entry bonus
    if entry_dec == "BUY": sc += 5

    # Regime penalty
    if regime == "TRENDING_BEAR": sc = int(sc * 0.65)
    elif regime == "RISK_OFF":    sc = int(sc * 0.80)

    return min(100, sc), pos[:5], miss[:3]


# ─── Decision ─────────────────────────────────────────────────────────────────

def decide(coin: dict) -> dict:
    regime = coin.get("regime", "RANGE")
    sc, pos, miss = _score(coin, regime)

    # Rating
    if sc >= 90:   rating, decision = "A+", "ELITE_BUY"
    elif sc >= 80: rating, decision = "A",  "BUY"
    elif sc >= 65: rating, decision = "B+", "SPECULATIVE"
    elif sc >= 45: rating, decision = "B",  "WATCH"
    else:          rating, decision = "C",  "IGNORE"

    # Bear/Risk-Off: רק A+ עוברים
    if regime in ("TRENDING_BEAR", "RISK_OFF") and rating not in ("A+",):
        decision = "IGNORE"
        miss.append(f"נדרש A+ ב-{regime} (יש {rating})")

    # גודל פוזיציה מומלץ
    pos_size = {
        "ELITE_BUY":   "פוזיציה מלאה (5%)",
        "BUY":         "פוזיציה מלאה (3%)",
        "SPECULATIVE": "רבע פוזיציה (1%)",
        "WATCH":       "ללא פוזיציה",
        "IGNORE":      "ללא פוזיציה",
    }.get(decision, "")

    # Signal למיפוי עם שאר המערכת
    signal_map = {
        "ELITE_BUY": "BUY", "BUY": "BUY",
        "SPECULATIVE": "PREPARE", "WATCH": "WATCH", "IGNORE": "IGNORE"
    }

    reason = f"ציון {sc}/100 — {rating}"

    return {
        "decision":   decision,
        "rating":     rating,
        "confidence": sc,
        "reason":     reason,
        "missing":    miss,
        "positives":  pos,
        "pos_size":   pos_size,
        "signal":     signal_map[decision],
    }


def decide_batch(coins: list[dict]) -> list[dict]:
    for c in coins:
        r = decide(c)
        c.update({
            "decision":   r["decision"],
            "rating":     r["rating"],
            "confidence": r["confidence"],
            "reason":     r["reason"],
            "missing":    r["missing"],
            "positives":  r["positives"],
            "pos_size":   r["pos_size"],
            "signal":     r["signal"],
        })
    return coins"""
CRYPTO-BOT Elite — Decision Engine v2

4 רמות במקום "הכל או כלום":
    ELITE_BUY    (95+) — A+, פוזיציה מלאה
    BUY          (85+) — A,  פוזיציה מלאה
    SPECULATIVE  (70+) — B+, רבע פוזיציה
    WATCH        (50+) — B,  מעקב בלבד
    IGNORE       (<50) — C,  לא רלוונטי

Quality Gate מדורג: ניקוד במקום תנאים בינאריים.
RVOL דינמי לפי regime.
"""
from utils.logger import get_logger
log = get_logger(__name__)

# ─── Dynamic RVOL threshold ───────────────────────────────────────────────────

_RVOL_BY_REGIME = {
    "TRENDING_BULL": 1.2,
    "ALTSEASON":     1.0,
    "RANGE":         1.0,
    "RISK_OFF":      1.5,
    "TRENDING_BEAR": 2.0,
}

_RATING_ORDER = ["C","B","B+","A","A+"]


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _score(coin: dict, regime: str) -> tuple[int, list[str], list[str]]:
    """
    מחשב ציון איכות 0-100.
    מחזיר (score, positives, missing).
    """
    flow       = coin.get("flow_score", 0)
    pre        = coin.get("pre_score", 0)
    rvol       = coin.get("rvol", 0)
    oi         = coin.get("oi_change", 0)
    compressed = coin.get("is_compressed", False)
    rs_1h      = coin.get("rs_1h", 0)
    whale      = coin.get("whale_detected", False)
    vol_exp    = coin.get("vol_explosion", False)
    entry_dec  = coin.get("entry_decision", "NO")
    catalyst   = coin.get("has_catalyst", False)

    rvol_min = _RVOL_BY_REGIME.get(regime, 1.0)

    sc = 0
    pos, miss = [], []

    # Flow (25 נקודות)
    if flow >= 75:   sc += 25; pos.append(f"Flow חזק ({flow:.0f})")
    elif flow >= 60: sc += 18; pos.append(f"Flow ({flow:.0f})")
    elif flow >= 45: sc += 10; pos.append(f"Flow בינוני ({flow:.0f})")
    elif flow >= 30: sc += 4
    else:            miss.append(f"Flow חלש ({flow:.0f})")

    # OI (20 נקודות) — פחות קשיח: 0.5% מספיק
    if oi >= 5:      sc += 20; pos.append(f"OI חזק {oi:+.1f}%")
    elif oi >= 2:    sc += 14; pos.append(f"OI עולה {oi:+.1f}%")
    elif oi >= 0.5:  sc += 7;  pos.append(f"OI {oi:+.1f}%")
    else:            miss.append("OI לא עולה")

    # RVOL דינמי (20 נקודות)
    if rvol >= rvol_min * 2:  sc += 20; pos.append(f"💥 RVOL {rvol:.1f}x")
    elif rvol >= rvol_min:    sc += 13; pos.append(f"RVOL {rvol:.1f}x")
    elif rvol >= rvol_min*0.7:sc += 6
    else:                      miss.append(f"RVOL נמוך ({rvol:.1f}x, נדרש {rvol_min})")

    # Compression (15 → בונוס, לא חובה)
    if compressed:  sc += 15; pos.append("Compression")
    # else לא miss — רק בונוס

    # RS (10 נקודות)
    if rs_1h >= 2:   sc += 10; pos.append(f"חזק מ-BTC {rs_1h:+.1f}%")
    elif rs_1h >= 0: sc += 5;  pos.append("חוזק מ-BTC")
    else:             miss.append(f"חולשה מ-BTC ({rs_1h:.1f}%)")

    # Whale + Catalyst (10 נקודות)
    if whale:    sc += 5;  pos.append("פעילות לווייתנים")
    if catalyst: sc += 5;  pos.append("Catalyst")

    # Vol explosion (בונוס)
    if vol_exp:  sc += 5;  pos.append("💥 פיצוץ נפח")

    # Entry bonus
    if entry_dec == "BUY": sc += 5

    # Regime penalty
    if regime == "TRENDING_BEAR": sc = int(sc * 0.65)
    elif regime == "RISK_OFF":    sc = int(sc * 0.80)

    return min(100, sc), pos[:5], miss[:3]


# ─── Decision ─────────────────────────────────────────────────────────────────

def decide(coin: dict) -> dict:
    regime = coin.get("regime", "RANGE")
    sc, pos, miss = _score(coin, regime)

    # Rating
    if sc >= 90:   rating, decision = "A+", "ELITE_BUY"
    elif sc >= 80: rating, decision = "A",  "BUY"
    elif sc >= 65: rating, decision = "B+", "SPECULATIVE"
    elif sc >= 45: rating, decision = "B",  "WATCH"
    else:          rating, decision = "C",  "IGNORE"

    # Bear/Risk-Off: רק A+ עוברים
    if regime in ("TRENDING_BEAR", "RISK_OFF") and rating not in ("A+",):
        decision = "IGNORE"
        miss.append(f"נדרש A+ ב-{regime} (יש {rating})")

    # גודל פוזיציה מומלץ
    pos_size = {
        "ELITE_BUY":   "פוזיציה מלאה (5%)",
        "BUY":         "פוזיציה מלאה (3%)",
        "SPECULATIVE": "רבע פוזיציה (1%)",
        "WATCH":       "ללא פוזיציה",
        "IGNORE":      "ללא פוזיציה",
    }.get(decision, "")

    # Signal למיפוי עם שאר המערכת
    signal_map = {
        "ELITE_BUY": "BUY", "BUY": "BUY",
        "SPECULATIVE": "PREPARE", "WATCH": "WATCH", "IGNORE": "IGNORE"
    }

    reason = f"ציון {sc}/100 — {rating}"

    return {
        "decision":   decision,
        "rating":     rating,
        "confidence": sc,
        "reason":     reason,
        "missing":    miss,
        "positives":  pos,
        "pos_size":   pos_size,
        "signal":     signal_map[decision],
    }


def decide_batch(coins: list[dict]) -> list[dict]:
    for c in coins:
        r = decide(c)
        c.update({
            "decision":   r["decision"],
            "rating":     r["rating"],
            "confidence": r["confidence"],
            "reason":     r["reason"],
            "missing":    r["missing"],
            "positives":  r["positives"],
            "pos_size":   r["pos_size"],
            "signal":     r["signal"],
        })
    return coins"""
CRYPTO-BOT Elite — Decision Engine v2

4 רמות במקום "הכל או כלום":
    ELITE_BUY    (95+) — A+, פוזיציה מלאה
    BUY          (85+) — A,  פוזיציה מלאה
    SPECULATIVE  (70+) — B+, רבע פוזיציה
    WATCH        (50+) — B,  מעקב בלבד
    IGNORE       (<50) — C,  לא רלוונטי

Quality Gate מדורג: ניקוד במקום תנאים בינאריים.
RVOL דינמי לפי regime.
"""
from utils.logger import get_logger
log = get_logger(__name__)

# ─── Dynamic RVOL threshold ───────────────────────────────────────────────────

_RVOL_BY_REGIME = {
    "TRENDING_BULL": 1.2,
    "ALTSEASON":     1.0,
    "RANGE":         1.0,
    "RISK_OFF":      1.5,
    "TRENDING_BEAR": 2.0,
}

_RATING_ORDER = ["C","B","B+","A","A+"]


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _score(coin: dict, regime: str) -> tuple[int, list[str], list[str]]:
    """
    מחשב ציון איכות 0-100.
    מחזיר (score, positives, missing).
    """
    flow       = coin.get("flow_score", 0)
    pre        = coin.get("pre_score", 0)
    rvol       = coin.get("rvol", 0)
    oi         = coin.get("oi_change", 0)
    compressed = coin.get("is_compressed", False)
    rs_1h      = coin.get("rs_1h", 0)
    whale      = coin.get("whale_detected", False)
    vol_exp    = coin.get("vol_explosion", False)
    entry_dec  = coin.get("entry_decision", "NO")
    catalyst   = coin.get("has_catalyst", False)

    rvol_min = _RVOL_BY_REGIME.get(regime, 1.0)

    sc = 0
    pos, miss = [], []

    # Flow (25 נקודות)
    if flow >= 75:   sc += 25; pos.append(f"Flow חזק ({flow:.0f})")
    elif flow >= 60: sc += 18; pos.append(f"Flow ({flow:.0f})")
    elif flow >= 45: sc += 10; pos.append(f"Flow בינוני ({flow:.0f})")
    elif flow >= 30: sc += 4
    else:            miss.append(f"Flow חלש ({flow:.0f})")

    # OI (20 נקודות) — פחות קשיח: 0.5% מספיק
    if oi >= 5:      sc += 20; pos.append(f"OI חזק {oi:+.1f}%")
    elif oi >= 2:    sc += 14; pos.append(f"OI עולה {oi:+.1f}%")
    elif oi >= 0.5:  sc += 7;  pos.append(f"OI {oi:+.1f}%")
    else:            miss.append("OI לא עולה")

    # RVOL דינמי (20 נקודות)
    if rvol >= rvol_min * 2:  sc += 20; pos.append(f"💥 RVOL {rvol:.1f}x")
    elif rvol >= rvol_min:    sc += 13; pos.append(f"RVOL {rvol:.1f}x")
    elif rvol >= rvol_min*0.7:sc += 6
    else:                      miss.append(f"RVOL נמוך ({rvol:.1f}x, נדרש {rvol_min})")

    # Compression (15 → בונוס, לא חובה)
    if compressed:  sc += 15; pos.append("Compression")
    # else לא miss — רק בונוס

    # RS (10 נקודות)
    if rs_1h >= 2:   sc += 10; pos.append(f"חזק מ-BTC {rs_1h:+.1f}%")
    elif rs_1h >= 0: sc += 5;  pos.append("חוזק מ-BTC")
    else:             miss.append(f"חולשה מ-BTC ({rs_1h:.1f}%)")

    # Whale + Catalyst (10 נקודות)
    if whale:    sc += 5;  pos.append("פעילות לווייתנים")
    if catalyst: sc += 5;  pos.append("Catalyst")

    # Vol explosion (בונוס)
    if vol_exp:  sc += 5;  pos.append("💥 פיצוץ נפח")

    # Entry bonus
    if entry_dec == "BUY": sc += 5

    # Regime penalty
    if regime == "TRENDING_BEAR": sc = int(sc * 0.65)
    elif regime == "RISK_OFF":    sc = int(sc * 0.80)

    return min(100, sc), pos[:5], miss[:3]


# ─── Decision ─────────────────────────────────────────────────────────────────

def decide(coin: dict) -> dict:
    regime = coin.get("regime", "RANGE")
    sc, pos, miss = _score(coin, regime)

    # Rating
    if sc >= 90:   rating, decision = "A+", "ELITE_BUY"
    elif sc >= 80: rating, decision = "A",  "BUY"
    elif sc >= 65: rating, decision = "B+", "SPECULATIVE"
    elif sc >= 45: rating, decision = "B",  "WATCH"
    else:          rating, decision = "C",  "IGNORE"

    # Bear/Risk-Off: רק A+ עוברים
    if regime in ("TRENDING_BEAR", "RISK_OFF") and rating not in ("A+",):
        decision = "IGNORE"
        miss.append(f"נדרש A+ ב-{regime} (יש {rating})")

    # גודל פוזיציה מומלץ
    pos_size = {
        "ELITE_BUY":   "פוזיציה מלאה (5%)",
        "BUY":         "פוזיציה מלאה (3%)",
        "SPECULATIVE": "רבע פוזיציה (1%)",
        "WATCH":       "ללא פוזיציה",
        "IGNORE":      "ללא פוזיציה",
    }.get(decision, "")

    # Signal למיפוי עם שאר המערכת
    signal_map = {
        "ELITE_BUY": "BUY", "BUY": "BUY",
        "SPECULATIVE": "PREPARE", "WATCH": "WATCH", "IGNORE": "IGNORE"
    }

    reason = f"ציון {sc}/100 — {rating}"

    return {
        "decision":   decision,
        "rating":     rating,
        "confidence": sc,
        "reason":     reason,
        "missing":    miss,
        "positives":  pos,
        "pos_size":   pos_size,
        "signal":     signal_map[decision],
    }


def decide_batch(coins: list[dict]) -> list[dict]:
    for c in coins:
        r = decide(c)
        c.update({
            "decision":   r["decision"],
            "rating":     r["rating"],
            "confidence": r["confidence"],
            "reason":     r["reason"],
            "missing":    r["missing"],
            "positives":  r["positives"],
            "pos_size":   r["pos_size"],
            "signal":     r["signal"],
        })
    return coins"""
CRYPTO-BOT Elite — Decision Engine v2

4 רמות במקום "הכל או כלום":
    ELITE_BUY    (95+) — A+, פוזיציה מלאה
    BUY          (85+) — A,  פוזיציה מלאה
    SPECULATIVE  (70+) — B+, רבע פוזיציה
    WATCH        (50+) — B,  מעקב בלבד
    IGNORE       (<50) — C,  לא רלוונטי

Quality Gate מדורג: ניקוד במקום תנאים בינאריים.
RVOL דינמי לפי regime.
"""
from utils.logger import get_logger
log = get_logger(__name__)

# ─── Dynamic RVOL threshold ───────────────────────────────────────────────────

_RVOL_BY_REGIME = {
    "TRENDING_BULL": 1.2,
    "ALTSEASON":     1.0,
    "RANGE":         1.0,
    "RISK_OFF":      1.5,
    "TRENDING_BEAR": 2.0,
}

_RATING_ORDER = ["C","B","B+","A","A+"]


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _score(coin: dict, regime: str) -> tuple[int, list[str], list[str]]:
    """
    מחשב ציון איכות 0-100.
    מחזיר (score, positives, missing).
    """
    flow       = coin.get("flow_score", 0)
    pre        = coin.get("pre_score", 0)
    rvol       = coin.get("rvol", 0)
    oi         = coin.get("oi_change", 0)
    compressed = coin.get("is_compressed", False)
    rs_1h      = coin.get("rs_1h", 0)
    whale      = coin.get("whale_detected", False)
    vol_exp    = coin.get("vol_explosion", False)
    entry_dec  = coin.get("entry_decision", "NO")
    catalyst   = coin.get("has_catalyst", False)

    rvol_min = _RVOL_BY_REGIME.get(regime, 1.0)

    sc = 0
    pos, miss = [], []

    # Flow (25 נקודות)
    if flow >= 75:   sc += 25; pos.append(f"Flow חזק ({flow:.0f})")
    elif flow >= 60: sc += 18; pos.append(f"Flow ({flow:.0f})")
    elif flow >= 45: sc += 10; pos.append(f"Flow בינוני ({flow:.0f})")
    elif flow >= 30: sc += 4
    else:            miss.append(f"Flow חלש ({flow:.0f})")

    # OI (20 נקודות) — פחות קשיח: 0.5% מספיק
    if oi >= 5:      sc += 20; pos.append(f"OI חזק {oi:+.1f}%")
    elif oi >= 2:    sc += 14; pos.append(f"OI עולה {oi:+.1f}%")
    elif oi >= 0.5:  sc += 7;  pos.append(f"OI {oi:+.1f}%")
    else:            miss.append("OI לא עולה")

    # RVOL דינמי (20 נקודות)
    if rvol >= rvol_min * 2:  sc += 20; pos.append(f"💥 RVOL {rvol:.1f}x")
    elif rvol >= rvol_min:    sc += 13; pos.append(f"RVOL {rvol:.1f}x")
    elif rvol >= rvol_min*0.7:sc += 6
    else:                      miss.append(f"RVOL נמוך ({rvol:.1f}x, נדרש {rvol_min})")

    # Compression (15 → בונוס, לא חובה)
    if compressed:  sc += 15; pos.append("Compression")
    # else לא miss — רק בונוס

    # RS (10 נקודות)
    if rs_1h >= 2:   sc += 10; pos.append(f"חזק מ-BTC {rs_1h:+.1f}%")
    elif rs_1h >= 0: sc += 5;  pos.append("חוזק מ-BTC")
    else:             miss.append(f"חולשה מ-BTC ({rs_1h:.1f}%)")

    # Whale + Catalyst (10 נקודות)
    if whale:    sc += 5;  pos.append("פעילות לווייתנים")
    if catalyst: sc += 5;  pos.append("Catalyst")

    # Vol explosion (בונוס)
    if vol_exp:  sc += 5;  pos.append("💥 פיצוץ נפח")

    # Entry bonus
    if entry_dec == "BUY": sc += 5

    # Regime penalty
    if regime == "TRENDING_BEAR": sc = int(sc * 0.65)
    elif regime == "RISK_OFF":    sc = int(sc * 0.80)

    return min(100, sc), pos[:5], miss[:3]


# ─── Decision ─────────────────────────────────────────────────────────────────

def decide(coin: dict) -> dict:
    regime = coin.get("regime", "RANGE")
    sc, pos, miss = _score(coin, regime)

    # Rating
    if sc >= 90:   rating, decision = "A+", "ELITE_BUY"
    elif sc >= 80: rating, decision = "A",  "BUY"
    elif sc >= 65: rating, decision = "B+", "SPECULATIVE"
    elif sc >= 45: rating, decision = "B",  "WATCH"
    else:          rating, decision = "C",  "IGNORE"

    # Bear/Risk-Off: רק A+ עוברים
    if regime in ("TRENDING_BEAR", "RISK_OFF") and rating not in ("A+",):
        decision = "IGNORE"
        miss.append(f"נדרש A+ ב-{regime} (יש {rating})")

    # גודל פוזיציה מומלץ
    pos_size = {
        "ELITE_BUY":   "פוזיציה מלאה (5%)",
        "BUY":         "פוזיציה מלאה (3%)",
        "SPECULATIVE": "רבע פוזיציה (1%)",
        "WATCH":       "ללא פוזיציה",
        "IGNORE":      "ללא פוזיציה",
    }.get(decision, "")

    # Signal למיפוי עם שאר המערכת
    signal_map = {
        "ELITE_BUY": "BUY", "BUY": "BUY",
        "SPECULATIVE": "PREPARE", "WATCH": "WATCH", "IGNORE": "IGNORE"
    }

    reason = f"ציון {sc}/100 — {rating}"

    return {
        "decision":   decision,
        "rating":     rating,
        "confidence": sc,
        "reason":     reason,
        "missing":    miss,
        "positives":  pos,
        "pos_size":   pos_size,
        "signal":     signal_map[decision],
    }


def decide_batch(coins: list[dict]) -> list[dict]:
    for c in coins:
        r = decide(c)
        c.update({
            "decision":   r["decision"],
            "rating":     r["rating"],
            "confidence": r["confidence"],
            "reason":     r["reason"],
            "missing":    r["missing"],
            "positives":  r["positives"],
            "pos_size":   r["pos_size"],
            "signal":     r["signal"],
        })
    return coins"""
CRYPTO-BOT Elite — Decision Engine v2

4 רמות במקום "הכל או כלום":
    ELITE_BUY    (95+) — A+, פוזיציה מלאה
    BUY          (85+) — A,  פוזיציה מלאה
    SPECULATIVE  (70+) — B+, רבע פוזיציה
    WATCH        (50+) — B,  מעקב בלבד
    IGNORE       (<50) — C,  לא רלוונטי

Quality Gate מדורג: ניקוד במקום תנאים בינאריים.
RVOL דינמי לפי regime.
"""
from utils.logger import get_logger
log = get_logger(__name__)

# ─── Dynamic RVOL threshold ───────────────────────────────────────────────────

_RVOL_BY_REGIME = {
    "TRENDING_BULL": 1.2,
    "ALTSEASON":     1.0,
    "RANGE":         1.0,
    "RISK_OFF":      1.5,
    "TRENDING_BEAR": 2.0,
}

_RATING_ORDER = ["C","B","B+","A","A+"]


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _score(coin: dict, regime: str) -> tuple[int, list[str], list[str]]:
    """
    מחשב ציון איכות 0-100.
    מחזיר (score, positives, missing).
    """
    flow       = coin.get("flow_score", 0)
    pre        = coin.get("pre_score", 0)
    rvol       = coin.get("rvol", 0)
    oi         = coin.get("oi_change", 0)
    compressed = coin.get("is_compressed", False)
    rs_1h      = coin.get("rs_1h", 0)
    whale      = coin.get("whale_detected", False)
    vol_exp    = coin.get("vol_explosion", False)
    entry_dec  = coin.get("entry_decision", "NO")
    catalyst   = coin.get("has_catalyst", False)

    rvol_min = _RVOL_BY_REGIME.get(regime, 1.0)

    sc = 0
    pos, miss = [], []

    # Flow (25 נקודות)
    if flow >= 75:   sc += 25; pos.append(f"Flow חזק ({flow:.0f})")
    elif flow >= 60: sc += 18; pos.append(f"Flow ({flow:.0f})")
    elif flow >= 45: sc += 10; pos.append(f"Flow בינוני ({flow:.0f})")
    elif flow >= 30: sc += 4
    else:            miss.append(f"Flow חלש ({flow:.0f})")

    # OI (20 נקודות) — פחות קשיח: 0.5% מספיק
    if oi >= 5:      sc += 20; pos.append(f"OI חזק {oi:+.1f}%")
    elif oi >= 2:    sc += 14; pos.append(f"OI עולה {oi:+.1f}%")
    elif oi >= 0.5:  sc += 7;  pos.append(f"OI {oi:+.1f}%")
    else:            miss.append("OI לא עולה")

    # RVOL דינמי (20 נקודות)
    if rvol >= rvol_min * 2:  sc += 20; pos.append(f"💥 RVOL {rvol:.1f}x")
    elif rvol >= rvol_min:    sc += 13; pos.append(f"RVOL {rvol:.1f}x")
    elif rvol >= rvol_min*0.7:sc += 6
    else:                      miss.append(f"RVOL נמוך ({rvol:.1f}x, נדרש {rvol_min})")

    # Compression (15 → בונוס, לא חובה)
    if compressed:  sc += 15; pos.append("Compression")
    # else לא miss — רק בונוס

    # RS (10 נקודות)
    if rs_1h >= 2:   sc += 10; pos.append(f"חזק מ-BTC {rs_1h:+.1f}%")
    elif rs_1h >= 0: sc += 5;  pos.append("חוזק מ-BTC")
    else:             miss.append(f"חולשה מ-BTC ({rs_1h:.1f}%)")

    # Whale + Catalyst (10 נקודות)
    if whale:    sc += 5;  pos.append("פעילות לווייתנים")
    if catalyst: sc += 5;  pos.append("Catalyst")

    # Vol explosion (בונוס)
    if vol_exp:  sc += 5;  pos.append("💥 פיצוץ נפח")

    # Entry bonus
    if entry_dec == "BUY": sc += 5

    # Regime penalty
    if regime == "TRENDING_BEAR": sc = int(sc * 0.65)
    elif regime == "RISK_OFF":    sc = int(sc * 0.80)

    return min(100, sc), pos[:5], miss[:3]


# ─── Decision ─────────────────────────────────────────────────────────────────

def decide(coin: dict) -> dict:
    regime = coin.get("regime", "RANGE")
    sc, pos, miss = _score(coin, regime)

    # Rating
    if sc >= 90:   rating, decision = "A+", "ELITE_BUY"
    elif sc >= 80: rating, decision = "A",  "BUY"
    elif sc >= 65: rating, decision = "B+", "SPECULATIVE"
    elif sc >= 45: rating, decision = "B",  "WATCH"
    else:          rating, decision = "C",  "IGNORE"

    # Bear/Risk-Off: רק A+ עוברים
    if regime in ("TRENDING_BEAR", "RISK_OFF") and rating not in ("A+",):
        decision = "IGNORE"
        miss.append(f"נדרש A+ ב-{regime} (יש {rating})")

    # גודל פוזיציה מומלץ
    pos_size = {
        "ELITE_BUY":   "פוזיציה מלאה (5%)",
        "BUY":         "פוזיציה מלאה (3%)",
        "SPECULATIVE": "רבע פוזיציה (1%)",
        "WATCH":       "ללא פוזיציה",
        "IGNORE":      "ללא פוזיציה",
    }.get(decision, "")

    # Signal למיפוי עם שאר המערכת
    signal_map = {
        "ELITE_BUY": "BUY", "BUY": "BUY",
        "SPECULATIVE": "PREPARE", "WATCH": "WATCH", "IGNORE": "IGNORE"
    }

    reason = f"ציון {sc}/100 — {rating}"

    return {
        "decision":   decision,
        "rating":     rating,
        "confidence": sc,
        "reason":     reason,
        "missing":    miss,
        "positives":  pos,
        "pos_size":   pos_size,
        "signal":     signal_map[decision],
    }


def decide_batch(coins: list[dict]) -> list[dict]:
    for c in coins:
        r = decide(c)
        c.update({
            "decision":   r["decision"],
            "rating":     r["rating"],
            "confidence": r["confidence"],
            "reason":     r["reason"],
            "missing":    r["missing"],
            "positives":  r["positives"],
            "pos_size":   r["pos_size"],
            "signal":     r["signal"],
        })
    return coins"""
CRYPTO-BOT Elite — Decision Engine v2

4 רמות במקום "הכל או כלום":
    ELITE_BUY    (95+) — A+, פוזיציה מלאה
    BUY          (85+) — A,  פוזיציה מלאה
    SPECULATIVE  (70+) — B+, רבע פוזיציה
    WATCH        (50+) — B,  מעקב בלבד
    IGNORE       (<50) — C,  לא רלוונטי

Quality Gate מדורג: ניקוד במקום תנאים בינאריים.
RVOL דינמי לפי regime.
"""
from utils.logger import get_logger
log = get_logger(__name__)

# ─── Dynamic RVOL threshold ───────────────────────────────────────────────────

_RVOL_BY_REGIME = {
    "TRENDING_BULL": 1.2,
    "ALTSEASON":     1.0,
    "RANGE":         1.0,
    "RISK_OFF":      1.5,
    "TRENDING_BEAR": 2.0,
}

_RATING_ORDER = ["C","B","B+","A","A+"]


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _score(coin: dict, regime: str) -> tuple[int, list[str], list[str]]:
    """
    מחשב ציון איכות 0-100.
    מחזיר (score, positives, missing).
    """
    flow       = coin.get("flow_score", 0)
    pre        = coin.get("pre_score", 0)
    rvol       = coin.get("rvol", 0)
    oi         = coin.get("oi_change", 0)
    compressed = coin.get("is_compressed", False)
    rs_1h      = coin.get("rs_1h", 0)
    whale      = coin.get("whale_detected", False)
    vol_exp    = coin.get("vol_explosion", False)
    entry_dec  = coin.get("entry_decision", "NO")
    catalyst   = coin.get("has_catalyst", False)

    rvol_min = _RVOL_BY_REGIME.get(regime, 1.0)

    sc = 0
    pos, miss = [], []

    # Flow (25 נקודות)
    if flow >= 75:   sc += 25; pos.append(f"Flow חזק ({flow:.0f})")
    elif flow >= 60: sc += 18; pos.append(f"Flow ({flow:.0f})")
    elif flow >= 45: sc += 10; pos.append(f"Flow בינוני ({flow:.0f})")
    elif flow >= 30: sc += 4
    else:            miss.append(f"Flow חלש ({flow:.0f})")

    # OI (20 נקודות) — פחות קשיח: 0.5% מספיק
    if oi >= 5:      sc += 20; pos.append(f"OI חזק {oi:+.1f}%")
    elif oi >= 2:    sc += 14; pos.append(f"OI עולה {oi:+.1f}%")
    elif oi >= 0.5:  sc += 7;  pos.append(f"OI {oi:+.1f}%")
    else:            miss.append("OI לא עולה")

    # RVOL דינמי (20 נקודות)
    if rvol >= rvol_min * 2:  sc += 20; pos.append(f"💥 RVOL {rvol:.1f}x")
    elif rvol >= rvol_min:    sc += 13; pos.append(f"RVOL {rvol:.1f}x")
    elif rvol >= rvol_min*0.7:sc += 6
    else:                      miss.append(f"RVOL נמוך ({rvol:.1f}x, נדרש {rvol_min})")

    # Compression (15 → בונוס, לא חובה)
    if compressed:  sc += 15; pos.append("Compression")
    # else לא miss — רק בונוס

    # RS (10 נקודות)
    if rs_1h >= 2:   sc += 10; pos.append(f"חזק מ-BTC {rs_1h:+.1f}%")
    elif rs_1h >= 0: sc += 5;  pos.append("חוזק מ-BTC")
    else:             miss.append(f"חולשה מ-BTC ({rs_1h:.1f}%)")

    # Whale + Catalyst (10 נקודות)
    if whale:    sc += 5;  pos.append("פעילות לווייתנים")
    if catalyst: sc += 5;  pos.append("Catalyst")

    # Vol explosion (בונוס)
    if vol_exp:  sc += 5;  pos.append("💥 פיצוץ נפח")

    # Entry bonus
    if entry_dec == "BUY": sc += 5

    # Regime penalty
    if regime == "TRENDING_BEAR": sc = int(sc * 0.65)
    elif regime == "RISK_OFF":    sc = int(sc * 0.80)

    return min(100, sc), pos[:5], miss[:3]


# ─── Decision ─────────────────────────────────────────────────────────────────

def decide(coin: dict) -> dict:
    regime = coin.get("regime", "RANGE")
    sc, pos, miss = _score(coin, regime)

    # Rating
    if sc >= 90:   rating, decision = "A+", "ELITE_BUY"
    elif sc >= 80: rating, decision = "A",  "BUY"
    elif sc >= 65: rating, decision = "B+", "SPECULATIVE"
    elif sc >= 45: rating, decision = "B",  "WATCH"
    else:          rating, decision = "C",  "IGNORE"

    # Bear/Risk-Off: רק A+ עוברים
    if regime in ("TRENDING_BEAR", "RISK_OFF") and rating not in ("A+",):
        decision = "IGNORE"
        miss.append(f"נדרש A+ ב-{regime} (יש {rating})")

    # גודל פוזיציה מומלץ
    pos_size = {
        "ELITE_BUY":   "פוזיציה מלאה (5%)",
        "BUY":         "פוזיציה מלאה (3%)",
        "SPECULATIVE": "רבע פוזיציה (1%)",
        "WATCH":       "ללא פוזיציה",
        "IGNORE":      "ללא פוזיציה",
    }.get(decision, "")

    # Signal למיפוי עם שאר המערכת
    signal_map = {
        "ELITE_BUY": "BUY", "BUY": "BUY",
        "SPECULATIVE": "PREPARE", "WATCH": "WATCH", "IGNORE": "IGNORE"
    }

    reason = f"ציון {sc}/100 — {rating}"

    return {
        "decision":   decision,
        "rating":     rating,
        "confidence": sc,
        "reason":     reason,
        "missing":    miss,
        "positives":  pos,
        "pos_size":   pos_size,
        "signal":     signal_map[decision],
    }


def decide_batch(coins: list[dict]) -> list[dict]:
    for c in coins:
        r = decide(c)
        c.update({
            "decision":   r["decision"],
            "rating":     r["rating"],
            "confidence": r["confidence"],
            "reason":     r["reason"],
            "missing":    r["missing"],
            "positives":  r["positives"],
            "pos_size":   r["pos_size"],
            "signal":     r["signal"],
        })
    return coins"""
CRYPTO-BOT Elite — Decision Engine v2

4 רמות במקום "הכל או כלום":
    ELITE_BUY    (95+) — A+, פוזיציה מלאה
    BUY          (85+) — A,  פוזיציה מלאה
    SPECULATIVE  (70+) — B+, רבע פוזיציה
    WATCH        (50+) — B,  מעקב בלבד
    IGNORE       (<50) — C,  לא רלוונטי

Quality Gate מדורג: ניקוד במקום תנאים בינאריים.
RVOL דינמי לפי regime.
"""
from utils.logger import get_logger
log = get_logger(__name__)

# ─── Dynamic RVOL threshold ───────────────────────────────────────────────────

_RVOL_BY_REGIME = {
    "TRENDING_BULL": 1.2,
    "ALTSEASON":     1.0,
    "RANGE":         1.0,
    "RISK_OFF":      1.5,
    "TRENDING_BEAR": 2.0,
}

_RATING_ORDER = ["C","B","B+","A","A+"]


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _score(coin: dict, regime: str) -> tuple[int, list[str], list[str]]:
    """
    מחשב ציון איכות 0-100.
    מחזיר (score, positives, missing).
    """
    flow       = coin.get("flow_score", 0)
    pre        = coin.get("pre_score", 0)
    rvol       = coin.get("rvol", 0)
    oi         = coin.get("oi_change", 0)
    compressed = coin.get("is_compressed", False)
    rs_1h      = coin.get("rs_1h", 0)
    whale      = coin.get("whale_detected", False)
    vol_exp    = coin.get("vol_explosion", False)
    entry_dec  = coin.get("entry_decision", "NO")
    catalyst   = coin.get("has_catalyst", False)

    rvol_min = _RVOL_BY_REGIME.get(regime, 1.0)

    sc = 0
    pos, miss = [], []

    # Flow (25 נקודות)
    if flow >= 75:   sc += 25; pos.append(f"Flow חזק ({flow:.0f})")
    elif flow >= 60: sc += 18; pos.append(f"Flow ({flow:.0f})")
    elif flow >= 45: sc += 10; pos.append(f"Flow בינוני ({flow:.0f})")
    elif flow >= 30: sc += 4
    else:            miss.append(f"Flow חלש ({flow:.0f})")

    # OI (20 נקודות) — פחות קשיח: 0.5% מספיק
    if oi >= 5:      sc += 20; pos.append(f"OI חזק {oi:+.1f}%")
    elif oi >= 2:    sc += 14; pos.append(f"OI עולה {oi:+.1f}%")
    elif oi >= 0.5:  sc += 7;  pos.append(f"OI {oi:+.1f}%")
    else:            miss.append("OI לא עולה")

    # RVOL דינמי (20 נקודות)
    if rvol >= rvol_min * 2:  sc += 20; pos.append(f"💥 RVOL {rvol:.1f}x")
    elif rvol >= rvol_min:    sc += 13; pos.append(f"RVOL {rvol:.1f}x")
    elif rvol >= rvol_min*0.7:sc += 6
    else:                      miss.append(f"RVOL נמוך ({rvol:.1f}x, נדרש {rvol_min})")

    # Compression (15 → בונוס, לא חובה)
    if compressed:  sc += 15; pos.append("Compression")
    # else לא miss — רק בונוס

    # RS (10 נקודות)
    if rs_1h >= 2:   sc += 10; pos.append(f"חזק מ-BTC {rs_1h:+.1f}%")
    elif rs_1h >= 0: sc += 5;  pos.append("חוזק מ-BTC")
    else:             miss.append(f"חולשה מ-BTC ({rs_1h:.1f}%)")

    # Whale + Catalyst (10 נקודות)
    if whale:    sc += 5;  pos.append("פעילות לווייתנים")
    if catalyst: sc += 5;  pos.append("Catalyst")

    # Vol explosion (בונוס)
    if vol_exp:  sc += 5;  pos.append("💥 פיצוץ נפח")

    # Entry bonus
    if entry_dec == "BUY": sc += 5

    # Regime penalty
    if regime == "TRENDING_BEAR": sc = int(sc * 0.65)
    elif regime == "RISK_OFF":    sc = int(sc * 0.80)

    return min(100, sc), pos[:5], miss[:3]


# ─── Decision ─────────────────────────────────────────────────────────────────

def decide(coin: dict) -> dict:
    regime = coin.get("regime", "RANGE")
    sc, pos, miss = _score(coin, regime)

    # Rating
    if sc >= 90:   rating, decision = "A+", "ELITE_BUY"
    elif sc >= 80: rating, decision = "A",  "BUY"
    elif sc >= 65: rating, decision = "B+", "SPECULATIVE"
    elif sc >= 45: rating, decision = "B",  "WATCH"
    else:          rating, decision = "C",  "IGNORE"

    # Bear/Risk-Off: רק A+ עוברים
    if regime in ("TRENDING_BEAR", "RISK_OFF") and rating not in ("A+",):
        decision = "IGNORE"
        miss.append(f"נדרש A+ ב-{regime} (יש {rating})")

    # גודל פוזיציה מומלץ
    pos_size = {
        "ELITE_BUY":   "פוזיציה מלאה (5%)",
        "BUY":         "פוזיציה מלאה (3%)",
        "SPECULATIVE": "רבע פוזיציה (1%)",
        "WATCH":       "ללא פוזיציה",
        "IGNORE":      "ללא פוזיציה",
    }.get(decision, "")

    # Signal למיפוי עם שאר המערכת
    signal_map = {
        "ELITE_BUY": "BUY", "BUY": "BUY",
        "SPECULATIVE": "PREPARE", "WATCH": "WATCH", "IGNORE": "IGNORE"
    }

    reason = f"ציון {sc}/100 — {rating}"

    return {
        "decision":   decision,
        "rating":     rating,
        "confidence": sc,
        "reason":     reason,
        "missing":    miss,
        "positives":  pos,
        "pos_size":   pos_size,
        "signal":     signal_map[decision],
    }


def decide_batch(coins: list[dict]) -> list[dict]:
    for c in coins:
        r = decide(c)
        c.update({
            "decision":   r["decision"],
            "rating":     r["rating"],
            "confidence": r["confidence"],
            "reason":     r["reason"],
            "missing":    r["missing"],
            "positives":  r["positives"],
            "pos_size":   r["pos_size"],
            "signal":     r["signal"],
        })
    return coins"""
CRYPTO-BOT Elite — Decision Engine v2

4 רמות במקום "הכל או כלום":
    ELITE_BUY    (95+) — A+, פוזיציה מלאה
    BUY          (85+) — A,  פוזיציה מלאה
    SPECULATIVE  (70+) — B+, רבע פוזיציה
    WATCH        (50+) — B,  מעקב בלבד
    IGNORE       (<50) — C,  לא רלוונטי

Quality Gate מדורג: ניקוד במקום תנאים בינאריים.
RVOL דינמי לפי regime.
"""
from utils.logger import get_logger
log = get_logger(__name__)

# ─── Dynamic RVOL threshold ───────────────────────────────────────────────────

_RVOL_BY_REGIME = {
    "TRENDING_BULL": 1.2,
    "ALTSEASON":     1.0,
    "RANGE":         1.0,
    "RISK_OFF":      1.5,
    "TRENDING_BEAR": 2.0,
}

_RATING_ORDER = ["C","B","B+","A","A+"]


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _score(coin: dict, regime: str) -> tuple[int, list[str], list[str]]:
    """
    מחשב ציון איכות 0-100.
    מחזיר (score, positives, missing).
    """
    flow       = coin.get("flow_score", 0)
    pre        = coin.get("pre_score", 0)
    rvol       = coin.get("rvol", 0)
    oi         = coin.get("oi_change", 0)
    compressed = coin.get("is_compressed", False)
    rs_1h      = coin.get("rs_1h", 0)
    whale      = coin.get("whale_detected", False)
    vol_exp    = coin.get("vol_explosion", False)
    entry_dec  = coin.get("entry_decision", "NO")
    catalyst   = coin.get("has_catalyst", False)

    rvol_min = _RVOL_BY_REGIME.get(regime, 1.0)

    sc = 0
    pos, miss = [], []

    # Flow (25 נקודות)
    if flow >= 75:   sc += 25; pos.append(f"Flow חזק ({flow:.0f})")
    elif flow >= 60: sc += 18; pos.append(f"Flow ({flow:.0f})")
    elif flow >= 45: sc += 10; pos.append(f"Flow בינוני ({flow:.0f})")
    elif flow >= 30: sc += 4
    else:            miss.append(f"Flow חלש ({flow:.0f})")

    # OI (20 נקודות) — פחות קשיח: 0.5% מספיק
    if oi >= 5:      sc += 20; pos.append(f"OI חזק {oi:+.1f}%")
    elif oi >= 2:    sc += 14; pos.append(f"OI עולה {oi:+.1f}%")
    elif oi >= 0.5:  sc += 7;  pos.append(f"OI {oi:+.1f}%")
    else:            miss.append("OI לא עולה")

    # RVOL דינמי (20 נקודות)
    if rvol >= rvol_min * 2:  sc += 20; pos.append(f"💥 RVOL {rvol:.1f}x")
    elif rvol >= rvol_min:    sc += 13; pos.append(f"RVOL {rvol:.1f}x")
    elif rvol >= rvol_min*0.7:sc += 6
    else:                      miss.append(f"RVOL נמוך ({rvol:.1f}x, נדרש {rvol_min})")

    # Compression (15 → בונוס, לא חובה)
    if compressed:  sc += 15; pos.append("Compression")
    # else לא miss — רק בונוס

    # RS (10 נקודות)
    if rs_1h >= 2:   sc += 10; pos.append(f"חזק מ-BTC {rs_1h:+.1f}%")
    elif rs_1h >= 0: sc += 5;  pos.append("חוזק מ-BTC")
    else:             miss.append(f"חולשה מ-BTC ({rs_1h:.1f}%)")

    # Whale + Catalyst (10 נקודות)
    if whale:    sc += 5;  pos.append("פעילות לווייתנים")
    if catalyst: sc += 5;  pos.append("Catalyst")

    # Vol explosion (בונוס)
    if vol_exp:  sc += 5;  pos.append("💥 פיצוץ נפח")

    # Entry bonus
    if entry_dec == "BUY": sc += 5

    # Regime penalty
    if regime == "TRENDING_BEAR": sc = int(sc * 0.65)
    elif regime == "RISK_OFF":    sc = int(sc * 0.80)

    return min(100, sc), pos[:5], miss[:3]


# ─── Decision ─────────────────────────────────────────────────────────────────

def decide(coin: dict) -> dict:
    regime = coin.get("regime", "RANGE")
    sc, pos, miss = _score(coin, regime)

    # Rating
    if sc >= 90:   rating, decision = "A+", "ELITE_BUY"
    elif sc >= 80: rating, decision = "A",  "BUY"
    elif sc >= 65: rating, decision = "B+", "SPECULATIVE"
    elif sc >= 45: rating, decision = "B",  "WATCH"
    else:          rating, decision = "C",  "IGNORE"

    # Bear/Risk-Off: רק A+ עוברים
    if regime in ("TRENDING_BEAR", "RISK_OFF") and rating not in ("A+",):
        decision = "IGNORE"
        miss.append(f"נדרש A+ ב-{regime} (יש {rating})")

    # גודל פוזיציה מומלץ
    pos_size = {
        "ELITE_BUY":   "פוזיציה מלאה (5%)",
        "BUY":         "פוזיציה מלאה (3%)",
        "SPECULATIVE": "רבע פוזיציה (1%)",
        "WATCH":       "ללא פוזיציה",
        "IGNORE":      "ללא פוזיציה",
    }.get(decision, "")

    # Signal למיפוי עם שאר המערכת
    signal_map = {
        "ELITE_BUY": "BUY", "BUY": "BUY",
        "SPECULATIVE": "PREPARE", "WATCH": "WATCH", "IGNORE": "IGNORE"
    }

    reason = f"ציון {sc}/100 — {rating}"

    return {
        "decision":   decision,
        "rating":     rating,
        "confidence": sc,
        "reason":     reason,
        "missing":    miss,
        "positives":  pos,
        "pos_size":   pos_size,
        "signal":     signal_map[decision],
    }


def decide_batch(coins: list[dict]) -> list[dict]:
    for c in coins:
        r = decide(c)
        c.update({
            "decision":   r["decision"],
            "rating":     r["rating"],
            "confidence": r["confidence"],
            "reason":     r["reason"],
            "missing":    r["missing"],
            "positives":  r["positives"],
            "pos_size":   r["pos_size"],
            "signal":     r["signal"],
        })
    return coins"""
CRYPTO-BOT Elite — Decision Engine v2

4 רמות במקום "הכל או כלום":
    ELITE_BUY    (95+) — A+, פוזיציה מלאה
    BUY          (85+) — A,  פוזיציה מלאה
    SPECULATIVE  (70+) — B+, רבע פוזיציה
    WATCH        (50+) — B,  מעקב בלבד
    IGNORE       (<50) — C,  לא רלוונטי

Quality Gate מדורג: ניקוד במקום תנאים בינאריים.
RVOL דינמי לפי regime.
"""
from utils.logger import get_logger
log = get_logger(__name__)

# ─── Dynamic RVOL threshold ───────────────────────────────────────────────────

_RVOL_BY_REGIME = {
    "TRENDING_BULL": 1.2,
    "ALTSEASON":     1.0,
    "RANGE":         1.0,
    "RISK_OFF":      1.5,
    "TRENDING_BEAR": 2.0,
}

_RATING_ORDER = ["C","B","B+","A","A+"]


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _score(coin: dict, regime: str) -> tuple[int, list[str], list[str]]:
    """
    מחשב ציון איכות 0-100.
    מחזיר (score, positives, missing).
    """
    flow       = coin.get("flow_score", 0)
    pre        = coin.get("pre_score", 0)
    rvol       = coin.get("rvol", 0)
    oi         = coin.get("oi_change", 0)
    compressed = coin.get("is_compressed", False)
    rs_1h      = coin.get("rs_1h", 0)
    whale      = coin.get("whale_detected", False)
    vol_exp    = coin.get("vol_explosion", False)
    entry_dec  = coin.get("entry_decision", "NO")
    catalyst   = coin.get("has_catalyst", False)

    rvol_min = _RVOL_BY_REGIME.get(regime, 1.0)

    sc = 0
    pos, miss = [], []

    # Flow (25 נקודות)
    if flow >= 75:   sc += 25; pos.append(f"Flow חזק ({flow:.0f})")
    elif flow >= 60: sc += 18; pos.append(f"Flow ({flow:.0f})")
    elif flow >= 45: sc += 10; pos.append(f"Flow בינוני ({flow:.0f})")
    elif flow >= 30: sc += 4
    else:            miss.append(f"Flow חלש ({flow:.0f})")

    # OI (20 נקודות) — פחות קשיח: 0.5% מספיק
    if oi >= 5:      sc += 20; pos.append(f"OI חזק {oi:+.1f}%")
    elif oi >= 2:    sc += 14; pos.append(f"OI עולה {oi:+.1f}%")
    elif oi >= 0.5:  sc += 7;  pos.append(f"OI {oi:+.1f}%")
    else:            miss.append("OI לא עולה")

    # RVOL דינמי (20 נקודות)
    if rvol >= rvol_min * 2:  sc += 20; pos.append(f"💥 RVOL {rvol:.1f}x")
    elif rvol >= rvol_min:    sc += 13; pos.append(f"RVOL {rvol:.1f}x")
    elif rvol >= rvol_min*0.7:sc += 6
    else:                      miss.append(f"RVOL נמוך ({rvol:.1f}x, נדרש {rvol_min})")

    # Compression (15 → בונוס, לא חובה)
    if compressed:  sc += 15; pos.append("Compression")
    # else לא miss — רק בונוס

    # RS (10 נקודות)
    if rs_1h >= 2:   sc += 10; pos.append(f"חזק מ-BTC {rs_1h:+.1f}%")
    elif rs_1h >= 0: sc += 5;  pos.append("חוזק מ-BTC")
    else:             miss.append(f"חולשה מ-BTC ({rs_1h:.1f}%)")

    # Whale + Catalyst (10 נקודות)
    if whale:    sc += 5;  pos.append("פעילות לווייתנים")
    if catalyst: sc += 5;  pos.append("Catalyst")

    # Vol explosion (בונוס)
    if vol_exp:  sc += 5;  pos.append("💥 פיצוץ נפח")

    # Entry bonus
    if entry_dec == "BUY": sc += 5

    # Regime penalty
    if regime == "TRENDING_BEAR": sc = int(sc * 0.65)
    elif regime == "RISK_OFF":    sc = int(sc * 0.80)

    return min(100, sc), pos[:5], miss[:3]


# ─── Decision ─────────────────────────────────────────────────────────────────

def decide(coin: dict) -> dict:
    regime = coin.get("regime", "RANGE")
    sc, pos, miss = _score(coin, regime)

    # Rating
    if sc >= 90:   rating, decision = "A+", "ELITE_BUY"
    elif sc >= 80: rating, decision = "A",  "BUY"
    elif sc >= 65: rating, decision = "B+", "SPECULATIVE"
    elif sc >= 45: rating, decision = "B",  "WATCH"
    else:          rating, decision = "C",  "IGNORE"

    # Bear/Risk-Off: רק A+ עוברים
    if regime in ("TRENDING_BEAR", "RISK_OFF") and rating not in ("A+",):
        decision = "IGNORE"
        miss.append(f"נדרש A+ ב-{regime} (יש {rating})")

    # גודל פוזיציה מומלץ
    pos_size = {
        "ELITE_BUY":   "פוזיציה מלאה (5%)",
        "BUY":         "פוזיציה מלאה (3%)",
        "SPECULATIVE": "רבע פוזיציה (1%)",
        "WATCH":       "ללא פוזיציה",
        "IGNORE":      "ללא פוזיציה",
    }.get(decision, "")

    # Signal למיפוי עם שאר המערכת
    signal_map = {
        "ELITE_BUY": "BUY", "BUY": "BUY",
        "SPECULATIVE": "PREPARE", "WATCH": "WATCH", "IGNORE": "IGNORE"
    }

    reason = f"ציון {sc}/100 — {rating}"

    return {
        "decision":   decision,
        "rating":     rating,
        "confidence": sc,
        "reason":     reason,
        "missing":    miss,
        "positives":  pos,
        "pos_size":   pos_size,
        "signal":     signal_map[decision],
    }


def decide_batch(coins: list[dict]) -> list[dict]:
    for c in coins:
        r = decide(c)
        c.update({
            "decision":   r["decision"],
            "rating":     r["rating"],
            "confidence": r["confidence"],
            "reason":     r["reason"],
            "missing":    r["missing"],
            "positives":  r["positives"],
            "pos_size":   r["pos_size"],
            "signal":     r["signal"],
        })
    return coins"""
CRYPTO-BOT Elite — Decision Engine v2

4 רמות במקום "הכל או כלום":
    ELITE_BUY    (95+) — A+, פוזיציה מלאה
    BUY          (85+) — A,  פוזיציה מלאה
    SPECULATIVE  (70+) — B+, רבע פוזיציה
    WATCH        (50+) — B,  מעקב בלבד
    IGNORE       (<50) — C,  לא רלוונטי

Quality Gate מדורג: ניקוד במקום תנאים בינאריים.
RVOL דינמי לפי regime.
"""
from utils.logger import get_logger
log = get_logger(__name__)

# ─── Dynamic RVOL threshold ───────────────────────────────────────────────────

_RVOL_BY_REGIME = {
    "TRENDING_BULL": 1.2,
    "ALTSEASON":     1.0,
    "RANGE":         1.0,
    "RISK_OFF":      1.5,
    "TRENDING_BEAR": 2.0,
}

_RATING_ORDER = ["C","B","B+","A","A+"]


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _score(coin: dict, regime: str) -> tuple[int, list[str], list[str]]:
    """
    מחשב ציון איכות 0-100.
    מחזיר (score, positives, missing).
    """
    flow       = coin.get("flow_score", 0)
    pre        = coin.get("pre_score", 0)
    rvol       = coin.get("rvol", 0)
    oi         = coin.get("oi_change", 0)
    compressed = coin.get("is_compressed", False)
    rs_1h      = coin.get("rs_1h", 0)
    whale      = coin.get("whale_detected", False)
    vol_exp    = coin.get("vol_explosion", False)
    entry_dec  = coin.get("entry_decision", "NO")
    catalyst   = coin.get("has_catalyst", False)

    rvol_min = _RVOL_BY_REGIME.get(regime, 1.0)

    sc = 0
    pos, miss = [], []

    # Flow (25 נקודות)
    if flow >= 75:   sc += 25; pos.append(f"Flow חזק ({flow:.0f})")
    elif flow >= 60: sc += 18; pos.append(f"Flow ({flow:.0f})")
    elif flow >= 45: sc += 10; pos.append(f"Flow בינוני ({flow:.0f})")
    elif flow >= 30: sc += 4
    else:            miss.append(f"Flow חלש ({flow:.0f})")

    # OI (20 נקודות) — פחות קשיח: 0.5% מספיק
    if oi >= 5:      sc += 20; pos.append(f"OI חזק {oi:+.1f}%")
    elif oi >= 2:    sc += 14; pos.append(f"OI עולה {oi:+.1f}%")
    elif oi >= 0.5:  sc += 7;  pos.append(f"OI {oi:+.1f}%")
    else:            miss.append("OI לא עולה")

    # RVOL דינמי (20 נקודות)
    if rvol >= rvol_min * 2:  sc += 20; pos.append(f"💥 RVOL {rvol:.1f}x")
    elif rvol >= rvol_min:    sc += 13; pos.append(f"RVOL {rvol:.1f}x")
    elif rvol >= rvol_min*0.7:sc += 6
    else:                      miss.append(f"RVOL נמוך ({rvol:.1f}x, נדרש {rvol_min})")

    # Compression (15 → בונוס, לא חובה)
    if compressed:  sc += 15; pos.append("Compression")
    # else לא miss — רק בונוס

    # RS (10 נקודות)
    if rs_1h >= 2:   sc += 10; pos.append(f"חזק מ-BTC {rs_1h:+.1f}%")
    elif rs_1h >= 0: sc += 5;  pos.append("חוזק מ-BTC")
    else:             miss.append(f"חולשה מ-BTC ({rs_1h:.1f}%)")

    # Whale + Catalyst (10 נקודות)
    if whale:    sc += 5;  pos.append("פעילות לווייתנים")
    if catalyst: sc += 5;  pos.append("Catalyst")

    # Vol explosion (בונוס)
    if vol_exp:  sc += 5;  pos.append("💥 פיצוץ נפח")

    # Entry bonus
    if entry_dec == "BUY": sc += 5

    # Regime penalty
    if regime == "TRENDING_BEAR": sc = int(sc * 0.65)
    elif regime == "RISK_OFF":    sc = int(sc * 0.80)

    return min(100, sc), pos[:5], miss[:3]


# ─── Decision ─────────────────────────────────────────────────────────────────

def decide(coin: dict) -> dict:
    regime = coin.get("regime", "RANGE")
    sc, pos, miss = _score(coin, regime)

    # Rating
    if sc >= 90:   rating, decision = "A+", "ELITE_BUY"
    elif sc >= 80: rating, decision = "A",  "BUY"
    elif sc >= 65: rating, decision = "B+", "SPECULATIVE"
    elif sc >= 45: rating, decision = "B",  "WATCH"
    else:          rating, decision = "C",  "IGNORE"

    # Bear/Risk-Off: רק A+ עוברים
    if regime in ("TRENDING_BEAR", "RISK_OFF") and rating not in ("A+",):
        decision = "IGNORE"
        miss.append(f"נדרש A+ ב-{regime} (יש {rating})")

    # גודל פוזיציה מומלץ
    pos_size = {
        "ELITE_BUY":   "פוזיציה מלאה (5%)",
        "BUY":         "פוזיציה מלאה (3%)",
        "SPECULATIVE": "רבע פוזיציה (1%)",
        "WATCH":       "ללא פוזיציה",
        "IGNORE":      "ללא פוזיציה",
    }.get(decision, "")

    # Signal למיפוי עם שאר המערכת
    signal_map = {
        "ELITE_BUY": "BUY", "BUY": "BUY",
        "SPECULATIVE": "PREPARE", "WATCH": "WATCH", "IGNORE": "IGNORE"
    }

    reason = f"ציון {sc}/100 — {rating}"

    return {
        "decision":   decision,
        "rating":     rating,
        "confidence": sc,
        "reason":     reason,
        "missing":    miss,
        "positives":  pos,
        "pos_size":   pos_size,
        "signal":     signal_map[decision],
    }


def decide_batch(coins: list[dict]) -> list[dict]:
    for c in coins:
        r = decide(c)
        c.update({
            "decision":   r["decision"],
            "rating":     r["rating"],
            "confidence": r["confidence"],
            "reason":     r["reason"],
            "missing":    r["missing"],
            "positives":  r["positives"],
            "pos_size":   r["pos_size"],
            "signal":     r["signal"],
        })
    return coins"""
CRYPTO-BOT Elite — Decision Engine v2

4 רמות במקום "הכל או כלום":
    ELITE_BUY    (95+) — A+, פוזיציה מלאה
    BUY          (85+) — A,  פוזיציה מלאה
    SPECULATIVE  (70+) — B+, רבע פוזיציה
    WATCH        (50+) — B,  מעקב בלבד
    IGNORE       (<50) — C,  לא רלוונטי

Quality Gate מדורג: ניקוד במקום תנאים בינאריים.
RVOL דינמי לפי regime.
"""
from utils.logger import get_logger
log = get_logger(__name__)

# ─── Dynamic RVOL threshold ───────────────────────────────────────────────────

_RVOL_BY_REGIME = {
    "TRENDING_BULL": 1.2,
    "ALTSEASON":     1.0,
    "RANGE":         1.0,
    "RISK_OFF":      1.5,
    "TRENDING_BEAR": 2.0,
}

_RATING_ORDER = ["C","B","B+","A","A+"]


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _score(coin: dict, regime: str) -> tuple[int, list[str], list[str]]:
    """
    מחשב ציון איכות 0-100.
    מחזיר (score, positives, missing).
    """
    flow       = coin.get("flow_score", 0)
    pre        = coin.get("pre_score", 0)
    rvol       = coin.get("rvol", 0)
    oi         = coin.get("oi_change", 0)
    compressed = coin.get("is_compressed", False)
    rs_1h      = coin.get("rs_1h", 0)
    whale      = coin.get("whale_detected", False)
    vol_exp    = coin.get("vol_explosion", False)
    entry_dec  = coin.get("entry_decision", "NO")
    catalyst   = coin.get("has_catalyst", False)

    rvol_min = _RVOL_BY_REGIME.get(regime, 1.0)

    sc = 0
    pos, miss = [], []

    # Flow (25 נקודות)
    if flow >= 75:   sc += 25; pos.append(f"Flow חזק ({flow:.0f})")
    elif flow >= 60: sc += 18; pos.append(f"Flow ({flow:.0f})")
    elif flow >= 45: sc += 10; pos.append(f"Flow בינוני ({flow:.0f})")
    elif flow >= 30: sc += 4
    else:            miss.append(f"Flow חלש ({flow:.0f})")

    # OI (20 נקודות) — פחות קשיח: 0.5% מספיק
    if oi >= 5:      sc += 20; pos.append(f"OI חזק {oi:+.1f}%")
    elif oi >= 2:    sc += 14; pos.append(f"OI עולה {oi:+.1f}%")
    elif oi >= 0.5:  sc += 7;  pos.append(f"OI {oi:+.1f}%")
    else:            miss.append("OI לא עולה")

    # RVOL דינמי (20 נקודות)
    if rvol >= rvol_min * 2:  sc += 20; pos.append(f"💥 RVOL {rvol:.1f}x")
    elif rvol >= rvol_min:    sc += 13; pos.append(f"RVOL {rvol:.1f}x")
    elif rvol >= rvol_min*0.7:sc += 6
    else:                      miss.append(f"RVOL נמוך ({rvol:.1f}x, נדרש {rvol_min})")

    # Compression (15 → בונוס, לא חובה)
    if compressed:  sc += 15; pos.append("Compression")
    # else לא miss — רק בונוס

    # RS (10 נקודות)
    if rs_1h >= 2:   sc += 10; pos.append(f"חזק מ-BTC {rs_1h:+.1f}%")
    elif rs_1h >= 0: sc += 5;  pos.append("חוזק מ-BTC")
    else:             miss.append(f"חולשה מ-BTC ({rs_1h:.1f}%)")

    # Whale + Catalyst (10 נקודות)
    if whale:    sc += 5;  pos.append("פעילות לווייתנים")
    if catalyst: sc += 5;  pos.append("Catalyst")

    # Vol explosion (בונוס)
    if vol_exp:  sc += 5;  pos.append("💥 פיצוץ נפח")

    # Entry bonus
    if entry_dec == "BUY": sc += 5

    # Regime penalty
    if regime == "TRENDING_BEAR": sc = int(sc * 0.65)
    elif regime == "RISK_OFF":    sc = int(sc * 0.80)

    return min(100, sc), pos[:5], miss[:3]


# ─── Decision ─────────────────────────────────────────────────────────────────

def decide(coin: dict) -> dict:
    regime = coin.get("regime", "RANGE")
    sc, pos, miss = _score(coin, regime)

    # Rating
    if sc >= 90:   rating, decision = "A+", "ELITE_BUY"
    elif sc >= 80: rating, decision = "A",  "BUY"
    elif sc >= 65: rating, decision = "B+", "SPECULATIVE"
    elif sc >= 45: rating, decision = "B",  "WATCH"
    else:          rating, decision = "C",  "IGNORE"

    # Bear/Risk-Off: רק A+ עוברים
    if regime in ("TRENDING_BEAR", "RISK_OFF") and rating not in ("A+",):
        decision = "IGNORE"
        miss.append(f"נדרש A+ ב-{regime} (יש {rating})")

    # גודל פוזיציה מומלץ
    pos_size = {
        "ELITE_BUY":   "פוזיציה מלאה (5%)",
        "BUY":         "פוזיציה מלאה (3%)",
        "SPECULATIVE": "רבע פוזיציה (1%)",
        "WATCH":       "ללא פוזיציה",
        "IGNORE":      "ללא פוזיציה",
    }.get(decision, "")

    # Signal למיפוי עם שאר המערכת
    signal_map = {
        "ELITE_BUY": "BUY", "BUY": "BUY",
        "SPECULATIVE": "PREPARE", "WATCH": "WATCH", "IGNORE": "IGNORE"
    }

    reason = f"ציון {sc}/100 — {rating}"

    return {
        "decision":   decision,
        "rating":     rating,
        "confidence": sc,
        "reason":     reason,
        "missing":    miss,
        "positives":  pos,
        "pos_size":   pos_size,
        "signal":     signal_map[decision],
    }


def decide_batch(coins: list[dict]) -> list[dict]:
    for c in coins:
        r = decide(c)
        c.update({
            "decision":   r["decision"],
            "rating":     r["rating"],
            "confidence": r["confidence"],
            "reason":     r["reason"],
            "missing":    r["missing"],
            "positives":  r["positives"],
            "pos_size":   r["pos_size"],
            "signal":     r["signal"],
        })
    return coins"""
CRYPTO-BOT Elite — Decision Engine v2

4 רמות במקום "הכל או כלום":
    ELITE_BUY    (95+) — A+, פוזיציה מלאה
    BUY          (85+) — A,  פוזיציה מלאה
    SPECULATIVE  (70+) — B+, רבע פוזיציה
    WATCH        (50+) — B,  מעקב בלבד
    IGNORE       (<50) — C,  לא רלוונטי

Quality Gate מדורג: ניקוד במקום תנאים בינאריים.
RVOL דינמי לפי regime.
"""
from utils.logger import get_logger
log = get_logger(__name__)

# ─── Dynamic RVOL threshold ───────────────────────────────────────────────────

_RVOL_BY_REGIME = {
    "TRENDING_BULL": 1.2,
    "ALTSEASON":     1.0,
    "RANGE":         1.0,
    "RISK_OFF":      1.5,
    "TRENDING_BEAR": 2.0,
}

_RATING_ORDER = ["C","B","B+","A","A+"]


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _score(coin: dict, regime: str) -> tuple[int, list[str], list[str]]:
    """
    מחשב ציון איכות 0-100.
    מחזיר (score, positives, missing).
    """
    flow       = coin.get("flow_score", 0)
    pre        = coin.get("pre_score", 0)
    rvol       = coin.get("rvol", 0)
    oi         = coin.get("oi_change", 0)
    compressed = coin.get("is_compressed", False)
    rs_1h      = coin.get("rs_1h", 0)
    whale      = coin.get("whale_detected", False)
    vol_exp    = coin.get("vol_explosion", False)
    entry_dec  = coin.get("entry_decision", "NO")
    catalyst   = coin.get("has_catalyst", False)

    rvol_min = _RVOL_BY_REGIME.get(regime, 1.0)

    sc = 0
    pos, miss = [], []

    # Flow (25 נקודות)
    if flow >= 75:   sc += 25; pos.append(f"Flow חזק ({flow:.0f})")
    elif flow >= 60: sc += 18; pos.append(f"Flow ({flow:.0f})")
    elif flow >= 45: sc += 10; pos.append(f"Flow בינוני ({flow:.0f})")
    elif flow >= 30: sc += 4
    else:            miss.append(f"Flow חלש ({flow:.0f})")

    # OI (20 נקודות) — פחות קשיח: 0.5% מספיק
    if oi >= 5:      sc += 20; pos.append(f"OI חזק {oi:+.1f}%")
    elif oi >= 2:    sc += 14; pos.append(f"OI עולה {oi:+.1f}%")
    elif oi >= 0.5:  sc += 7;  pos.append(f"OI {oi:+.1f}%")
    else:            miss.append("OI לא עולה")

    # RVOL דינמי (20 נקודות)
    if rvol >= rvol_min * 2:  sc += 20; pos.append(f"💥 RVOL {rvol:.1f}x")
    elif rvol >= rvol_min:    sc += 13; pos.append(f"RVOL {rvol:.1f}x")
    elif rvol >= rvol_min*0.7:sc += 6
    else:                      miss.append(f"RVOL נמוך ({rvol:.1f}x, נדרש {rvol_min})")

    # Compression (15 → בונוס, לא חובה)
    if compressed:  sc += 15; pos.append("Compression")
    # else לא miss — רק בונוס

    # RS (10 נקודות)
    if rs_1h >= 2:   sc += 10; pos.append(f"חזק מ-BTC {rs_1h:+.1f}%")
    elif rs_1h >= 0: sc += 5;  pos.append("חוזק מ-BTC")
    else:             miss.append(f"חולשה מ-BTC ({rs_1h:.1f}%)")

    # Whale + Catalyst (10 נקודות)
    if whale:    sc += 5;  pos.append("פעילות לווייתנים")
    if catalyst: sc += 5;  pos.append("Catalyst")

    # Vol explosion (בונוס)
    if vol_exp:  sc += 5;  pos.append("💥 פיצוץ נפח")

    # Entry bonus
    if entry_dec == "BUY": sc += 5

    # Regime penalty
    if regime == "TRENDING_BEAR": sc = int(sc * 0.65)
    elif regime == "RISK_OFF":    sc = int(sc * 0.80)

    return min(100, sc), pos[:5], miss[:3]


# ─── Decision ─────────────────────────────────────────────────────────────────

def decide(coin: dict) -> dict:
    regime = coin.get("regime", "RANGE")
    sc, pos, miss = _score(coin, regime)

    # Rating
    if sc >= 90:   rating, decision = "A+", "ELITE_BUY"
    elif sc >= 80: rating, decision = "A",  "BUY"
    elif sc >= 65: rating, decision = "B+", "SPECULATIVE"
    elif sc >= 45: rating, decision = "B",  "WATCH"
    else:          rating, decision = "C",  "IGNORE"

    # Bear/Risk-Off: רק A+ עוברים
    if regime in ("TRENDING_BEAR", "RISK_OFF") and rating not in ("A+",):
        decision = "IGNORE"
        miss.append(f"נדרש A+ ב-{regime} (יש {rating})")

    # גודל פוזיציה מומלץ
    pos_size = {
        "ELITE_BUY":   "פוזיציה מלאה (5%)",
        "BUY":         "פוזיציה מלאה (3%)",
        "SPECULATIVE": "רבע פוזיציה (1%)",
        "WATCH":       "ללא פוזיציה",
        "IGNORE":      "ללא פוזיציה",
    }.get(decision, "")

    # Signal למיפוי עם שאר המערכת
    signal_map = {
        "ELITE_BUY": "BUY", "BUY": "BUY",
        "SPECULATIVE": "PREPARE", "WATCH": "WATCH", "IGNORE": "IGNORE"
    }

    reason = f"ציון {sc}/100 — {rating}"

    return {
        "decision":   decision,
        "rating":     rating,
        "confidence": sc,
        "reason":     reason,
        "missing":    miss,
        "positives":  pos,
        "pos_size":   pos_size,
        "signal":     signal_map[decision],
    }


def decide_batch(coins: list[dict]) -> list[dict]:
    for c in coins:
        r = decide(c)
        c.update({
            "decision":   r["decision"],
            "rating":     r["rating"],
            "confidence": r["confidence"],
            "reason":     r["reason"],
            "missing":    r["missing"],
            "positives":  r["positives"],
            "pos_size":   r["pos_size"],
            "signal":     r["signal"],
        })
    return coins"""
CRYPTO-BOT Elite — Decision Engine v2

4 רמות במקום "הכל או כלום":
    ELITE_BUY    (95+) — A+, פוזיציה מלאה
    BUY          (85+) — A,  פוזיציה מלאה
    SPECULATIVE  (70+) — B+, רבע פוזיציה
    WATCH        (50+) — B,  מעקב בלבד
    IGNORE       (<50) — C,  לא רלוונטי

Quality Gate מדורג: ניקוד במקום תנאים בינאריים.
RVOL דינמי לפי regime.
"""
from utils.logger import get_logger
log = get_logger(__name__)

# ─── Dynamic RVOL threshold ───────────────────────────────────────────────────

_RVOL_BY_REGIME = {
    "TRENDING_BULL": 1.2,
    "ALTSEASON":     1.0,
    "RANGE":         1.0,
    "RISK_OFF":      1.5,
    "TRENDING_BEAR": 2.0,
}

_RATING_ORDER = ["C","B","B+","A","A+"]


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _score(coin: dict, regime: str) -> tuple[int, list[str], list[str]]:
    """
    מחשב ציון איכות 0-100.
    מחזיר (score, positives, missing).
    """
    flow       = coin.get("flow_score", 0)
    pre        = coin.get("pre_score", 0)
    rvol       = coin.get("rvol", 0)
    oi         = coin.get("oi_change", 0)
    compressed = coin.get("is_compressed", False)
    rs_1h      = coin.get("rs_1h", 0)
    whale      = coin.get("whale_detected", False)
    vol_exp    = coin.get("vol_explosion", False)
    entry_dec  = coin.get("entry_decision", "NO")
    catalyst   = coin.get("has_catalyst", False)

    rvol_min = _RVOL_BY_REGIME.get(regime, 1.0)

    sc = 0
    pos, miss = [], []

    # Flow (25 נקודות)
    if flow >= 75:   sc += 25; pos.append(f"Flow חזק ({flow:.0f})")
    elif flow >= 60: sc += 18; pos.append(f"Flow ({flow:.0f})")
    elif flow >= 45: sc += 10; pos.append(f"Flow בינוני ({flow:.0f})")
    elif flow >= 30: sc += 4
    else:            miss.append(f"Flow חלש ({flow:.0f})")

    # OI (20 נקודות) — פחות קשיח: 0.5% מספיק
    if oi >= 5:      sc += 20; pos.append(f"OI חזק {oi:+.1f}%")
    elif oi >= 2:    sc += 14; pos.append(f"OI עולה {oi:+.1f}%")
    elif oi >= 0.5:  sc += 7;  pos.append(f"OI {oi:+.1f}%")
    else:            miss.append("OI לא עולה")

    # RVOL דינמי (20 נקודות)
    if rvol >= rvol_min * 2:  sc += 20; pos.append(f"💥 RVOL {rvol:.1f}x")
    elif rvol >= rvol_min:    sc += 13; pos.append(f"RVOL {rvol:.1f}x")
    elif rvol >= rvol_min*0.7:sc += 6
    else:                      miss.append(f"RVOL נמוך ({rvol:.1f}x, נדרש {rvol_min})")

    # Compression (15 → בונוס, לא חובה)
    if compressed:  sc += 15; pos.append("Compression")
    # else לא miss — רק בונוס

    # RS (10 נקודות)
    if rs_1h >= 2:   sc += 10; pos.append(f"חזק מ-BTC {rs_1h:+.1f}%")
    elif rs_1h >= 0: sc += 5;  pos.append("חוזק מ-BTC")
    else:             miss.append(f"חולשה מ-BTC ({rs_1h:.1f}%)")

    # Whale + Catalyst (10 נקודות)
    if whale:    sc += 5;  pos.append("פעילות לווייתנים")
    if catalyst: sc += 5;  pos.append("Catalyst")

    # Vol explosion (בונוס)
    if vol_exp:  sc += 5;  pos.append("💥 פיצוץ נפח")

    # Entry bonus
    if entry_dec == "BUY": sc += 5

    # Regime penalty
    if regime == "TRENDING_BEAR": sc = int(sc * 0.65)
    elif regime == "RISK_OFF":    sc = int(sc * 0.80)

    return min(100, sc), pos[:5], miss[:3]


# ─── Decision ─────────────────────────────────────────────────────────────────

def decide(coin: dict) -> dict:
    regime = coin.get("regime", "RANGE")
    sc, pos, miss = _score(coin, regime)

    # Rating
    if sc >= 90:   rating, decision = "A+", "ELITE_BUY"
    elif sc >= 80: rating, decision = "A",  "BUY"
    elif sc >= 65: rating, decision = "B+", "SPECULATIVE"
    elif sc >= 45: rating, decision = "B",  "WATCH"
    else:          rating, decision = "C",  "IGNORE"

    # Bear/Risk-Off: רק A+ עוברים
    if regime in ("TRENDING_BEAR", "RISK_OFF") and rating not in ("A+",):
        decision = "IGNORE"
        miss.append(f"נדרש A+ ב-{regime} (יש {rating})")

    # גודל פוזיציה מומלץ
    pos_size = {
        "ELITE_BUY":   "פוזיציה מלאה (5%)",
        "BUY":         "פוזיציה מלאה (3%)",
        "SPECULATIVE": "רבע פוזיציה (1%)",
        "WATCH":       "ללא פוזיציה",
        "IGNORE":      "ללא פוזיציה",
    }.get(decision, "")

    # Signal למיפוי עם שאר המערכת
    signal_map = {
        "ELITE_BUY": "BUY", "BUY": "BUY",
        "SPECULATIVE": "PREPARE", "WATCH": "WATCH", "IGNORE": "IGNORE"
    }

    reason = f"ציון {sc}/100 — {rating}"

    return {
        "decision":   decision,
        "rating":     rating,
        "confidence": sc,
        "reason":     reason,
        "missing":    miss,
        "positives":  pos,
        "pos_size":   pos_size,
        "signal":     signal_map[decision],
    }


def decide_batch(coins: list[dict]) -> list[dict]:
    for c in coins:
        r = decide(c)
        c.update({
            "decision":   r["decision"],
            "rating":     r["rating"],
            "confidence": r["confidence"],
            "reason":     r["reason"],
            "missing":    r["missing"],
            "positives":  r["positives"],
            "pos_size":   r["pos_size"],
            "signal":     r["signal"],
        })
    return coins"""
CRYPTO-BOT Elite — Decision Engine v2

4 רמות במקום "הכל או כלום":
    ELITE_BUY    (95+) — A+, פוזיציה מלאה
    BUY          (85+) — A,  פוזיציה מלאה
    SPECULATIVE  (70+) — B+, רבע פוזיציה
    WATCH        (50+) — B,  מעקב בלבד
    IGNORE       (<50) — C,  לא רלוונטי

Quality Gate מדורג: ניקוד במקום תנאים בינאריים.
RVOL דינמי לפי regime.
"""
from utils.logger import get_logger
log = get_logger(__name__)

# ─── Dynamic RVOL threshold ───────────────────────────────────────────────────

_RVOL_BY_REGIME = {
    "TRENDING_BULL": 1.2,
    "ALTSEASON":     1.0,
    "RANGE":         1.0,
    "RISK_OFF":      1.5,
    "TRENDING_BEAR": 2.0,
}

_RATING_ORDER = ["C","B","B+","A","A+"]


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _score(coin: dict, regime: str) -> tuple[int, list[str], list[str]]:
    """
    מחשב ציון איכות 0-100.
    מחזיר (score, positives, missing).
    """
    flow       = coin.get("flow_score", 0)
    pre        = coin.get("pre_score", 0)
    rvol       = coin.get("rvol", 0)
    oi         = coin.get("oi_change", 0)
    compressed = coin.get("is_compressed", False)
    rs_1h      = coin.get("rs_1h", 0)
    whale      = coin.get("whale_detected", False)
    vol_exp    = coin.get("vol_explosion", False)
    entry_dec  = coin.get("entry_decision", "NO")
    catalyst   = coin.get("has_catalyst", False)

    rvol_min = _RVOL_BY_REGIME.get(regime, 1.0)

    sc = 0
    pos, miss = [], []

    # Flow (25 נקודות)
    if flow >= 75:   sc += 25; pos.append(f"Flow חזק ({flow:.0f})")
    elif flow >= 60: sc += 18; pos.append(f"Flow ({flow:.0f})")
    elif flow >= 45: sc += 10; pos.append(f"Flow בינוני ({flow:.0f})")
    elif flow >= 30: sc += 4
    else:            miss.append(f"Flow חלש ({flow:.0f})")

    # OI (20 נקודות) — פחות קשיח: 0.5% מספיק
    if oi >= 5:      sc += 20; pos.append(f"OI חזק {oi:+.1f}%")
    elif oi >= 2:    sc += 14; pos.append(f"OI עולה {oi:+.1f}%")
    elif oi >= 0.5:  sc += 7;  pos.append(f"OI {oi:+.1f}%")
    else:            miss.append("OI לא עולה")

    # RVOL דינמי (20 נקודות)
    if rvol >= rvol_min * 2:  sc += 20; pos.append(f"💥 RVOL {rvol:.1f}x")
    elif rvol >= rvol_min:    sc += 13; pos.append(f"RVOL {rvol:.1f}x")
    elif rvol >= rvol_min*0.7:sc += 6
    else:                      miss.append(f"RVOL נמוך ({rvol:.1f}x, נדרש {rvol_min})")

    # Compression (15 → בונוס, לא חובה)
    if compressed:  sc += 15; pos.append("Compression")
    # else לא miss — רק בונוס

    # RS (10 נקודות)
    if rs_1h >= 2:   sc += 10; pos.append(f"חזק מ-BTC {rs_1h:+.1f}%")
    elif rs_1h >= 0: sc += 5;  pos.append("חוזק מ-BTC")
    else:             miss.append(f"חולשה מ-BTC ({rs_1h:.1f}%)")

    # Whale + Catalyst (10 נקודות)
    if whale:    sc += 5;  pos.append("פעילות לווייתנים")
    if catalyst: sc += 5;  pos.append("Catalyst")

    # Vol explosion (בונוס)
    if vol_exp:  sc += 5;  pos.append("💥 פיצוץ נפח")

    # Entry bonus
    if entry_dec == "BUY": sc += 5

    # Regime penalty
    if regime == "TRENDING_BEAR": sc = int(sc * 0.65)
    elif regime == "RISK_OFF":    sc = int(sc * 0.80)

    return min(100, sc), pos[:5], miss[:3]


# ─── Decision ─────────────────────────────────────────────────────────────────

def decide(coin: dict) -> dict:
    regime = coin.get("regime", "RANGE")
    sc, pos, miss = _score(coin, regime)

    # Rating
    if sc >= 90:   rating, decision = "A+", "ELITE_BUY"
    elif sc >= 80: rating, decision = "A",  "BUY"
    elif sc >= 65: rating, decision = "B+", "SPECULATIVE"
    elif sc >= 45: rating, decision = "B",  "WATCH"
    else:          rating, decision = "C",  "IGNORE"

    # Bear/Risk-Off: רק A+ עוברים
    if regime in ("TRENDING_BEAR", "RISK_OFF") and rating not in ("A+",):
        decision = "IGNORE"
        miss.append(f"נדרש A+ ב-{regime} (יש {rating})")

    # גודל פוזיציה מומלץ
    pos_size = {
        "ELITE_BUY":   "פוזיציה מלאה (5%)",
        "BUY":         "פוזיציה מלאה (3%)",
        "SPECULATIVE": "רבע פוזיציה (1%)",
        "WATCH":       "ללא פוזיציה",
        "IGNORE":      "ללא פוזיציה",
    }.get(decision, "")

    # Signal למיפוי עם שאר המערכת
    signal_map = {
        "ELITE_BUY": "BUY", "BUY": "BUY",
        "SPECULATIVE": "PREPARE", "WATCH": "WATCH", "IGNORE": "IGNORE"
    }

    reason = f"ציון {sc}/100 — {rating}"

    return {
        "decision":   decision,
        "rating":     rating,
        "confidence": sc,
        "reason":     reason,
        "missing":    miss,
        "positives":  pos,
        "pos_size":   pos_size,
        "signal":     signal_map[decision],
    }


def decide_batch(coins: list[dict]) -> list[dict]:
    for c in coins:
        r = decide(c)
        c.update({
            "decision":   r["decision"],
            "rating":     r["rating"],
            "confidence": r["confidence"],
            "reason":     r["reason"],
            "missing":    r["missing"],
            "positives":  r["positives"],
            "pos_size":   r["pos_size"],
            "signal":     r["signal"],
        })
    return coins"""
CRYPTO-BOT Elite — Decision Engine v2

4 רמות במקום "הכל או כלום":
    ELITE_BUY    (95+) — A+, פוזיציה מלאה
    BUY          (85+) — A,  פוזיציה מלאה
    SPECULATIVE  (70+) — B+, רבע פוזיציה
    WATCH        (50+) — B,  מעקב בלבד
    IGNORE       (<50) — C,  לא רלוונטי

Quality Gate מדורג: ניקוד במקום תנאים בינאריים.
RVOL דינמי לפי regime.
"""
from utils.logger import get_logger
log = get_logger(__name__)

# ─── Dynamic RVOL threshold ───────────────────────────────────────────────────

_RVOL_BY_REGIME = {
    "TRENDING_BULL": 1.2,
    "ALTSEASON":     1.0,
    "RANGE":         1.0,
    "RISK_OFF":      1.5,
    "TRENDING_BEAR": 2.0,
}

_RATING_ORDER = ["C","B","B+","A","A+"]


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _score(coin: dict, regime: str) -> tuple[int, list[str], list[str]]:
    """
    מחשב ציון איכות 0-100.
    מחזיר (score, positives, missing).
    """
    flow       = coin.get("flow_score", 0)
    pre        = coin.get("pre_score", 0)
    rvol       = coin.get("rvol", 0)
    oi         = coin.get("oi_change", 0)
    compressed = coin.get("is_compressed", False)
    rs_1h      = coin.get("rs_1h", 0)
    whale      = coin.get("whale_detected", False)
    vol_exp    = coin.get("vol_explosion", False)
    entry_dec  = coin.get("entry_decision", "NO")
    catalyst   = coin.get("has_catalyst", False)

    rvol_min = _RVOL_BY_REGIME.get(regime, 1.0)

    sc = 0
    pos, miss = [], []

    # Flow (25 נקודות)
    if flow >= 75:   sc += 25; pos.append(f"Flow חזק ({flow:.0f})")
    elif flow >= 60: sc += 18; pos.append(f"Flow ({flow:.0f})")
    elif flow >= 45: sc += 10; pos.append(f"Flow בינוני ({flow:.0f})")
    elif flow >= 30: sc += 4
    else:            miss.append(f"Flow חלש ({flow:.0f})")

    # OI (20 נקודות) — פחות קשיח: 0.5% מספיק
    if oi >= 5:      sc += 20; pos.append(f"OI חזק {oi:+.1f}%")
    elif oi >= 2:    sc += 14; pos.append(f"OI עולה {oi:+.1f}%")
    elif oi >= 0.5:  sc += 7;  pos.append(f"OI {oi:+.1f}%")
    else:            miss.append("OI לא עולה")

    # RVOL דינמי (20 נקודות)
    if rvol >= rvol_min * 2:  sc += 20; pos.append(f"💥 RVOL {rvol:.1f}x")
    elif rvol >= rvol_min:    sc += 13; pos.append(f"RVOL {rvol:.1f}x")
    elif rvol >= rvol_min*0.7:sc += 6
    else:                      miss.append(f"RVOL נמוך ({rvol:.1f}x, נדרש {rvol_min})")

    # Compression (15 → בונוס, לא חובה)
    if compressed:  sc += 15; pos.append("Compression")
    # else לא miss — רק בונוס

    # RS (10 נקודות)
    if rs_1h >= 2:   sc += 10; pos.append(f"חזק מ-BTC {rs_1h:+.1f}%")
    elif rs_1h >= 0: sc += 5;  pos.append("חוזק מ-BTC")
    else:             miss.append(f"חולשה מ-BTC ({rs_1h:.1f}%)")

    # Whale + Catalyst (10 נקודות)
    if whale:    sc += 5;  pos.append("פעילות לווייתנים")
    if catalyst: sc += 5;  pos.append("Catalyst")

    # Vol explosion (בונוס)
    if vol_exp:  sc += 5;  pos.append("💥 פיצוץ נפח")

    # Entry bonus
    if entry_dec == "BUY": sc += 5

    # Regime penalty
    if regime == "TRENDING_BEAR": sc = int(sc * 0.65)
    elif regime == "RISK_OFF":    sc = int(sc * 0.80)

    return min(100, sc), pos[:5], miss[:3]


# ─── Decision ─────────────────────────────────────────────────────────────────

def decide(coin: dict) -> dict:
    regime = coin.get("regime", "RANGE")
    sc, pos, miss = _score(coin, regime)

    # Rating
    if sc >= 90:   rating, decision = "A+", "ELITE_BUY"
    elif sc >= 80: rating, decision = "A",  "BUY"
    elif sc >= 65: rating, decision = "B+", "SPECULATIVE"
    elif sc >= 45: rating, decision = "B",  "WATCH"
    else:          rating, decision = "C",  "IGNORE"

    # Bear/Risk-Off: רק A+ עוברים
    if regime in ("TRENDING_BEAR", "RISK_OFF") and rating not in ("A+",):
        decision = "IGNORE"
        miss.append(f"נדרש A+ ב-{regime} (יש {rating})")

    # גודל פוזיציה מומלץ
    pos_size = {
        "ELITE_BUY":   "פוזיציה מלאה (5%)",
        "BUY":         "פוזיציה מלאה (3%)",
        "SPECULATIVE": "רבע פוזיציה (1%)",
        "WATCH":       "ללא פוזיציה",
        "IGNORE":      "ללא פוזיציה",
    }.get(decision, "")

    # Signal למיפוי עם שאר המערכת
    signal_map = {
        "ELITE_BUY": "BUY", "BUY": "BUY",
        "SPECULATIVE": "PREPARE", "WATCH": "WATCH", "IGNORE": "IGNORE"
    }

    reason = f"ציון {sc}/100 — {rating}"

    return {
        "decision":   decision,
        "rating":     rating,
        "confidence": sc,
        "reason":     reason,
        "missing":    miss,
        "positives":  pos,
        "pos_size":   pos_size,
        "signal":     signal_map[decision],
    }


def decide_batch(coins: list[dict]) -> list[dict]:
    for c in coins:
        r = decide(c)
        c.update({
            "decision":   r["decision"],
            "rating":     r["rating"],
            "confidence": r["confidence"],
            "reason":     r["reason"],
            "missing":    r["missing"],
            "positives":  r["positives"],
            "pos_size":   r["pos_size"],
            "signal":     r["signal"],
        })
    return coins"""
CRYPTO-BOT Elite — Decision Engine v2

4 רמות במקום "הכל או כלום":
    ELITE_BUY    (95+) — A+, פוזיציה מלאה
    BUY          (85+) — A,  פוזיציה מלאה
    SPECULATIVE  (70+) — B+, רבע פוזיציה
    WATCH        (50+) — B,  מעקב בלבד
    IGNORE       (<50) — C,  לא רלוונטי

Quality Gate מדורג: ניקוד במקום תנאים בינאריים.
RVOL דינמי לפי regime.
"""
from utils.logger import get_logger
log = get_logger(__name__)

# ─── Dynamic RVOL threshold ───────────────────────────────────────────────────

_RVOL_BY_REGIME = {
    "TRENDING_BULL": 1.2,
    "ALTSEASON":     1.0,
    "RANGE":         1.0,
    "RISK_OFF":      1.5,
    "TRENDING_BEAR": 2.0,
}

_RATING_ORDER = ["C","B","B+","A","A+"]


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _score(coin: dict, regime: str) -> tuple[int, list[str], list[str]]:
    """
    מחשב ציון איכות 0-100.
    מחזיר (score, positives, missing).
    """
    flow       = coin.get("flow_score", 0)
    pre        = coin.get("pre_score", 0)
    rvol       = coin.get("rvol", 0)
    oi         = coin.get("oi_change", 0)
    compressed = coin.get("is_compressed", False)
    rs_1h      = coin.get("rs_1h", 0)
    whale      = coin.get("whale_detected", False)
    vol_exp    = coin.get("vol_explosion", False)
    entry_dec  = coin.get("entry_decision", "NO")
    catalyst   = coin.get("has_catalyst", False)

    rvol_min = _RVOL_BY_REGIME.get(regime, 1.0)

    sc = 0
    pos, miss = [], []

    # Flow (25 נקודות)
    if flow >= 75:   sc += 25; pos.append(f"Flow חזק ({flow:.0f})")
    elif flow >= 60: sc += 18; pos.append(f"Flow ({flow:.0f})")
    elif flow >= 45: sc += 10; pos.append(f"Flow בינוני ({flow:.0f})")
    elif flow >= 30: sc += 4
    else:            miss.append(f"Flow חלש ({flow:.0f})")

    # OI (20 נקודות) — פחות קשיח: 0.5% מספיק
    if oi >= 5:      sc += 20; pos.append(f"OI חזק {oi:+.1f}%")
    elif oi >= 2:    sc += 14; pos.append(f"OI עולה {oi:+.1f}%")
    elif oi >= 0.5:  sc += 7;  pos.append(f"OI {oi:+.1f}%")
    else:            miss.append("OI לא עולה")

    # RVOL דינמי (20 נקודות)
    if rvol >= rvol_min * 2:  sc += 20; pos.append(f"💥 RVOL {rvol:.1f}x")
    elif rvol >= rvol_min:    sc += 13; pos.append(f"RVOL {rvol:.1f}x")
    elif rvol >= rvol_min*0.7:sc += 6
    else:                      miss.append(f"RVOL נמוך ({rvol:.1f}x, נדרש {rvol_min})")

    # Compression (15 → בונוס, לא חובה)
    if compressed:  sc += 15; pos.append("Compression")
    # else לא miss — רק בונוס

    # RS (10 נקודות)
    if rs_1h >= 2:   sc += 10; pos.append(f"חזק מ-BTC {rs_1h:+.1f}%")
    elif rs_1h >= 0: sc += 5;  pos.append("חוזק מ-BTC")
    else:             miss.append(f"חולשה מ-BTC ({rs_1h:.1f}%)")

    # Whale + Catalyst (10 נקודות)
    if whale:    sc += 5;  pos.append("פעילות לווייתנים")
    if catalyst: sc += 5;  pos.append("Catalyst")

    # Vol explosion (בונוס)
    if vol_exp:  sc += 5;  pos.append("💥 פיצוץ נפח")

    # Entry bonus
    if entry_dec == "BUY": sc += 5

    # Regime penalty
    if regime == "TRENDING_BEAR": sc = int(sc * 0.65)
    elif regime == "RISK_OFF":    sc = int(sc * 0.80)

    return min(100, sc), pos[:5], miss[:3]


# ─── Decision ─────────────────────────────────────────────────────────────────

def decide(coin: dict) -> dict:
    regime = coin.get("regime", "RANGE")
    sc, pos, miss = _score(coin, regime)

    # Rating
    if sc >= 90:   rating, decision = "A+", "ELITE_BUY"
    elif sc >= 80: rating, decision = "A",  "BUY"
    elif sc >= 65: rating, decision = "B+", "SPECULATIVE"
    elif sc >= 45: rating, decision = "B",  "WATCH"
    else:          rating, decision = "C",  "IGNORE"

    # Bear/Risk-Off: רק A+ עוברים
    if regime in ("TRENDING_BEAR", "RISK_OFF") and rating not in ("A+",):
        decision = "IGNORE"
        miss.append(f"נדרש A+ ב-{regime} (יש {rating})")

    # גודל פוזיציה מומלץ
    pos_size = {
        "ELITE_BUY":   "פוזיציה מלאה (5%)",
        "BUY":         "פוזיציה מלאה (3%)",
        "SPECULATIVE": "רבע פוזיציה (1%)",
        "WATCH":       "ללא פוזיציה",
        "IGNORE":      "ללא פוזיציה",
    }.get(decision, "")

    # Signal למיפוי עם שאר המערכת
    signal_map = {
        "ELITE_BUY": "BUY", "BUY": "BUY",
        "SPECULATIVE": "PREPARE", "WATCH": "WATCH", "IGNORE": "IGNORE"
    }

    reason = f"ציון {sc}/100 — {rating}"

    return {
        "decision":   decision,
        "rating":     rating,
        "confidence": sc,
        "reason":     reason,
        "missing":    miss,
        "positives":  pos,
        "pos_size":   pos_size,
        "signal":     signal_map[decision],
    }


def decide_batch(coins: list[dict]) -> list[dict]:
    for c in coins:
        r = decide(c)
        c.update({
            "decision":   r["decision"],
            "rating":     r["rating"],
            "confidence": r["confidence"],
            "reason":     r["reason"],
            "missing":    r["missing"],
            "positives":  r["positives"],
            "pos_size":   r["pos_size"],
            "signal":     r["signal"],
        })
    return coins
