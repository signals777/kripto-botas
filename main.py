import requests
from flask import Flask, render_template, request, redirect, url_for
from datetime import datetime
import threading
import time
import random
from collections import deque

app = Flask(__name__)

def fetch_top_100_pairs(n=100):
    url = "https://api.binance.com/api/v3/ticker/24hr"
    data = requests.get(url, timeout=10).json()
    usdt_pairs = [d for d in data if d['symbol'].endswith('USDT')]
    usdt_pairs.sort(key=lambda x: float(x['quoteVolume']), reverse=True)
    return [d['symbol'] for d in usdt_pairs[:n]]

PAIRS = fetch_top_100_pairs()
if not PAIRS:
    PAIRS = [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT", "DOGEUSDT", "TONUSDT", "TRXUSDT",
        "AVAXUSDT", "LINKUSDT", "DOTUSDT", "MATICUSDT", "WBTCUSDT", "SHIBUSDT", "LTCUSDT", "BCHUSDT", "ICPUSDT",
        "NEARUSDT", "UNIUSDT"
    ]

TA_FILTERS = ['EMA', 'MACD', 'BB', 'RSI', 'SMA', 'CCI']

settings = {
    "n_pairs": 100,
    "ta_filters": TA_FILTERS.copy()
}

trade_history = []
balance = 500.0
bot_running = True
commission_rate = 0.002

price_history = {symbol: deque(maxlen=100) for symbol in PAIRS}

def get_binance_price(symbol):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        return float(data['price'])
    except:
        return None

def ema(prices, n):
    if len(prices) < n:
        return sum(prices) / len(prices)
    k = 2 / (n + 1)
    ema_prev = prices[0]
    for price in prices:
        ema_prev = (price * k) + (ema_prev * (1 - k))
    return ema_prev

def macd(prices):
    if len(prices) < 26:
        return 0
    ema12 = ema(list(prices)[-12:], 12)
    ema26 = ema(list(prices)[-26:], 26)
    return ema12 - ema26

def bollinger_bands(prices, n=20):
    if len(prices) < n:
        return (0, 0, 0)
    avg = sum(prices[-n:]) / n
    std = (sum((p - avg) ** 2 for p in prices[-n:]) / n) ** 0.5
    upper = avg + 2 * std
    lower = avg - 2 * std
    return upper, avg, lower

def rsi(prices, n=14):
    if len(prices) < n + 1:
        return 50
    gains, losses = [], []
    for i in range(1, n + 1):
        diff = prices[-i] - prices[-i - 1]
        if diff > 0:
            gains.append(diff)
        else:
            losses.append(-diff)
    avg_gain = sum(gains) / n if gains else 0
    avg_loss = sum(losses) / n if losses else 0
    if avg_gain == 0 and avg_loss == 0:
        return 50
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def evaluate_symbol(symbol, prices, ta_filters):
    score = 0

    if 'EMA' in ta_filters and len(prices) >= 20:
        if ema(prices[-5:], 5) > ema(prices[-20:], 20):
            score += 1
    if 'MACD' in ta_filters and len(prices) >= 26:
        if macd(prices) > 0:
            score += 1
    if 'BB' in ta_filters and len(prices) >= 20:
        upper, mid, lower = bollinger_bands(prices)
        if prices[-1] < lower:
            score += 1
    if 'RSI' in ta_filters and len(prices) >= 15:
        if rsi(prices) < 30:
            score += 1
    if 'SMA' in ta_filters and len(prices) >= 20:
        sma = sum(prices[-20:]) / 20
        if prices[-1] > sma:
            score += 1
    if 'CCI' in ta_filters and len(prices) >= 21:
        typical_prices = [(p + p + p) / 3 for p in prices]
        tp = typical_prices[-20:]
        mean_tp = sum(tp) / 20
        mean_dev = sum(abs(t - mean_tp) for t in tp) / 20
        if mean_dev != 0:
            cci_val = (tp[-1] - mean_tp) / (0.015 * mean_dev)
            if cci_val > 100:
                score += 1
    return score

def ai_demo_bot():
    global balance, trade_history, bot_running, PAIRS, price_history
    while True:
        if bot_running:
            try:
                top_pairs = fetch_top_100_pairs(settings["n_pairs"])
                if top_pairs:
                    PAIRS[:] = top_pairs
            except:
                pass

            best_pair = None
            best_score = 0
            best_price = None

            for symbol in PAIRS[:settings["n_pairs"]]:
                price = get_binance_price(symbol)
                if price is None:
                    continue
                price_history.setdefault(symbol, deque(maxlen=100)).append(price)
                score = evaluate_symbol(symbol, price_history[symbol], settings["ta_filters"])
                if score > best_score:
                    best_score = score
                    best_pair = symbol
                    best_price = price

            if best_pair and best_score >= 3:
                rsi_val = rsi(price_history[best_pair])
                upper, mid, lower = bollinger_bands(price_history[best_pair])
                if rsi_val < 30 or price_history[best_pair][-1] < lower:
                    pct = random.uniform(-1.5, 2.0)
                    profit = round(balance * (pct / 100), 2)
                    commission = round(abs(balance * commission_rate * (pct / 100)), 4)
                    profit -= commission
                    balance += profit
                    trade_history.insert(0, {
                        "laikas": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        "pora": best_pair,
                        "kryptis": "PIRKTI",
                        "kaina": best_price,
                        "pelnas": round(profit, 2),
                        "procentai": round(pct, 2),
                        "komisinis": commission,
                        "balansas": round(balance, 2)
                    })
                    if len(trade_history) > 200:
                        trade_history.pop()
            time.sleep(1)
        else:
            time.sleep(1)
            @app.route("/", methods=["GET", "POST"])
def index():
    global settings, PAIRS
    if request.method == "POST":
        try:
            settings["n_pairs"] = int(request.form.get("n_pairs", 100))
            settings["ta_filters"] = request.form.getlist("ta_filters")
        except:
            pass
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
        times=times,
        ta_filters=TA_FILTERS
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

@app.route("/refresh")
def refresh():
    return redirect(url_for("index"))

@app.route("/top100")
def refresh_top100():
    global PAIRS
    PAIRS = fetch_top_100_pairs()
    return redirect(url_for("index"))

if __name__ == "__main__":
    t = threading.Thread(target=ai_demo_bot)
    t.daemon = True
    t.start()
    app.run(host="0.0.0.0", port=8000)
