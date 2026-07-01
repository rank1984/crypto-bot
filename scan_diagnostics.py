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
