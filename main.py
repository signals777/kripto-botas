import os
import time
import datetime
import numpy as np
import pandas as pd
from pybit.unified_trading import HTTP
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange
from sklearn.linear_model import LogisticRegression

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
            min_qty = float(item["lotSizeFilter"]["minOrderQty"]) if "lotSizeFilter" in item and "minOrderQty" in item["lotSizeFilter"] else None
            qty_step = float(item["lotSizeFilter"]["qtyStep"]) if "lotSizeFilter" in item and "qtyStep" in item["lotSizeFilter"] else None
            min_notional = float(item["lotSizeFilter"]["minNotionalValue"]) if "lotSizeFilter" in item and "minNotionalValue" in item["lotSizeFilter"] else 5
            max_leverage = int(float(item["leverageFilter"]["maxLeverage"])) if "leverageFilter" in item and "maxLeverage" in item["leverageFilter"] else 1
            instruments_info[symbol] = (min_qty, qty_step, min_notional, max_leverage)
            return min_qty, qty_step, min_notional, max_leverage
        else:
            instruments_info[symbol] = (None, None, None, 1)
            return None, None, None, 1
    except Exception as e:
        instruments_info[symbol] = (None, None, None, 1)
        print(f"❌ Klaida get_symbol_info({symbol}): {e}")
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

def calculate_qty(symbol, percent=20):
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

def get_klines(symbol, interval="1", limit=150):
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
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['volume'] = df['volume'].astype(float)
        return df
    except Exception as e:
        print(f"❌ Klaida get_klines({symbol}): {e}")
        return pd.DataFrame()

def apply_ema(df, window=15):
    try:
        ema = EMAIndicator(df['close'], window=window).ema_indicator()
        df['ema'] = ema
        return df
    except Exception as e:
        print(f"❌ EMA klaida: {e}")
        return df

def apply_atr(df, window=5):
    try:
        atr = AverageTrueRange(df['high'], df['low'], df['close'], window=window).average_true_range()
        df['atr'] = atr
        return df
    except Exception as e:
        print(f"❌ ATR klaida: {e}")
        return df

def fetch_top_symbols(limit=15):
    session = get_session_api()
    try:
        tickers = session.get_tickers(category="linear")['result']['list']
        df = pd.DataFrame(tickers)
        df['volume24h'] = df['turnover24h'].astype(float)
        df = df[df['symbol'].str.endswith("USDT")]
        df = df[df['symbol'].str.isalpha()]
        top = df.sort_values("volume24h", ascending=False).head(limit)
        return top['symbol'].tolist()
    except Exception as e:
        print(f"❌ Klaida fetch_top_symbols: {e}")
        return []

def open_position(symbol, qty):
    session = get_session_api()
    try:
        lev = 5
        try:
            session.set_leverage(category="linear", symbol=symbol, buyLeverage=lev, sellLeverage=lev)
        except Exception as lev_err:
            print(f"⚠️ Sverto klaida {symbol}: {lev_err}")
        order = session.place_order(
            category="linear",
            symbol=symbol,
            side="Sell",
            orderType="Market",
            qty=qty,
            timeInForce="GoodTillCancel"
        )
        entry_price = float(order['result']['avgPrice']) if order.get('result', {}).get('avgPrice') else None
        print(f"✅ SHORT (Sell): {symbol} kiekis: {qty} kaina: {entry_price} svertas: x{lev}")
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
            side="Buy",
            orderType="Market",
            qty=qty,
            timeInForce="GoodTillCancel",
            reduceOnly=True
        )
        print(f"🔻 SHORT CLOSE (Buy): {symbol} kiekis: {qty}")
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

def train_simple_ai(df):
    X = []
    y = []
    for i in range(6, len(df)-1):
        changes = list((df['close'].iloc[i-5:i].pct_change().fillna(0).values)*100)
        feat = changes + [df['atr'].iloc[i], df['ema'].iloc[i], df['volume'].iloc[i]]
        X.append(feat)
        y.append(1 if (df['close'].iloc[i+1] - df['close'].iloc[i])/df['close'].iloc[i] < -0.003 else 0)
    if len(X) < 5:
        return None
    model = LogisticRegression()
    model.fit(X, y)
    return model

def ai_predict_next(df, model):
    if model is None or len(df) < 7:
        return True
    i = len(df)-1
    changes = list((df['close'].iloc[i-5:i].pct_change().fillna(0).values)*100)
    feat = changes + [df['atr'].iloc[i], df['ema'].iloc[i], df['volume'].iloc[i]]
    pred = model.predict([feat])[0]
    return bool(pred)

