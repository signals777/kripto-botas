import os
import time
import math
import threading
from flask import Flask, render_template
from datetime import timedelta
import pandas as pd
import numpy as np
from pybit.unified_trading import HTTP
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volatility import BollingerBands
from sklearn.linear_model import LinearRegression

app = Flask(__name__)
app.secret_key = "slaptas_raktas"
app.permanent_session_lifetime = timedelta(minutes=60)

# 🔐 API raktai
api_key = "b2tL6abuyH7gEQjIC1"
api_secret = "azEVdZmiRBlHID75zQehXHYYYKw0jB8DDFPJ"

def get_session_api():
    return HTTP(api_key=api_key, api_secret=api_secret)

settings = {
    "position_size_pct": 10,
    "take_profit": 0.03,
    "stop_loss": 0.015,
    "n_pairs": 75,
    "max_trades_per_hour": 4,
}

symbol_cooldowns = {}
bot_status = "running"
last_balance = None
hourly_trade_counter = []
open_positions = {}

def fetch_top_symbols():
    try:
        session = get_session_api()
        tickers = session.get_tickers(category="linear")["result"]["list"]
        top_volume = sorted(tickers, key=lambda x: float(x["turnover24h"]), reverse=True)
        return [t["symbol"] for t in top_volume if "USDT" in t["symbol"]][:settings["n_pairs"]]
    except Exception as e:
        print(f"Klaida fetch_top_symbols: {e}")
        return []

def get_klines(symbol, interval="60", limit=100):
    try:
        session = get_session_api()
        klines = session.get_kline(category="linear", symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(klines["result"]["list"], columns=["timestamp", "open", "high", "low", "close", "volume", "_"])
        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        df[["open", "high", "low", "close", "volume"]] = df[["open", "high", "low", "close", "volume"]].astype(float)
        return df
    except Exception as e:
        print(f"Klaida get_klines: {e}")
        return None

def calculate_qty(symbol):
    try:
        session = get_session_api()
        price = float(next(t for t in session.get_tickers(category="linear")["result"]["list"] if t["symbol"] == symbol)["lastPrice"])
        wallet = session.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]
        balance = float(wallet["totalEquity"])
        usdt_amount = (balance * settings["position_size_pct"] / 100)
        leverage = determine_leverage(0)
        qty = math.floor((usdt_amount * leverage) / price * 1000) / 1000
        return round(qty, 3)
    except Exception as e:
        print(f"Klaida calculate_qty: {e}")
        return None

def determine_leverage(score):
    if score >= 7:
        return 10
    elif score >= 4:
        return 5
    return 1

def place_order(symbol, side, qty, tp_pct, sl_pct):
    try:
        session = get_session_api()
        price = float(next(t for t in session.get_tickers(category="linear")["result"]["list"] if t["symbol"] == symbol)["lastPrice"])
        tp_price = round(price * (1 + tp_pct), 4)
        sl_price = round(price * (1 - sl_pct), 4)
        order = session.place_order(
            category="linear",
            symbol=symbol,
            side=side,
            orderType="Market",
            qty=qty,
            timeInForce="GoodTillCancel",
            takeProfit=tp_price,
            stopLoss=sl_price,
            reduceOnly=False
        )
        open_positions[symbol] = {
            "entry_price": price,
            "max_profit": 0,
            "qty": qty
        }
        print(f"✅ Užsakymas: {symbol} {side} {qty}")
    except Exception as e:
        print(f"❌ Klaida place_order: {e}")

def ai_predict(df):
    try:
        df["returns"] = df["close"].pct_change()
        df["rsi"] = RSIIndicator(df["close"]).rsi()
        df["ema"] = EMAIndicator(df["close"], window=14).ema_indicator()
        df.dropna(inplace=True)
        X = df[["rsi", "ema"]].values[-10:]
        y = df["returns"].shift(-1).dropna().values[-10:]
        if len(X) < 10 or len(y) < 10:
            return False
        model = LinearRegression().fit(X, y)
        pred = model.predict(X[-1].reshape(1, -2))[0]
        return pred > 0
    except Exception as e:
        print(f"Klaida AI modelyje: {e}")
        return False

