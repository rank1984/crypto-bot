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
