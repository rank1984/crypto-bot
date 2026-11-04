"""
Deep diagnostic of vwap_dist — is it calculated correctly?
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    print("="*70)
    print("  VWAP_DIST DEEP DIAGNOSTIC")
    print("="*70)

    from scanner.dynamic_universe import build_dynamic_universe
    from scanner.market_data import get_all_timeframes
    from scanner.indicators import calc_indicators

    symbols = build_dynamic_universe(btc_1h_move=0.0)
    print(f"Universe: {len(symbols)} symbols\n")

    print(f"{'symbol':12s} {'close':>12s} {'vwap':>12s} {'vwap_dist':>12s} {'min_vwap_dist':>15s}")
    print("-" * 70)

    neg_count = 0
    zero_count = 0
    pos_count = 0

    for s in symbols[:20]:
        try:
            dfs = get_all_timeframes(s)
            if not dfs or "5min" not in dfs or dfs["5min"] is None:
                continue

            df = dfs["5min"]
            ind = calc_indicators(df, dfs.get("1hour"))

            close = float(df["close"].iloc[-1])
            vwap = ind.get("vwap", 0) or 0
            vwap_dist = ind.get("vwap_dist", 0) or 0

            # Manual calculation
            manual_dist = ((close - vwap) / vwap * 100) if vwap > 0 else 0

            # Min vwap_dist over last 20 bars
            min_vd = 0
            for i in range(max(0, len(df) - 20), len(df)):
                c = float(df["close"].iloc[i])
                if vwap > 0:
                    d = (c - vwap) / vwap * 100
                    if d < min_vd:
                        min_vd = d

            if vwap_dist < -0.5:
                neg_count += 1
            elif vwap_dist > 0.5:
                pos_count += 1
            else:
                zero_count += 1

            marker = ""
            if abs(vwap_dist - manual_dist) > 0.1:
                marker = " ⚠️ MISMATCH"

            print(f"{s:12s} {close:>12.6f} {vwap:>12.6f} {vwap_dist:>12.3f} {min_vd:>15.3f}{marker}")

        except Exception as e:
            print(f"{s:12s} ERROR: {e}")

    print()
    print("="*70)
    print("  SUMMARY")
    print("="*70)
    print(f"  vwap_dist < -0.5:  {neg_count}")
    print(f"  -0.5 to 0.5:       {zero_count}")
    print(f"  vwap_dist > 0.5:   {pos_count}")
    print()
    print("  If most are between -0.5 and 0.5:")
    print("    → VWAP follows price too closely (short window)")
    print("    → DIP_BUY as defined (-2%) will never trigger")
    print()
    print("  If manual_dist != vwap_dist:")
    print("    → vwap_dist is calculated incorrectly in indicators.py")


if __name__ == "__main__":
    main()