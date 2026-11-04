"""
Diagnose why DIP_BUY setup is never detected.
Read-only — no modifications.
"""
import sys
import os

# ── FIX: add repo root to sys.path ─────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    print("="*70)
    print("  DIP_BUY DIAGNOSTIC")
    print("="*70)

    from scanner.dynamic_universe import build_dynamic_universe
    from scanner.market_data import get_all_timeframes
    from scanner.indicators import calc_indicators
    from scanner.volume import calc_volume
    from scanner.relative_strength import calc_relative_strength, set_btc_reference

    # Set BTC reference
    print("\nLoading BTC reference...")
    try:
        btc = get_all_timeframes("BTCUSDT")
        if btc and btc.get("1hour") is not None:
            set_btc_reference(btc["1hour"])
            print("  ✅ BTC reference set")
        else:
            print("  ⚠️ BTC 1h not available — rs_1h will be 0")
    except Exception as e:
        print(f"  ⚠️ BTC reference failed: {e}")

    print("\nBuilding universe...")
    symbols = build_dynamic_universe(btc_1h_move=0.0)
    print(f"  Universe: {len(symbols)} symbols")

    # 🆕 NEW thresholds (match entry_engine v8.9)
    VWAP_THRESHOLD = -0.8
    VOL_THRESHOLD = 0.5
    RS_THRESHOLD = 0.2

    print("\n" + "="*70)
    print(f"  Thresholds: vwap_dist<{VWAP_THRESHOLD}, vol_accel>{VOL_THRESHOLD}, rs_1h>{RS_THRESHOLD}")
    print("="*70)
    print(f"  {'symbol':15s} {'vwap_dist':>12s} {'vol_accel':>12s} {'rs_1h':>10s} {'DIP?':>6s}")
    print("  " + "-"*60)

    dip_count = 0
    vwap_deep = 0
    vol_high = 0
    rs_pos = 0
    all_three = 0
    checked = 0

    for s in symbols:
        try:
            dfs = get_all_timeframes(s)
            if not dfs or "5min" not in dfs or dfs["5min"] is None or len(dfs["5min"]) == 0:
                continue

            ind = calc_indicators(dfs["5min"], dfs.get("1hour"))
            vol = calc_volume(dfs["5min"])
            rs = calc_relative_strength(dfs["1hour"]) if dfs.get("1hour") is not None else {"rs_1h": 0}

            vd = ind.get("vwap_dist", 0) or 0
            va = vol.get("vol_accel", 0) or 0
            rs1h = rs.get("rs_1h", 0) or 0

            cond_vwap = vd < VWAP_THRESHOLD
            cond_vol = va > VOL_THRESHOLD
            cond_rs = rs1h > RS_THRESHOLD

            if cond_vwap:
                vwap_deep += 1
            if cond_vol:
                vol_high += 1
            if cond_rs:
                rs_pos += 1
            if cond_vwap and cond_vol and cond_rs:
                all_three += 1
                dip_count += 1

            checked += 1
            is_dip = cond_vwap and cond_vol and cond_rs

            marker = "✅" if is_dip else "no"
            print(f"  {s:15s} {vd:>12.2f} {va:>12.2f} {rs1h:>10.3f} {marker:>6s}")

        except Exception as e:
            print(f"  {s:15s} ERROR: {e}")

    print("\n" + "="*70)
    print("  SUMMARY")
    print("="*70)
    print(f"  Checked:              {checked}")
    print(f"  vwap_dist < {VWAP_THRESHOLD}:     {vwap_deep}  ({vwap_deep*100//checked if checked else 0}%)")
    print(f"  vol_accel > {VOL_THRESHOLD}:      {vol_high}  ({vol_high*100//checked if checked else 0}%)")
    print(f"  rs_1h > {RS_THRESHOLD}:            {rs_pos}  ({rs_pos*100//checked if checked else 0}%)")
    print(f"  ALL THREE (DIP_BUY):  {all_three}  ({all_three*100//checked if checked else 0}%)")
    print()

    if all_three == 0:
        print("  ❌ 0 DIP_BUY — at least one condition always fails")
        print()
        print("  Which condition is the blocker?")
        if vwap_deep == 0:
            print(f"    → vwap_dist NEVER < {VWAP_THRESHOLD} — market has no dips")
            print(f"      Fix: relax further to {VWAP_THRESHOLD + 0.3}")
        elif vol_high == 0:
            print(f"    → vol_accel NEVER > {VOL_THRESHOLD} — volume acceleration broken")
            print(f"      Fix: check calc_volume, or relax to {VOL_THRESHOLD - 0.2}")
        elif rs_pos == 0:
            print(f"    → rs_1h NEVER > {RS_THRESHOLD} — market is weak vs BTC")
            print(f"      Fix: remove rs_1h condition, or relax to {RS_THRESHOLD - 0.2}")
        else:
            print("    → Each condition passes sometimes, but never together")
            print("      Fix: relax one or more thresholds")
    else:
        print(f"  ✅ {all_three} DIP_BUY candidates found")

    print("\n✅ Diagnostic complete\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())