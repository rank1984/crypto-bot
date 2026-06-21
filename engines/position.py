def calc_position_pct(confidence: float) -> float:
    if confidence >= 90:
        return 5.0
    elif confidence >= 80:
        return 3.0
    elif confidence >= 70:
        return 2.0
    else:
        return 0.0 # מתחת ל-70 אנחנו רק במעקב