def trading_loop():
    print("🚀 PRO greito scalping SHORT botas (150 žvakių, EMA15, 20 % balanso, 1 pozicija) paleistas!")
    opened_positions = {}
    TARGET_PROFIT_PCT = 0.7
    STOP_LOSS_PCT = -0.7
    POSITION_PCT = 20
    symbol_in_position = None

    while True:
        now = datetime.datetime.utcnow()
        if symbol_in_position is None:
            symbols = fetch_top_symbols(limit=15)
            print(f"\n[{now.strftime('%H:%M:%S')}] Tikrinam {symbols}")

            for symbol in symbols:
                min_qty, qty_step, min_notional, max_leverage = get_symbol_info(symbol)
                if min_qty is None or qty_step is None or min_notional is None:
                    print(f"{symbol}: nėra min dydžio info (skip)")
                    continue

                df = get_klines(symbol, interval="1", limit=150)
                time.sleep(0.5)
                print(f"{symbol}: Gauta žvakių: {len(df)}")
                if df.empty or len(df) < 15:
                    print(f"{symbol}: Per mažai žvakių EMA/ATR skaičiavimui ({len(df)}/15), skip")
                    continue

                df = apply_ema(df, window=15)
                print(f"{symbol}: Po EMA skaičiavimo – žvakių: {len(df)}, null EMA: {df['ema'].isnull().sum()} (iš {len(df)})")
                df = apply_atr(df, window=5)
                if 'atr' not in df.columns or df['atr'].isnull().all():
                    print(f"{symbol}: nėra ATR (skip)")
                    continue

                df['min10'] = df['low'].rolling(window=10).min()
                last = df.iloc[-1]
                prev = df.iloc[-2]
                price_now = last['close']
                price_prev = prev['close']
                change_1m = (price_now - price_prev) / price_prev * 100

                if 'ema' in df.columns and not pd.isna(df['ema'].iloc[-1]):
                    below_ema = price_now < last['ema']
                else:
                    below_ema = True
                    print(f"{symbol}: EMA nėra arba NaN – tęsiam be EMA filtro")

                high_atr = last['atr'] > df['atr'].mean()
                is_breakout_short = price_now < last['min10']
                is_volume_spike = last['volume'] > 1.3 * df['volume'].mean()
                ai_model = train_simple_ai(df)
                ai_decision = ai_predict_next(df, ai_model)

                print(f"{symbol}: 1m change={change_1m:.2f}%, EMA15={last.get('ema', 0):.4f}, ATR5={last['atr']:.4f}, breakoutS={is_breakout_short}, vol_spike={is_volume_spike}, AI={ai_decision} | SHORT: {change_1m<=-0.4} {below_ema} {high_atr} {is_breakout_short} {is_volume_spike} {ai_decision}")

                if change_1m <= -0.4 and below_ema and high_atr and is_breakout_short and is_volume_spike and ai_decision:
                    qty, usdt_amount = calculate_qty(symbol, percent=POSITION_PCT)
                    if qty > 0:
                        entry_price = open_position(symbol, qty)
                        if entry_price:
                            opened_positions[symbol] = (datetime.datetime.utcnow(), qty, entry_price)
                            symbol_in_position = symbol
                            print(f"🎯 Atidaryta SHORT pozicija: {symbol} kiekis {qty} @ {entry_price}")
                            break
                    else:
                        print(f"{symbol}: qty={qty}, suma per maža arba nerasta, skip.")

        else:
            open_time, qty, entry_price = opened_positions[symbol_in_position]
            last_price = get_last_prices([symbol_in_position]).get(symbol_in_position, None)
            if last_price and entry_price:
                price_change = (entry_price - last_price) / entry_price * 100
                profit = qty * (entry_price - last_price) * 5
                print(f"🔄 {symbol_in_position} [SHORT]: {qty} vnt, Kaina {entry_price:.4f} → {last_price:.4f} | PnL: {profit:.2f} USDT ({price_change:.2f}%)")

                if price_change >= TARGET_PROFIT_PCT:
                    print(f"🎯 {symbol_in_position} [SHORT] +{TARGET_PROFIT_PCT}% profit! Uždarymas.")
                    close_position(symbol_in_position, qty)
                    del opened_positions[symbol_in_position]
                    symbol_in_position = None
                elif price_change <= STOP_LOSS_PCT:
                    print(f"🛑 {symbol_in_position} [SHORT] stop loss {STOP_LOSS_PCT}%, uždarom!")
                    close_position(symbol_in_position, qty)
                    del opened_positions[symbol_in_position]
                    symbol_in_position = None

        time.sleep(2)

if __name__ == "__main__":
    print("🚀 PRO greito scalping SHORT botas (150 žvakių, EMA15, 20 % balanso, 1 pozicija) paleistas!")
    trading_loop()
