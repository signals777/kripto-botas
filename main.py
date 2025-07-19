import os
import time
import math
import threading
from flask import Flask, render_template, request, redirect, url_for, session
from datetime import timedelta, datetime
import pandas as pd
import numpy as np
from pybit.unified_trading import HTTP
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import EMAIndicator, SMAIndicator, CCIIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume import OnBalanceVolumeIndicator
from sklearn.linear_model import LinearRegression

app = Flask(__name__)
app.secret_key = "slaptas_raktas"
app.permanent_session_lifetime = timedelta(minutes=60)

api_key = "b2tL6abuyH7gEQjIC1"
api_secret = "azEVdZmiRBlHID75zQehXHYYYKw0jB8DDFPJ"

def get_session_api():
    return HTTP(api_key=api_key, api_secret=api_secret)

settings = {
    "position_size_pct": 10,
    "take_profit": 0.03,
    "stop_loss": 0.015,
    "n_pairs": 75,
    "cooldown": 5,
}

symbol_cooldowns = {}
highest_balance = None
risk_mode = False
bot_status = "stopped"

def fetch_top_symbols():
    try:
        session = get_session_api()
        response = session.get_instruments(category="linear")
        data = response["result"]["list"]
        tradable = [item["symbol"] for item in data if item["status"] == "Trading"]
        return tradable[:settings["n_pairs"]]
    except Exception as e:
        print(f"Klaida fetch_top_symbols: {e}")
        return []

def get_klines(symbol, interval="15", limit=100):
    try:
        session = get_session_api()
        response = session.get_kline(category="linear", symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(response["result"]["list"], columns=["timestamp", "open", "high", "low", "close", "volume", "_"])
        df = df.iloc[:, :6]
        df.columns = ["timestamp", "open", "high", "low", "close", "volume"]
        df[["open", "high", "low", "close", "volume"]] = df[["open", "high", "low", "close", "volume"]].astype(float)
        return df
    except Exception as e:
        print(f"Klaida get_klines: {e}")
        return None

def calculate_qty(symbol):
    try:
        session = get_session_api()
        tickers = session.get_tickers(category="linear")["result"]["list"]
        last_price = float(next(t for t in tickers if t["symbol"] == symbol)["lastPrice"])
        instruments = session.get_instruments(category="linear")["result"]["list"]
        inst = next(i for i in instruments if i["symbol"] == symbol)
        min_qty = float(inst["lotSizeFilter"]["minOrderQty"])
        step = float(inst["lotSizeFilter"]["qtyStep"])
        wallet = session.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]
        balance = float(wallet["totalEquity"])
        usdt_amount = (balance * settings["position_size_pct"] / 100)
        leverage = determine_leverage(0)
        qty = math.floor((usdt_amount * leverage) / last_price / step) * step
        return round(max(qty, min_qty), 3)
    except Exception as e:
        print(f"Klaida calculate_qty: {e}")
        return None

def determine_leverage(score):
    if score >= 7:
        return 10
    elif score >= 3:
        return 5
    return 1

def place_order(symbol, side, qty, tp_pct, sl_pct):
    try:
        session = get_session_api()
        price = float(session.get_tickers(category="linear")["result"]["list"][0]["lastPrice"])
        tp_price = round(price * (1 + tp_pct), 2) if side == "Buy" else round(price * (1 - tp_pct), 2)
        sl_price = round(price * (1 - sl_pct), 2) if side == "Buy" else round(price * (1 + sl_pct), 2)
        session.place_order(
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
        print(f"✅ Užsakymas: {symbol} {side} {qty}")
    except Exception as e:
        print(f"❌ Klaida place_order: {e}")

def ai_predict(df):
    try:
        df["returns"] = df["close"].pct_change()
        df.dropna(inplace=True)
        df["rsi"] = RSIIndicator(df["close"]).rsi()
        df["ema"] = EMAIndicator(df["close"]).ema_indicator()
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

def trading_loop():
    global highest_balance, risk_mode, bot_status
    while True:
        if bot_status != "running":
            time.sleep(3)
            continue
        try:
            session = get_session_api()
            wallet = session.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]
            balance = float(wallet["totalEquity"])
            if highest_balance is None or balance > highest_balance:
                highest_balance = balance
            drawdown = (balance - highest_balance) / highest_balance
            if drawdown < -0.005:
                risk_mode = True
                print("🛑 Balansas krito daugiau nei 0.5%, stabdome prekybą.")
                time.sleep(30)
                continue
            elif drawdown >= 0:
                risk_mode = False

            symbols = fetch_top_symbols()
            for symbol in symbols:
                time.sleep(0.4)
                if risk_mode or (symbol in symbol_cooldowns and time.time() - symbol_cooldowns[symbol] < settings["cooldown"] * 60):
                    continue
                df = get_klines(symbol)
                if df is None or len(df) < 50:
                    continue
                score = 0
                close = df["close"]
                if RSIIndicator(close).rsi().iloc[-1] < 30:
                    score += 1
                if close.iloc[-1] < BollingerBands(close).bollinger_lband().iloc[-1]:
                    score += 1
                if EMAIndicator(close).ema_indicator().iloc[-1] < close.iloc[-1]:
                    score += 1
                if SMAIndicator(close).sma_indicator().iloc[-1] < close.iloc[-1]:
                    score += 1
                if CCIIndicator(close=close, high=df["high"], low=df["low"]).cci().iloc[-1] < -100:
                    score += 1
                if AverageTrueRange(high=df["high"], low=df["low"], close=close).average_true_range().iloc[-1] > 0.5:
                    score += 1
                if StochasticOscillator(high=df["high"], low=df["low"], close=close).stoch().iloc[-1] < 20:
                    score += 1
                if OnBalanceVolumeIndicator(close, df["volume"]).on_balance_volume().iloc[-1] > 0:
                    score += 1
                if ai_predict(df):
                    score += 2

                if score >= 3:
                    qty = calculate_qty(symbol)
                    leverage = determine_leverage(score)
                    session.set_leverage(category="linear", symbol=symbol, buyLeverage=leverage, sellLeverage=leverage)
                    place_order(symbol, "Buy", qty, settings["take_profit"], settings["stop_loss"])
                    symbol_cooldowns[symbol] = time.time()
        except Exception as e:
            print(f"Klaida trading_loop: {e}")
        time.sleep(5)

@app.route("/", methods=["GET", "POST"])
def index():
    if "logged_in" not in session:
        return redirect(url_for("login"))
    return render_template("index.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        password = request.form.get("password")
        if password == "QwertghjkL123***":
            session["logged_in"] = True
            return redirect(url_for("index"))
    return render_template("login.html")

@app.route("/start")
def start_bot():
    global bot_status
    if "logged_in" in session:
        bot_status = "running"
    return redirect(url_for("index"))

@app.route("/stop")
def stop_bot():
    global bot_status
    if "logged_in" in session:
        bot_status = "stopped"
    return redirect(url_for("index"))

if __name__ == "__main__":
    print("🔁 Boto ciklas paleistas automatiškai (serverio starto metu)")
    t = threading.Thread(target=trading_loop)
    t.daemon = True
    t.start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
