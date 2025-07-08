import requests
from flask import Flask, render_template, request, redirect, url_for
from datetime import datetime
import threading
import time
import random
from collections import deque
import math

app = Flask(__name__)

PAIRS = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
    "ADA/USDT", "AVAX/USDT", "LINK/USDT", "MATIC/USDT", "DOT/USDT",
    "LTC/USDT", "DOGE/USDT", "NEAR/USDT", "INJ/USDT", "APT/USDT",
    "ATOM/USDT", "ARB/USDT", "OP/USDT", "RNDR/USDT", "TIA/USDT"
]

BINANCE_PAIRS = [p.replace("/", "") for p in PAIRS]

settings = {
    "take_profit": 2.0,
    "stop_loss": 1.5,
    "n_pairs": 20,
    "cooldown": 5,
}

trade_history = []
balance = 500.0
bot_running = True

price_history = {symbol: deque(maxlen=100) for symbol in BINANCE_PAIRS}
volume_history = {symbol: deque(maxlen=100) for symbol in BINANCE_PAIRS}
last_trade_time = {symbol: 0 for symbol in BINANCE_PAIRS}

PANEL_URL = "http://localhost:8000/receive_signal"  # Pakeisk į tikrą jei reikia

def get_binance_price(symbol):
    try:
        r = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=5)
        return float(r.json()['price'])
    except:
        return None

def get_binance_volume(symbol):
    try:
        r = requests.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}", timeout=5)
        return float(r.json()['volume'])
    except:
        return None

def ema(prices, n):
    if len(prices) < n:
        return sum(prices) / len(prices)
    k = 2 / (n + 1)
    ema_val = prices[0]
    for price in prices:
        ema_val = price * k + ema_val * (1 - k)
    return ema_val

def sma(prices, n):
    if len(prices) < n:
        return sum(prices) / len(prices)
    return sum(prices[-n:]) / n

def macd(prices):
    if len(prices) < 26:
        return 0
    return ema(prices[-12:], 12) - ema(prices[-26:], 26)

def bollinger_bands(prices, n=20):
    if len(prices) < n:
        return (0, 0, 0)
    avg = sma(prices, n)
    std = (sum((p - avg)**2 for p in prices[-n:]) / n)**0.5
    return avg + 2 * std, avg, avg - 2 * std

def rsi(prices, n=14):
    if len(prices) < n + 1:
        return 50
    gains = losses = 0
    for i in range(-n, -1):
        delta = prices[i+1] - prices[i]
        if delta > 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / n
    avg_loss = losses / n if losses else 1
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def cci(prices, n=20):
    if len(prices) < n:
        return 0
    tp = prices[-n:]
    sma_tp = sum(tp) / n
    mean_dev = sum(abs(p - sma_tp) for p in tp) / n
    if mean_dev == 0:
        return 0
    return (tp[-1] - sma_tp) / (0.015 * mean_dev)

def stochastic_rsi(prices, n=14):
    if len(prices) < n + 1:
        return 0.5
    rsi_vals = [rsi(prices[i:i+n+1], n) for i in range(len(prices) - n)]
    min_rsi = min(rsi_vals)
    max_rsi = max(rsi_vals)
    if max_rsi - min_rsi == 0:
        return 0.5
    return (rsi_vals[-1] - min_rsi) / (max_rsi - min_rsi)

def atr(prices, n=14):
    if len(prices) < n+1:
        return 0
    tr = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
    return sum(tr[-n:]) / n

def vwap(prices, volumes):
    if len(prices) != len(volumes) or not prices:
        return 0
    pv = sum(p * v for p, v in zip(prices, volumes))
    return pv / sum(volumes) if sum(volumes) else prices[-1]

def ai_decision(prices, volumes):
    score = 0
    if len(prices) < 30 or len(volumes) < 30:
        return None

    if ema(prices[-5:], 5) > ema(prices[-20:], 20): score += 1
    if sma(prices, 10) > sma(prices, 20): score += 1
    if macd(prices) > 0: score += 1
    if rsi(prices) < 30: score += 1
    upper, _, lower = bollinger_bands(prices)
    if prices[-1] < lower: score += 1
    if cci(prices) < -100: score += 1
    if stochastic_rsi(prices) < 0.2: score += 1
    if atr(prices) > 0.5: score += 1
    if prices[-1] > vwap(prices, volumes): score += 1
    if volumes[-1] > sum(volumes)/len(volumes): score += 1

    if score >= 5:
        return "PIRKTI"
    return None

def ai_bot():
    global balance, trade_history, bot_running
    while True:
        if bot_running:
            now = time.time()
            for i, pair in enumerate(PAIRS[:settings["n_pairs"]]):
                symbol = BINANCE_PAIRS[i]
                price = get_binance_price(symbol)
                volume = get_binance_volume(symbol)
                if price is None or volume is None:
                    continue
                price_history[symbol].append(price)
                volume_history[symbol].append(volume)
                signal = ai_decision(list(price_history[symbol]), list(volume_history[symbol]))

                if not signal or (now - last_trade_time[symbol] < settings["cooldown"]*60):
                    continue
                last_trade_time[symbol] = now

                pct = random.uniform(-settings["stop_loss"], settings["take_profit"])
                result = round(balance * (pct / 100), 2)
                balance += result

                trade = {
                    "laikas": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "pora": pair,
                    "kryptis": signal,
                    "kaina": price,
                    "pelnas": result,
                    "procentai": round(pct, 2),
                    "balansas": round(balance, 2)
                }
                trade_history.insert(0, trade)
                if len(trade_history) > 200:
                    trade_history.pop()

                try:
                    requests.post(PANEL_URL, json=trade, timeout=3)
                except:
                    pass

                time.sleep(0.2)
        else:
            time.sleep(2)

@app.route("/", methods=["GET", "POST"])
def index():
    global settings
    if request.method == "POST":
        try:
            settings["n_pairs"] = int(request.form.get("n_pairs", 20))
            settings["take_profit"] = float(request.form.get("take_profit", 2))
            settings["stop_loss"] = float(request.form.get("stop_loss", 1.5))
            settings["cooldown"] = int(request.form.get("cooldown", 5))
        except:
            pass
        return redirect(url_for("index"))
    graph = [t["balansas"] for t in reversed(trade_history[-100:])]
    times = [t["laikas"] for t in reversed(trade_history[-100:])]
    return render_template("index.html", trade_history=trade_history, demo_balance=balance,
                           settings=settings, bot_status="Veikia" if bot_running else "Stabdyta",
                           graph=graph, times=times)

@app.route("/start")
def start_bot():
    global bot_running
    bot_running = True
    return redirect(url_for("index"))

@app.route("/stop")
def stop_bot():
    global bot_running
    bot_running = False
    return redirect(url_for("index"))

if __name__ == "__main__":
    t = threading.Thread(target=ai_bot)
    t.daemon = True
    t.start()
    app.run(host="0.0.0.0", port=8000)
