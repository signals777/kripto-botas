import os
import time
import datetime
import numpy as np
import pandas as pd
from pybit.unified_trading import HTTP
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator

# Bybit API raktai
api_key = "8BF7HTSnuLzRIhfLaI"
api_secret = "wL68dHNUyNqLFkUaRsSFX6vBxzeAQc3uHVxG"

# Prisijungimas prie Bybit
def get_session_api():
    return HTTP(api_key=api_key, api_secret=api_secret)

# Gauk žvakes
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

# TA filtrai
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

# Gauk top poras pagal apimtį ir 1h pokytį
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

# Apskaičiuok pozicijos kiekį
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

# Atidaryk poziciją
def open_position(symbol, qty):
    session = get_session_api()
    try:
        try:
            session.set_leverage(category="linear", symbol=symbol, buyLeverage=5, sellLeverage=5)
        except Exception as lev_err:
            print(f"⚠️ Sverto klaida {symbol}: {lev_err}")
        order = session.place_order(
            category="linear",
            symbol=symbol,
            side="Buy",
            orderType="Market",
            qty=qty,
            timeInForce="GoodTillCancel"
        )
        # Gaunam atidarymo kainą po užsakymo
        entry_price = float(order['result']['avgPrice']) if order.get('result', {}).get('avgPrice') else None
        print(f"✅ BUY: {symbol} kiekis: {qty} kaina: {entry_price}")
        return entry_price
    except Exception as e:
        print(f"❌ Orderio klaida {symbol}: {e}")
        return None

# Uždaryk poziciją
def close_position(symbol, qty):
    session = get_session_api()
    try:
        session.place_order(
            category="linear",
            symbol=symbol,
            side="Sell",
            orderType="Market",
            qty=qty,
            timeInForce="GoodTillCancel",
            reduceOnly=True
        )
        print(f"🔻 SELL: {symbol} kiekis: {qty}")
    except Exception as e:
        print(f"❌ Uždarymo klaida {symbol}: {e}")

# Gauk paskutinę kainą
def get_last_price(symbol):
    session = get_session_api()
    try:
        tickers = session.get_tickers(category="linear")['result']['list']
        price = next((float(t['lastPrice']) for t in tickers if t['symbol'] == symbol), None)
        return price
    except Exception as e:
        print(f"❌ Kainos gavimo klaida {symbol}: {e}")
        return None

# --- Pagrindinis ciklas su SL, TP, Trailing ---
def trading_loop():
    print("🚀 Botas paleistas!")
    # opened_positions: symbol -> (open_time, qty, entry_price, max_price)
    opened_positions = {}

    # Parametrai (galima koreguoti):
    STOP_LOSS_PCT = -1          # -1 %
    TAKE_PROFIT_PCT = 3         # +3 %
    TRAILING_STOP_PCT = 0.8     # 0.8 % nuo max kainos

    while True:
        now = datetime.datetime.utcnow()
        if now.minute == 0 and now.second < 10:
            print(f"\n🕐 Nauja valanda {now.strftime('%H:%M:%S')} – ieškom 4 porų...")

            symbols = fetch_top_symbols()
            selected = []

            for symbol in symbols:
                if symbol in opened_positions:
                    print(f"⏭️ {symbol} jau atidaryta, praleidžiam.")
                    continue
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
                if symbol in opened_positions:
                    print(f"⏭️ {symbol} jau atidaryta, praleidžiam.")
                    continue
                qty = calculate_qty(symbol)
                if qty > 0:
                    entry_price = open_position(symbol, qty)
                    if entry_price:
                        opened_positions[symbol] = (now, qty, entry_price, entry_price)

            time.sleep(60)

        # Patikrinam visus saugiklius
        for symbol in list(opened_positions.keys()):
            open_time, qty, entry_price, max_price = opened_positions[symbol]
            now = datetime.datetime.utcnow()
            last_price = get_last_price(symbol)
            if last_price and entry_price:
                # Skaičiuojam pokytį nuo atidarymo
                price_change = (last_price - entry_price) / entry_price * 100

                # 1. STOP LOSS
                if price_change <= STOP_LOSS_PCT:
                    print(f"🛑 {symbol} kritimas daugiau nei {STOP_LOSS_PCT} % ({price_change:.2f} %), UŽDAROM!")
                    close_position(symbol, qty)
                    del opened_positions[symbol]
                    continue

                # 2. TAKE PROFIT
                if price_change >= TAKE_PROFIT_PCT:
                    print(f"✅ {symbol} pasiektas +{TAKE_PROFIT_PCT} % TP ({price_change:.2f} %), UŽDAROM!")
                    close_position(symbol, qty)
                    del opened_positions[symbol]
                    continue

                # 3. TRAILING STOP
                if last_price > max_price:
                    max_price = last_price  # atnaujinam max_price
                    opened_positions[symbol] = (open_time, qty, entry_price, max_price)

                trailing_change = (last_price - max_price) / max_price * 100
                if max_price > entry_price and trailing_change <= -TRAILING_STOP_PCT:
                    print(f"🚩 {symbol} Trailing stop aktyvuotas ({trailing_change:.2f} % nuo max), UŽDAROM!")
                    close_position(symbol, qty)
                    del opened_positions[symbol]
                    continue

            # 4. Uždarom kaip anksčiau po 1 valandos
            if (now - open_time).seconds >= 3600:
                print(f"⌛ {symbol} pozicijai suėjo 1 valanda, UŽDAROM.")
                close_position(symbol, qty)
                del opened_positions[symbol]

        time.sleep(5)

if __name__ == "__main__":
    print("🚀 Botas paleistas!")
    trading_loop()
