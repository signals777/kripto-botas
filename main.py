import os
import time
import threading
import pandas as pd
from pybit.unified_trading import HTTP

api_key = "6jW8juUDFLe1ykvL3L"
api_secret = "3UH1avHKHWWyMCmU26RMxh784TGSA8lurzST"

MAX_POSITIONS = 3
LEVERAGE = 5
RISK_PERCENT = 5
TRAILING_TRIGGER = 0.02  # +2%
TRAILING_DROP = 0.01     # -1%
CHECK_INTERVAL = 60 * 60  # 1 val.

def get_session():
    return HTTP(api_key=api_key, api_secret=api_secret)

def get_balance():
    try:
        session = get_session()
        data = session.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]["coin"]
        usdt = next((x for x in data if x["coin"] == "USDT"), {})
        bal = float(usdt.get("walletBalance", 0))
        print(f"💰 Balansas: {bal:.2f} USDT")
        return bal
    except Exception as e:
        print(f"❌ Balanso klaida: {e}")
        return 0

def get_price(symbol):
    try:
        session = get_session()
        data = session.get_tickers(category="linear")["result"]["list"]
        price = next((float(i["lastPrice"]) for i in data if i["symbol"] == symbol), None)
        return price
    except:
        return None

def calculate_qty(symbol):
    try:
        session = get_session()
        data = session.get_tickers(category="linear")["result"]["list"]
        price = next((float(i["lastPrice"]) for i in data if i["symbol"] == symbol), None)
        balance = get_balance()
        usdt_to_risk = balance * RISK_PERCENT / 100
        qty = (usdt_to_risk * LEVERAGE) / price
        qty = round(qty, 3)
        return qty if qty >= 0.01 else 0
    except:
        return 0

def open_long(symbol, qty):
    try:
        session = get_session()
        session.set_leverage(category="linear", symbol=symbol, buyLeverage=LEVERAGE, sellLeverage=LEVERAGE)
        order = session.place_order(
            category="linear", symbol=symbol, side="Buy",
            orderType="Market", qty=qty
        )
        entry = float(order["result"]["avgPrice"])
        print(f"🟢 LONG atidarytas: {symbol}, qty={qty}, entry={entry}")
        return entry
    except Exception as e:
        print(f"❌ Orderio klaida: {e}")
        return None

def close_long(symbol, qty):
    try:
        session = get_session()
        session.place_order(
            category="linear", symbol=symbol, side="Sell",
            orderType="Market", qty=qty, reduceOnly=True
        )
        print(f"🔴 LONG uždarytas: {symbol}, qty={qty}")
    except Exception as e:
        print(f"❌ Uždarymo klaida: {e}")

def progressive_risk_guard(symbol, entry_price, qty):
    peak = entry_price
    cumulative_loss = 0
    last_price = entry_price

    while True:
        price = get_price(symbol)
        if price is None:
            time.sleep(10)
            continue

        if price > peak:
            peak = price
            cumulative_loss = 0
            print(f"📈 Naujas pikas: {peak:.4f} ({symbol})")

        elif price < last_price:
            drop = (last_price - price) / peak
            cumulative_loss += drop
            print(f"📉 Kaina krenta: {symbol}, sumažėjimas={drop*100:.2f}%, sukauptas={cumulative_loss*100:.2f}%")

            if cumulative_loss >= TRAILING_DROP:
                print(f"⛔ Progresyvus SL suveikė: {symbol}, uždaryta ties {price:.4f}")
                close_long(symbol, qty)
                break

        last_price = price
        time.sleep(60)

def get_klines(symbol, interval="60", limit=100):
    try:
        session = get_session()
        raw = session.get_kline(category="linear", symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(raw["result"]["list"])
        df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'turnover']
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        return df
    except:
        return pd.DataFrame()

def analyze_symbol(df):
    last = df.iloc[-1]
    prev_highs = df['close'].rolling(5).max()
    breakout = last['close'] > prev_highs.iloc[-2]
    vol_spike = last['volume'] > df['volume'].mean() * 1.2
    green = last['close'] > last['open']
    return breakout, vol_spike, green

def fetch_symbols():
    try:
        session = get_session()
        data = session.get_tickers(category="linear")["result"]["list"]
        return [x["symbol"] for x in data if x["symbol"].endswith("USDT")]
    except:
        return []

def trading_loop():
    opened = {}
    while True:
        if len(opened) >= MAX_POSITIONS:
            time.sleep(CHECK_INTERVAL)
            continue

        symbols = fetch_symbols()
        print(f"🔄 Tikrinamos {len(symbols)} poros")

        for symbol in symbols:
            if symbol in opened:
                continue
            df = get_klines(symbol)
            if df.empty or len(df) < 10:
                continue
            breakout, vol_spike, green = analyze_symbol(df)
            print(f"{symbol}: green={green}, breakout={breakout}, vol_spike={vol_spike}")
            if not green:
                print(f"⛔ {symbol} atmetama – žvakė raudona (green=False)")
                continue
            if not breakout:
                print(f"⛔ {symbol} atmetama – breakout=False")
                continue
            if not vol_spike:
                print(f"⛔ {symbol} atmetama – vol_spike=False")
                continue

            qty = calculate_qty(symbol)
            if qty == 0:
                print(f"⚠️ {symbol} atmetama – kiekis per mažas")
                continue

            entry = open_long(symbol, qty)
            if entry:
                opened[symbol] = (entry, qty)
                threading.Thread(target=progressive_risk_guard, args=(symbol, entry, qty), daemon=True).start()
                if len(opened) >= MAX_POSITIONS:
                    break
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    trading_loop()
