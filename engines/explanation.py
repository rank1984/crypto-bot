def get_coin_explanation(c: dict) -> tuple[list[str], list[str]]:
    """
    Explanation Layer:
    מפרק את מצב השוק והלחץ המצטבר לצ'ק-ליסט ויזואלי של סימנים חיוביים ושליליים.
    """
    pos_signals = []
    neg_signals = []
    
    flow_comp = c.get("flow_components", {})
    pre_comp = c.get("pre_components", {})
    
    # 1. בדיקת לחץ (Compression)
    if pre_comp.get("compression", 0) >= 7 or c.get("is_compressed", False):
        pos_signals.append("Compression — לחץ מצטבר")
    else:
        neg_signals.append("אין Compression")
        
    # 2. בדיקת כסף חדש וזרימה (OI & CVD)
    if flow_comp.get("oi", 0) >= 12 or c.get("oi_rising", False):
        pos_signals.append("OI עולה — כסף חדש נכנס")
    else:
        neg_signals.append("אין כסף חדש / OI חלש")
        
    if flow_comp.get("whale", 0) >= 7 or c.get("whale_detected", False):
        pos_signals.append("פעילות לווייתנים תומכת")
        
    # 3. בדיקת עוצמה יחסית (RS)
    if flow_comp.get("rs", 0) >= 10 or c.get("rs_positive", False):
        pos_signals.append("RS מול BTC חיובי")
    else:
        neg_signals.append("חולשה מול BTC")
        
    return pos_signals, neg_signals
