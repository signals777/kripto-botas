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

open_positions = {}

def log(msg):
    print(msg)

def get_top_symbols():
    try:
        response = session.get_market_leaderboard(category="spot", type="gainers")
        symbols = response["result"]["list"]
        filtered = []
        for item in symbols:
            symbol = item["symbol"]
            if symbol.endswith("USDT") and "1000" not in symbol:
                filtered.append(symbol)
        log(f"\n📈 Atrinkta {len(filtered[:SYMBOL_LIMIT])} SPOT gainer porų")
        return filtered[:SYMBOL_LIMIT]
    except Exception as e:
        log(f"❌ Klaida gaunant TOP poras: {e}")
        return []

def get_klines_dual(symbol):
    for category in ["spot", "linear"]:
        try:
            data = session.get_kline(category=category, symbol=symbol, interval=SYMBOL_INTERVAL, limit=20)
            klines = data["result"]["list"]
            if not klines or len(klines) < 3:
                log(f"⛔ {symbol}: per mažai žvakių ({category}): {len(klines)}")
                continue

            max_columns = max(len(k) for k in klines)
            columns = ["timestamp", "open", "high", "low", "close", "volume"]
            for i in range(6, min(max_columns, 15)):
                columns.append(f"col{i}")

            df = pd.DataFrame(klines, columns=columns[:len(klines[0])])
            df = df.astype({col: float for col in ["open", "high", "low", "close", "volume"]})
            return df
        except Exception as e:
            log(f"⛔ {symbol}: klaida gaunant žvakes ({category}): {e}")
    return None

def is_breakout(df):
    return df["close"].iloc[-1] > df["high"].iloc[-6:-1].max()

def volume_spike(df):
    return df["volume"].iloc[-1] > df["volume"].iloc[-6:-1].mean() * 1.05

def is_green_candle(df):
    return df["close"].iloc[-1] > df["open"].iloc[-1]

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
            log(f"⚠️ {symbol}: atmetama – kiekis per mažas: {qty} < {min_qty}")
            return 0
        return round(qty, 6)
    except Exception as e:
        log(f"⚠️ {symbol}: klaida skaičiuojant kiekį: {e}")
        return 0

def get_wallet_balance():
    try:
        usdt = next(c for c in session.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]["coin"] if c["coin"] == "USDT")
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
            log(f"📉 {symbol}: kaina={price}, pikas={peak}, kritimas={drawdown:.4f}")
            if drawdown <= -0.015:
                log(f"❌ {symbol}: pasiektas -1.5% nuo piko, pozicija uždaroma")
                session.place_order(category="linear", symbol=symbol, side="Sell", orderType="Market", qty=open_positions[symbol])
                del open_positions[symbol]
                break
        except Exception as e:
            log(f"⚠️ {symbol}: klaida stebint kainą: {e}")

def analyze_and_trade():
    log("\n" + "="*50)
    log(f"🕒 Analizės pradžia: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    symbols = get_top_symbols()
    log(f"\n🔄 Prasideda porų analizė – bus tikrinamos {len(symbols)} poros")

    balance = get_wallet_balance()
    log(f"💰 Balansas: {balance:.2f} USDT")

    filtered, opened = 0, 0
    rejected = []

    for symbol in symbols:
        time.sleep(0.5)
        df = get_klines_dual(symbol)
        if df is None:
            rejected.append((symbol, "klaida žvakėse"))
            continue

        green = is_green_candle(df)
        breakout = is_breakout(df)
        vol_spike = volume_spike(df)

        log(f"{symbol}: green={green}, breakout={breakout}, vol_spike={vol_spike}")

        if not (green or breakout or vol_spike):
            log(f"⛔ {symbol}: neatitinka filtrų")
            rejected.append((symbol, "neatitinka filtrų"))
            continue

        filtered += 1
        price = df["close"].iloc[-1]
        qty = calculate_qty(symbol, price, balance)
        if qty == 0:
            rejected.append((symbol, "kiekis per mažas"))
            continue

        try:
            session.set_leverage(category="linear", symbol=symbol, buyLeverage=LEVERAGE, sellLeverage=LEVERAGE)
            session.place_order(category="linear", symbol=symbol, side="Buy", orderType="Market", qty=qty)
            open_positions[symbol] = qty
            log(f"✅ Atidaryta pozicija: {symbol}, kiekis={qty}, kaina={price}")
            opened += 1
            progressive_risk_guard(symbol, price)
            if opened >= 3:
                break
        except Exception as e:
            log(f"❌ {symbol}: klaida atidarant poziciją: {e}")
            rejected.append((symbol, f"orderio klaida: {e}"))

    log(f"\n📊 ANALIZĖS ATASKAITA:")
    for sym, reason in rejected:
        log(f"⛔ {sym}: {reason}")
    log(f"\n✅ Atitiko filtrus: {filtered} porų")
    log(f"📥 Atidaryta pozicijų: {opened}")

def trading_loop():
    while True:
        analyze_and_trade()
        log("\n💤 Miegama 3600 sekundžių...\n")
        time.sleep(3600)

if __name__ == "__main__":
    trading_loop()
