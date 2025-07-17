from flask import Flask, render_template, request, redirect, url_for, session
from datetime import timedelta, datetime
import threading
import time
import pandas as pd
import os
import math
from pybit.unified_trading import HTTP
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import EMAIndicator, SMAIndicator, CCIIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume import OnBalanceVolumeIndicator

app = Flask(__name__)
app.secret_key = 'QwertghjkL123***'
app.permanent_session_lifetime = timedelta(minutes=60)

USERS = {"virglel@gmail.com": "QwertghjkL123***"}

def get_session_api():
    return HTTP(
        api_key="b2tL6abuyH7gEQjIC1",
        api_secret="azEVdZmiRBlHID75zQehXHYYYKw0jB8DDFPJ",
        testnet=False,
    )

settings = {
    "leverage": 5,
    "position_size_pct": 10,
    "take_profit": 0.03,
    "stop_loss": 0.015,
    "n_pairs": 75,
    "cooldown": 5,
    "ta_filters": ["EMA", "RSI", "BB", "StochRSI", "CCI", "SMA", "VWAP", "Volume", "ATR", "AI"]
}

last_trade_time = {}
symbols = []
trade_history = []
balance_graph = []
balance_times = []
bot_status = "Sustabdyta"
max_balance = 0
risk_mode = False

def get_klines(symbol):
    try:
        api = get_session_api()
        klines = api.get_kline(category="linear", symbol=symbol, interval=15, limit=100)
        data = klines["result"]["list"]
        df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close", "volume", "turnover"])
        df["close"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)
        return df
    except Exception as e:
        print(f"Klaida gaunant klines {symbol}: {e}")
        return None

def apply_ta_filters(df):
    score = 0
    close = df["close"]
    volume = df["volume"]

    if "EMA" in settings["ta_filters"]:
        ema = EMAIndicator(close, window=20).ema_indicator()
        if close.iloc[-1] > ema.iloc[-1]:
            score += 1
    if "RSI" in settings["ta_filters"]:
        rsi = RSIIndicator(close, window=14).rsi()
        if rsi.iloc[-1] < 30:
            score += 1
    if "BB" in settings["ta_filters"]:
        bb = BollingerBands(close, window=20)
        if close.iloc[-1] < bb.bollinger_lband().iloc[-1]:
            score += 1
    if "StochRSI" in settings["ta_filters"]:
        stoch = StochasticOscillator(close, close, close)
        if stoch.stoch().iloc[-1] < 20:
            score += 1
    if "CCI" in settings["ta_filters"]:
        cci = CCIIndicator(close, close, close, window=20)
        if cci.cci().iloc[-1] < -100:
            score += 1
    if "SMA" in settings["ta_filters"]:
        sma = SMAIndicator(close, window=50).sma_indicator()
        if close.iloc[-1] > sma.iloc[-1]:
            score += 1
    if "Volume" in settings["ta_filters"]:
        vol_avg = volume.rolling(20).mean()
        if volume.iloc[-1] > vol_avg.iloc[-1]:
            score += 1
    if "ATR" in settings["ta_filters"]:
        atr = AverageTrueRange(high=close, low=close, close=close).average_true_range()
        if atr.iloc[-1] > atr.mean():
            score += 1
    if "AI" in settings["ta_filters"]:
        score += 0  # rezervuota AI

    return score

def balance_info():
    global max_balance, risk_mode
    try:
        api = get_session_api()
        bal = float(api.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]["totalEquity"])
        bal = round(bal, 2)

        if max_balance == 0:
            max_balance = bal

        if bal > max_balance:
            max_balance = bal
            risk_mode = False

        elif bal < max_balance * 0.995:
            if not risk_mode:
                print("⚠️ Įjungtas rizikos režimas (-0.5%)")
                risk_mode = True

        return {"balansas": bal}
    except:
        return {"balansas": 0}

def fetch_top_symbols():
    global symbols
    try:
        api = get_session_api()
        tickers = api.get_tickers(category="linear")["result"]["list"]
        info = api.get_symbols(category="linear")["result"]["list"]

        valid = {item["symbol"]: item for item in info if item.get("contractType") == "Linear"}
        sorted_tickers = sorted(tickers, key=lambda x: float(x["volume24h"]), reverse=True)

        filtered = []
        for t in sorted_tickers:
            symbol = t["symbol"]
            if symbol in valid:
                filt = valid[symbol]
                if filt.get("lotSizeFilter"):
                    min_qty = float(filt["lotSizeFilter"]["minOrderQty"])
                    qty_step = float(filt["lotSizeFilter"]["qtyStep"])
                    if min_qty > 0 and qty_step > 0:
                        filtered.append(symbol)
            if len(filtered) >= settings["n_pairs"]:
                break
        symbols = filtered
    except Exception as e:
        print(f"Klaida fetch_top_symbols: {e}")
        symbols = []