def close_position(symbol):
    try:
        session = get_session_api()
        qty = open_positions[symbol]["qty"]
        session.place_order(
            category="linear",
            symbol=symbol,
            side="Sell",
            orderType="Market",
            qty=qty,
            timeInForce="GoodTillCancel",
            reduceOnly=True
        )
        print(f"❎ Pozicija uždaryta: {symbol}")
        del open_positions[symbol]
    except Exception as e:
        print(f"❌ Klaida close_position: {e}")

def trading_loop():
    global last_balance
    while True:
        if bot_status != "running":
            time.sleep(3)
            continue

        try:
            session = get_session_api()
            balance = float(session.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]["totalEquity"])

            # ✅ Balanso saugumo apsauga: max 50% balanso prekyboje
            used_balance = len(open_positions) * (balance * settings["position_size_pct"] / 100)
            if used_balance > balance * 0.5:
                print("🚫 Pasiekta 50% balanso riba – nauji sandoriai nestartuojami.")
                time.sleep(10)
                continue

            # 🔍 Stebime esamas pozicijas
            for symbol in list(open_positions.keys()):
                df = get_klines(symbol)
                if df is None:
                    continue
                entry = open_positions[symbol]["entry_price"]
                current = df["close"].iloc[-1]
                profit_pct = (current - entry) / entry
                if profit_pct > open_positions[symbol]["max_profit"]:
                    open_positions[symbol]["max_profit"] = profit_pct
                max_profit = open_positions[symbol]["max_profit"]

                if profit_pct >= 0.01:
                    if profit_pct < max_profit - 0.002:
                        print(f"📉 Progresyvus kritimas: {symbol} +{profit_pct:.2%} (max +{max_profit:.2%}) – PARDUODAM")
                        close_position(symbol)
                elif profit_pct <= -settings["stop_loss"]:
                    print(f"🔻 Stop Loss: {symbol} {profit_pct:.2%}")
                    close_position(symbol)

            # ✅ Kas valandą nauji pirkimai (max 4)
            now = time.time()
            hourly_trade_counter[:] = [t for t in hourly_trade_counter if now - t < 3600]
            if len(hourly_trade_counter) >= settings["max_trades_per_hour"]:
                time.sleep(10)
                continue

            symbols = fetch_top_symbols()
            trades = 0
            for symbol in symbols:
                if trades >= settings["max_trades_per_hour"]:
                    break
                if symbol in open_positions:
                    continue
                df = get_klines(symbol)
                if df is None or len(df) < 50:
                    continue

                change = (df["close"].iloc[-1] - df["close"].iloc[-2]) / df["close"].iloc[-2]
                if change < 0.015:
                    continue

                score = 0
                close = df["close"]
                if RSIIndicator(close).rsi().iloc[-1] < 30:
                    score += 1
                if close.iloc[-1] < BollingerBands(close).bollinger_lband().iloc[-1]:
                    score += 1
                if EMAIndicator(close).ema_indicator().iloc[-1] < close.iloc[-1]:
                    score += 1
                if ai_predict(df):
                    score += 2
                if df["volume"].iloc[-1] > df["volume"].rolling(20).mean().iloc[-1]:
                    score += 1

                if score >= 4:
                    qty = calculate_qty(symbol)
                    lev = determine_leverage(score)
                    try:
                        session.set_leverage(category="linear", symbol=symbol, buyLeverage=lev, sellLeverage=lev)
                    except Exception as e:
                        print(f"Sverto klaida {symbol}: {e}")
                        continue
                    place_order(symbol, "Buy", qty, settings["take_profit"], settings["stop_loss"])
                    hourly_trade_counter.append(time.time())
                    trades += 1

        except Exception as e:
            print(f"Klaida trading_loop: {e}")
        time.sleep(5)

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

if __name__ == "__main__":
    print("🔁 Boto paleidimas...")
    t = threading.Thread(target=trading_loop)
    t.daemon = True
    t.start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
