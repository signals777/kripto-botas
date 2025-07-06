import requests
from flask import Flask, render_template, request, redirect, url_for
from datetime import datetime
import threading
import time
import random
from collections import deque

app = Flask(__name__)

# TOP 100 kripto valiutų porų (gali keisti kiekį panelėje)
PAIRS = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "ADA/USDT", "XRP/USDT", "DOGE/USDT", "TON/USDT", "TRX/USDT",
    "AVAX/USDT", "LINK/USDT", "DOT/USDT", "MATIC/USDT", "WBTC/USDT", "SHIB/USDT", "LTC/USDT", "BCH/USDT", "ICP/USDT",
    "NEAR/USDT", "UNI/USDT", "DAI/USDT", "STETH/USDT", "APT/USDT", "FIL/USDT", "PEPE/USDT", "RNDR/USDT", "ETC/USDT",
    "OKB/USDT", "TAO/USDT", "FDUSD/USDT", "LEO/USDT", "TIA/USDT", "CRO/USDT", "IMX/USDT", "INJ/USDT", "STX/USDT",
    "ARB/USDT", "MKR/USDT", "OP/USDT", "VET/USDT", "SUI/USDT", "GRT/USDT", "LDO/USDT", "QNT/USDT", "AAVE/USDT",
    "THETA/USDT", "XLM/USDT", "FLOW/USDT", "AXS/USDT", "SNX/USDT", "KAVA/USDT", "MNT/USDT", "XAUT/USDT", "TIA/USDT",
    "YFI/USDT", "KNC/USDT", "DOGE/USDT", "VET/USDT", "SHIBA/USDT", "QNT/USDT", "LINK/USDT", "ETC/USDT", "ALGO/USDT",
    "ARBUSDT", "MATIC/USDT", "SAND/USDT", "EOS/USDT", "MKR/USDT", "UNI/USDT", "AVAX/USDT", "FTM/USDT", "GALA/USDT",
    "ENJ/USDT", "1INCH/USDT", "BAT/USDT", "CRV/USDT", "CHZ/USDT", "FTM/USDT", "MANA/USDT", "GALA/USDT", "ENJ/USDT",
    "1INCH/USDT", "BAT/USDT", "CELO/USDT", "LRC/USDT", "KAVA/USDT", "ALGO/USDT", "ARB/USDT", "EOS/USDT"
]

BINANCE_PAIRS = [p.replace("/", "") for p in PAIRS]

# Parametrai, kuriuos galima keisti panelėje
settings = {
    "take_profit": 2.0,
    "stop_loss": 1.5,
    "interval": 8,        # valandų, default 8
    "n_pairs": 50         # kiek valiutų analizuoti
}

trade_history = []
balance = 500.0
bot_running = True

# Kainų istorija AI analizei
price_history = {symbol: deque(maxlen=25) for symbol in BINANCE_PAIRS}

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

def ai_decision(prices):
    # EMA5/EMA20 crossover signalas
    if len(prices) < 20:
        return None
    short = ema(list(prices)[-5:], 5)
    long = ema(list(prices)[-20:], 20)
    if short > long:
        return "PIRKTI"
    elif short < long:
        return "PARDUOTI"
    else:
        return None

def ai_demo_bot():
    global balance, trade_history, bot_running
    while True:
        if bot_running:
            # Kiek valiutų naudoti (naudotojo pasirinkimas)
            n = int(settings["n_pairs"])
            for i, pair in enumerate(PAIRS[:n]):
                symbol = BINANCE_PAIRS[i]
                price = get_binance_price(symbol)
                if price is None:
                    continue
                # Pildom kainų istoriją AI analizei
                price_history[symbol].append(price)
                signal = ai_decision(price_history[symbol])
                if not signal:
                    continue  # Jei nėra aiškaus signalo, praleidžiam

                # Simuliuojam sandorio pelną iki kito ciklo (demo logika)
                pct = random.uniform(-settings["stop_loss"], settings["take_profit"])
                if signal == "PIRKTI":
                    result = round(balance * (pct / 100), 2)
                else:
                    result = round(-balance * (pct / 100), 2)
                balance += result

                trade_history.insert(0, {
                    "laikas": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "pora": pair,
                    "kryptis": signal,
                    "kaina": price,
                    "pelnas": result,
                    "procentai": round(pct, 2),
                    "balansas": round(balance, 2)
                })
                if len(trade_history) > 200:
                    trade_history.pop()
                time.sleep(0.2)  # demo greitis

            # Laukti iki kito ciklo
            time.sleep(int(settings["interval"]) * 60 * 60)
        else:
            time.sleep(2)

@app.route("/", methods=["GET", "POST"])
def index():
    global settings
    if request.method == "POST":
        # Atnaujinti nustatymus iš panelės
        try:
            settings["interval"] = int(request.form.get("interval", 8))
            settings["n_pairs"] = int(request.form.get("n_pairs", 50))
        except Exception as e:
            pass
        return redirect(url_for("index"))
    # Sugeneruoti balanso grafikui
    graph = [float(t["balansas"]) for t in reversed(trade_history[-100:])]
    times = [t["laikas"] for t in reversed(trade_history[-100:])]
    return render_template(
        "index.html",
        trade_history=trade_history,
        demo_balance=round(balance, 2),
        settings=settings,
        bot_status="Veikia" if bot_running else "Stabdyta",
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

@app.route("/refresh")
def refresh():
    return redirect(url_for("index"))

if __name__ == "__main__":
    t = threading.Thread(target=ai_demo_bot)
    t.daemon = True
    t.start()
    app.run(host="0.0.0.0", port=8000)
