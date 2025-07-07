import requests
from flask import Flask, render_template, request, redirect, url_for
from datetime import datetime
import threading
import time
import random
from collections import deque

app = Flask(__name__)

FEE = 0.001   # 0.1% Binance komisinis
MAX_TRADES = 200

def get_top_pairs(n=100):
    url = "https://api.binance.com/api/v3/ticker/24hr"
    r = requests.get(url, timeout=10)
    tickers = r.json()
    pairs = [t for t in tickers if t['symbol'].endswith("USDT") and not t['symbol'].endswith("BUSD")]
    pairs.sort(key=lambda x: float(x['quoteVolume']), reverse=True)
    return [t['symbol'] for t in pairs[:n]]

BINANCE_PAIRS = get_top_pairs(100)

def ema(prices, n):
    if len(prices) < n: return sum(prices) / len(prices)
    k = 2 / (n + 1)
    ema_prev = prices[0]
    for price in prices:
        ema_prev = price * k + ema_prev * (1 - k)
    return ema_prev

def macd(prices):
    if len(prices) < 26: return 0
    ema12 = ema(prices[-12:], 12)
    ema26 = ema(prices[-26:], 26)
    return ema12 - ema26

def bb(prices):
    if len(prices) < 20: return (0, 0)
    sma = sum(prices[-20:]) / 20
    std = (sum([(p - sma) ** 2 for p in prices[-20:]]) / 20) ** 0.5
    return (sma + 2 * std, sma - 2 * std)

def rsi(prices, period=14):
    if len(prices) < period + 1: return 50
    gains = [max(prices[i+1]-prices[i], 0) for i in range(-period-1, -1)]
    losses = [abs(min(prices[i+1]-prices[i], 0)) for i in range(-period-1, -1)]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period if sum(losses) > 0 else 0.0001
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

TA_FILTERS = ["EMA", "MACD", "BB", "RSI"]

settings = {
    "n_pairs": 100,
    "ta_filters": ["EMA", "MACD", "BB", "RSI"]
}
trade_history = []
balance = 500.0
bot_running = True
price_history = {symbol: deque(maxlen=40) for symbol in BINANCE_PAIRS}

def get_binance_price(symbol):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        return float(data['price'])
    except Exception:
        return None

def ai_decision(prices, active_filters):
    signals = []
    if "EMA" in active_filters and len(prices) >= 20:
        if ema(prices[-5:], 5) > ema(prices[-20:], 20): signals.append("PIRKTI")
        if ema(prices[-5:], 5) < ema(prices[-20:], 20): signals.append("PARDUOTI")
    if "MACD" in active_filters and len(prices) >= 26:
        if macd(prices) > 0: signals.append("PIRKTI")
        if macd(prices) < 0: signals.append("PARDUOTI")
    if "BB" in active_filters and len(prices) >= 20:
        upper, lower = bb(prices)
        if prices[-1] > upper: signals.append("PARDUOTI")
        if prices[-1] < lower: signals.append("PIRKTI")
    if "RSI" in active_filters and len(prices) >= 15:
        r = rsi(prices)
        if r < 30: signals.append("PIRKTI")
        if r > 70: signals.append("PARDUOTI")
    if signals.count("PIRKTI") > signals.count("PARDUOTI") and signals:
        return "PIRKTI"
    if signals.count("PARDUOTI") > signals.count("PIRKTI") and signals:
        return "PARDUOTI"
    return None

def ai_demo_bot():
    global balance, trade_history, bot_running, price_history, BINANCE_PAIRS
    while True:
        if bot_running:
            pairs_to_check = BINANCE_PAIRS[:settings["n_pairs"]]
            for symbol in pairs_to_check:
                price = get_binance_price(symbol)
                if price is None: continue
                price_history[symbol].append(price)
                signal = ai_decision(list(price_history[symbol]), settings["ta_filters"])
                if not signal: continue
                pct = random.uniform(-1.5, 2.0)
                gross = balance * (pct/100)
                fee_paid = abs(gross) * FEE
                net_profit = gross - fee_paid
                balance += net_profit

                trade_history.insert(0, {
                    "laikas": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "pora": symbol,
                    "kryptis": signal,
                    "kaina": price,
                    "pelnas": round(net_profit, 2),
                    "procentai": round(pct, 2),
                    "komisinis": round(fee_paid, 2),
                    "balansas": round(balance, 2),
                })
                if len(trade_history) > MAX_TRADES:
                    trade_history.pop()
                time.sleep(0.2)  # Demo "gyvumas"
        else:
            time.sleep(2)

@app.route("/", methods=["GET", "POST"])
def index():
    global settings, BINANCE_PAIRS
    if request.method == "POST":
        try:
            settings["n_pairs"] = int(request.form.get("n_pairs", 100))
            filters = request.form.getlist("ta_filters")
            settings["ta_filters"] = filters if filters else ["EMA"]
        except Exception: pass
        return redirect(url_for("index"))
    graph = [float(t["balansas"]) for t in reversed(trade_history[-100:])]
    times = [t["laikas"] for t in reversed(trade_history[-100:])]
    return render_template(
        "index.html",
        trade_history=trade_history,
        demo_balance=round(balance, 2),
        settings=settings,
        bot_status="Veikia" if bot_running else "Stabdyta",
        graph=graph,
        times=times,
        all_filters=TA_FILTERS,
        all_pairs=BINANCE_PAIRS
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

@app.route("/refresh_pairs")
def refresh_pairs():
    global BINANCE_PAIRS, price_history
    BINANCE_PAIRS = get_top_pairs(100)
    price_history = {symbol: deque(maxlen=40) for symbol in BINANCE_PAIRS}
    return redirect(url_for("index"))

if __name__ == "__main__":
    t = threading.Thread(target=ai_demo_bot)
    t.daemon = True
    t.start()
    app.run(host="0.0.0.0", port=8000)
