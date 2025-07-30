import os
import time
import datetime
import numpy as np
import pandas as pd
from pybit.unified_trading import HTTP
from sklearn.linear_model import LogisticRegression

# BYBIT API RAKTAI
api_key = "6jW8juUDFLe1ykvL3L"
api_secret = "3UH1avHKHWWyMCmU26RMxh784TGSA8lurzST"

def get_session_api():
    return HTTP(api_key=api_key, api_secret=api_secret)

instruments_info = {}

def get_symbol_info(symbol):
    global instruments_info
    if symbol in instruments_info:
        return instruments_info[symbol]
    session = get_session_api()
    try:
        info = session.get_instruments_info(category="linear", symbol=symbol)
        if "result" in info and info["result"]["list"]:
            item = info["result"]["list"][0]
            min_qty = float(item["lotSizeFilter"]["minOrderQty"])
            qty_step = float(item["lotSizeFilter"]["qtyStep"])
            min_notional = float(item["lotSizeFilter"]["minNotionalValue"])
            instruments_info[symbol] = (min_qty, qty_step, min_notional)
            return min_qty, qty_step, min_notional
    except Exception as e:
        print(f"❌ get_symbol_info klaida {symbol}: {e}")
    return None, None, None

def get_balance():
    session = get_session_api()
    try:
        wallets = session.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]["coin"]
        usdt = next((c for c in wallets if c["coin"] == "USDT"), None)
        return float(usdt["availableToTrade"]) if usdt else 0
    except Exception as e:
        print(f"❌ Balanso klaida: {e}")
        return 0

def get_last_prices(symbols):
    session = get_session_api()
    try:
        tickers = session.get_tickers(category="linear")["result"]["list"]
        return {t['symbol']: float(t['lastPrice']) for t in tickers if t['symbol'] in symbols}
    except Exception as e:
        print(f"❌ Kainos klaida: {e}")
        return {}

def round_qty(qty, qty_step):
    if qty_step == 0:
        return qty
    return round(np.floor(qty / qty_step) * qty_step, int(abs(np.log10(qty_step))))

def calculate_qty(symbol, percent=20):
    session = get_session_api()
    try:
        min_qty, qty_step, min_notional = get_symbol_info(symbol)
        balance = get_balance()
        usdt_amount = balance * percent / 100
        price = next((float(t['lastPrice']) for t in session.get_tickers(category="linear")["result"]["list"] if t["symbol"] == symbol), None)
        if not price: return 0, 0
        qty = round_qty(usdt_amount / price, qty_step)
        if qty < min_qty or qty * price < min_notional:
            print(f"⚠️ Netinkama suma {symbol}: qty={qty}, notional={qty*price:.2f}")
            return 0, 0
        return qty, usdt_amount
    except Exception as e:
        print(f"❌ Qty klaida {symbol}: {e}")
        return 0, 0

