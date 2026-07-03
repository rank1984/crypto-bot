"""
CRYPTO-BOT Elite — Scan Diagnostics

מעדכן בכל סריקה ומסביר למה אין עסקאות.
"""
import os
from dataclasses import dataclass, field
from utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class ScanStats:
    scanned:    int = 0
    no_data:    int = 0
    rvol_fail:  int = 0
    hard_fail:  int = 0
    score_fail: int = 0
    flow_fail:  int = 0
    signal_ignore: int = 0
    watch:      int = 0
    prepare:    int = 0
    buy:        int = 0
    regime:     str = "RANGE"
    hard_reasons: dict = field(default_factory=dict)
    top_flow_scores: list = field(default_factory=list)   # Flow scores שנראו
    top_rvol_values: list = field(default_factory=list)   # RVOL values שנראו

    def record_rvol(self, v: float):
        self.top_rvol_values.append(round(v, 2))

    def record_flow(self, v: float):
        self.top_flow_scores.append(round(v, 1))

    def main_bottleneck(self) -> tuple[str, int]:
        stages = {
            "RVOL נמוך":        self.rvol_fail,
            "Hard Filters":     self.hard_fail,
            "Score נמוך":       self.score_fail,
            "Flow חלש":         self.flow_fail,
            "Signal → IGNORE":  self.signal_ignore,
        }
        return max(stages.items(), key=lambda x: x[1])


def format_no_signal_message(stats: ScanStats) -> str:
    """
    הודעת "אין עסקה" עם הסבר ברור.
    """
    bn_name, bn_count = stats.main_bottleneck()
    total = stats.scanned

    # הסבר ראשי
    if bn_name == "RVOL נמוך" and bn_count > total * 0.4:
        main_reason = "היום אין התפוצצות נפח משמעותית."
    elif bn_name == "Flow חלש" and bn_count > 5:
        main_reason = "אין כרגע כניסת כסף משמעותית לשוק (OI/CVD חלש)."
    elif bn_name == "Score נמוך":
        main_reason = "המטבעות לא חזקים מספיק ביחס לשוק."
    elif bn_name == "Hard Filters":
        top_reason = max(stats.hard_reasons, key=stats.hard_reasons.get) if stats.hard_reasons else "RSI/VWAP"
        main_reason = f"מטבעות רבים נפסלו על {top_reason}."
    elif stats.regime in ("TRENDING_BEAR", "RISK_OFF"):
        main_reason = "המערכת בדיוק מחפשת רק עסקאות A+ בגלל מצב השוק."
    else:
        main_reason = "אין מטבע שעומד בכל התנאים כרגע."

    # Pipeline funnel
    passed_rvol  = total - stats.no_data - stats.rvol_fail
    passed_hard  = passed_rvol - stats.hard_fail
    passed_score = passed_hard - stats.score_fail
    passed_flow  = passed_score - stats.flow_fail
    passed_signal = stats.watch + stats.prepare + stats.buy

    lines = [
        "🔥 CRYPTO-BOT ELITE",
        f"📊 נסרקו: {total} מטבעות",
        "━━━━━━━━━━━━━━━━━━",
    ]

    if stats.regime in ("TRENDING_BEAR", "RISK_OFF"):
        regime_map = {"TRENDING_BEAR": "🔴 Bear Market", "RISK_OFF": "🔴 שוק בפחד"}
        lines += [
            f"📊 מצב שוק: {regime_map[stats.regime]}",
            "המערכת מחפשת רק עסקאות A+",
            "━━━━━━━━━━━━━━━━━━",
        ]

    # Funnel
    def _row(label, val, emoji="✅"):
        return f"{emoji} {label}: {val}"

    lines += [
        _row("עברו נזילות/נתונים", total - stats.no_data),
        _row("עברו RVOL",          passed_rvol,  "✅" if passed_rvol > 10 else "⚠️"),
        _row("עברו Hard Filters",  passed_hard,  "✅" if passed_hard > 5  else "⚠️"),
        _row("עברו Score",         passed_score, "✅" if passed_score > 3  else "⚠️"),
        _row("עברו Flow",          passed_flow,  "✅" if passed_flow > 0   else "⚠️"),
        _row("עברו Signal (A/B+)", passed_signal,"✅" if passed_signal > 0 else "❌"),
        "━━━━━━━━━━━━━━━━━━",
        f"לא נמצאה עסקה איכותית כרגע.",
        "",
        f"הסיבה העיקרית:",
        f"❌ {main_reason}",
    ]

    # ה-Flow הכי גבוה שנראה
    if stats.top_flow_scores:
        top3 = sorted(stats.top_flow_scores, reverse=True)[:3]
        lines.append(f"\nFlow גבוה ביותר: {top3[0]:.0f} (צריך 55+)")
    if stats.top_rvol_values:
        top3 = sorted(stats.top_rvol_values, reverse=True)[:3]
        lines.append(f"RVOL גבוה ביותר: {top3[0]:.1f}x (צריך 0.8+)")

    lines.append("\n⏳ ממשיכים לסרוק...")
    return "\n".join(lines)


