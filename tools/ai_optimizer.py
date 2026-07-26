"""
CRYPTO-BOT Elite — AI Optimizer
מפיק הצעות לשיפור ספים על סמך נתוני Dashboard
"""
from tools.learning_dashboard import get_stats
from utils.logger import get_logger

log = get_logger("ai_optimizer")

def get_suggestions():
    stats = get_stats()
    if stats["total_trades"] < 20:
        return None

    suggestions = []

    # בדיקת Probability ranges עם EV שלילי
    for r in stats["prob_ranges"]:
        win = r.get("tp1_rate", 0) or 0
        avg_win = r.get("avg_win", 0) or 0
        avg_loss = abs(r.get("avg_loss", 0) or 0)
        cnt = r.get("cnt", 0)
        if cnt < 10:
            continue
        ev = round((win * avg_win) - ((1 - win) * avg_loss), 2)
        if ev < 0:
            suggestions.append(f"Prob {r['seg']} (cnt={cnt}): EV={ev}% – consider skipping")

    # Flow ranges
    for r in stats["flow_ranges"]:
        win = r.get("tp1_rate", 0) or 0
        avg_win = r.get("avg_win", 0) or 0
        avg_loss = abs(r.get("avg_loss", 0) or 0)
        cnt = r.get("cnt", 0)
        if cnt < 10: continue
        ev = round((win * avg_win) - ((1 - win) * avg_loss), 2)
        if ev < 0:
            suggestions.append(f"Flow {r['seg']} (cnt={cnt}): EV={ev}% – consider skipping")

    # Setup ranges
    for r in stats["setup_ranges"]:
        win = r.get("tp1_rate", 0) or 0
        cnt = r.get("cnt", 0)
        if cnt < 10: continue
        if win < 0.3:
            suggestions.append(f"Setup {r['seg']} (cnt={cnt}): WinRate={win*100:.0f}% – consider disabling")

    if suggestions:
        log.info("AI Optimizer suggestions:\n" + "\n".join(suggestions))
    return suggestions
