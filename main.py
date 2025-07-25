import os
import time
import datetime
import numpy as np
import pandas as pd
from pybit.unified_trading import HTTP
from ta.trend import EMAIndicator

api_key = "8BF7HTSnuLzRIhfLaI"
api_secret = "wL68dHNUyNqLFkUaRsSFX6vBxzeAQc3uHVxG"

def get_session_api():
    return HTTP(api_key=api_key, api_secret=api_secret)

def get_balance():
    session = get_session_api()
    try:
        wallets = session.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]["coin"]
        usdt = next((c for c in wallets if c["coin"] == "USDT"), None)
        if usdt:
            # Tikrinam visus galimus laukus, grąžinam pirmą rastą (tinka ir walletBalance!)
            for key in ["availableToTrade", "availableBalance", "walletBalance", "equity"]:
                if key in usdt and usdt[key] is not None:
                    return float(usdt[key])
            return 0.0
        else:
            return 0.0
    except Exception as e:
        print(f"❌ Balanso gavimo klaida: {e}")
        return 0.0

def calculate_qty(symbol, percent=8):
    session = get_session_api()
    try:
        balance = get_balance()
        usdt_amount = balance * percent / 100
        tickers = session.get_tickers(category="linear")['result']['list']
        price = next((float(t['lastPrice']) for t in tickers if t['symbol'] == symbol), None)
        if not price:
            return 0, 0
        qty = round(usdt_amount / price, 3)
        return qty, usdt_amount
    except Exception as e:
        print(f"❌ Qty klaida {symbol}: {e}")
        return 0, 0

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

def apply_ema(df):
    try:
        ema = EMAIndicator(df['close'], window=20).ema_indicator()
        df['ema'] = ema
        return df
    except Exception as e:
        print(f"❌ EMA klaida: {e}")
        return df

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
        return top['symbol'].tolist(), top['symbol'].tolist()[:10]  # 75 ir top10
    except Exception as e:
        print(f"❌ Klaida fetch_top_symbols: {e}")
        return [], []

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
        entry_price = float(order['result']['avgPrice']) if order.get('result', {}).get('avgPrice') else None
        print(f"✅ BUY: {symbol} kiekis: {qty} kaina: {entry_price}")
        return entry_price
    except Exception as e:
        print(f"❌ Orderio klaida {symbol}: {e}")
        return None

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

def get_last_prices(symbols):
    session = get_session_api()
    try:
        tickers = session.get_tickers(category="linear")['result']['list']
        prices = {t['symbol']: float(t['lastPrice']) for t in tickers if t['symbol'] in symbols}
        return prices
    except Exception as e:
        print(f"❌ Kainų gavimo klaida: {e}")
        return {}

def trading_loop():
    print("🚀 Botas paleistas!")
    opened_positions = {}

    STOP_LOSS_PCT = -1     # -1 % nuo atidarymo
    TRAILING_FROM_MAX = -1 # -1 % nuo max (progresyvus trailing)
    BALANCE_LIMIT_PCT = 40
    POSITION_PCT = 8       # 8 % balanso vienai pozicijai
    MAX_POSITIONS = 5

    while True:
        now = datetime.datetime.utcnow()
        if now.minute == 0 and now.second < 10:
            print(f"\n🕐 Nauja valanda {now.strftime('%H:%M:%S')} – ieškom pozicijų...")

            symbols, lyderiai = fetch_top_symbols()
            selected = []

            for symbol in symbols:   # Eina per VISAS 75 poras!
                if symbol in opened_positions:
                    continue
                df = get_klines(symbol)
                time.sleep(10)   # <-- API RATE LIMIT APSAUGA (10 s per porą)
                if df.empty:
                    continue
                df = apply_ema(df)
                if df.empty:
                    continue
                last = df.iloc[-1]
                open1h = df.iloc[-2]['close']
                price_now = last['close']
                price_change_1h = (price_now - open1h) / open1h * 100
                ema20 = last['ema']
                volume_leader = symbol in lyderiai

                score = 0
                if price_change_1h >= 1.5:
                    score += 1
                if price_now > ema20:
                    score += 1
                if volume_leader:
                    score += 1

                if score >= 2:
                    selected.append((symbol, score, price_change_1h, price_now, ema20, volume_leader))

            selected = sorted(selected, key=lambda x: (x[1], x[2]), reverse=True)[:MAX_POSITIONS]

            balance = get_balance()
            used_balance = 0
            count_opened = 0

            for symbol, score, price_change_1h, price_now, ema20, volume_leader in selected:
                if symbol in opened_positions:
                    continue
                qty, usdt_amount = calculate_qty(symbol, percent=POSITION_PCT)
                if qty > 0 and (used_balance + usdt_amount) <= (balance * BALANCE_LIMIT_PCT / 100) and count_opened < MAX_POSITIONS:
                    entry_price = open_position(symbol, qty)
                    if entry_price:
                        opened_positions[symbol] = (now, qty, entry_price, entry_price)
                        used_balance += usdt_amount
                        count_opened += 1

            time.sleep(60)

        open_symbols = list(opened_positions.keys())
        last_prices = get_last_prices(open_symbols) if open_symbols else {}

        for symbol in open_symbols:
            open_time, qty, entry_price, max_price = opened_positions[symbol]
            now = datetime.datetime.utcnow()
            last_price = last_prices.get(symbol, None)
            if last_price and entry_price:
                price_change = (last_price - entry_price) / entry_price * 100

                # 1. STOP LOSS nuo atidarymo kainos
                if price_change <= STOP_LOSS_PCT:
                    print(f"🛑 {symbol} kritimas daugiau nei {STOP_LOSS_PCT} % nuo atidarymo ({price_change:.2f} %), UŽDAROM!")
                    close_position(symbol, qty)
                    del opened_positions[symbol]
                    continue

                # 2. Progresyvus trailing stop nuo max pelno
                if last_price > max_price:
                    max_price = last_price
                    opened_positions[symbol] = (open_time, qty, entry_price, max_price)
                trailing_from_max = (last_price - max_price) / max_price * 100
                if max_price > entry_price and trailing_from_max <= TRAILING_FROM_MAX:
                    print(f"🚩 {symbol} kritimas nuo max virš 1 %, UŽDAROM!")
                    close_position(symbol, qty)
                    del opened_positions[symbol]
                    continue

            # 3. Uždarom po 1 valandos nepriklausomai nuo pelno/nuostolio
            if (now - open_time).seconds >= 3600:
                print(f"⌛ {symbol} pozicijai suėjo 1 valanda, UŽDAROM.")
                close_position(symbol, qty)
                del opened_positions[symbol]

        time.sleep(10)

if __name__ == "__main__":
    print("🚀 Botas paleistas!")
    trading_loop()
