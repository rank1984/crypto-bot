"""
CRYPTO-BOT Elite — Learning Database

6 טבלאות:
    scans       — כל סריקה
    candidates  — כל מטבע שנבדק
    failures    — למה נפסל
    outcomes    — מה קרה אחר כך (1h/4h/24h)
    setups      — איזה setup היה
    performance — סיכום ביצועים לפי setup
"""
import os, sqlite3
from datetime import datetime, timezone

DB_PATH = os.getenv("LEARNING_DB", "data/learning.db")


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS scans (
            scan_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL,
            regime      TEXT,
            btc_price   REAL,
            coins_scanned INTEGER DEFAULT 0,
            rvol_fail   INTEGER DEFAULT 0,
            hard_fail   INTEGER DEFAULT 0,
            score_fail  INTEGER DEFAULT 0,
            flow_fail   INTEGER DEFAULT 0,
            buy_count   INTEGER DEFAULT 0,
            prepare_count INTEGER DEFAULT 0,
            watch_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS candidates (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id     INTEGER REFERENCES scans(scan_id),
            ts          TEXT NOT NULL,
            symbol      TEXT NOT NULL,
            price       REAL,
            flow        REAL,
            pre_score   REAL,
            oi_change   REAL,
            rvol        REAL,
            compressed  INTEGER DEFAULT 0,
            rs_1h       REAL,
            whale       INTEGER DEFAULT 0,
            vol_explosion INTEGER DEFAULT 0,
            rating      TEXT,
            confidence  REAL,
            signal      TEXT,
            decision    TEXT,
            ready_pct   REAL,
            entry_price REAL,
            sl_price    REAL,
            tp1_price   REAL
        );

        CREATE TABLE IF NOT EXISTS failures (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id INTEGER REFERENCES scans(scan_id),
            symbol  TEXT NOT NULL,
            reason  TEXT NOT NULL,
            stage   TEXT
        );

        CREATE TABLE IF NOT EXISTS outcomes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER REFERENCES candidates(id),
            symbol      TEXT NOT NULL,
            entry_price REAL,
            ret_1h      REAL,
            ret_4h      REAL,
            ret_24h     REAL,
            max_gain    REAL,
            hit_tp1     INTEGER DEFAULT 0,
            hit_sl      INTEGER DEFAULT 0,
            updated_ts  TEXT
        );

        CREATE TABLE IF NOT EXISTS setups (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER REFERENCES candidates(id),
            symbol      TEXT NOT NULL,
            compression INTEGER DEFAULT 0,
            whale       INTEGER DEFAULT 0,
            flow_strong INTEGER DEFAULT 0,
            momentum    INTEGER DEFAULT 0,
            sympathy    INTEGER DEFAULT 0,
            oi_surge    INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS performance (
            setup_name  TEXT PRIMARY KEY,
            trades      INTEGER DEFAULT 0,
            wins        INTEGER DEFAULT 0,
            avg_win     REAL DEFAULT 0,
            avg_loss    REAL DEFAULT 0,
            expectancy  REAL DEFAULT 0,
            profit_factor REAL DEFAULT 0,
            last_updated TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_cand_symbol  ON candidates(symbol);
        CREATE INDEX IF NOT EXISTS idx_cand_scan    ON candidates(scan_id);
        CREATE INDEX IF NOT EXISTS idx_outcome_sym  ON outcomes(symbol);
        CREATE INDEX IF NOT EXISTS idx_fail_stage   ON failures(stage);
        """)
