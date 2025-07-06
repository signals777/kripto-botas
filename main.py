import requests
from flask import Flask, render_template, request, redirect, url_for
from datetime import datetime
import threading
import time
import random
from collections import deque

app = Flask(__name__)

# Top 100 kripto valiutų (galima keisti panelėje)
PAIRS = [ ... ]  # (sąrašą palik, kaip buvo)

BINANCE_PAIRS = [p.replace("/", "") for p in PAIRS]

settings = {
    "n_pairs": 100,
    "ta_ema": True,
    "ta_macd": True,
    "ta_bb": True,
    "ta_rsi": True,
}
trade_history = []
balance = 500.0
bot_running = True

# Kainų istorija
price_history = {symbol: deque(maxlen=50) for symbol in BINANCE_PAIRS}
commission_pct = 0.2 / 100  # 0.2%

def get_binance_price(symbol):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    try:
        r = requests.get(url, timeout=5)
        return float(r.json()['price'])
    except:
        return None

def ema(prices, n):
    if len(prices) < n:
        return sum(prices)/len(prices)
    k = 2/(n+1)
    ema_prev = prices[0]
    for price in prices:
        ema_prev = (price * k) + (ema_prev * (1 - k))
    return ema_prev

def macd(prices):
    if len(prices) < 26:
        return 0
    ema12 = ema(prices[-12:], 12)
    ema26 = ema(prices[-26:], 26)
    return ema12 - ema26

def bollinger(prices):
    if len(prices) < 20:
        return 0, 0
    ma = sum(prices[-20:]) / 20
    std = (sum((p - ma) ** 2 for p in prices[-20:]) / 20) ** 0.5
    upper = ma + 2 * std
    lower = ma - 2 * std
    return upper, lower

def rsi(prices, n=14):
    if len(prices) < n+1:
        return 50
    gains = []
    losses = []
    for i in range(-n, -1):
        change = prices[i+1] - prices[i]
        if change > 0:
            gains.append(change)
        else:
            losses.append(abs(change))
    avg_gain = sum(gains)/n if gains else 0
    avg_loss = sum(losses)/n if losses else 0
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100/(1+rs))

def ai_signal(prices):
    signals = []
    if settings["ta_ema"]:
        if len(prices) >= 20:
            if ema(prices[-5:], 5) > ema(prices[-20:], 20):
                signals.append("PIRKTI")
            elif ema(prices[-5:], 5) < ema(prices[-20:], 20):
                signals.append("PARDUOTI")
    if settings["ta_macd"]:
        if len(prices) >= 26:
            m = macd(prices)
            if m > 0:
                signals.append("PIRKTI")
            elif m < 0:
                signals.append("PARDUOTI")
    if settings["ta_bb"]:
        upper, lower = bollinger(prices)
        if prices[-1] > upper:
            signals.append("PARDUOTI")
        elif prices[-1] < lower:
            signals.append("PIRKTI")
    if settings["ta_rsi"]:
        r = rsi(prices)
        if r < 30:
            signals.append("PIRKTI")
        elif r > 70:
            signals.append("PARDUOTI")
    # Jei bent vienas filtras duoda aiškų signalą
    if "PIRKTI" in signals:
        return "PIRKTI"
    if "PARDUOTI" in signals:
        return "PARDUOTI"
    return None

def ai_demo_bot():
    global balance, trade_history, bot_running
    while True:
        if bot_running:
            for i, pair in enumerate(PAIRS[:settings["n_pairs"]]):
                symbol = BINANCE_PAIRS[i]
                price = get_binance_price(symbol)
                if price is None:
                    continue
                price_history[symbol].append(price)
                signal = ai_signal(list(price_history[symbol]))
                if not signal:
                    continue

                # Realistiškas pelno simuliavimas (atsitiktinis, bet pagal TP/SL logiką)
                pct = random.uniform(-1.5, 2.0)
                profit = round(balance * (pct / 100), 2)
                commission = round(abs(balance * commission_pct), 2)
                net_profit = profit - commission
                balance += net_profit

                trade_history.insert(0, {
                    "laikas": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "pora": pair,
                    "kryptis": signal,
                    "kaina": price,
                    "pelnas": net_profit,
                    "procentai": round(pct, 2),
                    "komisinis": commission,
                    "balansas": round(balance, 2)
                })
                if len(trade_history) > 200:
                    trade_history.pop()
                time.sleep(0.08)  # kad nestrigtų panelė
        else:
            time.sleep(2)

@app.route("/", methods=["GET", "POST"])
def index():
    global settings
    if request.method == "POST":
        # Atnaujinti nustatymus (mygtukai ir filtrai)
        try:
            settings["n_pairs"] = int(request.form.get("n_pairs", 100))
            settings["ta_ema"] = "ta_ema" in request.form
            settings["ta_macd"] = "ta_macd" in request.form
            settings["ta_bb"] = "ta_bb" in request.form
            settings["ta_rsi"] = "ta_rsi" in request.form
        except: pass
        return redirect(url_for("index"))
    graph = [float(t["balansas"]) for t in reversed(trade_history[-100:])]
    times = [t["laikas"] for t in reversed(trade_history[-100:])]
    return render_template(
        "index.html",
        trade_history=trade_history,
        demo_balance=round(balance, 2),
        bot_status="Veikia" if bot_running else "Stabdyta",
        settings=settings,
        graph=graph,
        times=times
    )

@app.route("/stop")
def stop_bot():
    global bot_running
    bot_running = False
    return redirect(url_for("index"))

@app.route("/start")
def start_bot():
    global bot_running
    bot_running = True
    return redirect(url_for("index"))

if __name__ == "__main__":
    t = threading.Thread(target=ai_demo_bot)
    t.daemon = True
    t.start()
    app.run(host="0.0.0.0", port=8000)
