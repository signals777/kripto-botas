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
from ta.trend import EMAIndicator, SMAIndicator
from ta.volatility import BollingerBands
from sklearn.linear_model import LinearRegression

app = Flask(__name__)
app.secret_key = "slaptas_raktas"
app.permanent_session_lifetime = timedelta(minutes=60)

api_key = "TAVO_API_KEY"
api_secret = "TAVO_API_SECRET"

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
bot_status = "running"
market_blocked_until = 0
drop_count = 0
last_balance = None

def fetch_top_symbols():
    try:
        session = get_session_api()
        tickers = session.get_tickers(category="linear")["result"]["list"]
        return [t["symbol"] for t in tickers if "USDT" in t["symbol"]][:settings["n_pairs"]]
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
        wallet = session.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]
        balance = float(wallet["totalEquity"])
        usdt_amount = (balance * settings["position_size_pct"] / 100)
        leverage = determine_leverage(0)
        qty = math.floor((usdt_amount * leverage) / last_price * 1000) / 1000
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
    if time.time() < market_blocked_until:
        print(f"🚫 Prekyba sustabdyta – neleidžiama vykdyti užsakymų: {symbol}")
        return
    try:
        session = get_session_api()
        tickers = session.get_tickers(category="linear")["result"]["list"]
        price = float(next(t for t in tickers if t["symbol"] == symbol)["lastPrice"])
        tp_price = round(price * (1 + tp_pct), 4) if side == "Buy" else round(price * (1 - tp_pct), 4)
        sl_price = round(price * (1 - sl_pct), 4) if side == "Buy" else round(price * (1 + sl_pct), 4)
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

def analyze_market():
    try:
        up_count = 0
        symbols = fetch_top_symbols()
        for symbol in symbols:
            df = get_klines(symbol)
            if df is None or len(df) < 20:
                continue
            rsi = RSIIndicator(df["close"]).rsi().iloc[-1]
            ema = EMAIndicator(df["close"], window=14).ema_indicator().iloc[-1]
            candle_up = df["close"].iloc[-1] > df["open"].iloc[-1]
            if rsi > 50 and df["close"].iloc[-1] > ema and candle_up:
                up_count += 1
        print(f"📊 Rinkos analizė: {up_count} porų rodo kilimą")
        return up_count >= 25
    except Exception as e:
        print(f"Klaida rinkos analizėje: {e}")
        return False

def trading_loop():
    global bot_status, market_blocked_until, drop_count, last_balance
    while True:
        if bot_status != "running":
            time.sleep(3)
            continue

        now = time.time()
        if now < market_blocked_until:
            print("⏸️ Prekyba sustabdyta. AI analizuoja rinką...")
            if analyze_market():
                print("✅ AI: Rinka atsigauna – paleidžiama prekyba")
                market_blocked_until = 0
                drop_count = 0
            else:
                print("🔄 AI: Rinka vis dar krenta – laukiam dar 5 min.")
                market_blocked_until = time.time() + 300
            time.sleep(5)
            continue

        try:
            session = get_session_api()
            wallet = session.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]
            balance = float(wallet["totalEquity"])

            if last_balance is not None:
                drop_pct = (last_balance - balance) / last_balance
                if drop_pct >= 0.0015:
                    drop_count += 1
                    print(f"⚠️ Fiksuotas {drop_count} kritimas ({drop_pct*100:.2f}%)")
                if drop_count >= 4:
                    print("🛑 AI: Per daug kritimų, stabdom prekybą 15 min.")
                    market_blocked_until = time.time() + 900
                    drop_count = 0
            last_balance = balance

            symbols = fetch_top_symbols()
            for symbol in symbols:
                time.sleep(0.4)
                if symbol in symbol_cooldowns and time.time() - symbol_cooldowns[symbol] < settings["cooldown"] * 60:
                    continue
                df = get_klines(symbol)
                if df is None or len(df) < 50:
                    continue

                change_1h = (df["close"].iloc[-1] - df["close"].iloc[-4]) / df["close"].iloc[-4]
                if change_1h < 0.015:
                    continue

                score = 0
                close = df["close"]
                if RSIIndicator(close, window=14).rsi().iloc[-1] < 30:
                    score += 1
                if close.iloc[-1] < BollingerBands(close, window=14).bollinger_lband().iloc[-1]:
                    score += 1
                if EMAIndicator(close, window=14).ema_indicator().iloc[-1] < close.iloc[-1]:
                    score += 1
                if SMAIndicator(close, window=14).sma_indicator().iloc[-1] < close.iloc[-1]:
                    score += 1
                if ai_predict(df):
                    score += 2
                volume = df["volume"].iloc[-1]
                avg_volume = df["volume"].rolling(window=20).mean().iloc[-1]
                if volume > avg_volume:
                    score += 1

                print(f"{symbol} balas: {score}")
                if score >= 4:
                    qty = calculate_qty(symbol)
                    leverage = determine_leverage(score)
                    try:
                        session.set_leverage(category="linear", symbol=symbol, buyLeverage=leverage, sellLeverage=leverage)
                    except Exception as e:
                        print(f"Klaida nustatant svertą {symbol}: {e}")
                        continue
                    place_order(symbol, "Buy", qty, settings["take_profit"], settings["stop_loss"])
                    symbol_cooldowns[symbol] = time.time()
        except Exception as e:
            print(f"Klaida trading_loop: {e}")
        time.sleep(5)

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

if __name__ == "__main__":
    print("🔁 Boto ciklas paleistas automatiškai (serverio starto metu)")
    t = threading.Thread(target=trading_loop)
    t.daemon = True
    t.start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
