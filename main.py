from flask import Flask, render_template, request, redirect, url_for
from datetime import datetime
import threading
import time
import random

app = Flask(__name__)

# 50 populiariausių kriptovaliutų porų (pavyzdžiai, galima papildyti)
PAIRS = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "XRP/USDT", "SOL/USDT",
    "ADA/USDT", "AVAX/USDT", "DOGE/USDT", "SHIB/USDT", "TRX/USDT",
    "LINK/USDT", "LTC/USDT", "MATIC/USDT", "DOT/USDT", "UNI/USDT",
    "BCH/USDT", "XLM/USDT", "FIL/USDT", "ETC/USDT", "APT/USDT",
    "ICP/USDT", "OP/USDT", "HBAR/USDT", "VET/USDT", "SUI/USDT",
    "GRT/USDT", "AAVE/USDT", "STX/USDT", "MKR/USDT", "EOS/USDT",
    "QNT/USDT", "NEAR/USDT", "IMX/USDT", "ARB/USDT", "ALGO/USDT",
    "SNX/USDT", "RUNE/USDT", "DYDX/USDT", "KAVA/USDT", "SAND/USDT",
    "GALA/USDT", "MANA/USDT", "FTM/USDT", "CHZ/USDT", "CRV/USDT",
    "ENJ/USDT", "1INCH/USDT", "BAT/USDT", "CELO/USDT", "LRC/USDT"
]

bot_running = False
bot_thread = None

# Demo sandorių istorija ir nustatymai
trade_history = []
balance = 500.0  # Pradinis demo balansas
settings = {"take_profit": 2.0, "stop_loss": 1.5, "interval": 8}

def demo_trade_bot():
    global bot_running, balance
    while bot_running:
        for pair in PAIRS:
            # DEMO: "atsitiktinis" pelnas/nuostolis
            direction = random.choice(["PIRKTI", "PARDUOTI"])
            price = round(random.uniform(0.5, 2.5), 3)
            result_pct = random.uniform(-settings["stop_loss"], settings["take_profit"])
            result = round(balance * (result_pct / 100), 2)
            balance += result
            trade_history.append({
                "pora": pair,
                "kryptis": direction,
                "kaina": price,
                "pelnas": result,
                "balansas": round(balance, 2),
                "procentai": round(result_pct, 2)
                "laikas": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            
            time.sleep(0.1)  # Demo greitis, realiai intervalas ilgesnis
        time.sleep(settings["interval"] * 60 * 60)  # intervalas valandomis

@app.route("/", methods=["GET", "POST"])
def index():
    global bot_running
    msg = ""
    if request.method == "POST":
        if "start" in request.form:
            if not bot_running:
                start_bot()
                msg = "Botas paleistas!"
            else:
                msg = "Botas jau veikia."
        elif "stop" in request.form:
            stop_bot()
            msg = "Botas sustabdytas!"
        elif "update" in request.form:
            try:
                tp = float(request.form.get("take_profit", 2.0))
                sl = float(request.form.get("stop_loss", 1.5))
                iv = float(request.form.get("interval", 8))
                settings["take_profit"] = tp
                settings["stop_loss"] = sl
                settings["interval"] = iv
                msg = "Nustatymai atnaujinti!"
            except Exception:
                msg = "Klaida atnaujinant nustatymus."
    return render_template("index.html",
                           bot_running=bot_running,
                           balance=balance,
                           trade_history=trade_history[-100:][::-1],
                           settings=settings,
                           msg=msg)

def start_bot():
    global bot_running, bot_thread
    if not bot_running:
        bot_running = True
        bot_thread = threading.Thread(target=demo_trade_bot)
        bot_thread.start()

def stop_bot():
    global bot_running
    bot_running = False

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
