# ✅ Konservatyvi LONG strategija su breakout + volume spike + trailing SL
# Rizika: 5% balanso vienai pozicijai, x5 svertas, max 3 pozicijos

import time
import threading
import pandas as pd
from pybit.unified_trading import HTTP

# 🔐 Tavo BYBIT API raktai
api_key = "6jW8juUDFLe1ykvL3L"
api_secret = "3UH1avHKHWWyMCmU26RMxh784TGSA8lurzST"

def get_session_api():
    return HTTP(api_key=api_key, api_secret=api_secret)

def get_balance():
    try:
        session = get_session_api()
        data = session.get_wallet_balance(accountType="UNIFIED")
        wallet = data['result']['list'][0]['coin']
        usdt = next((c for c in wallet if c['coin'] == 'USDT'), None)
        if usdt:
            balance = float(usdt.get('walletBalance', 0))
            print(f"💰 Rastas USDT balansas: {balance:.2f} USDT")
            return balance
    except Exception as e:
        print(f"❌ Balanso klaida: {e}")
    return 0

def get_price(symbol):
    try:
        session = get_session_api()
        data = session.get_tickers(category="linear")
        price = next((float(i["lastPrice"]) for i in data["result"]["list"] if i["symbol"] == symbol), None)
        return price
    except:
        return None

def get_klines(symbol, interval="240", limit=100):
    try:
        session = get_session_api()
        k = session.get_kline(category="linear", symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(k["result"]["list"], columns=['timestamp','open','high','low','close','volume','turnover'])
        df[['open','high','low','close','volume']] = df[['open','high','low','close','volume']].astype(float)
        return df
    except Exception as e:
        print(f"❌ Klines klaida {symbol}: {e}")
        return pd.DataFrame()

def calculate_qty(symbol, risk_percent=5):
    try:
        price = get_price(symbol)
        balance = get_balance()
        usdt_amount = balance * risk_percent / 100
        qty = (usdt_amount * 5) / price
        print(f"🧮 {symbol}: kaina={price}, balansas={balance}, kiekis={qty}")
        return round(qty, 3)
    except Exception as e:
        print(f"❌ Qty klaida: {e}")
        return 0

def open_long(symbol, qty):
    try:
        session = get_session_api()
        session.set_leverage(category="linear", symbol=symbol, buyLeverage=5, sellLeverage=5)
        order = session.place_order(category="linear", symbol=symbol, side="Buy", orderType="Market", qty=qty)
        entry = float(order["result"]["avgPrice"])
        print(f"🟢 LONG atidarytas: {symbol}, qty={qty}, entry={entry}")
        return entry
    except Exception as e:
        print(f"❌ Orderio klaida: {e}")
        return None

def close_long(symbol, qty):
    try:
        session = get_session_api()
        session.place_order(category="linear", symbol=symbol, side="Sell", orderType="Market", qty=qty, reduceOnly=True)
        print(f"🔴 LONG uždarytas: {symbol}, qty={qty}")
    except Exception as e:
        print(f"❌ Uždarymo klaida: {e}")

def progressive_risk_guard(symbol, entry, qty, get_price_fn):
    peak = entry
    drawdown = 0
    active = False
    while True:
        price = get_price_fn(symbol)
        if not price:
            time.sleep(10)
            continue
        if price > peak:
            peak = price
            drawdown = 0
        else:
            decline = (peak - price) / peak * 100
            drawdown += decline
            if drawdown >= 1:
                print(f"🔻 {symbol} pasiekė -1% nuo piko: uždaroma pozicija (PnL={(price-entry)/entry*100:.2f}%)")
                close_long(symbol, qty)
                break
        time.sleep(60)

def analyze_symbol(symbol):
    df = get_klines(symbol)
    if df.empty or len(df) < 20:
        print(f"⚠️ {symbol}: per mažai žvakių.")
        return False, None

    last = df.iloc[-1]
    prev_highs = df['close'].rolling(5).max()
    breakout = last['close'] > prev_highs.iloc[-2]
    vol_spike = last['volume'] > df['volume'].mean() * 1.2
    green = last['close'] > last['open']

    print(f"{symbol}: green={green}, breakout={breakout}, vol_spike={vol_spike}")
    
    if not green:
        print(f"⛔ {symbol} atmetama – žvakė raudona (green=False)")
        return False, None
    if not breakout:
        print(f"⛔ {symbol} atmetama – breakout=False")
        return False, None
    if not vol_spike:
        print(f"⛔ {symbol} atmetama – vol_spike=False")
        return False, None
    return True, df

def fetch_symbols(limit=30):
    try:
        session = get_session_api()
        data = session.get_tickers(category="linear")["result"]["list"]
        df = pd.DataFrame(data)
        df = df[df["symbol"].str.endswith("USDT")]
        df["turnover24h"] = df["turnover24h"].astype(float)
        return df.sort_values("turnover24h", ascending=False).head(limit)["symbol"].tolist()
    except Exception as e:
        print(f"❌ fetch_symbols klaida: {e}")
        return []

def trading_loop():
    opened = {}
    while True:
        print("\n🔄 Prasideda porų analizė")
        if len(opened) < 3:
            symbols = fetch_symbols()
            print(f"🟡 Tikrinamos poros: {symbols}")
            for sym in symbols:
                if sym in opened:
                    continue
                valid, df = analyze_symbol(sym)
                if not valid:
                    continue
                qty = calculate_qty(sym)
                if qty <= 0:
                    print(f"⚠️ {sym} atmetama – nepakanka balanso arba netinkamas kiekis (qty={qty})")
                    continue
                entry = open_long(sym, qty)
                if entry:
                    opened[sym] = (entry, qty)
                    threading.Thread(target=progressive_risk_guard, args=(sym, entry, qty, get_price), daemon=True).start()
                    if len(opened) >= 3:
                        break
        time.sleep(3600)

if __name__ == "__main__":
    trading_loop()
