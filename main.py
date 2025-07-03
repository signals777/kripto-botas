import requests
from flask import Flask, render_template
from datetime import datetime
import threading
import time
import random

app = Flask(__name__)

# Tavo valiutų poros
PAIRS = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "AVAX/USDT", "DOGE/USDT", "LINK/USDT", "LTC/USDT", "MATIC/USDT",
    "BCH/USDT", "XLM/USDT", "FIL/USDT", "ICP/USDT", "OP/USDT", "HBAR/USDT", "VET/USDT", "GRT/USDT", "AAVE/USDT", "STX/USDT",
    "QNT/USDT", "NEAR/USDT", "IMX/USDT", "SNX/USDT", "RUNE/USDT", "DYDX/USDT", "GALA/USDT", "MANA/USDT", "FTM/USDT", "ENJ/USDT",
    "1INCH/USDT", "BAT/USDT", "CRV/USDT", "CHZ/USDT", "CELO/USDT", "LRC/USDT", "SAND/USDT", "KAVA/USDT", "ALGO/USDT", "ARB/USDT",
    "EOS/USDT", "MKR/USDT", "UNI/USDT", "DOT/USDT", "SHIB/USDT", "SOL/USDT", "XTZ/USDT", "ALN/USDT", "MNT/USDT", "XAUT/USDT"
]

# Automatinė konversija į Binance formatą (be "/")
BINANCE_PAIRS = [p.replace("/", "") for p in PAIRS]

trade_history = []
balance = 500.0  # Pradinis balansas
settings = {
    "take_profit": 2.0,   # Max. pelnas (procentais) sandoriui demo
    "stop_loss": 1.5,     # Max. nuostolis (procentais) sandoriui demo
    "interval": 4.0       # Simuliuojamas sandorio intervalas (valandomis)
}

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
    global balance
    while True:
        for i, pair in enumerate(PAIRS):
            symbol = BINANCE_PAIRS[i]
            price = get_binance_price(symbol)
            if price is None:
                continue  # Praleisti jei negauta kaina

            direction = random.choice(["PIRKTI", "PARDUOTI"])
            # Demo: pelnas/nuostolis generuojamas pagal intervalą
            result_pct = random.uniform(-settings["stop_loss"], settings["take_profit"])
            result = round(balance * (result_pct / 100), 2)
            balance += result

            trade_history.insert(0, {
                "laikas": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "pora": pair,
                "kryptis": direction,
                "kaina": price,
                "pelnas": result,
                "procentai": round(result_pct, 2),
                "balansas": round(balance, 2)
            })
            # Tik paskutiniai 100 įrašų
            if len(trade_history) > 100:
                trade_history.pop()
            time.sleep(1)  # Demo: 1 sek. tarp porų

        # Po visų porų, laukiam intervalą (tarkim, 4 val.)
        time.sleep(settings["interval"] * 60 * 60)

@app.route("/")
def index():
    return render_template("index.html",
        trade_history=trade_history,
        demo_balance=balance,
        settings=settings,
        bot_status="VEIKIA"
    )

if __name__ == "__main__":
    t = threading.Thread(target=demo_trade_bot)
    t.daemon = True
    t.start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
