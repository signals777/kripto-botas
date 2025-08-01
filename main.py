# ✅ Konservatyvi LONG strategija su breakout + volume spike + trailing SL
# Rizika: 5% balanso vienai pozicijai, x5 svertas, max 3 pozicijos

import os
import time
import datetime
import numpy as np
import pandas as pd
from pybit.unified_trading import HTTP

# 🔐 Tavo BYBIT API raktai
api_key = "6jW8juUDFLe1ykvL3L"
api_secret = "3UH1avHKHWWyMCmU26RMxh784TGSA8lurzST"

def get_session_api():
    return HTTP(api_key=api_key, api_secret=api_secret)

def get_balance():
    try:
        session = get_session_api()
        wallets = session.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]["coin"]
        usdt = next((c for c in wallets if c["coin"] == "USDT"), None)
        if usdt:
            print(f"💰 Rastas USDT balansas: {usdt['walletBalance']} USDT")
            return float(usdt["walletBalance"])
        else:
            print("⚠️ USDT balansas nerastas.")
            return 0
    except Exception as e:
        print(f"❌ Balanso klaida: {e}")
        return 0

def get_klines(symbol, interval="240", limit=100):
    try:
        session = get_session_api()
        klines = session.get_kline(category="linear", symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(klines["result"]["list"])
        df.columns = ['timestamp','open','high','low','close','volume','turnover']
        df['close'] = df['close'].astype(float)
        df['open'] = df['open'].astype(float)
        df['volume'] = df['volume'].astype(float)
        return df
    except Exception as e:
        print(f"❌ Klines klaida {symbol}: {e}")
        return pd.DataFrame()

def fetch_top_symbols(limit=30):
    try:
        session = get_session_api()
        data = session.get_tickers(category="linear")["result"]["list"]
        df = pd.DataFrame(data)
        df = df[df['symbol'].str.endswith("USDT")]
        df['turnover24h'] = df['turnover24h'].astype(float)
        top = df.sort_values("turnover24h", ascending=False).head(limit)
        return top['symbol'].tolist()
    except Exception as e:
        print(f"❌ fetch_top_symbols klaida: {e}")
        return []

def calculate_qty(symbol, risk_percent=5):
    try:
        session = get_session_api()
        tickers = session.get_tickers(category="linear")["result"]["list"]
        price = next((float(t["lastPrice"]) for t in tickers if t["symbol"] == symbol), None)
        balance = get_balance()
        usdt_amount = balance * risk_percent / 100
        qty = (usdt_amount * 5) / price  # x5 leverage
        print(f"🧮 {symbol}: kaina={price}, balansas={balance}, kiekis={qty}")
        return round(qty, 3)
    except Exception as e:
        print(f"❌ Qty klaida: {e}")
        return 0

def open_long(symbol, qty):
    try:
        session = get_session_api()
        order = session.place_order(category="linear", symbol=symbol, side="Buy", orderType="Market", qty=qty)
        entry = float(order["result"]["avgPrice"])
        print(f"🟢 LONG atidarytas: {symbol}, qty={qty}, entry={entry}")
        return entry
    except Exception as e:
        print(f"❌ Orderio klaida: {e}")
        return None

def close_long(symbol, qty):
    try:
        session = get_session_api()
        session.place_order(category="linear", symbol=symbol, side="Sell", orderType="Market", qty=qty, reduceOnly=True)
        print(f"🔴 LONG uždarytas: {symbol}, qty={qty}")
    except Exception as e:
        print(f"❌ LONG uždarymo klaida: {e}")

def get_price(symbol):
    try:
        session = get_session_api()
        tick = session.get_tickers(category="linear")["result"]["list"]
        price = next((float(t["lastPrice"]) for t in tick if t["symbol"] == symbol), None)
        return price
    except:
        return None

def progressive_risk_guard(symbol, entry_price, qty, get_price_fn):
    peak = entry_price
    trail_active = False
    while True:
        price = get_price_fn(symbol)
        if not price:
            time.sleep(5)
            continue
        change = (price - entry_price) / entry_price * 100
        if change >= 2 and not trail_active:
            trail_active = True
            print(f"🔔 Trailing aktyvuotas: {symbol} @ +2%")

        if trail_active:
            if price > peak:
                peak = price
                print(f"📈 Naujas pikas: {peak:.4f}")
            drawdown = (peak - price) / peak * 100
            if drawdown >= 1.5:
                print(f"🔻 SL suveikė: {symbol}, PnL={(price - entry_price)/entry_price*100:.2f}%")
                close_long(symbol, qty)
                break
        time.sleep(60)

def analyze_symbol(symbol):
    df = get_klines(symbol)
    if df.empty or len(df) < 20:
        print(f"⚠️ {symbol}: per mažai žvakių.")
        return None
    last = df.iloc[-1]
    prev_highs = df['close'].rolling(5).max()
    breakout = last['close'] > prev_highs.iloc[-2]
    vol_spike = last['volume'] > df['volume'].mean() * 1.2
    green = last['close'] > last['open']
    print(f"{symbol}: green={green}, breakout={breakout}, vol_spike={vol_spike}")
    if not green:
        print(f"⛔ {symbol} atmetama – žvakė raudona (green=False)")
    if not breakout:
        print(f"⛔ {symbol} atmetama – breakout=False")
    if not vol_spike:
        print(f"⛔ {symbol} atmetama – vol_spike=False")
    if green and breakout and vol_spike:
        return True
    return False

def trading_loop():
    opened = {}
    while True:
        print("\n🔄 Prasideda porų analizė")
        symbols = fetch_top_symbols()
        print(f"🟡 Tikrinamos poros: {symbols}")
        for sym in symbols:
            if sym in opened:
                continue
            if analyze_symbol(sym):
                qty = calculate_qty(sym)
                if qty > 0:
                    entry = open_long(sym, qty)
                    if entry:
                        opened[sym] = (entry, qty)
                        import threading
                        threading.Thread(target=progressive_risk_guard, args=(sym, entry, qty, get_price), daemon=True).start()
                        if len(opened) >= 3:
                            break
        time.sleep(3600)

if __name__ == "__main__":
    trading_loop()
