import json
import os

RUNNER_FILE = "active_runners.json"

def load_runners() -> dict:
    if not os.path.exists(RUNNER_FILE):
        return {}
    with open(RUNNER_FILE, "r") as f:
        try:
            return json.load(f)
        except:
            return {}

def save_runner(symbol: str, entry_price: float, sl: float, tp1: float, tp2: float):
    runners = load_runners()
    runners[symbol] = {
        "entry": entry_price,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "highest_price": entry_price
    }
    with open(RUNNER_FILE, "w") as f:
        json.dump(runners, f, indent=4)

def check_runner_status(symbol: str, current_price: float) -> dict:
    runners = load_runners()
    if symbol not in runners:
        return None
    
    data = runners[symbol]
    # עדכון מחיר שיא (לטובת Trailing Stop בעתיד)
    if current_price > data["highest_price"]:
        data["highest_price"] = current_price
        with open(RUNNER_FILE, "w") as f:
            json.dump(runners, f, indent=4)
            
    open_pnl = ((current_price - data["entry"]) / data["entry"]) * 100
    
    return {
        "is_active": True,
        "entry": data["entry"],
        "open_pnl_pct": round(open_pnl, 1)
    }
