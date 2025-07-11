from flask import Flask, render_template, request, redirect, url_for, session
from datetime import timedelta
import threading
import time
import pandas as pd
from pybit.unified_trading import HTTP
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import EMAIndicator, SMAIndicator, CCIIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume import OnBalanceVolumeIndicator

app = Flask(__name__)
app.secret_key = 'azEVdZmiRBlHID75zQehXHYYYKw0jB8DDFPJ'  # Pakeisk į saugų raktą!
app.permanent_session_lifetime = timedelta(minutes=60)

# Vartotojai
USERS = {"v@gmail.com": "*********L123***
}

# Bybit API
session_api = HTTP(
    api_key="b2tL6abuyH7gEQjIC1",
    api_secret="azEVdZmiRBlHID75zQehXHYYYKw0jB8DDFPJ",
    testnet=False,
)

# Nustatymai
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

def fetch_top_symbols():
    global symbols
    try:
        response = session_api.get_tickers(category="linear")
        data = response.get("result", {}).get("list", [])
        usdt_pairs = [item["symbol"] for item in data if item["symbol"].endswith("USDT")]
        symbols = usdt_pairs[:settings["n_pairs"]]
    except Exception as e:
        print("❌ Nepavyko gauti simbolių:", e)

def get_klines(symbol, interval="15"):
    try:
        klines = session_api.get_kline(category="linear", symbol=symbol, interval=interval, limit=100)
        data = klines['result']['list']
        df = pd.DataFrame(data, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "", "", "", "", "", ""
        ])
        df["close"] = df["close"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["volume"] = df["volume"].astype(float)
        return df
    except Exception as e:
        print(f"❌ Klines klaida {symbol}: {e}")
        return None

def apply_ta_filters(df):
    score = 0
    try:
        if "EMA" in settings["ta_filters"]:
            ema_fast = EMAIndicator(df["close"], window=5).ema_indicator()
            ema_slow = EMAIndicator(df["close"], window=20).ema_indicator()
            if ema_fast.iloc[-1] > ema_slow.iloc[-1]: score += 1
        if "SMA" in settings["ta_filters"]:
            sma_fast = SMAIndicator(df["close"], window=5).sma_indicator()
            sma_slow = SMAIndicator(df["close"], window=20).sma_indicator()
            if sma_fast.iloc[-1] > sma_slow.iloc[-1]: score += 1
        if "RSI" in settings["ta_filters"]:
            rsi = RSIIndicator(df["close"]).rsi()
            if rsi.iloc[-1] < 30: score += 1
        if "StochRSI" in settings["ta_filters"]:
            stoch = StochasticOscillator(df["high"], df["low"], df["close"])
            if stoch.stoch().iloc[-1] < 20: score += 1
        if "CCI" in settings["ta_filters"]:
            cci = CCIIndicator(df["high"], df["low"], df["close"]).cci()
            if cci.iloc[-1] < -100: score += 1
        if "BB" in settings["ta_filters"]:
            bb = BollingerBands(df["close"])
            if df["close"].iloc[-1] < bb.bollinger_lband().iloc[-1]: score += 1
        if "VWAP" in settings["ta_filters"]:
            tp = (df["high"] + df["low"] + df["close"]) / 3
            vwap = (tp * df["volume"]).cumsum() / df["volume"].cumsum()
            if df["close"].iloc[-1] < vwap.iloc[-1]: score += 1
        if "Volume" in settings["ta_filters"]:
            obv = OnBalanceVolumeIndicator(df["close"], df["volume"]).on_balance_volume()
            if obv.iloc[-1] > obv.iloc[-2]: score += 1
        if "ATR" in settings["ta_filters"]:
            atr = AverageTrueRange(df["high"], df["low"], df["close"]).average_true_range()
            if atr.iloc[-1] > atr.iloc[-2]: score += 1
        if "AI" in settings["ta_filters"]:
            ema5 = EMAIndicator(df["close"], window=5).ema_indicator()
            ema20 = EMAIndicator(df["close"], window=20).ema_indicator()
            rsi = RSIIndicator(df["close"]).rsi()
            if ema5.iloc[-1] > ema20.iloc[-1] and rsi.iloc[-1] < 35: score += 1
    except Exception as e:
        print("⚠️ TA klaida:", e)
    return score

def calculate_qty(symbol):
    try:
        balance_info = session_api.get_wallet_balance(accountType="UNIFIED")
        usdt = float(balance_info["result"]["list"][0]["totalEquity"])
        amount = usdt * settings["position_size_pct"] / 100
        price = float(session_api.get_ticker(category="linear", symbol=symbol)["result"]["list"][0]["lastPrice"])
        qty = round((amount * settings["leverage"]) / price, 3)
        return qty
    except Exception as e:
        print(f"⚠️ Kiekio klaida {symbol}: {e}")
        return 0.01

def place_order(symbol, side):
    try:
        qty = calculate_qty(symbol)
        session_api.place_order(
            category="linear",
            symbol=symbol,
            side=side,
            order_type="Market",
            qty=qty,
            time_in_force="GoodTillCancel",
            reduce_only=False
        )
        price = float(session_api.get_ticker(category="linear", symbol=symbol)["result"]["list"][0]["lastPrice"])
        trade_history.append({
            "laikas": time.strftime("%Y-%m-%d %H:%M:%S"),
            "pora": symbol,
            "kryptis": side,
            "kaina": price,
            "pozicija": round(qty * price, 2)
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

# ------------------ Boto paleidimas -------------------

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

# ------------------ Web panelė -------------------

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

# ----------------------
if __name__ == "__main__":
    print("🔁 Boto ciklas paleistas")
    t = threading.Thread(target=trading_loop)
    t.daemon = True
    t.start()
    app.run(host="0.0.0.0", port=8000)
