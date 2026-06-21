"""
CRYPTO-BOT Elite — Telegram Pro
פלט מקצועי עם כל המנועים.
"""
import requests
from utils.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from utils.logger import get_logger

log = get_logger(__name__)

_GRADES = [(90,"A+"),(80,"A"),(70,"A-"),(60,"B+"),(50,"B"),(0,"B-")]

def _grade(s):
    for t,l in _GRADES:
        if s >= t: return l
    return "C"

def _fp(p):
    if p >= 1:      return f"{p:.4f}"
    if p >= 0.01:   return f"{p:.5f}"
    if p >= 0.0001: return f"{p:.6f}"
    return f"{p:.8f}"

def _pct(v):
    return f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"

def _e(s: str) -> str:
    for c in r"\_*[]()~`>#+-=|{}.!":
        s = s.replace(c, f"\\{c}")
    return s


def format_message(top_coins: list[dict]) -> str:
    lines = ["🔥 *CRYPTO\\-BOT Elite*\n"]

    if top_coins:
        regime = top_coins[0].get("regime", "RANGE")
        r_em   = {"TRENDING_BULL":"🟢","ALTSEASON":"🚀","RANGE":"🟡",
                   "RISK_OFF":"🔴","TRENDING_BEAR":"⛔"}.get(regime,"⚪")
        lines.append(f"{r_em} Regime: `{_e(regime)}`\n")

    for i, c in enumerate(top_coins, 1):
        sym   = _e(c["symbol"])
        grade = _grade(c["final_score"])
        dec   = c.get("entry_decision","NO")
        setup = c.get("entry_setup","")
        phase = c.get("pre_exp_phase","")
        p_em  = c.get("pre_exp_emoji","⚪")

        # ── Entry decision ────────────────────────────────────────────────────
        if dec == "BUY":
            action_block = (
                f"\n🟢 *BUY* — {_e(setup)}\n"
                f"📌 Entry: `{_fp(c['entry_price'])}`\n"
                f"🛑 SL:    `{_fp(c['entry_sl'])}`\n"
                f"🎯 TP1:   `{_fp(c['entry_tp1'])}`  TP2: `{_fp(c['entry_tp2'])}`\n"
                f"⚖️ R:R:   `{c['entry_rr']:.1f}x`"
            )
        elif dec == "WAIT":
            action_block = f"\n🟡 *WAIT* — {_e(setup)} setup detectado"
        else:
            reason = _e(c.get("entry_reason",""))
            action_block = f"\n⚪ *NO TRADE* — {reason}"

        # ── Why block (reasons) ───────────────────────────────────────────────
        reasons = []
        comps   = c.get("flow_components", {})
        if comps.get("oi",0)    > 5:  reasons.append("✓ OI Expansion")
        if comps.get("cvd",0)   > 8:  reasons.append("✓ Positive CVD")
        if comps.get("rs",0)    > 8:  reasons.append("✓ RS vs BTC strong")
        if comps.get("whale",0) > 5:  reasons.append("✓ Whale activity")
        if c.get("is_compressed"):    reasons.append("✓ Compression detected")
        if c.get("is_sympathy"):      reasons.append(f"✓ Sympathy: {_e(c.get('leader','').replace('USDT',''))}")
        if not reasons:               reasons.append("Volume + Momentum")

        reasons_str = "\n".join(reasons)

        # ── Full block ────────────────────────────────────────────────────────
        block = "\n".join(filter(None, [
            f"*{i}\\. {sym}* \\[{grade}\\]",
            "",
            f"👑 Score: `{c['final_score']:.0f}` | Flow: `{c.get('flow_score',0):.0f}` | Pre\\-Exp: `{c.get('pre_exp_score',0):.0f}`",
            f"💰 Price: `{_fp(c['price'])}`",
            "",
            f"{p_em} Phase: *{_e(phase)}*",
            f"📈 Direction: *{_e(c.get('pre_exp_dir','NEUTRAL'))}*",
            "",
            f"📊 RVOL: `{c['rvol']:.1f}x` | Accel: `{c['vol_accel']:.1f}x`",
            f"🟢 VWAP: `{_pct(c['vwap_dist'])}` | RSI: `{c['rsi_14']:.0f}`",
            f"⏱ Mom: 5m `{_pct(c['momentum_5m'])}` 15m `{_pct(c['momentum_15m'])}` 1h `{_pct(c['momentum_1h'])}`",
            f"💪 RS BTC: `{_pct(c.get('rs_1h',0))}` 1h | `{_pct(c.get('rs_4h',0))}` 4h",
            "",
            f"*Why:*\n{_e(reasons_str)}",
            action_block,
        ]))

        lines.append(block)
        lines.append("━━━━━━━━━━━━")

    return "\n".join(lines)


def send_telegram(top_coins: list[dict]) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram not configured — printing to stdout")
        print(format_message(top_coins))
        return False

    text = format_message(top_coins)
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        r = requests.post(url, json={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       text,
            "parse_mode": "MarkdownV2",
        }, timeout=10)
        r.raise_for_status()
        log.info("Telegram ✓")
        return True
    except Exception as e:
        log.error(f"Telegram failed: {e}")
        # Fallback: plain text
        try:
            plain = "\n".join([
                f"{i+1}. {c['symbol']} | {c['final_score']:.0f} | Flow:{c.get('flow_score',0):.0f} | {c.get('pre_exp_phase','')} | {c.get('entry_decision','NO')}"
                for i, c in enumerate(top_coins)
            ])
            requests.post(url, json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text":    f"CRYPTO-BOT Elite\n\n{plain}",
            }, timeout=10)
        except Exception:
            pass
        return False
