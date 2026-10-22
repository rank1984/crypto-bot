"""
Check if there are DIP_BUY candidates that ranking is missing.
Read-only. Makes API calls to KuCoin.
"""
import os


def main():
    print("="*70)
    print("  DIP_BUY CHECK")
    print("="*70)

    from scanner.dynamic_universe import build_dynamic_universe
    from scanner.market_data import get_all_timeframes
    from scanner.indicators import calc_indicators

    print("Building universe...")
    symbols = build_dynamic_universe(btc_1h_move=0.0)
    print(f"Universe size: {len(symbols)}")

    deep_dips = []
    vwap_reclaims = []
    others = []
    checked = 0

    print(f"Checking first 40 symbols for vwap_dist...")
    for i, s in enumerate(symbols[:40], 1):
        if i % 10 == 0:
            print(f"  ... {i}/40")
        try:
            dfs = get_all_timeframes(s)
            if '5min' not in dfs or dfs['5min'] is None or len(dfs['5min']) == 0:
                continue
            ind = calc_indicators(dfs['5min'], dfs.get('1hour'))
            checked += 1
            vd = ind.get('vwap_dist', 0) or 0
            if vd < -2.0:
                deep_dips.append((s, vd))
            elif -0.5 < vd < 0.5:
                vwap_reclaims.append((s, vd))
            else:
                others.append((s, vd))
        except Exception as e:
            print(f"  {s}: ERROR {e}")

    print(f"\n{'='*70}")
    print(f"  RESULTS")
    print(f"{'='*70}")
    print(f"  Checked: {checked}")
    print(f"  DIP_BUY candidates (vwap_dist < -2.0): {len(deep_dips)}")
    for s, v in deep_dips[:15]:
        print(f"    {s}: vwap_dist={v:.2f}%")

    print(f"\n  VWAP_RECLAIM candidates (|vwap_dist| < 0.5): {len(vwap_reclaims)}")
    for s, v in vwap_reclaims[:10]:
        print(f"    {s}: vwap_dist={v:.2f}%")

    print(f"\n  Other (not DIP, not VWAP): {len(others)}")
    for s, v in others[:10]:
        print(f"    {s}: vwap_dist={v:.2f}%")

    print(f"\n{'='*70}")
    print(f"  VERDICT")
    print(f"{'='*70}")
    if len(deep_dips) == 0:
        print("  0 DIP_BUY available right now.")
        print("  → 0 BUY is CORRECT. Market has no dips. Wait for conditions.")
    else:
        print(f"  {len(deep_dips)} DIP_BUY candidates EXIST.")
        print("  → Problem is in RANKING, not entry_engine.")
        print("  → Ranking is picking VWAP_RECLAIM symbols instead of DIP_BUY.")


if __name__ == "__main__":
    main()
