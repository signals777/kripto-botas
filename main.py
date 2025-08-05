import time
import pandas as pd
import numpy as np
from datetime import datetime
from pybit.unified_trading import HTTP

API_KEY = "6jW8juUDFLe1ykvL3L"
API_SECRET = "3UH1avHKHWWyMCmU26RMxh784TGSA8lurzST"

session = HTTP(api_key=API_KEY, api_secret=API_SECRET)

LEVERAGE = 5
RISK_PERCENT = 0.05
SYMBOL_INTERVAL = "30"
SYMBOL_LIMIT = 30

def log(msg):
    print(msg)

def get_top_symbols():
    try:
        tickers = session.get_tickers(category="linear")["result"]["list"]
        symbols = []
        for item in tickers:
            symbol = item["symbol"]
            if symbol.endswith("USDT") and "1000" not in symbol and "10000" not in symbol:
                symbols.append(symbol)
        log(f"\n📈 Atrinkta {len(symbols[:SYMBOL_LIMIT])} FUTURES porų tikrinimui")
        return symbols[:SYMBOL_LIMIT]
    except Exception as e:
        log(f"❌ Klaida gaunant TOP poras: {e}")
        return []

def get_klines_progressive(session, symbol: str, interval: str = "30"):
    for limit in range(15, 2, -1):
        try:
            data = session.get_kline(category="linear", symbol=symbol, interval=interval, limit=limit)
            klines = data["result"]["list"]
            if not klines or len(klines) < 3:
                log(f"{symbol}: gauta {len(klines)} žvakių su limit={limit}")
                continue
            df = pd.DataFrame(klines, columns=["timestamp", "open", "high", "low", "close", "volume", "_", "_"])
            df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
            return df, None
        except Exception:
            continue
    return None, f"{symbol}: nepavyko gauti pakankamai žvakių (3–15 bandymų nesėkmingi)"

def is_breakout(df):
    last_close = df["close"].iloc[-1]
    prev_highs = df["high"].iloc[-6:-1]
    return last_close > prev_highs.max()

def volume_spike(df):
    recent = df["volume"].iloc[-1]
    average = df["volume"].iloc[-6:-1].mean()
    return recent > average * 1.05

def is_green_candle(df):
    last = df.iloc[-1]
    return last["close"] > last["open"]

def calculate_qty(symbol, entry_price, balance):
    risk_amount = balance * RISK_PERCENT
    loss_per_unit = entry_price * 0.015
    qty = (risk_amount * LEVERAGE) / loss_per_unit
    try:
        info = session.get_instruments_info(category="linear", symbol=symbol)["result"]["list"][0]
        qty_step = float(info["lotSizeFilter"]["qtyStep"])
        min_qty = float(info["lotSizeFilter"]["minOrderQty"])
        qty = np.floor(qty / qty_step) * qty_step
        if qty < min_qty:
            return 0, f"{symbol}: kiekis per mažas ({qty} < {min_qty})"
        return round(qty, 6), None
    except Exception as e:
        return 0, f"{symbol}: klaida gaunant kiekio info: {e}"

def get_wallet_balance():
    try:
        balance = session.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]["coin"]
        usdt = next(c for c in balance if c["coin"] == "USDT")
        return float(usdt["walletBalance"])
    except Exception as e:
        log(f"❌ Klaida gaunant balansą: {e}")
        return 0

def progressive_risk_guard(symbol, entry_price):
    peak = entry_price
    while True:
        time.sleep(15)
        try:
            price = float(session.get_tickers(category="linear", symbol=symbol)["result"]["list"][0]["lastPrice"])
            if price > peak:
                peak = price
            drawdown = (price - peak) / peak
            log(f"📉 {symbol}: kaina={price:.4f}, pikas={peak:.4f}, kritimas={drawdown:.2%}")
            if drawdown <= -0.015:
                log(f"❌ {symbol}: -1.5% nuo piko – pozicija uždaroma")
                session.place_order(category="linear", symbol=symbol, side="Sell", orderType="Market", qty=open_positions[symbol])
                del open_positions[symbol]
                break
        except Exception as e:
            log(f"⚠️ Klaida stebint {symbol}: {e}")

open_positions = {}

def analyze_and_trade():
    log("\n" + "="*60)
    log(f"🕒 Analizės pradžia: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")

    symbols = get_top_symbols()
    log(f"\n🔄 Prasideda porų analizė – tikrinamos {len(symbols)} poros")
    balance = get_wallet_balance()
    log(f"💰 Balansas: {balance:.2f} USDT")

    opened_count = 0
    reason_counter = {}

    for symbol in symbols:
        time.sleep(0.5)
        df, err = get_klines_progressive(session, symbol, interval=SYMBOL_INTERVAL)
        if err:
            log(f"⛔ {err}")
            reason_key = err.split(":")[1].strip() if ":" in err else err
            reason_counter[reason_key] = reason_counter.get(reason_key, 0) + 1
            continue

        green = is_green_candle(df)
        breakout = is_breakout(df)
        vol_spike = volume_spike(df)

        log(f"{symbol}: green={green}, breakout={breakout}, vol_spike={vol_spike}")

        if not vol_spike:
            reason = "nėra tūrio šuolio"
            log(f"⛔ {symbol} atmetama – {reason}")
            reason_counter[reason] = reason_counter.get(reason, 0) + 1
            continue

        price = df["close"].iloc[-1]
        qty, qty_err = calculate_qty(symbol, price, balance)
        if qty_err:
            log(f"⚠️ {qty_err}")
            reason_counter["mažas kiekis / netinkamas"] = reason_counter.get("mažas kiekis / netinkamas", 0) + 1
            continue

        try:
            session.set_leverage(category="linear", symbol=symbol, buyLeverage=LEVERAGE, sellLeverage=LEVERAGE)
            session.place_order(category="linear", symbol=symbol, side="Buy", orderType="Market", qty=qty)
            log(f"✅ Atidaryta pozicija: {symbol}, kiekis={qty}, kaina={price}")
            open_positions[symbol] = qty
            opened_count += 1
            progressive_risk_guard(symbol, price)
            if opened_count >= 3:
                break
        except Exception as e:
            log(f"❌ Orderio klaida: {e}")
            reason_counter["orderio klaida"] = reason_counter.get("orderio klaida", 0) + 1

    log("\n📊 ANALIZĖS ATASKAITA:")
    for reason, count in reason_counter.items():
        log(f"❌ Atmesta dėl „{reason}“: {count} porų")
    log(f"✅ Iš viso atidaryta pozicijų: {opened_count}")

def trading_loop():
    while True:
        analyze_and_trade()
        log("\n💤 Miegama 3600 sekundžių...\n")
        time.sleep(3600)

if __name__ == "__main__":
    trading_loop()