# ─── Pipeline Heatmap ────────────────────────────────────────────────────────

def format_pipeline_heatmap(stats: "ScanStats") -> str:
    """
    📡 Pipeline Heatmap — בר גרפי של כמה מטבעות עברו כל שלב.

    Universe           ██████████████ 386
    Liquidity          ████████████   342
    RVOL               █████          96
    Flow               ███            31
    Quality Gate       ██             9
    BUY                ▏              0
    """
    n = stats.scanned
    if n == 0:
        return "אין נתונים"

    passed_rv  = max(0, n - getattr(stats, "no_data", 0) - getattr(stats, "rvol_fail", 0))
    passed_hd  = max(0, passed_rv - getattr(stats, "hard_fail", 0))
    passed_sc  = max(0, passed_hd - getattr(stats, "score_fail", 0))
    passed_fl  = max(0, passed_sc - getattr(stats, "flow_fail", 0))
    passed_sig = getattr(stats, "watch", 0) + getattr(stats, "prepare", 0) + getattr(stats, "buy", 0)
    passed_buy = getattr(stats, "buy", 0)

    stages = [
        ("Universe",     n),
        ("Liquidity",    n - getattr(stats, "no_data", 0)),
        ("RVOL",         passed_rv),
        ("Flow/Score",   passed_fl),
        ("Quality Gate", passed_sig),
        ("BUY",          passed_buy),
    ]

    max_val = n if n > 0 else 1
    bar_len = 14   # אורך מקסימלי של הבר

    lines = ["📡 Pipeline Heatmap", ""]
    for label, val in stages:
        filled = round(val / max_val * bar_len) if max_val > 0 else 0
        filled = max(0, min(bar_len, filled))
        bar = "█" * filled + ("▏" if val > 0 and filled == 0 else "")
        pct = f"({val/n*100:.0f}%)" if n > 0 else ""
        lines.append(f"{label:<14} {bar:<14} {val} {pct}")

    # הדגש bottleneck
    bn, _ = stats.main_bottleneck()
    lines += ["", f"🔍 Bottleneck: {bn}"]
    return "\n".join(lines)


