import requests
from flask import Flask, render_template, redirect, url_for
from datetime import datetime
import threading
import time
import random

app = Flask(__name__)

# 50 kripto valiutų porų
PAIRS = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "ADA/USDT", "XRP/USDT",
    "DOGE/USDT", "TON/USDT", "TRX/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
    "MATIC/USDT", "WBTC/USDT", "SHIB/USDT", "LTC/USDT", "BCH/USDT", "ICP/USDT",
    "NEAR/USDT", "UNI/USDT", "DAI/USDT", "STETH/USDT", "APT/USDT", "FIL/USDT",
    "PEPE/USDT", "RNDR/USDT", "ETC/USDT", "OKB/USDT", "TAO/USDT", "FDUSD/USDT",
    "LEO/USDT", "TIA/USDT", "CRO/USDT", "IMX/USDT", "INJ/USDT", "STX/USDT",
    "ARB/USDT", "MKR/USDT", "OP/USDT", "VET/USDT", "SUI/USDT", "GRT/USDT",
    "LDO/USDT", "QNT/USDT", "AAVE/USDT", "THETA/USDT", "XLM/USDT", "FLOW/USDT",
    "AXS/USDT", "SNX/USDT"
]

BINANCE_PAIRS = [p.replace("/", "") for p in PAIRS]

trade_history = []
balance = 500.0

settings = {
    "take_profit": 2.0,    # TP %
    "stop_loss": 1.5,      # SL %
    "interval": 8.0        # kas kiek valandų ciklas (8 val)
}

bot_running = True  # start/stop

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
            for i, pair in enumerate(PAIRS):
                symbol = BINANCE_PAIRS[i]
                price = get_binance_price(symbol)
                if price is None:
                    continue

                direction = random.choice(["PIRKTI", "PARDUOTI"])
                # Pelnas random, bet realios ribos pagal TP/SL
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
                time.sleep(0.5)  # demo greitis, kad panelėje būtų gyvumo

            # po visų porų laukti iki kito ciklo (pvz. 8 val. realybėj)
            time.sleep(settings["interval"] * 60 * 60)
        else:
            time.sleep(2)

@app.route("/")
def index():
    return render_template(
        "index.html",
        trade_history=trade_history,
        demo_balance=balance,
        settings=settings,
        bot_status="Veikia" if bot_running else "Stabdyta"
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
    # Paprastas atnaujinimas be meta refresh
    return redirect(url_for("index"))

if __name__ == "__main__":
    t = threading.Thread(target=demo_trade_bot)
    t.daemon = True
    t.start()
    app.run(host="0.0.0.0", port=8000)
