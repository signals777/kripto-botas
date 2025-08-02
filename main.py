import time
import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from pybit.unified_trading import HTTP

# ⛔️ BYBIT API KEY ir SECRET – ĮRAŠYK SAVO
API_KEY = "6jW8juUDFLe1ykvL3L"
API_SECRET = "3UH1avHKHWWyMCmU26RMxh784TGSA8lurzST"

session = HTTP(api_key=API_KEY, api_secret=API_SECRET)

# 🔁 Strategijos parametrai
LEVERAGE = 5
RISK_PERCENT = 0.05
SYMBOL_INTERVAL = "4h"
SYMBOL_LIMIT = 200
TOP_N_GAINERS = 50  # Tik top 50 pagal kainos kilimą

def get_symbols_sorted_by_gainers():
    try:
        tickers = session.get_tickers(category="linear")["result"]["list"]
        filtered = [t for t in tickers if t["symbol"].endswith("USDT") and "USDC" not in t["symbol"]]
        df = pd.DataFrame(filtered)
        df["priceChangePercent"] = df["price24hPcnt"].astype(float)
        df = df.sort_values("priceChangePercent", ascending=False)
        symbols = df["symbol"].head(TOP_N_GAINERS).tolist()
        print(f"📈 Atrinkta TOP {TOP_N_GAINERS} porų pagal kainos kilimą")
        return symbols
    except Exception as e:
        print(f"❌ Klaida gaunant gainers: {e}")
        return []

def get_klines(symbol):
    try:
        klines = session.get_kline(category="linear", symbol=symbol, interval=SYMBOL_INTERVAL, limit=SYMBOL_LIMIT)["result"]["list"]
        df = pd.DataFrame(klines, columns=["timestamp", "open", "high", "low", "close", "volume", "_", "_"])
        df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
        return df
    except Exception as e:
        print(f"⚠️ Klaida gaunant žvakes {symbol}: {e}")
        return None

def is_breakout(df):
    last_close = df["close"].iloc[-1]
    prev_highs = df["high"].iloc[-6:-1]
    return last_close > prev_highs.max()

def volume_spike(df):
    recent = df["volume"].iloc[-1]
    average = df["volume"].iloc[-6:-1].mean()
    return recent > average * 1.2

def is_green_candle(df):
    last = df.iloc[-1]
    return float(last["close"]) > float(last["open"])

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
            print(f"⚠️ {symbol} atmetama – kiekis per mažas: {qty} < {min_qty}")
            return 0
        return round(qty, 6)
    except Exception as e:
        print(f"⚠️ Klaida gaunant kiekio info {symbol}: {e}")
        return 0

def get_wallet_balance():
    try:
        balance = session.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]["coin"]
        usdt = next(c for c in balance if c["coin"] == "USDT")
        return float(usdt["walletBalance"])
    except Exception as e:
        print(f"❌ Klaida gaunant balansą: {e}")
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
            print(f"📉 {symbol}: kaina={price}, pikas={peak}, kritimas={drawdown:.4f}")
            if drawdown <= -0.015:
                print(f"❌ {symbol}: pasiektas -1.5% nuo piko, pozicija uždaroma")
                session.place_order(category="linear", symbol=symbol, side="Sell", orderType="Market", qty=open_positions[symbol])
                del open_positions[symbol]
                break
        except Exception as e:
            print(f"⚠️ Klaida stebint {symbol}: {e}")

open_positions = {}

def analyze_and_trade():
    symbols = get_symbols_sorted_by_gainers()
    print(f"\n🔄 Prasideda porų analizė\n🟡 Tikrinamos {len(symbols)} poros")
    balance = get_wallet_balance()
    print(f"💰 Balansas: {balance:.2f} USDT")

    for symbol in symbols:
        df = get_klines(symbol)
        if df is None or len(df) < 10:
            continue

        green = is_green_candle(df)
        breakout = is_breakout(df)
        vol_spike = volume_spike(df)

        print(f"\n{symbol}: green={green}, breakout={breakout}, vol_spike={vol_spike}")

        if not green:
            print(f"⛔ {symbol} atmetama – žvakė raudona")
            continue
        if not breakout:
            print(f"⛔ {symbol} atmetama – breakout=False")
            continue
        if not vol_spike:
            print(f"⛔ {symbol} atmetama – vol_spike=False")
            continue

        price = df["close"].iloc[-1]
        qty = calculate_qty(symbol, price, balance)

        if qty == 0:
            print(f"⚠️ {symbol} atmetama – netinkamas kiekis arba balansas")
            continue

        try:
            session.set_leverage(category="linear", symbol=symbol, buyLeverage=LEVERAGE, sellLeverage=LEVERAGE)
            order = session.place_order(category="linear", symbol=symbol, side="Buy", orderType="Market", qty=qty)
            print(f"✅ Atidaryta LONG pozicija: {symbol}, kiekis={qty}, kaina={price}")
            open_positions[symbol] = qty
            progressive_risk_guard(symbol, price)
        except Exception as e:
            print(f"❌ Orderio klaida: {e}")

def trading_loop():
    while True:
        analyze_and_trade()
        print("\n💤 Miegama 3600 sekundžių...\n")
        time.sleep(3600)

if __name__ == "__main__":
    trading_loop()
