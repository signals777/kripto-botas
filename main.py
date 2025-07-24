import os
import time
import datetime
import threading
import numpy as np
import pandas as pd
from pybit.unified_trading import HTTP
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator

# ✅ Bybit API raktai
api_key = "b2tL6abuyH7gEQjIC1"
api_secret = "azEVdZmiRBlHID75zQehXHYYYKw0jB8DDFPJ"

# ✅ Prisijungimas prie Bybit
def get_session_api():
    return HTTP(api_key=api_key, api_secret=api_secret)

# ✅ Gauk žvakes
def get_klines(symbol, interval="60", limit=200):
    session = get_session_api()
    try:
        response = session.get_kline(
            category="linear",
            symbol=symbol,
            interval=interval,
            limit=limit
        )
        df = pd.DataFrame(response['result']['list'])
        df.columns = ['timestamp','open','high','low','close','volume','turnover']
        df = df.iloc[::-1]
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        return df
    except Exception as e:
        print(f"❌ Klaida get_klines({symbol}): {e}")
        return pd.DataFrame()

# ✅ TA filtrai
def apply_filters(df):
    try:
        ema = EMAIndicator(df['close'], window=20).ema_indicator()
        rsi = RSIIndicator(df['close'], window=14).rsi()
        df['ema'] = ema
        df['rsi'] = rsi
        return df
    except Exception as e:
        print(f"❌ TA filtrų klaida: {e}")
        return df

# ✅ Gauk top poras pagal apimtį ir 1h pokytį
def fetch_top_symbols(limit=75):
    session = get_session_api()
    try:
        tickers = session.get_tickers(category="linear")['result']['list']
        df = pd.DataFrame(tickers)
        df['volume24h'] = df['turnover24h'].astype(float)
        df['priceChange'] = df['price24hPcnt'].astype(float) * 100
        df = df[df['symbol'].str.endswith("USDT")]
        df = df[df['symbol'].str.isalpha()]
        top = df.sort_values("volume24h", ascending=False).head(limit)
        return top['symbol'].tolist()
    except Exception as e:
        print(f"❌ Klaida fetch_top_symbols: {e}")
        return []

# ✅ Apskaičiuok pozicijos kiekį
def calculate_qty(symbol, usdt_amount=20):
    session = get_session_api()
    try:
        tickers = session.get_tickers(category="linear")['result']['list']
        price = next((float(t['lastPrice']) for t in tickers if t['symbol'] == symbol), None)
        if not price:
            return 0
        qty = round(usdt_amount / price, 3)
        return qty
    except Exception as e:
        print(f"❌ Qty klaida {symbol}: {e}")
        return 0

# ✅ Atidaryk poziciją
def open_position(symbol, qty):
    session = get_session_api()
    try:
        # Svertas
        try:
            session.set_leverage(category="linear", symbol=symbol, buyLeverage=5, sellLeverage=5)
        except Exception as lev_err:
            print(f"⚠️ Sverto klaida {symbol}: {lev_err}")

        # Pirkti
        order = session.place_order(
            category="linear",
            symbol=symbol,
            side="Buy",
            orderType="Market",
            qty=qty,
            timeInForce="GoodTillCancel"
        )
        print(f"✅ BUY: {symbol} kiekis: {qty}")
        return order
    except Exception as e:
        print(f"❌ Orderio klaida {symbol}: {e}")
        return None

# ✅ Uždaryk poziciją
def close_position(symbol):
    session = get_session_api()
    try:
        qty = calculate_qty(symbol)
        session.place_order(
            category="linear",
            symbol=symbol,
            side="Sell",
            orderType="Market",
            qty=qty,
            timeInForce="GoodTillCancel",
            reduceOnly=True
        )
        print(f"🔻 SELL: {symbol}")
    except Exception as e:
        print(f"❌ Uždarymo klaida {symbol}: {e}")

# ✅ Pagrindinis boto ciklas
def trading_loop():
    print("🚀 Botas paleistas!")
    opened_positions = {}
    while True:
        now = datetime.datetime.utcnow()
        if now.minute == 0 and now.second < 10:
            print(f"\n🕐 Nauja valanda {now.strftime('%H:%M:%S')} – ieškom 4 porų...")

            symbols = fetch_top_symbols()
            selected = []

            for symbol in symbols:
                df = get_klines(symbol)
                if df.empty:
                    continue
                df = apply_filters(df)
                if df.empty:
                    continue

                last = df.iloc[-1]
                score = 0
                if last['rsi'] < 30:
                    score += 1
                if last['close'] > last['ema']:
                    score += 1
                if score >= 2:
                    selected.append((symbol, score))

            selected = sorted(selected, key=lambda x: x[1], reverse=True)[:4]

            for symbol, score in selected:
                qty = calculate_qty(symbol)
                if qty > 0:
                    open_position(symbol, qty)
                    opened_positions[symbol] = now

            time.sleep(60)  # palaukti 1 minutę kad išvengtų dubliavimo

        # ✅ Patikrinti ar praėjo 1 valanda ir uždaryti pozicijas
        for symbol, open_time in list(opened_positions.items()):
            if (datetime.datetime.utcnow() - open_time).seconds >= 3600:
                close_position(symbol)
                del opened_positions[symbol]

        time.sleep(5)

# ✅ Automatinis paleidimas
if __name__ == "__main__":
    print("🚀 Botas paleistas!")
    trading_loop()
