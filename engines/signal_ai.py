def get_signal_state(raw_decision: str, confidence: float, is_active_runner: bool) -> str:
    """
    Decision Layer:
    מחשב ומחזיר את המצב הטהור של המטבע בלבד.
    """
    if is_active_runner:
        return "RUNNER"
        
    if raw_decision == "BUY" and confidence >= 70:
        return "BUY"
        
    if raw_decision == "WAIT" or (60 <= confidence < 70):
        return "PREPARE"
        
    if 40 <= confidence < 60:
        return "WATCH"
        
    return "IGNORE"
