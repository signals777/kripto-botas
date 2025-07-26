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
            min_qty = float(item["lotSizeFilter"]["minOrderQty"]) if "lotSizeFilter" in item and "minOrderQty" in item["lotSizeFilter"] else None
            qty_step = float(item["lotSizeFilter"]["qtyStep"]) if "lotSizeFilter" in item and "qtyStep" in item["lotSizeFilter"] else None
            min_notional = float(item["lotSizeFilter"]["minNotionalValue"]) if "lotSizeFilter" in item and "minNotionalValue" in item["lotSizeFilter"] else 5
            max_leverage = int(float(item["leverageFilter"]["maxLeverage"])) if "leverageFilter" in item and "maxLeverage" in item["leverageFilter"] else 1
            instruments_info[symbol] = (min_qty, qty_step, min_notional, max_leverage)
            return min_qty, qty_step, min_notional, max_leverage
        else:
            print(f"⚠️ Nerasta instrumentų info {symbol}")
            instruments_info[symbol] = (None, None, None, 1)
            return None, None, None, 1
    except Exception as e:
        print(f"❌ Klaida get_symbol_info({symbol}): {e}")
        instruments_info[symbol] = (None, None, None, 1)
        return None, None, None, 1

def get_balance():
    session = get_session_api()
    try:
        wallets = session.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]["coin"]
        usdt = next((c for c in wallets if c["coin"] == "USDT"), None)
        if usdt:
            for key in ["availableToTrade", "availableBalance", "walletBalance", "equity"]:
                if key in usdt and usdt[key] is not None:
                    return float(usdt[key])
            return 0.0
        else:
            return 0.0
    except Exception as e:
        print(f"❌ Balanso gavimo klaida: {e}")
        return 0.0

def round_qty(qty, qty_step):
    if qty_step is None or qty_step == 0:
        return qty
    decimals = abs(int(np.log10(qty_step)))
    return round(np.floor(qty / qty_step) * qty_step, decimals)

def calculate_qty(symbol, percent=10):
    session = get_session_api()
    try:
        min_qty, qty_step, min_notional, _ = get_symbol_info(symbol)
        if min_qty is None or qty_step is None or min_notional is None:
            print(f"⚠️ Trūksta min dydžio info {symbol}, skip.")
            return 0, 0
        balance = get_balance()
        usdt_amount = balance * percent / 100
        tickers = session.get_tickers(category="linear")['result']['list']
        price = next((float(t['lastPrice']) for t in tickers if t['symbol'] == symbol), None)
        if not price:
            print(f"⚠️ Nerasta kainos {symbol}, skip.")
            return 0, 0
        qty = round_qty(usdt_amount / price, qty_step)
        if qty < min_qty or (qty * price) < min_notional:
            print(f"⚠️ Kiekis arba suma per maža {symbol} (qty={qty}, sum={qty*price:.3f}), skip.")
            return 0, 0
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

def fetch_top_symbols(limit=100):
    session = get_session_api()
    try:
        tickers = session.get_tickers(category="linear")['result']['list']
        df = pd.DataFrame(tickers)
        df['volume24h'] = df['turnover24h'].astype(float)
        df['priceChange'] = df['price24hPcnt'].astype(float) * 100
        df = df[df['symbol'].str.endswith("USDT")]
        df = df[df['symbol'].str.isalpha()]
        top = df.sort_values("volume24h", ascending=False).head(limit)
        return top['symbol'].tolist(), top['symbol'].tolist()[:10]  # visas sąrašas ir TOP10
    except Exception as e:
        print(f"❌ Klaida fetch_top_symbols: {e}")
        return [], []

def open_position(symbol, qty):
    session = get_session_api()
    try:
        min_qty, qty_step, min_notional, max_leverage = get_symbol_info(symbol)
        lev = 5  # Naudojamas x5 svertas
        try:
            session.set_leverage(category="linear", symbol=symbol, buyLeverage=lev, sellLeverage=lev)
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
        print(f"✅ BUY: {symbol} kiekis: {qty} kaina: {entry_price} svertas: x{lev}")
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
    TARGET_PROFIT_PCT = 1      # Uždaryti kai +1%
    POSITION_PCT = 10          # 10% balanso vienai pozicijai
    symbol_in_position = None  # Tik viena pozicija

    while True:
        now = datetime.datetime.utcnow()
        if symbol_in_position is None:
            symbols, lyderiai = fetch_top_symbols(limit=100)  # gaunam visą ir TOP10
            for symbol in symbols:
                min_qty, qty_step, min_notional, max_leverage = get_symbol_info(symbol)
                if min_qty is None or qty_step is None or min_notional is None:
                    continue

                df = get_klines(symbol)
                time.sleep(1.5)
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

                # FILTRAI
                filter1 = price_change_1h >= 0.5
                filter2 = price_now > ema20
                filter3 = symbol in lyderiai
                print(f"{symbol}: 1h change={price_change_1h:.2f}%, EMA20={ema20:.4f}, TOP10={filter3} | Filtrai: {filter1} {filter2} {filter3}")

                if filter1 and filter2 and filter3:
                    qty, usdt_amount = calculate_qty(symbol, percent=POSITION_PCT)
                    if qty > 0:
                        entry_price = open_position(symbol, qty)
                        if entry_price:
                            opened_positions[symbol] = (datetime.datetime.utcnow(), qty, entry_price)
                            symbol_in_position = symbol
                            break

        else:
            open_time, qty, entry_price = opened_positions[symbol_in_position]
            last_price = get_last_prices([symbol_in_position]).get(symbol_in_position, None)
            if last_price and entry_price:
                price_change = (last_price - entry_price) / entry_price * 100
                profit_pct = price_change * 5  # x5 svertas
                print(f"🔄 {symbol_in_position} P/L={profit_pct:.2f}% (su svertu), kaina: {last_price} (entry: {entry_price})")
                if price_change >= TARGET_PROFIT_PCT / 100:
                    print(f"🎯 {symbol_in_position} pasiekė +{TARGET_PROFIT_PCT}% (x5 svertas ~{profit_pct:.2f}%), parduodam!")
                    close_position(symbol_in_position, qty)
                    del opened_positions[symbol_in_position]
                    symbol_in_position = None

        time.sleep(10)

if __name__ == "__main__":
    print("🚀 Botas paleistas!")
    trading_loop()
