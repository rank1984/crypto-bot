"""
CRYPTO-BOT Elite — Event Engine

מזהה אירועים קריטיים (FOMC, CPI וכו') ומנטרל מסחר.
מקור: רשימה ידנית או CSV.
"""
import csv
import os
from datetime import datetime, timedelta
from utils.logger import get_logger

log = get_logger(__name__)

# ─── Events DB ────────────────────────────────────────────────────────────────
EVENTS_FILE = "data/economic_events.csv"

IMPACT_WEIGHT = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}

def load_events():
    """טען אירועים מקובץ CSV (date, time, event, impact)"""
    events = []
    if not os.path.exists(EVENTS_FILE):
        # קובץ לדוגמה עם אירועים קרובים (יש לעדכן)
        sample_events = [
            ("2026-07-15", "14:00", "FOMC Minutes", "HIGH"),
            ("2026-07-20", "08:30", "CPI m/m", "CRITICAL"),
        ]
        os.makedirs("data", exist_ok=True)
        with open(EVENTS_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "time", "event", "impact"])
            for ev in sample_events:
                writer.writerow(ev)
        log.info(f"Created sample events file: {EVENTS_FILE}")

    with open(EVENTS_FILE, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                dt = datetime.strptime(f"{row['date']} {row['time']}", "%Y-%m-%d %H:%M")
                events.append({
                    "datetime": dt,
                    "event": row["event"],
                    "impact": row["impact"].strip(),
                })
            except Exception as e:
                log.warning(f"Error parsing event: {row} -> {e}")
    return events

def check_upcoming_events(minutes_ahead: int = 15):
    """
    מחזיר רשימת אירועים קרובים (בתוך minutes_ahead דקות)
    ומחרוזת של האזהרה.
    """
    events = load_events()
    now = datetime.now()
    upcoming = []
    for ev in events:
        diff = (ev["datetime"] - now).total_seconds() / 60
        if 0 <= diff <= minutes_ahead:
            upcoming.append(ev)
    return upcoming

def trading_disabled():
    """מחזיר True אם יש אירוע CRITICAL/HIGH בתוך 15 דקות"""
    upcoming = check_upcoming_events(15)
    for ev in upcoming:
        if ev["impact"] in ("HIGH", "CRITICAL"):
            return True
    return False

def get_event_warning():
    upcoming = check_upcoming_events(15)
    if not upcoming:
        return ""
    warning = "⚠️ High Impact Events Soon:\n"
    for ev in upcoming:
        warning += f"{ev['event']} at {ev['datetime'].strftime('%H:%M')} ({ev['impact']})\n"
    return warning
