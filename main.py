import requests
from flask import Flask, render_template, request, redirect, url_for
from datetime import datetime
import threading
import time
import random

app = Flask(__name__)

# Parametrai
settings = {
    "take_profit": 2.0,
    "stop_loss": 1.5,
    "interval": 8,        # valandos (pvz., 1-12)
    "pair_count": 100     # kiek valiutų analizuoti (50–100)
}

PAIRS = []
BINANCE_PAIRS = []
trade_history = []
balance = 500.0
bot_running = True  # start/stop

def get_top_pairs(limit=100):
    url = "https://api.binance.com/api/v3/ticker/24hr"
    data = requests.get(url, timeout=10).json()
    usdt_pairs = [d for d in data if d["symbol"].endswith("USDT")]
    sorted_pairs = sorted(usdt_pairs, key=lambda d: float(d["quoteVolume"]), reverse=True)
    top = sorted_pairs[:limit]
    return [p["symbol"][:-4] + "/USDT" for p in top]

def update_pairs():
    global PAIRS, BINANCE_PAIRS
    PAIRS = get_top_pairs(settings["pair_count"])
    BINANCE_PAIRS = [p.replace("/", "") for p in PAIRS]

def get_binance_price(symbol):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        return float(data['price'])
    except Exception as e:
        print(f"Klaida gaunant {symbol} kainą:", e)
        return None

def demo_trade_bot():
    global balance, trade_history, bot_running
    while True:
        if bot_running:
            update_pairs()
            for i, pair in enumerate(PAIRS):
                symbol = BINANCE_PAIRS[i]
                price = get_binance_price(symbol)
                if price is None:
                    continue

                direction = random.choice(["PIRKTI", "PARDUOTI"])
                result_pct = random.uniform(-settings["stop_loss"], settings["take_profit"])
                profit = round(balance * (result_pct / 100), 2)
                balance += profit

                trade_history.insert(0, {
                    "laikas": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "pora": pair,
                    "kryptis": direction,
                    "kaina": price,
                    "pelnas": profit,
                    "procentai": round(result_pct, 2),
                    "balansas": round(balance, 2)
                })
                if len(trade_history) > 200:
                    trade_history.pop()
                time.sleep(0.2)  # demo greitis, galima didinti

            time.sleep(settings["interval"] * 60 * 60)
        else:
            time.sleep(2)

@app.route("/", methods=["GET"])
def index():
    return render_template(
        "index.html",
        trade_history=trade_history,
        demo_balance=balance,
        settings=settings,
        bot_status="Veikia" if bot_running else "Stabdyta",
        pairs=PAIRS
    )

@app.route("/update_settings", methods=["POST"])
def update_settings():
    interval = int(request.form.get("interval", 8))
    pair_count = int(request.form.get("pair_count", 100))
    settings["interval"] = min(max(interval, 1), 12)
    settings["pair_count"] = min(max(pair_count, 50), 100)
    return redirect(url_for("index"))

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

if __name__ == "__main__":
    t = threading.Thread(target=demo_trade_bot)
    t.daemon = True
    t.start()
    app.run(host="0.0.0.0", port=8000)
