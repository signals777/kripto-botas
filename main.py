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

# --- Instrumentų info cache ---
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

def calculate_qty(symbol, usdt_amount):
    session = get_session_api()
    try:
        min_qty, qty_step, min_notional, _ = get_symbol_info(symbol)
        if min_qty is None or qty_step is None or min_notional is None:
            print(f"⚠️ Trūksta min dydžio info {symbol}, skip.")
            return 0, 0
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

def fetch_top_symbols(limit=150):
    session = get_session_api()
    try:
        tickers = session.get_tickers(category="linear")['result']['list']
        df = pd.DataFrame(tickers)
        df['volume24h'] = df['turnover24h'].astype(float)
        df['priceChange'] = df['price24hPcnt'].astype(float) * 100
        df = df[df['symbol'].str.endswith("USDT")]
        df = df[df['symbol'].str.isalpha()]
        top = df.sort_values("volume24h", ascending=False).head(limit)
        return top['symbol'].tolist(), top['symbol'].tolist()[:10]
    except Exception as e:
        print(f"❌ Klaida fetch_top_symbols: {e}")
        return [], []

def open_position(symbol, qty):
    session = get_session_api()
    try:
        min_qty, qty_step, min_notional, max_leverage = get_symbol_info(symbol)
        lev = max_leverage
        if lev > 5:
            lev = 5
        if lev < 1:
            lev = 1
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

    STOP_LOSS_PCT = -1     # -1 % nuo atidarymo
    TRAILING_FROM_MAX = -1 # -1 % nuo max (progresyvus trailing)
    # NEBENAUDOJAM BALANCE_LIMIT_PCT, naudojam VISĄ balansą
    MAX_TOP_SYMBOLS = 150

    while True:
        now = datetime.datetime.utcnow()
        if now.minute == 0 and now.second < 10:
            print(f"\n🕐 Nauja valanda {now.strftime('%H:%M:%S')} – ieškom pozicijų...")

            symbols, lyderiai = fetch_top_symbols(limit=MAX_TOP_SYMBOLS)
            selected = []
            total_checked = 0
            filtered_count = 0
            skipped_info = 0
            skipped_filter = 0

            balance = get_balance()
            min_pos_usdt = 1000
            # Surandam mažiausią reikalingą sumą vienam sandoriui tarp visų top porų
            for symbol in symbols:
                min_qty, qty_step, min_notional, max_leverage = get_symbol_info(symbol)
                if min_notional and min_notional < min_pos_usdt:
                    min_pos_usdt = min_notional
            # Automatinis galimų pozicijų kiekis pagal balansą ir min_notional
            max_theory_positions = int(balance // max(min_pos_usdt, 1))
            if max_theory_positions == 0:
                print(f"⚠️ Balansas per mažas net minimaliam sandoriui ({min_pos_usdt:.2f} USDT). Sandoriai neatidaromi.")
            else:
                print(f"ℹ️ Balansas: {balance:.2f} USDT | Galimos max pozicijos: {max_theory_positions} | "
                      f"Skiriama ~{balance / max_theory_positions:.2f} USDT vienai pozicijai")

            # Ieškom nuo +0.5% pokyčio per valandą
            for symbol in symbols:
                total_checked += 1
                if symbol in opened_positions:
                    continue

                min_qty, qty_step, min_notional, max_leverage = get_symbol_info(symbol)
                if min_qty is None or qty_step is None or min_notional is None:
                    skipped_info += 1
                    print(f"⚠️ {symbol}: Trūksta min dydžio info, skip.")
                    continue

                df = get_klines(symbol)
                time.sleep(2.5)
                if df.empty:
                    print(f"⚠️ {symbol} – nėra žvakės, skip.")
                    continue
                df = apply_ema(df)
                if df.empty:
                    print(f"⚠️ {symbol} – EMA error, skip.")
                    continue
                last = df.iloc[-1]
                open1h = df.iloc[-2]['close']
                price_now = last['close']
                price_change_1h = (price_now - open1h) / open1h * 100
                ema20 = last['ema']
                volume_leader = symbol in lyderiai

                score = 0
                if price_change_1h >= 0.5:
                    score += 1
                if price_now > ema20:
                    score += 1
                if volume_leader:
                    score += 1

                if score >= 2:
                    filtered_count += 1
                    selected.append((symbol, score, price_change_1h, price_now, ema20, volume_leader))
                else:
                    skipped_filter += 1
                    print(f"⚠️ {symbol} – neatitinka filtrų (change: {price_change_1h:.2f}%), skip.")

            print(f"🔎 Patikrinta {total_checked} porų. Tinkamų: {filtered_count}. Skip dėl info: {skipped_info}, skip dėl filtrų: {skipped_filter}")

            # Kiek iš tikro galim atidaryti pozicijų
            max_open = max(1, min(filtered_count, max_theory_positions))
            if filtered_count == 0 or max_open == 0:
                print("⚠️ Nėra tinkamų porų. Nepirks.")
            else:
                used_balance = 0
                count_opened = 0
                usdt_per_position = balance / max_open
                for symbol, score, price_change_1h, price_now, ema20, volume_leader in selected[:max_open]:
                    if symbol in opened_positions:
                        continue
                    qty, usdt_amount = calculate_qty(symbol, usdt_per_position)
                    if qty > 0 and count_opened < max_open:
                        entry_price = open_position(symbol, qty)
                        if entry_price:
                            opened_positions[symbol] = (now, qty, entry_price, entry_price)
                            used_balance += usdt_amount
                            count_opened += 1
                            time.sleep(1.2)
                if count_opened == 0:
                    print("⚠️ Nepavyko atidaryti nė vienos pozicijos: balansas arba porų dydis per mažas.")

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