def calculate_qty(symbol):
    try:
        api = get_session_api()
        balance = balance_info()["balansas"]
        tickers = api.get_tickers(category="linear")["result"]["list"]
        price_data = next((item for item in tickers if item["symbol"] == symbol), None)
        if price_data is None:
            raise Exception(f"Kaina nerasta simboliui {symbol}")
        price = float(price_data["lastPrice"])

        info = api.get_symbols(category="linear")["result"]["list"]
        sym_info = next((i for i in info if i["symbol"] == symbol), None)
        if not sym_info:
            print(f"❌ Simbolio info nerasta: {symbol}")
            return 0

        min_qty = float(sym_info['lotSizeFilter']['minOrderQty'])
        qty_step = float(sym_info['lotSizeFilter']['qtyStep'])

        position_value = balance * (settings["position_size_pct"] / 100)
        raw_qty = (position_value * settings["leverage"]) / price

        precision = round(-math.log10(qty_step))
        qty = round(raw_qty, precision)

        if qty < min_qty:
            print(f"❌ Kiekis per mažas: {symbol}")
            return 0

        return qty
    except Exception as e:
        print(f"❌ Klaida skaičiuojant kiekį {symbol}: {e}")
        return 0

def place_order(symbol, side):
    try:
        api = get_session_api()
        qty = calculate_qty(symbol)
        if qty == 0:
            return

        tickers = api.get_tickers(category="linear")["result"]["list"]
        entry = next((item for item in tickers if item["symbol"] == symbol), None)
        if entry is None:
            raise Exception("Nepavyko gauti kainos")
        entry_price = float(entry["lastPrice"])
        tp = round(entry_price * (1 + settings["take_profit"]), 2)
        sl = round(entry_price * (1 - settings["stop_loss"]), 2)

        api.place_order(category="linear", symbol=symbol, side=side, order_type="Market", qty=qty, time_in_force="GoodTillCancel", reduce_only=False)
        api.place_order(category="linear", symbol=symbol, side="Sell" if side == "Buy" else "Buy", order_type="Limit", qty=qty, price=str(tp), time_in_force="GoodTillCancel", reduce_only=True)
        api.place_order(category="linear", symbol=symbol, side="Sell" if side == "Buy" else "Buy", order_type="StopMarket", qty=qty, stop_loss=str(sl), trigger_price=str(sl), trigger_by="LastPrice", time_in_force="GoodTillCancel", reduce_only=True)

        trade_history.append({"laikas": time.strftime("%Y-%m-%d %H:%M:%S"), "pora": symbol, "kryptis": side, "kaina": entry_price, "pozicija": round(qty * entry_price, 2)})
        balance_graph.append(balance_info()["balansas"])
        balance_times.append(datetime.now().strftime("%H:%M"))
        print(f"✅ Užsakymas: {symbol} - {side}")
    except Exception as e:
        print(f"❌ Užsakymo klaida {symbol}: {e}")

@app.route("/", methods=["GET", "POST"])
def index():
    if "user" not in session:
        return redirect(url_for("login"))
    if request.method == "POST":
        settings["n_pairs"] = int(request.form.get("n_pairs"))
        settings["ta_filters"] = request.form.getlist("ta_filters")
    return render_template("index.html", settings=settings, bot_status=bot_status, trade_history=trade_history[::-1], balance=balance_info()["balansas"], all_filters=["EMA", "RSI", "BB", "StochRSI", "CCI", "SMA", "VWAP", "Volume", "ATR", "AI"], graph=balance_graph, times=balance_times)

@app.route("/login", methods=["POST", "GET"])
def login():
    if request.method == "POST":
        user = request.form["username"]
        password = request.form["password"]
        if user in USERS and USERS[user] == password:
            session["user"] = user
            return redirect(url_for("index"))
        return "<h3>Neteisingas prisijungimas.</h3>"
    return render_template("index.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("index"))

@app.route("/start")
def start_bot():
    global bot_status
    bot_status = "Veikia"
    return redirect(url_for("index"))

@app.route("/stop")
def stop_bot():
    global bot_status
    bot_status = "Sustabdyta"
    return redirect(url_for("index"))

@app.route("/change_password", methods=["POST"])
def change_password():
    old = request.form.get("old_password")
    new = request.form.get("new_password")
    user = session.get("user")
    if user and USERS[user] == old:
        USERS[user] = new
        return redirect(url_for("index"))
    return "<h3>Neteisingas senas slaptažodis.</h3>"

def trading_loop():
    global bot_status
    while True:
        if bot_status == "Veikia":
            fetch_top_symbols()
            for symbol in symbols:
                df = get_klines(symbol)
                if df is None or len(df) < 50:
                    continue
                score = apply_ta_filters(df)
                now = time.time()
                if not risk_mode and score >= 3 and now - last_trade_time.get(symbol, 0) > settings["cooldown"] * 60:
                    place_order(symbol, "Buy")
                    last_trade_time[symbol] = now
                elif risk_mode and score >= 5 and now - last_trade_time.get(symbol, 0) > settings["cooldown"] * 60:
                    place_order(symbol, "Buy")
                    last_trade_time[symbol] = now
                time.sleep(0.4)
        time.sleep(60)

if __name__ == "__main__":
    print("🔁 Boto ciklas pasiruošęs (paleidimas tik per panelę)")
    t = threading.Thread(target=trading_loop)
    t.daemon = True
    t.start()
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
