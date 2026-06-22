from datetime import datetime
from db.research_layer import log_filtered_coin

def passes_hard_filters(coin_metrics: dict) -> bool:
    """
    בודק פילטרים קשיחים פיזיים (נפח, נזילות).
    במידה ונכשל, מתעד את כל המטריקות לתוך SQLite למחקר עתידי.
    """
    rvol = coin_metrics.get('rvol', 0)
    reason_filtered = None
    
    # הרף הקשיח המקורי לפני המעבר למודל אדפטיבי
    if rvol < 3.0:
        reason_filtered = "Low RVOL"
        
    # במידה ויש פילטרים קשיחים נוספים בעתיד
    # elif market_cap < 5000000: reason_filtered = "Ultra-Small Cap"

    if reason_filtered:
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "symbol": coin_metrics['symbol'],
            "final_score": coin_metrics.get('final_score', 0),
            "flow_score": coin_metrics.get('flow_score', 0),
            "pre_score": coin_metrics.get('pre_score', 0),
            "rvol": rvol,
            "oi_change": coin_metrics.get('oi_change', 0),
            "rs_1h": coin_metrics.get('rs_1h', 0),
            "is_compressed": int(coin_metrics.get('is_compressed', False)),
            "whale_detected": int(coin_metrics.get('whale_detected', False)),
            "reason_filtered": reason_filtered
        }
        log_filtered_coin(log_data)
        return False
        
    return True
