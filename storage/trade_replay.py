"""
CRYPTO-BOT Elite — Trade Replay

שומר snapshot של כל עסקה כל 5 דקות.
מאפשר שחזור מלא של מהלך העסקה.
"""
import sqlite3
import json
from datetime import datetime
from utils.logger import get_logger

log = get_logger("trade_replay")

DB_PATH = "storage/trades.db"

def init_replay_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trade_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id TEXT,
            timestamp TEXT,
            entry_price REAL,
            current_price REAL,
            highest_price REAL,
            lowest_price REAL,
            mfe REAL,
            mae REAL,
            flow_score REAL,
            oi_change REAL,
            funding REAL,
            rs_1h REAL,
            news_score REAL,
            btc_regime TEXT,
            market_health REAL,
            trade_health REAL,
            state TEXT,
            pnl_pct REAL
        )
    """)
    conn.commit()
    conn.close()

def save_snapshot(trade, coin_data, market_health, news_score, btc_regime):
    """
    שומר snapshot של העסקה.
    trade: אובייקט Trade
    coin_data: מילון עם נתוני המטבע
    """
    conn = sqlite3.connect(DB_PATH)
    current_price = coin_data.get("last_price", trade.entry_price)
    mfe = ((trade.highest_high - trade.entry_price) / trade.entry_price) * 100
    mae = ((coin_data.get("lowest_low", current_price) - trade.entry_price) / trade.entry_price) * 100
    pnl_pct = ((current_price - trade.entry_price) / trade.entry_price) * 100

    conn.execute("""
        INSERT INTO trade_snapshots 
        (trade_id, timestamp, entry_price, current_price, highest_price, lowest_price,
         mfe, mae, flow_score, oi_change, funding, rs_1h, news_score, btc_regime,
         market_health, trade_health, state, pnl_pct)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trade.symbol,
        datetime.now().isoformat(),
        trade.entry_price,
        current_price,
        trade.highest_high,
        coin_data.get("lowest_low", current_price),
        mfe,
        mae,
        coin_data.get("flow_score", 0),
        coin_data.get("oi_change", 0),
        coin_data.get("funding", 0),
        coin_data.get("rs_1h", 0),
        news_score,
        btc_regime,
        market_health,
        trade.health,
        trade.state,
        pnl_pct
    ))
    conn.commit()
    conn.close()
