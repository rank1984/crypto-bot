"""
CRYPTO-BOT Elite — Recorder

שומר כל סריקה + כל מועמד + סיבות פסילה.
"""
import sqlite3
from datetime import datetime, timezone
from learning.database import _conn, init_db
from utils.logger import get_logger

log = get_logger(__name__)


def record_scan(stats, coins: list[dict]) -> int:
    """
    שומר סריקה. מחזיר scan_id.
    stats = ScanStats מ-scan_diagnostics
    coins = כל המטבעות שהגיעו ל-ranking
    """
    init_db()
    ts = datetime.now(timezone.utc).isoformat()

    with _conn() as c:
        cur = c.execute("""
            INSERT INTO scans (ts, regime, coins_scanned,
                rvol_fail, hard_fail, score_fail, flow_fail,
                buy_count, prepare_count, watch_count)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            ts,
            getattr(stats, "regime", "") if stats else "",
            getattr(stats, "scanned", len(coins)) if stats else len(coins),
            getattr(stats, "rvol_fail", 0)   if stats else 0,
            getattr(stats, "hard_fail", 0)   if stats else 0,
            getattr(stats, "score_fail", 0)  if stats else 0,
            getattr(stats, "flow_fail", 0)   if stats else 0,
            sum(1 for c2 in coins if c2.get("decision") == "BUY"),
            sum(1 for c2 in coins if c2.get("decision") == "WAIT"),
            sum(1 for c2 in coins if c2.get("signal") == "WATCH"),
        ))
        scan_id = cur.lastrowid

    # שמור כל מועמד
    cand_ids = {}
    for coin in coins:
        cid = _record_candidate(scan_id, coin)
        cand_ids[coin["symbol"]] = cid
        _record_setup(cid, coin)

    log.info(f"Recorded scan #{scan_id}: {len(coins)} coins")
    return scan_id


def _record_candidate(scan_id: int, c: dict) -> int:
    ts = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        cur = conn.execute("""
            INSERT INTO candidates (
                scan_id, ts, symbol, price,
                flow, pre_score, oi_change, rvol,
                compressed, rs_1h, whale, vol_explosion,
                rating, confidence, signal, decision, ready_pct,
                entry_price, sl_price, tp1_price
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            scan_id, ts, c["symbol"], c.get("price"),
            c.get("flow_score"), c.get("pre_score"),
            c.get("oi_change"), c.get("rvol"),
            int(c.get("is_compressed", False)),
            c.get("rs_1h"), int(c.get("whale_detected", False)),
            int(c.get("vol_explosion", False)),
            c.get("rating"), c.get("confidence"),
            c.get("signal"), c.get("decision"),
            c.get("confidence"),   # ready_pct = confidence
            c.get("entry_price"), c.get("entry_sl"), c.get("entry_tp1"),
        ))
        return cur.lastrowid


def _record_setup(cand_id: int, c: dict):
    with _conn() as conn:
        conn.execute("""
            INSERT INTO setups (
                candidate_id, symbol,
                compression, whale, flow_strong,
                momentum, sympathy, oi_surge
            ) VALUES (?,?,?,?,?,?,?,?)
        """, (
            cand_id, c["symbol"],
            int(c.get("is_compressed", False)),
            int(c.get("whale_detected", False)),
            int(c.get("flow_score", 0) >= 65),
            int(abs(c.get("momentum_1h", 0)) >= 1.5),
            int(c.get("is_sympathy", False)),
            int(c.get("oi_change", 0) >= 3),
        ))


def record_failure(scan_id: int, symbol: str, reason: str, stage: str):
    """שומר סיבת פסילה."""
    with _conn() as c:
        c.execute("""
            INSERT INTO failures (scan_id, symbol, reason, stage)
            VALUES (?,?,?,?)
        """, (scan_id, symbol, reason, stage))