def get_klines(symbol, interval="1", limit=150):
    session = get_session_api()
    try:
        response = session.get_kline(category="linear", symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(response["result"]["list"])
        df.columns = ['timestamp','open','high','low','close','volume','turnover']
        df = df.iloc[::-1]
        df['close'] = df['close'].astype(float)
        df['low'] = df['low'].astype(float)
        df['volume'] = df['volume'].astype(float)
        return df
    except Exception as e:
        print(f"❌ Klines klaida {symbol}: {e}")
        return pd.DataFrame()

def fetch_top_symbols(limit=15):
    session = get_session_api()
    try:
        data = session.get_tickers(category="linear")["result"]["list"]
        df = pd.DataFrame(data)
        df['turnover24h'] = df['turnover24h'].astype(float)
        df = df[df['symbol'].str.endswith("USDT")]
        top = df.sort_values("turnover24h", ascending=False).head(limit)
        return top['symbol'].tolist()
    except Exception as e:
        print(f"❌ fetch_top_symbols klaida: {e}")
        return []

def open_position(symbol, qty):
    session = get_session_api()
    try:
        session.set_leverage(category="linear", symbol=symbol, buyLeverage=5, sellLeverage=5)
        order = session.place_order(
            category="linear", symbol=symbol, side="Sell", orderType="Market",
            qty=qty, timeInForce="GoodTillCancel")
        entry = float(order["result"]["avgPrice"]) if "result" in order and order["result"].get("avgPrice") else None
        print(f"🟢 SHORT atidarytas: {symbol}, qty={qty}, kaina={entry}")
        return entry
    except Exception as e:
        print(f"❌ Orderio klaida {symbol}: {e}")
        return None

def close_position(symbol, qty):
    session = get_session_api()
    try:
        session.place_order(
            category="linear", symbol=symbol, side="Buy",
            orderType="Market", qty=qty, reduceOnly=True,
            timeInForce="GoodTillCancel")
        print(f"🔴 SHORT Uždarytas: {symbol}, qty={qty}")
    except Exception as e:
        print(f"❌ Uždarymo klaida {symbol}: {e}")

def train_ai(df):
    X, y = [], []
    for i in range(6, len(df)-1):
        changes = list((df['close'].iloc[i-5:i].pct_change().fillna(0))*100)
        vol = df['volume'].iloc[i]
        feat = changes + [vol]
        label = int((df['close'].iloc[i+1] - df['close'].iloc[i]) / df['close'].iloc[i] < -0.004)
        X.append(feat)
        y.append(label)
    # Naujas saugiklis: jei klasės tik viena, AI tiesiog ignoruojamas, klaidos nėra!
    if len(set(y)) < 2:
        print("⚠️ AI mokymo duomenyse per mažai įvairovės (viena klasė), AI ignoruojamas (praleidžiamas).")
        return None
    model = LogisticRegression()
    model.fit(X, y)
    return model

def ai_decision(df, model):
    try:
        if model is None:
            return True
        changes = list((df['close'].iloc[-6:-1].pct_change().fillna(0))*100)
        vol = df['volume'].iloc[-1]
        feat = changes + [vol]
        return bool(model.predict([feat])[0])
    except:
        return True

def trading_loop():
    print("🚀 Boto paleidimas...")  # dabar tikrai visada rašo paleidimą
    opened = {}
    highest_balance = get_balance()
    cooldown_until = None

    while True:
        now = datetime.datetime.utcnow()

        if cooldown_until and now < cooldown_until:
            print(f"🕒 Botas sustabdytas dėl balanso kritimo iki {cooldown_until.strftime('%H:%M:%S')}")
            time.sleep(10)
            continue

        balance = get_balance()
        if balance > highest_balance:
            highest_balance = balance
        elif balance < highest_balance * 0.995:
            print(f"⚠️ Balansas krito daugiau nei -0.5%. Botas stabdomas 5 min.")
            cooldown_until = now + datetime.timedelta(minutes=5)
            continue

        if not opened:
            symbols = fetch_top_symbols()
            print(f"\n[{now.strftime('%H:%M:%S')}] Tikrinamos poros: {symbols}")
            for sym in symbols:
                df = get_klines(sym)
                if df.empty or len(df) < 15:
                    print(f"⚠️ {sym}: per mažai žvakių.")
                    continue
                df['min10'] = df['low'].rolling(window=10).min()
                last = df.iloc[-1]
                prev = df.iloc[-2]
                drop = (last['close'] - prev['close']) / prev['close'] * 100
                breakout = last['close'] < last['min10']
                volume_spike = last['volume'] > df['volume'].mean() * 1.5
                model = train_ai(df)
                ai = ai_decision(df, model)
                print(f"{sym}: kritimas={drop:.2f}%, breakout={breakout}, vol_spike={volume_spike}, AI={ai}")

                if drop <= -0.4 and breakout and volume_spike and ai:
                    qty, _ = calculate_qty(sym)
                    if qty > 0:
                        entry = open_position(sym, qty)
                        if entry:
                            opened[sym] = (datetime.datetime.utcnow(), qty, entry)
                            break
                    else:
                        print(f"⚠️ {sym}: Kiekis netinkamas.")
        else:
            for sym in list(opened):
                entry_time, qty, entry_price = opened[sym]
                price = get_last_prices([sym]).get(sym, None)
                if price:
                    pnl = (entry_price - price) / entry_price * 100
                    print(f"🔄 {sym}: entry={entry_price:.4f}, now={price:.4f}, PnL={pnl:.2f}%")
                    if pnl >= 0.7 or pnl <= -0.7:
                        print(f"🔔 {sym}: Pozicija uždaroma. PnL: {pnl:.2f}%")
                        close_position(sym, qty)
                        del opened[sym]
        time.sleep(2)

if __name__ == "__main__":
    trading_loop()