def format_full_diagnostic(stats: "ScanStats", coins: list = None) -> str:
    """
    הודעה מלאה: Funnel + Heatmap + מועמד קרוב.
    """
    coins = coins or []
    n = stats.scanned

    # ── Header ────────────────────────────────────────────────────────────────
    passed_rv  = max(0, n - getattr(stats, "no_data", 0) - getattr(stats, "rvol_fail", 0))
    passed_hd  = max(0, passed_rv - getattr(stats, "hard_fail", 0))
    passed_sc  = max(0, passed_hd - getattr(stats, "score_fail", 0))
    passed_fl  = max(0, passed_sc - getattr(stats, "flow_fail", 0))
    passed_sig = getattr(stats, "watch", 0) + getattr(stats, "prepare", 0) + getattr(stats, "buy", 0)

    def row(label, val, warn_below=1):
        icon = "✅" if val >= warn_below else ("⚠️" if val > 0 else "❌")
        pct  = f"({val/n*100:.0f}%)" if n > 0 else ""
        return f"{icon} {label}: {val} {pct}"

    lines = [
        f"📡 נסרקו:          {n}",
        f"📊 לאחר RVOL:      {passed_rv}",
        f"⭐ לאחר Score:     {passed_sc}",
        f"👀 עברו Quality:   {passed_sig}",
        "",
        row("עברו נזילות",   n - getattr(stats, "no_data", 0), 50),
        row("עברו RVOL",     passed_rv,  10),
        row("עברו Filters",  passed_hd,  5),
        row("עברו Score",    passed_sc,  3),
        row("עברו Flow",     passed_fl,  1),
        row("עסקאות A/A+",  passed_sig, 1),
        "",
        format_pipeline_heatmap(stats),
    ]

    # ── Rating breakdown ──────────────────────────────────────────────────────
    if coins:
        by_rating = {}
        for c in coins:
            r = c.get("rating", "C")
            by_rating[r] = by_rating.get(r, 0) + 1
        if by_rating:
            lines += ["", "🎯 מצב הסריקה"]
            for r in ["A+","A","B+","B","C"]:
                if r in by_rating:
                    lines.append(f"   {r}: {by_rating[r]}")

    return "\n".join(lines)


# ─── True Bottleneck Detection ───────────────────────────────────────────────

def calc_loss_rates(stats: "ScanStats") -> list[tuple[str, int, float]]:
    """
    מחשב loss rate אמיתי בכל שלב.
    מחזיר [(stage, lost, loss_pct), ...]
    """
    n = stats.scanned
    if n == 0:
        return []

    no_data = getattr(stats, "no_data", 0)
    rv_fail = getattr(stats, "rvol_fail", 0)
    hd_fail = getattr(stats, "hard_fail", 0)
    sc_fail = getattr(stats, "score_fail", 0)
    fl_fail = getattr(stats, "flow_fail", 0)

    passed_liq = n - no_data
    passed_rv  = passed_liq - rv_fail
    passed_hd  = passed_rv  - hd_fail
    passed_sc  = passed_hd  - sc_fail
    passed_fl  = passed_sc  - fl_fail

    stages = [
        ("Liquidity", no_data,  n),
        ("RVOL",      rv_fail,  passed_liq),
        ("Filters",   hd_fail,  passed_rv),
        ("Score",     sc_fail,  passed_hd),
        ("Flow/OI",   fl_fail,  passed_sc),
    ]

    result = []
    for name, lost, pool in stages:
        pct = lost / pool * 100 if pool > 0 else 0
        result.append((name, lost, round(pct, 1)))
    return result


def format_true_bottleneck(stats: "ScanStats") -> str:
    """
    Loss Rate per stage — איפה איבדנו הכי הרבה.
    """
    rates = calc_loss_rates(stats)
    if not rates:
        return ""

    max_loss = max(r[2] for r in rates)
    lines = ["📉 Loss Rate per Stage:"]
    for name, lost, pct in rates:
        bar_len = round(pct / 100 * 10)
        bar     = "█" * bar_len
        flag    = " 🔥 bottleneck" if pct == max_loss and pct > 30 else ""
        lines.append(f"  {name:<12} -{pct:.0f}%  {bar}{flag}")
    return "\n".join(lines)


# ─── Near Miss Classifier ────────────────────────────────────────────────────

def classify_near_miss(coin: dict) -> tuple[str, str]:
    """
    מחזיר (category, label):
        NEAR_MISS      — חסר רק תנאי אחד קריטי
        SETUP_BUILDING — עוד לא בשל
    """
    missing = coin.get("missing", [])
    rating  = coin.get("rating", "C")

    # קריטריון: מועמד ממש קרוב
    if rating in ("A+","A","B+") and len(missing) <= 1:
        return "NEAR_MISS", "🟡 Near Miss — חסר תנאי אחד"
    if rating in ("B+","B") and len(missing) <= 2:
        return "SETUP_BUILDING", "🟠 Setup Building — עוד לא בשל"
    return "TOO_EARLY", "⚪ Too Early"


