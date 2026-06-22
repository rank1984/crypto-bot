from datetime import datetime
from db.manager import log_filtered_coin

def check_and_log_filters(coin_metrics: dict) -> bool:
    """
    מריץ פילטרים קשיחים. אם מטבע נפסל, 
    מתעד את כל המטריקות שלו ואת סיבת הפסילה ב-DB.
    """
    reason_filtered = None
    rvol = coin_metrics.get('rvol', 0)
    
    # הפילטר הקשיח הנוכחי (לפני השינוי ל-Adaptive)
    if rvol < 3.0:
        reason_filtered = "Low RVOL"
        
    # [כאן אפשר להוסיף פילטרים קשיחים נוספים כמו סחירות, מרווחים וכו']
    # elif gap_risk > X: reason_filtered = "High Gap Risk"

    if reason_filtered:
        # בניית אובייקט התיעוד המלא
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "symbol": coin_metrics['symbol'],
            "final_score": coin_metrics.get('final_score', 0),
            "flow_score": coin_metrics.get('flow_score', 0),
            "pre_score": coin_metrics.get('pre_score', 0),
            "rvol": rvol,
            "oi_change": coin_metrics.get('oi_change', 0),
            "rs_1h": coin_metrics.get('rs_1h', 0),
            "rs_4h": coin_metrics.get('rs_4h', 0),
            "is_compressed": int(coin_metrics.get('is_compressed', False)),
            "whale_detected": int(coin_metrics.get('whale_detected', False)),
            "reason_filtered": reason_filtered
        }
        
        # שמירה אסינכרונית או ישירה ל-DB
        log_filtered_coin(log_data)
        return False # המטבע נפסל
        
    return True # המטבע עבר את הפילטרים
