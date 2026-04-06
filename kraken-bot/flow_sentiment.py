from __future__ import annotations

from logic import calculate_rsi, calculate_atr


def compute_order_flow_imbalance(recent_trades: list[dict]) -> dict:
    buy_vol = 0.0
    sell_vol = 0.0

    for trade in recent_trades:
        cost = float(trade.get("cost") or 0.0)
        if cost <= 0:
            price = float(trade.get("price") or 0.0)
            amount = float(trade.get("amount") or 0.0)
            cost = price * amount
        if cost <= 0:
            continue

        side = (trade.get("side") or "").lower()
        if side == "buy":
            buy_vol += cost
        else:
            sell_vol += cost

    total_vol = buy_vol + sell_vol
    if total_vol <= 0:
        return {"buy_vol": 0.0, "sell_vol": 0.0, "total_vol": 0.0, "ratio": 0.5}

    return {
        "buy_vol": buy_vol,
        "sell_vol": sell_vol,
        "total_vol": total_vol,
        "ratio": round(buy_vol / total_vol, 4),
    }


def evaluate_flow_sentiment(
    recent_trades: list[dict],
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    current_price: float,
    vpin: float,
    imbalance_long_threshold: float = 0.65,
    imbalance_short_threshold: float = 0.35,
    vpin_max: float = 0.75,
    vpin_spike_block: float = 0.85,
    rsi_min: float = 40.0,
    rsi_max: float = 60.0,
    volume_ma_period: int = 20,
    volume_mult: float = 1.5,
    rsi_period: int = 14,
) -> dict:
    atr = calculate_atr(highs, lows, closes)
    rsi = calculate_rsi(closes, period=rsi_period)

    flow = compute_order_flow_imbalance(recent_trades)

    result = {
        "strategy": "flow_sentiment",
        "signal": None,
        "side": None,
        "conviction": 0.0,
        "rsi": rsi,
        "atr": atr,
        "price": current_price,
        "flow_ratio": flow["ratio"],
        "flow_buy_vol": flow["buy_vol"],
        "flow_sell_vol": flow["sell_vol"],
        "vpin": vpin,
        "volume_confirmed": False,
        "vpin_ok": False,
        "vpin_spike": False,
        "rsi_ok": False,
    }

    if atr <= 0 or len(closes) < rsi_period + 2:
        return result

    if vpin >= vpin_spike_block:
        result["vpin_spike"] = True
        return result

    vpin_ok = vpin < vpin_max
    result["vpin_ok"] = vpin_ok
    if not vpin_ok:
        return result

    rsi_ok = rsi_min <= rsi <= rsi_max
    result["rsi_ok"] = rsi_ok

    vol_slice = volumes[-volume_ma_period:]
    vol_avg = sum(vol_slice) / max(len(vol_slice), 1) if vol_slice else 0
    latest_vol = volumes[-1] if volumes else 0
    volume_confirmed = latest_vol > vol_avg * volume_mult and vol_avg > 0
    result["volume_confirmed"] = volume_confirmed

    long_flow = flow["ratio"] >= imbalance_long_threshold
    short_flow = flow["ratio"] <= imbalance_short_threshold

    if long_flow and rsi_ok and volume_confirmed and vpin_ok:
        conviction = 0.65
        if flow["ratio"] >= 0.75:
            conviction += 0.10
        if flow["ratio"] >= 0.80:
            conviction += 0.05
        if vpin < 0.50:
            conviction += 0.05
        if 45 <= rsi <= 55:
            conviction += 0.05
        rvol = latest_vol / vol_avg if vol_avg > 0 else 0
        if rvol >= 2.0:
            conviction += 0.05
        conviction = min(conviction, 1.0)

        result["signal"] = "long"
        result["side"] = "long"
        result["conviction"] = round(conviction, 2)

    elif short_flow and rsi_ok and volume_confirmed and vpin_ok:
        conviction = 0.65
        if flow["ratio"] <= 0.25:
            conviction += 0.10
        if flow["ratio"] <= 0.20:
            conviction += 0.05
        if vpin < 0.50:
            conviction += 0.05
        if 45 <= rsi <= 55:
            conviction += 0.05
        rvol = latest_vol / vol_avg if vol_avg > 0 else 0
        if rvol >= 2.0:
            conviction += 0.05
        conviction = min(conviction, 1.0)

        result["signal"] = "short"
        result["side"] = "short"
        result["conviction"] = round(conviction, 2)

    return result
