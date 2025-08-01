# ✅ Konservatyvi LONG strategija su breakout + volume spike + trailing SL + print debug
# Rizika: 5% balanso vienai pozicijai, x5 svertas, max 3 pozicijos

import time
import datetime
import numpy as np
import pandas as pd
from pybit.unified_trading import HTTP
import threading

# 🔐 BYBIT API raktai
api_key = "6jW8juUDFLe1ykvL3L"
api_secret = "3UH1avHKHWWyMCmU26RMxh784TGSA8lurzST"

def get_session_api():
    return HTTP(api_key=api_key, api_secret=api_secret)

def get_balance():
    try:
        session = get_session_api()
        result = session.get_wallet_balance(accountType="UNIFIED")["result"]
        print("💰 BALANSO ATSAKYMAS:")
        print(result)
        try:
            coins = result["list"][0]["coin"]
        except:
            coins = result.get("balance", [])
        usdt = next((c for c in coins if c["coin"] == "USDT"), None)
        if not usdt:
            print("⚠️ Nerastas USDT balansas.")
            return 0
        for key in ["availableToTrade", "availableBalance", "walletBalance"]:
            if key in usdt:
                print(f"✅ Panaudotas balanso laukas: {key}")
                return float(usdt[key])
        print("⚠️ Nerastas tinkamas balanso laukas USDT objekte.")
        return 0
    except Exception as e:
        print(f"❌ Balanso klaida: {e}")
        return 0

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

def get_klines(symbol, interval="240", limit=100):
    try:
        session = get_session_api()
        klines = session.get_kline(category="linear", symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(klines["result"]["list"])
        df.columns = ['timestamp','open','high','low','close','volume','turnover']
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        return df
    except Exception as e:
        print(f"❌ Klines klaida {symbol}: {e}")
        return pd.DataFrame()

def calculate_qty(symbol, risk_percent=5):
    try:
        session = get_session_api()
        tickers = session.get_tickers(category="linear")["result"]["list"]
        price = next((float(t["lastPrice"]) for t in tickers if t["symbol"] == symbol), None)
        balance = get_balance()
        usdt_amount = balance * risk_percent / 100
        qty = (usdt_amount * 5) / price
        return round(qty, 3)
    except Exception as e:
        print(f"❌ Qty klaida: {e}")
        return 0

def get_price(symbol):
    try:
        session = get_session_api()
        tick = session.get_tickers(category="linear")["result"]["list"]
        price = next((float(t["lastPrice"]) for t in tick if t["symbol"] == symbol), None)
        return price
    except:
        return None

def open_long(symbol, qty):
    try:
        session = get_session_api()
        session.set_leverage(category="linear", symbol=symbol, buyLeverage=5, sellLeverage=5)
        order = session.place_order(category="linear", symbol=symbol, side="Buy", orderType="Market", qty=qty)
        entry = float(order["result"]["avgPrice"])
        print(f"🟢 LONG atidarytas: {symbol}, qty={qty}, entry={entry}")
        return entry
    except Exception as e:
        print(f"❌ LONG orderio klaida: {e}")
        return None

def close_long(symbol, qty):
    try:
        session = get_session_api()
        session.place_order(category="linear", symbol=symbol, side="Sell", orderType="Market", qty=qty, reduceOnly=True)
        print(f"🔴 LONG uždarytas: {symbol}, qty={qty}")
    except Exception as e:
        print(f"❌ LONG uždarymo klaida: {e}")

def progressive_risk_guard(symbol, entry_price, qty, get_price_fn):
    peak = entry_price
    min_drawdown = 0
    while True:
        price = get_price_fn(symbol)
        if not price:
            time.sleep(10)
            continue
        if price > peak:
            peak = price
            min_drawdown = 0
        else:
            drop = (peak - price) / peak * 100
            if drop < min_drawdown:
                min_drawdown = drop
            if min_drawdown >= 1.5:
                print(f"🔻 SL suveikė: {symbol}, PnL={(price - entry_price) / entry_price * 100:.2f}%")
                close_long(symbol, qty)
                break
        time.sleep(60)

def trading_loop():
    opened = {}
    while True:
        if len(opened) < 3:
            symbols = fetch_top_symbols()
            print(f"\n🟡 Tikrinamos poros: {symbols}")
            for sym in symbols:
                if sym in opened:
                    continue
                df = get_klines(sym)
                if df.empty or len(df) < 20:
                    continue
                df['green'] = df['close'] > df['close'].shift(1)
                df['trend'] = df['close'] > df['close'].rolling(10).mean()
                last = df.iloc[-1]
                breakout = last['close'] > df['close'].rolling(5).max().iloc[-2]
                vol_spike = last['volume'] > df['volume'].mean() * 1.2
                green = last['green']
                trend = last['trend']
                print(f"{sym}: green={green}, breakout={breakout}, vol_spike={vol_spike}, trend={trend}")
                if green and breakout and vol_spike:
                    qty = calculate_qty(sym)
                    if qty > 0:
                        entry = open_long(sym, qty)
                        if entry:
                            opened[sym] = (entry, qty)
                            threading.Thread(target=progressive_risk_guard, args=(sym, entry, qty, get_price), daemon=True).start()
                            if len(opened) >= 3:
                                break
        time.sleep(3600)

if __name__ == "__main__":
    trading_loop()
