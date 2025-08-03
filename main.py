import time
import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from pybit.unified_trading import HTTP

API_KEY = "6jW8juUDFLe1ykvL3L"
API_SECRET = "3UH1avHKHWWyMCmU26RMxh784TGSA8lurzST"

session = HTTP(api_key=API_KEY, api_secret=API_SECRET)

LEVERAGE = 5
RISK_PERCENT = 0.05
SYMBOL_INTERVAL = "4h"
SYMBOL_LIMIT = 50

open_positions = {}

def log_to_file(text):
    with open("analysis_log.txt", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now()} – {text}\n")

def get_symbols():
    try:
        tickers = session.get_tickers(category="linear")["result"]["list"]
        valid = []
        for t in tickers:
            if not t["symbol"].endswith("USDT"):
                continue
            if "10000" in t["symbol"] or "1000000" in t["symbol"]:
                continue
            try:
                change = float(t["change24h"])
                valid.append((t["symbol"], change))
            except:
                continue
        sorted_tickers = sorted(valid, key=lambda x: x[1], reverse=True)
        top_symbols = [x[0] for x in sorted_tickers[:SYMBOL_LIMIT]]
        print(f"\n📈 Atrinkta TOP {len(top_symbols)} porų pagal kainos kilimą")
        log_to_file(f"Atrinkta TOP {len(top_symbols)} porų pagal kainos kilimą")
        return top_symbols
    except Exception as e:
        print(f"❌ Klaida gaunant simbolius: {e}")
        return []

def get_klines(symbol):
    try:
        klines = session.get_kline(category="linear", symbol=symbol, interval=SYMBOL_INTERVAL, limit=50)["result"]["list"]
        if len(klines) < 10:
            print(f"⛔ {symbol} atmetama – per mažai žvakių (gauta {len(klines)})")
            log_to_file(f"{symbol} atmetama – per mažai žvakių (gauta {len(klines)})")
            return None
        df = pd.DataFrame(klines, columns=["timestamp", "open", "high", "low", "close", "volume", "_", "_"])
        df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
        return df
    except Exception as e:
        print(f"⛔ {symbol} atmetama – duomenų klaida: {e}")
        log_to_file(f"{symbol} atmetama – duomenų klaida: {e}")
        return None

def is_breakout(df):
    return df["close"].iloc[-1] > df["high"].iloc[-6:-1].max()

def volume_spike(df):
    return df["volume"].iloc[-1] > df["volume"].iloc[-6:-1].mean() * 1.2

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
            print(f"⚠️ {symbol} atmetama – kiekis per mažas: {qty} < {min_qty}")
            log_to_file(f"{symbol} atmetama – kiekis per mažas: {qty} < {min_qty}")
            return 0
        return round(qty, 6)
    except Exception as e:
        print(f"⚠️ {symbol} atmetama – kiekio klaida: {e}")
        log_to_file(f"{symbol} atmetama – kiekio klaida: {e}")
        return 0

def get_wallet_balance():
    try:
        balance = session.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]["coin"]
        usdt = next(c for c in balance if c["coin"] == "USDT")
        return float(usdt["walletBalance"])
    except Exception as e:
        print(f"❌ Klaida gaunant balansą: {e}")
        log_to_file(f"Klaida gaunant balansą: {e}")
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
                log_to_file(f"{symbol} uždaryta dėl -1.5% nuo piko")
                session.place_order(category="linear", symbol=symbol, side="Sell", orderType="Market", qty=open_positions[symbol])
                del open_positions[symbol]
                break
        except Exception as e:
            print(f"⚠️ Klaida stebint {symbol}: {e}")

def analyze_and_trade():
    symbols = get_symbols()
    print(f"\n🔄 Prasideda porų analizė\n🟡 Tikrinamos {len(symbols)} poros")
    log_to_file(f"Prasideda analizė: {len(symbols)} poros")

    balance = get_wallet_balance()
    print(f"💰 Balansas: {balance:.2f} USDT")
    log_to_file(f"Balansas: {balance:.2f} USDT")

    filtered = 0
    opened = 0

    for symbol in symbols:
        if opened >= 3:
            break

        df = get_klines(symbol)
        if df is None:
            continue

        green = is_green_candle(df)
        breakout = is_breakout(df)
        vol = volume_spike(df)

        print(f"{symbol}: green={green}, breakout={breakout}, vol_spike={vol}")
        log_to_file(f"{symbol}: green={green}, breakout={breakout}, vol_spike={vol}")

        if not (green or breakout or vol):
            print(f"⛔ {symbol} atmetama – neatitinka jokių kriterijų")
            log_to_file(f"{symbol} atmetama – neatitinka jokių kriterijų")
            continue

        price = df["close"].iloc[-1]
        qty = calculate_qty(symbol, price, balance)
        if qty == 0:
            continue

        try:
            session.set_leverage(category="linear", symbol=symbol, buyLeverage=LEVERAGE, sellLeverage=LEVERAGE)
            session.place_order(category="linear", symbol=symbol, side="Buy", orderType="Market", qty=qty)
            print(f"✅ Atidaryta pozicija: {symbol}, kiekis={qty}, kaina={price}")
            log_to_file(f"✅ Nupirkta: {symbol}, qty={qty}, kaina={price}")
            open_positions[symbol] = qty
            opened += 1
            progressive_risk_guard(symbol, price)
        except Exception as e:
            print(f"❌ Orderio klaida {symbol}: {e}")
            log_to_file(f"Orderio klaida {symbol}: {e}")

    print(f"\n📊 Atitiko filtrus: {filtered} porų")
    print(f"📥 Atidaryta pozicijų: {opened}")
    log_to_file(f"Atitiko filtrus: {filtered}, Atidaryta pozicijų: {opened}")

def trading_loop():
    while True:
        analyze_and_trade()
        print("\n💤 Miegama 3600 sekundžių...\n")
        time.sleep(3600)

if __name__ == "__main__":
    trading_loop()
