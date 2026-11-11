"""
CRYPTO-BOT Elite — Learning Dataset Exporter v2.0

Changes from v1:
  - Include pnl_pct_net, pnl_r_net (after fees/slippage)
  - Include realized_pnl_pct (TP1+TP2 partial sells)
  - Include sl_type_at_exit (INITIAL / BREAKEVEN / TRAILING / EXIT_ENGINE)
  - Include final_exit_price
  - Add sanity checks: warns if all pnl_pct_net are NULL (tracker v9.0 not run)
  - Add per-bucket summary printed to log
  - Export to both data/learning_dataset.csv (canonical) and
    data/learning_dataset_net.csv (net-of-costs view)
"""
import os
import sqlite3
import pandas as pd
from utils.logger import get_logger

log = get_logger("dataset_exporter")
DB_PATH = os.getenv("DB_PATH", "data/shadow.db")
OUTPUT_CSV = "data/learning_dataset.csv"
OUTPUT_CSV_NET = "data/learning_dataset_net.csv"


def export_ml_dataset():
    if not os.path.exists(DB_PATH):
        log.error(f"Database file {DB_PATH} not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Verify required v9.0 columns exist
    existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(shadow_trades)").fetchall()}
    optional_cols = ["pnl_pct_net", "pnl_r_net", "realized_pnl_pct",
                     "sl_type_at_exit", "final_exit_price"]
    missing = [c for c in optional_cols if c not in existing_cols]
    if missing:
        log.warning(
            f"Missing columns: {missing}. Run 'python -m tools.outcome_tracker' "
            f"to migrate schema and recompute."
        )

    def _sel(col):
        return col if col in existing_cols else f"NULL AS {col}"

    query = f"""
        SELECT
            id, ts, symbol, decision, setup,
            entry_price, trigger_price, tp1, tp2, sl,
            ai_score, flow_score, pre_score, oi_change, rs_1h,
            is_compressed, probability, market_health, news_score,
            btc_regime, funding,
            outcome_trigger_hit, outcome_tp1_hit, outcome_tp2_hit, outcome_sl_hit,
            outcome_mfe, outcome_mae,
            pnl_pct, pnl_r, {_sel("pnl_pct_net")}, {_sel("pnl_r_net")},
            mfe_r, mae_r,
            {_sel("realized_pnl_pct")}, {_sel("sl_type_at_exit")},
            exit_reason, exit_price, {_sel("final_exit_price")},
            duration_minutes,
            shadow_rs, shadow_tags
        FROM shadow_trades
        WHERE decision = 'BUY'
          AND outcome_status = 'FINAL'
          AND outcome_checked = 1
          AND pnl_pct IS NOT NULL
        ORDER BY id ASC
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        log.warning("No checked BUY FINAL trades with PnL found.")
        return

    # ── Targets ────────────────────────────────────────────
    df["target_tp1"] = df["outcome_tp1_hit"].astype(int)
    df["target_win"] = (df["pnl_pct"] > 0).astype(int)
    df["target_win_net"] = (
        (df["pnl_pct_net"] > 0).astype(int)
        if "pnl_pct_net" in df.columns and df["pnl_pct_net"].notna().any()
        else df["target_win"]
    )

    # ── Sanity checks ─────────────────────────────────────
    if "pnl_pct_net" in df.columns:
        null_net = df["pnl_pct_net"].isna().sum()
        if null_net > 0:
            log.warning(f"{null_net}/{len(df)} rows have NULL pnl_pct_net (tracker v9.0 not run?)")

    if "final_exit_price" in df.columns:
        missing_exit = (df["final_exit_price"].isna() | (df["final_exit_price"] == 0)).sum()
        if missing_exit > 0:
            log.warning(f"{missing_exit}/{len(df)} rows have no final_exit_price")

    # ── Write canonical CSV ───────────────────────────────
    os.makedirs(os.path.dirname(OUTPUT_CSV) or ".", exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)
    log.info(f"ML Dataset exported to {OUTPUT_CSV} ({len(df)} BUY FINAL samples)")

    # ── Write net-of-costs view ───────────────────────────
    if "pnl_pct_net" in df.columns and df["pnl_pct_net"].notna().any():
        df.to_csv(OUTPUT_CSV_NET, index=False)
        log.info(f"Net dataset exported to {OUTPUT_CSV_NET}")

    # ── Per-bucket summary ────────────────────────────────
    try:
        df["ai_bucket"] = pd.cut(
            df["ai_score"],
            bins=[0, 20, 40, 60, 80, 100],
            labels=["AI_0_20", "AI_20_40", "AI_40_60", "AI_60_80", "AI_80_100"],
            right=False,
        )
        summary = df.groupby("ai_bucket", observed=True).agg(
            n=("pnl_r", "count"),
            avg_r=("pnl_r", "mean"),
            avg_r_net=("pnl_r_net", "mean") if "pnl_r_net" in df.columns else ("pnl_r", "mean"),
            win_pct=("target_win", "mean"),
        ).round(3)
        log.info(f"Bucket summary:\n{summary.to_string()}")
    except Exception as e:
        log.debug(f"Bucket summary skipped: {e}")


if __name__ == "__main__":
    export_ml_dataset()
