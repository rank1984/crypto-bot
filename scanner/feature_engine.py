"""
CRYPTO-BOT Elite — Feature Engine
מייצר סיגנלים ראשוניים מה-Universe
"""

import random

def enrich_coin(c: dict) -> dict:
    """
    הופך מטבע רדום למטבע עם signal intelligence בסיסי
    (בינתיים סימולציה — אחר כך נחבר real data feeds)
    """

    price = c.get("price", 1)

    # ── סימולציה חכמה של market behavior ──
    flow = random.randint(10, 90)
    pre = random.randint(10, 90)

    compression = random.random() > 0.7
    oi_change = random.uniform(-3, 8)
    rs = random.uniform(-5, 5)

    c["flow_score"] = flow
    c["pre_score"] = pre
    c["is_compressed"] = compression
    c["oi_change"] = oi_change
    c["rs_1h"] = rs

    return c


def enrich_universe(coins: list[dict]) -> list[dict]:
    return [enrich_coin(c) for c in coins]
