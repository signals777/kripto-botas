from flask import Flask, render_template, request, redirect, url_for, session
from datetime import timedelta, datetime
import threading
import time
import pandas as pd
import os
from pybit.unified_trading import HTTP
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import EMAIndicator, SMAIndicator, CCIIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume import OnBalanceVolumeIndicator

app = Flask(__name__)
app.secret_key = 'QwertghjkL123***'
app.permanent_session_lifetime = timedelta(minutes=60)

USERS = {"virglel@gmail.com": "QwertghjkL123***"}

session_api = HTTP(
    api_key="b2tL6abuyH7gEQjIC1",
    api_secret="azEVdZmiRBlHID75zQehXHYYYKw0jB8DDFPJ",
    testnet=False,
)

settings = {
    "leverage": 5,
    "position_size_pct": 10,
    "take_profit": 0.03,
    "stop_loss": 0.015,
    "n_pairs": 100,
    "cooldown": 5,
    "ta_filters": ["EMA", "RSI", "BB", "StochRSI", "CCI", "SMA", "VWAP", "Volume", "ATR", "AI"]
}

last_trade_time = {}
symbols = []
trade_history = []
balance_graph = []
balance_times = []
bot_status = "Sustabdyta"

def get_klines(symbol):
    try:
        klines = session_api.get_kline(
            category="linear",
            symbol=symbol,
            interval="15",
            limit=100
        )
        data = klines["result"]["list"]
        df = pd.DataFrame(data, columns=[
    "timestamp", "open", "high", "low", "close", "volume", "turnover"
])
        df["close"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)
        return df
    except Exception as e:
        def calculate_qty(symbol):
    balance = balance_info()["balansas"]

    try:
        tickers = session_api.get_tickers(category="linear")["result"]["list"]
        price_data = next((item for item in tickers if item["symbol"] == symbol), None)
        if price_data is None:
            raise Exception(f"Kaina nerasta simboliui {symbol}")
        price = float(price_data["lastPrice"])
    except Exception as e:
        print(f"❌ Klaida gaunant kainą {symbol}: {e}")
        return 0

    position_value = balance * (settings["position_size_pct"] / 100)
    return round((position_value * settings["leverage"]) / price, 3)
def place_order(symbol, side):
    try:
        qty = calculate_qty(symbol)
        ticker = session_api.get_ticker(category="linear", symbol=symbol)
        entry_price = float(ticker["result"]["list"][0]["lastPrice"])

        tp_price = round(entry_price * (1 + settings["take_profit"]), 2)
        sl_price = round(entry_price * (1 - settings["stop_loss"]), 2)

        session_api.place_order(
            category="linear",
            symbol=symbol,
            side=side,
            order_type="Market",
            qty=qty,
            time_in_force="GoodTillCancel",
            reduce_only=False
        )

        session_api.place_order(
            category="linear",
            symbol=symbol,
            side="Sell" if side == "Buy" else "Buy",
            order_type="Limit",
            qty=qty,
            price=str(tp_price),
            time_in_force="GoodTillCancel",
            reduce_only=True
        )

        session_api.place_order(
            category="linear",
            symbol=symbol,
            side="Sell" if side == "Buy" else "Buy",
            order_type="StopMarket",
            qty=qty,
            stop_loss=str(sl_price),
            trigger_price=str(sl_price),
            trigger_by="LastPrice",
            time_in_force="GoodTillCancel",
            reduce_only=True
        )

        trade_history.append({
            "laikas": time.strftime("%Y-%m-%d %H:%M:%S"),
            "pora": symbol,
            "kryptis": side,
            "kaina": entry_price,
            "pozicija": round(qty * entry_price, 2)
        })
        balance_graph.append(balance_info()["balansas"])
        balance_times.append(datetime.now().strftime("%H:%M"))
        print(f"✅ Užsakymas: {symbol} - {side}")
    except Exception as e:
        print(f"❌ Užsakymo klaida {symbol}: {e}")

def balance_info():
    try:
        bal = float(session_api.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]["totalEquity"])
        return {"balansas": round(bal, 2)}
    except:
        return {"balansas": 0}

@app.route("/", methods=["GET", "POST"])
def index():
    if "user" not in session:
        return redirect(url_for("login"))
    if request.method == "POST":
        settings["n_pairs"] = int(request.form.get("n_pairs"))
        settings["ta_filters"] = request.form.getlist("ta_filters")
    return render_template("index.html",
        settings=settings,
        bot_status=bot_status,
        trade_history=trade_history[::-1],
        balance=balance_info()["balansas"],
        all_filters=["EMA", "RSI", "BB", "StochRSI", "CCI", "SMA", "VWAP", "Volume", "ATR", "AI"],
        graph=balance_graph,
        times=balance_times
    )

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
                if score >= 3 and now - last_trade_time.get(symbol, 0) > settings["cooldown"] * 60:
                    place_order(symbol, side="Buy")
                    last_trade_time[symbol] = now
        time.sleep(60)

if __name__ == "__main__":
    print("🔁 Boto ciklas paleistas")
    t = threading.Thread(target=trading_loop)
    t.daemon = True
    t.start()
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