# ─── Expected Value Engine ────────────────────────────────────────────────────

def calc_expected_value(
    win_rate_pct: float,   # % הצלחה
    avg_win_pct:  float,   # % רווח ממוצע בעסקה מוצלחת
    avg_loss_pct: float,   # % הפסד ממוצע (חיובי)
    commission:   float = 0.10,   # עמלה לכל צד (%)
    tax_rate:     float = 25.0,   # מס רווחי הון ישראל (%)
) -> dict:
    """
    מחשב Expected Value נקי לאחר עמלות ומיסוי.

    EV = (WR × avg_win) - ((1-WR) × avg_loss) - commissions - tax
    """
    wr  = win_rate_pct / 100
    # עמלות: כניסה + יציאה
    total_commission = commission * 2

    # רווח גולמי צפוי
    gross_ev = (wr * avg_win_pct) - ((1 - wr) * avg_loss_pct)

    # רווח לאחר עמלות
    after_commission = gross_ev - total_commission

    # מס רק על רווח (אם יש)
    tax = max(0, after_commission * tax_rate / 100)
    net_ev = after_commission - tax

    # Profit Factor
    pf = (wr * avg_win_pct) / ((1 - wr) * avg_loss_pct) if (1 - wr) * avg_loss_pct > 0 else 0

    return {
        "gross_ev":   round(gross_ev, 2),
        "net_ev":     round(net_ev, 2),
        "commission": round(total_commission, 2),
        "tax":        round(tax, 2),
        "pf":         round(pf, 2),
        "worthwhile": net_ev > 0.5,   # שווה לבצע רק אם נטו > 0.5%
    }


def expected_setups_per_day(stats: "ScanStats") -> dict:
    """
    אומדן עסקאות צפויות ביום לפי קצב ההצלחה הנוכחי.
    """
    scans_per_day = 24 * 60 // 5   # סריקה כל 5 דקות = 288 ביום
    n = stats.scanned
    if n == 0:
        return {}

    buy   = getattr(stats, "buy", 0)
    watch = getattr(stats, "watch", 0) + getattr(stats, "prepare", 0)

    buy_rate   = buy   / n
    watch_rate = watch / n

    return {
        "scans_per_day":    scans_per_day,
        "expected_buy":     round(buy_rate   * scans_per_day, 1),
        "expected_watch":   round(watch_rate * scans_per_day, 1),
        "buy_rate_pct":     round(buy_rate   * 100, 2),
        "scanned_today":    n,
    }


def format_expected_value_section(
    stats: "ScanStats",
    win_rate: float   = 55.0,
    avg_win:  float   = 8.0,
    avg_loss: float   = 3.0,
) -> str:
    """
    מציג EV + תחזית עסקאות ביום.
    """
    ev  = calc_expected_value(win_rate, avg_win, avg_loss)
    exp = expected_setups_per_day(stats)

    lines = [
        "💰 Expected Value (לפי ספים נוכחיים):",
        f"  Win Rate נדרש:  {win_rate:.0f}%",
        f"  Avg Win:        +{avg_win:.1f}%",
        f"  Avg Loss:       -{avg_loss:.1f}%",
        f"  EV גולמי:       {ev['gross_ev']:+.2f}%",
        f"  EV נטו (עמלות+מס): {ev['net_ev']:+.2f}%",
        f"  {'✅ שווה לבצע' if ev['worthwhile'] else '❌ לא כדאי בשלב זה'}",
    ]

    if exp:
        lines += [
            "",
            "📅 תחזית יומית:",
            f"  Expected BUY/day:   {exp['expected_buy']:.1f}",
            f"  Expected WATCH/day: {exp['expected_watch']:.1f}",
        ]
        if exp["expected_buy"] < 0.5:
            lines.append("  ⚠️ פחות מ-1 עסקה ביום — בדוק אם הפילטרים קשוחים מדי")

    return "\n".join(lines)
