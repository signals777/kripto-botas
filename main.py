# -*- coding: utf-8 -*-
import os
import time
import datetime
import numpy as np
import pandas as pd
import csv
from pybit.unified_trading import HTTP
from sklearn.linear_model import LogisticRegression

# BYBIT API RAKTAI
api_key = "6jW8juUDFLe1ykvL3L"
api_secret = "3UH1avHKHWWyMCmU26RMxh784TGSA8lurzST"

# STRATEGIJOS PARAMETRAI
MAX_OPEN_POSITIONS = 3
TRIGGER_PNL = 0.02  # +2% pelno
TRAILING_DISTANCE = 0.015  # -1.5% nuo piko
TP_TARGET = 0.03  # +3%
SL_DEFAULT = 0.01  # -1%
LEVERAGE = 5
RISK_PERCENT = 1  # 1% balanso

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

def get_klines(symbol, interval="240", limit=150):
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

def fetch_top_symbols(limit=30):
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
        session.set_leverage(category="linear", symbol=symbol, buyLeverage=LEVERAGE, sellLeverage=LEVERAGE)
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

def log_trade(symbol, direction, qty, entry_price, exit_price, pnl, reason):
    filename = "trade_log.csv"
    file_exists = os.path.isfile(filename)
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    with open(filename, mode='a', newline='') as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(["Time", "Symbol", "Direction", "Qty", "Entry", "Exit", "PnL (%)", "Reason"])
        writer.writerow([now, symbol, direction, qty, entry_price, exit_price, f"{pnl*100:.2f}", reason])

def calculate_qty_with_risk(symbol, entry_price, stop_price, risk_percent=1, leverage=5):
    balance = get_balance()
    if balance <= 0:
        print("⚠️ Balansas lygus nuliui")
        return 0, 0
    risk_usdt = balance * (risk_percent / 100)
    sl_distance = abs(entry_price - stop_price)
    if sl_distance == 0:
        print("⚠️ SL atstumas 0")
        return 0, 0
    position_usdt = risk_usdt / (sl_distance / entry_price)
    max_position = balance * leverage
    position_usdt = min(position_usdt, max_position)
    min_qty, qty_step, _ = get_symbol_info(symbol)
    qty = round_qty(position_usdt / entry_price, qty_step)
    if qty < min_qty:
        print(f"⚠️ {symbol}: qty {qty} mažesnis nei min {min_qty}")
        return 0, 0
    return qty, position_usdt

def train_ai(df):
    X, y = [], []
    for i in range(6, len(df)-1):
        changes = list((df['close'].iloc[i-5:i].pct_change().fillna(0))*100)
        vol = df['volume'].iloc[i]
        feat = changes + [vol]
        label = int((df['close'].iloc[i+1] - df['close'].iloc[i]) / df['close'].iloc[i] < -0.004)
        X.append(feat)
        y.append(label)
    if len(set(y)) < 2:
        print("⚠️ AI mokymo duomenyse per mažai įvairovės (viena klasė), AI ignoruojamas.")
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
        proba = model.predict_proba([feat])[0][1]
        return proba > 0.8
    except:
        return True

def trading_loop_cycle():
    print("🚀 Profesionalus breakout+AI+trailing botas paleistas")
    opened = {}

    while True:
        try:
            now = datetime.datetime.utcnow()

            # Patikrinam aktyvias pozicijas
            for symbol in list(opened):
                data = opened[symbol]
                price = get_last_prices([symbol]).get(symbol)
                if not price:
                    continue
                entry = data['entry_price']
                qty = data['qty']
                peak = data['peak_price']
                pnl = (entry - price) / entry
                peak = min(price, peak)
                opened[symbol]['peak_price'] = peak
                if pnl >= TRIGGER_PNL and price >= peak * (1 + TRAILING_DISTANCE):
                    print(f"🔻 {symbol} Trailing SL hit. PnL: {pnl:.2%}")
                    close_position(symbol, qty)
                    log_trade(symbol, "short", qty, entry, price, pnl, "Trailing SL")
                    del opened[symbol]
                    continue
                if price <= entry * (1 - TP_TARGET):
                    print(f"🎯 {symbol} TP hit! PnL: {pnl:.2%}")
                    close_position(symbol, qty)
                    log_trade(symbol, "short", qty, entry, price, pnl, "TP")
                    del opened[symbol]
                    continue
                if price >= entry * (1 + SL_DEFAULT):
                    print(f"🛑 {symbol} SL hit! PnL: {pnl:.2%}")
                    close_position(symbol, qty)
                    log_trade(symbol, "short", qty, entry, price, pnl, "SL")
                    del opened[symbol]
                    continue

            # Ieškom naujų signalų
            if len(opened) < MAX_OPEN_POSITIONS:
                symbols = fetch_top_symbols(limit=30)
                print(f"\n[{now.strftime('%H:%M:%S')}] Tikrinamos poros: {symbols}")
                for sym in symbols:
                    if sym in opened:
                        continue
                    df = get_klines(sym, interval="240")
                    if df.empty or len(df) < 15:
                        continue
                    df['min10'] = df['low'].rolling(10).min()
                    last = df.iloc[-1]
                    prev = df.iloc[-2]
                    drop = (last['close'] - prev['close']) / prev['close'] * 100
                    breakout = last['close'] < last['min10']
                    vol_spike = last['volume'] > df['volume'].mean() * 1.5
                    model = train_ai(df)
                    ai = ai_decision(df, model)
                    print(f"{sym}: kritimas={drop:.2f}%, breakout={breakout}, vol_spike={vol_spike}, AI={ai}")
                    if drop <= -0.4 and breakout and vol_spike and ai:
                        entry_price = last['close']
                        stop_price = entry_price * (1 + SL_DEFAULT)
                        qty, _ = calculate_qty_with_risk(sym, entry_price, stop_price)
                        if qty > 0:
                            entry = open_position(sym, qty)
                            if entry:
                                opened[sym] = {
                                    'entry_time': now,
                                    'qty': qty,
                                    'entry_price': entry,
                                    'peak_price': entry,
                                    'direction': 'short'
                                }
                                if len(opened) >= MAX_OPEN_POSITIONS:
                                    break
            time.sleep(3600)
        except Exception as e:
            print(f"❌ Loop klaida: {e}")
            time.sleep(10)

if __name__ == "__main__":
    trading_loop_cycle()
