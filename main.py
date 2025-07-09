# === app.py sugeneruota 2025-07-09 16:42:00 ===

from flask import Flask, render_template, request, redirect, url_for
from datetime import datetime
import threading
import time
from pybit.unified_trading import HTTP
from ta.momentum import RSIIndicator, StochasticOscillator, CCIIndicator
from ta.trend import EMAIndicator, SMAIndicator
from ta.volatility import BollingerBands
from ta.volume import OnBalanceVolumeIndicator
from ta.volatility import AverageTrueRange
from ta.trend import VWAPIndicator
import pandas as pd
import requests

app = Flask(__name__)

# BYBIT API
session = HTTP(
    api_key="b2tL6abuyH7gEQjIC1",
    api_secret="azEVdZmiRBlHID75zQehXHYYYKw0jB8DDFPJ",
    testnet=False,
)

# Pagrindiniai nustatymai
settings = {
    "leverage": 5,
    "position_size_pct": 10,
    "take_profit": 0.03,
    "stop_loss": 0.015,
    "n_pairs": 100,
    "cooldown": 5,
    "ta_filters": ["EMA", "RSI", "BB", "StochRSI", "CCI", "SMA", "VWAP", "Volume", "ATR", "AI"]
}

balance = 1000.0
last_trade_time = {}
symbols = []

def fetch_top_symbols():
    global symbols
    response = session.get_tickers(category="linear")
    data = response.get("result", {}).get("list", [])
    usdt_pairs = [item["symbol"] for item in data if item["symbol"].endswith("USDT")]
    symbols = usdt_pairs[:settings["n_pairs"]]

def get_klines(symbol, interval="15"):
    try:
        klines = session.get_kline(
            category="linear",
            symbol=symbol,
            interval=interval,
            limit=100
        )
        data = klines['result']['list']
        df = pd.DataFrame(data, columns=[
            "timestamp", "open", "high", "low", "close", "volume", "", "", "", "", "", ""
        ])
        df["close"] = df["close"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["volume"] = df["volume"].astype(float)
        return df
    except:
        return None

def apply_ta_filters(df):
    score = 0
    try:
        if "EMA" in settings["ta_filters"]:
            ema_fast = EMAIndicator(df["close"], window=5).ema_indicator()
            ema_slow = EMAIndicator(df["close"], window=20).ema_indicator()
            if ema_fast.iloc[-1] > ema_slow.iloc[-1]:
                score += 1

        if "SMA" in settings["ta_filters"]:
            sma_fast = SMAIndicator(df["close"], window=5).sma_indicator()
            sma_slow = SMAIndicator(df["close"], window=20).sma_indicator()
            if sma_fast.iloc[-1] > sma_slow.iloc[-1]:
                score += 1

        if "RSI" in settings["ta_filters"]:
            rsi = RSIIndicator(df["close"]).rsi()
            if rsi.iloc[-1] < 30:
                score += 1

        if "StochRSI" in settings["ta_filters"]:
            stoch = StochasticOscillator(df["high"], df["low"], df["close"])
            if stoch.stoch().iloc[-1] < 20:
                score += 1

        if "CCI" in settings["ta_filters"]:
            cci = CCIIndicator(df["high"], df["low"], df["close"], window=20).cci()
            if cci.iloc[-1] < -100:
                score += 1

        if "BB" in settings["ta_filters"]:
            bb = BollingerBands(df["close"])
            if df["close"].iloc[-1] < bb.bollinger_lband().iloc[-1]:
                score += 1

        if "VWAP" in settings["ta_filters"]:
            vwap = VWAPIndicator(df["high"], df["low"], df["close"], df["volume"])
            if df["close"].iloc[-1] < vwap.vwap().iloc[-1]:
                score += 1

        if "Volume" in settings["ta_filters"]:
            obv = OnBalanceVolumeIndicator(df["close"], df["volume"]).on_balance_volume()
            if obv.iloc[-1] > obv.iloc[-2]:
                score += 1

        if "ATR" in settings["ta_filters"]:
            atr = AverageTrueRange(df["high"], df["low"], df["close"]).average_true_range()
            if atr.iloc[-1] > atr.iloc[-2]:
                score += 1

        if "AI" in settings["ta_filters"]:
            ema5 = EMAIndicator(df["close"], window=5).ema_indicator()
            ema20 = EMAIndicator(df["close"], window=20).ema_indicator()
            rsi = RSIIndicator(df["close"]).rsi()
            if ema5.iloc[-1] > ema20.iloc[-1] and rsi.iloc[-1] < 35:
                score += 1

    except Exception as e:
        print("TA klaida:", e)

    return score

def place_order(symbol, side):
    try:
        session.place_order(
            category="linear",
            symbol=symbol,
            side=side,
            order_type="Market",
            qty=calculate_qty(symbol),
            time_in_force="GoodTillCancel",
            reduce_only=False
        )
        print(f"✅ {side} įvykdytas: {symbol}")
    except Exception as e:
        print(f"❌ Užsakymo klaida {symbol}: {e}")

def calculate_qty(symbol):
    try:
        balance_info = session.get_wallet_balance(accountType="UNIFIED")
        usdt = float(balance_info["result"]["list"][0]["totalEquity"])
        amount = usdt * settings["position_size_pct"] / 100
        price = float(session.get_ticker(category="linear", symbol=symbol)["result"]["list"][0]["lastPrice"])
        qty = round((amount * settings["leverage"]) / price, 3)
        return qty
    except:
        return 0.01

def trading_loop():
    while True:
        fetch_top_symbols()
        for symbol in symbols:
            df = get_klines(symbol)
            if df is None or len(df) < 50:
                continue
            score = apply_ta_filters(df)
            now = time.time()
            if score >= 3 and now - last_trade_time.get(symbol, 0) > settings["cooldown"] * 60:
                place_order(symbol, side="Buy")
                last_trade_time[symbol] = now
        time.sleep(60)

@app.route("/")
def index():
    return f"<h3>Bybit AI Bot veikia. TOP {settings['n_pairs']} porų. Naudojami filtrai: {', '.join(settings['ta_filters'])}</h3>"

if __name__ == "__main__":
    t = threading.Thread(target=trading_loop)
    t.daemon = True
    t.start()
    app.run(host="0.0.0.0", port=8000)
