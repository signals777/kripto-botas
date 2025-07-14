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
            interval=15,
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
        score += 0

    return score

def fetch_top_symbols():
    global symbols
    try:
        ticker_data = session_api.get_tickers(category="linear")["result"]["list"]
        filtered = []
        for item in ticker_data:
            if "symbol" in item and "lastPrice" in item:
                filtered.append(item)
        sorted_tickers = sorted(filtered, key=lambda x: float(x["volume24h"]), reverse=True)
        symbols[:] = [t["symbol"] for t in sorted_tickers[:settings["n_pairs"]]]
    except Exception as e:
        print(f"Klaida fetch_top_symbols: {e}")
        symbols = []

def balance_info():
    try:
        bal = float(session_api.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]["totalEquity"])
        return {"balansas": round(bal, 2)}
    except:
        return {"balansas": 0}

def calculate_qty(symbol):
    balance = balance_info()["balansas"]
    try:
        tickers = session_api.get_tickers(category="linear")["result"]["list"]
        price_data = next((item for item in tickers if item["symbol"] == symbol), None)
        instruments = session_api.get_symbols(category="linear")["result"]["list"]
        instrument = next((item for item in instruments if item["symbol"] == symbol), None)

        if price_data is None or "lastPrice" not in price_data:
            raise Exception(f"Nerasta kaina instrumentui {symbol}")
        if instrument is None or "lotSizeFilter" not in instrument:
            raise Exception(f"Nerasta lotSizeFilter instrumentui {symbol}")

        price = float(price_data["lastPrice"])
        min_qty = float(instrument["lotSizeFilter"]["minOrderQty"])
        step = float(instrument["lotSizeFilter"]["qtyStep"])

        position_value = balance * (settings["position_size_pct"] / 100)
        qty = (position_value * settings["leverage"]) / price

        qty = max(min_qty, round(qty / step) * step)
        return round(qty, 8)

    except Exception as e:
        print(f"❌ Klaida skaičiuojant kiekį {symbol}: {e}")
        return 0

def place_order(symbol, side):
    try:
        qty = calculate_qty(symbol)
        if qty <= 0:
            raise Exception("Apskaičiuotas kiekis yra 0")
        price_data = session_api.get_tickers(category="linear")["result"]["list"]
        entry_data = next((item for item in price_data if item["symbol"] == symbol), None)
        if entry_data is None or "lastPrice" not in entry_data:
            raise Exception("Nepavyko gauti kainos")
        entry_price = float(entry_data["lastPrice"])

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
