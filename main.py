import time
import numpy as np
from datetime import datetime
from pybit.unified_trading import HTTP

API_KEY = "6jW8juUDFLe1ykvL3L"
API_SECRET = "3UH1avHKHWWyMCmU26RMxh784TGSA8lurzST"

session = HTTP(api_key=API_KEY, api_secret=API_SECRET)

LEVERAGE = 5
RISK_PERCENT = 0.05
SYMBOL_LIMIT = 30

def log(msg):
    print(msg)

def get_top_symbols_by_volume():
    try:
        tickers = session.get_tickers(category="linear")["result"]["list"]
        symbols = []
        for item in tickers:
            symbol = item["symbol"]
            if (
                symbol.endswith("USDT")
                and "1000" not in symbol
                and "10000" not in symbol
                and float(item["turnover24h"]) > 1000000
            ):
                symbols.append((symbol, float(item["turnover24h"])))
        symbols.sort(key=lambda x: x[1], reverse=True)
        top_symbols = [s[0] for s in symbols[:SYMBOL_LIMIT]]
        log(f"\n📈 Atrinkta {len(top_symbols)} TOP porų pagal 24h tūrį")
        return top_symbols
    except Exception as e:
        log(f"❌ Klaida gaunant TOP poras pagal tūrį: {e}")
        return []

def get_wallet_balance():
    try:
        balance = session.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]["coin"]
        usdt = next(c for c in balance if c["coin"] == "USDT")
        return float(usdt["walletBalance"])
    except Exception as e:
        log(f"❌ Klaida gaunant balansą: {e}")
        return 0

def calculate_qty(symbol, entry_price, balance):
    risk_amount = balance * RISK_PERCENT
    loss_per_unit = entry_price * 0.015
    qty = (risk_amount * LEVERAGE) / loss_per_unit
    try:
        info = session.get_instruments_info(category="linear", symbol=symbol)["result"]["list"][0]
        qty_step = float(info["lotSizeFilter"]["qtyStep"])
        min_qty = float(info["lotSizeFilter"]["minOrderQty"])
        qty = np.floor(qty / qty_step) * qty_step
        if qty < min_qty:
            return 0, f"{symbol}: kiekis per mažas ({qty} < {min_qty})"
        return round(qty, 6), None
    except Exception as e:
        return 0, f"{symbol}: klaida gaunant kiekio info: {e}"

def progressive_risk_guard(symbol, entry_price):
    peak = entry_price
    while True:
        time.sleep(15)
        try:
            price = float(session.get_tickers(category="linear", symbol=symbol)["result"]["list"][0]["lastPrice"])
            if price > peak:
                peak = price
            drawdown = (price - peak) / peak
            log(f"📉 {symbol}: kaina={price:.4f}, pikas={peak:.4f}, kritimas={drawdown:.2%}")
            if drawdown <= -0.015:
                log(f"❌ {symbol}: -1.5% nuo piko – pozicija uždaroma")
                session.place_order(category="linear", symbol=symbol, side="Sell", orderType="Market", qty=open_positions[symbol])
                del open_positions[symbol]
                break
        except Exception as e:
            log(f"⚠️ Klaida stebint {symbol}: {e}")

open_positions = {}

def analyze_and_trade():
    log("\n" + "="*60)
    log(f"🕒 Analizės pradžia: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")

    symbols = get_top_symbols_by_volume()
    log(f"\n🔄 Prasideda porų analizė – tikrinamos {len(symbols)} poros")
    balance = get_wallet_balance()
    log(f"💰 Balansas: {balance:.2f} USDT")

    opened = 0
    for symbol in symbols:
        time.sleep(0.2)
        try:
            price = float(session.get_tickers(category="linear", symbol=symbol)["result"]["list"][0]["lastPrice"])
            qty, err = calculate_qty(symbol, price, balance)
            if err:
                log(f"⚠️ {err}")
                continue
            session.set_leverage(category="linear", symbol=symbol, buyLeverage=LEVERAGE, sellLeverage=LEVERAGE)
            session.place_order(category="linear", symbol=symbol, side="Buy", orderType="Market", qty=qty)
            log(f"✅ Atidaryta pozicija: {symbol}, kiekis={qty}, kaina={price}")
            open_positions[symbol] = qty
            opened += 1
            progressive_risk_guard(symbol, price)
            if opened >= 3:
                break
        except Exception as e:
            log(f"❌ Orderio klaida: {e}")

    log(f"\n📊 Atidaryta pozicijų: {opened}")

def trading_loop():
    while True:
        analyze_and_trade()
        log("\n💤 Miegama 1800 sekundžių (30 min)...\n")
        time.sleep(1800)

if __name__ == "__main__":
    trading_loop()
