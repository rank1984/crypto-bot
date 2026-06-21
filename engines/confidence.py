def calc_confidence(score: float, pre: float, flow: float, fakeout_risk: str, whales: bool) -> float:
    # משקלות בסיס
    base_conf = (score * 0.40) + (flow * 0.35) + (pre * 0.25)
    
    # בונוסים וקנסות
    if whales:
        base_conf += 5
    if fakeout_risk in ["בינוני", "גבוה"]:
        base_conf -= 15
        
    return min(max(base_conf, 0.0), 100.0)
