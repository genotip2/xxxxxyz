from binance.client import Client
import pandas as pd
import numpy as np
import os
import requests
from datetime import datetime

# ==============================
# KONFIGURASI (Environment Variables)
# ==============================
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
INTERVAL = Client.KLINE_INTERVAL_4HOUR
MIN_VOLUME = 2000000  # 2 juta USDT

# ==============================
# INISIALISASI
# ==============================
client = Client()
active_buys = {}

def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calculate_macd(series, fast, slow, signal):
    ema_fast = calculate_ema(series, fast)
    ema_slow = calculate_ema(series, slow)
    macd = ema_fast - ema_slow
    signal_line = calculate_ema(macd, signal)
    return macd, signal_line

def calculate_atr(df, period):
    df['prev_close'] = df['close'].shift(1)
    tr = np.maximum(
        df['high'] - df['low'],
        np.abs(df['high'] - df['prev_close']),
        np.abs(df['low'] - df['prev_close'])
    )
    return tr.rolling(period).mean()

def calculate_rsi(series, period):
    delta = series.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_adx(df, period):
    high = df['high']
    low = df['low']
    close = df['close']
    
    up = high.diff()
    down = -low.diff()
    
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    
    tr = calculate_atr(df, period)
    
    plus_di = 100 * calculate_ema(pd.Series(plus_dm), period) / tr
    minus_di = 100 * calculate_ema(pd.Series(minus_dm), period) / tr
    
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    return calculate_ema(pd.Series(dx), period)

def get_top_pairs():
    tickers = client.get_ticker()
    usdt_pairs = [t for t in tickers if t['symbol'].endswith('USDT')]
    
    filtered = [
        p for p in usdt_pairs 
        if float(p['quoteVolume']) > MIN_VOLUME 
        and float(p['count']) > 1000
    ]
    
    sorted_pairs = sorted(filtered, 
                        key=lambda x: float(x['quoteVolume']), 
                        reverse=True)[:50]
    return [p['symbol'] for p in sorted_pairs]

def calculate_indicators(df):
    try:
        # Price-based indicators
        df['ema12'] = calculate_ema(df['close'], 12)
        df['ema26'] = calculate_ema(df['close'], 26)
        df['macd'], df['signal'] = calculate_macd(df['close'], 12, 26, 9)
        
        # Volatility
        df['atr'] = calculate_atr(df, 14)
        
        # Momentum
        df['rsi'] = calculate_rsi(df['close'], 14)
        df['adx'] = calculate_adx(df, 14)
        
        # Trend
        df['ema200'] = calculate_ema(df['close'], 200)
        df['sma50'] = df['close'].rolling(50).mean()
        
        # Volume
        df['volume_ma'] = df['volume'].rolling(20).mean()
        
        # Price Action
        df['24h_high'] = df['high'].rolling(6).max()
        df['24h_low'] = df['low'].rolling(6).min()
        
        # Support & Resistance
        df['resistance'] = df['high'].rolling(14).max().shift(1)
        df['support'] = df['low'].rolling(14).min().shift(1)
        
        return df.dropna()
    except Exception as e:
        print(f"Error calculating indicators: {e}")
        return df

def adaptive_macd_params(volatility):
    if volatility > 7:
        return 8, 16, 6
    elif volatility > 4:
        return 12, 24, 8
    else:
        return 14, 28, 9

def dynamic_rsi_thresholds(adx_value):
    if adx_value > 25:
        return 70, 30
    else:
        return 65, 35

def analyze_pair(symbol):
    try:
        klines = client.get_klines(
            symbol=symbol,
            interval=INTERVAL,
            limit=300
        )
        
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
            'taker_buy_quote', 'ignore'
        ]).apply(pd.to_numeric)
        
        df = calculate_indicators(df)
        if len(df) < 100:
            return None
            
        current = df.iloc[-1]
        prev = df.iloc[-2]
        
        volatility = df['close'].pct_change().std() * 100
        market_trend = 'trending' if current['adx'] > 25 else 'ranging'
        
        fast, slow, signal = adaptive_macd_params(volatility)
        df['macd'], df['signal'] = calculate_macd(df['close'], fast, slow, signal)
        
        overbought, oversold = dynamic_rsi_thresholds(current['adx'])
        
        macd_bullish = prev['macd'] < prev['signal'] and current['macd'] > current['signal']
        macd_bearish = prev['macd'] > prev['signal'] and current['macd'] < current['signal']
        
        buy_conditions = (
            macd_bullish and
            current['rsi'] < overbought and
            current['close'] > current['ema200'] and
            current['close'] > df['24h_high'].iloc[-2] and
            current['volume'] > current['volume_ma'] and
            market_trend == 'trending'
        )
        
        sell_conditions = (
            macd_bearish and
            current['rsi'] > oversold and
            current['close'] < df['24h_low'].iloc[-2] and
            symbol in active_buys
        )
        
        if buy_conditions or sell_conditions:
            return 'buy' if buy_conditions else 'sell', current
        return None, None
        
    except Exception as e:
        print(f"Error analyzing {symbol}: {e}")
        return None, None

def send_telegram_alert(symbol, signal, data):
    message = (
        f"🚨 **{signal.upper()} {symbol}**\n"
        f"▫️ Harga: ${data['close']:.4f}\n"
        f"▫️ RSI: {data['rsi']:.1f} | ADX: {data['adx']:.1f}\n"
        f"▫️ Support: ${data['support']:.4f}\n"
        f"▫️ Resistance: ${data['resistance']:.4f}\n"
        f"▫️ EMA200: ${data['ema200']:.4f}\n"
        f"▫️ Volume: {data['volume']:.2f} vs MA: {data['volume_ma']:.2f}\n"
        f"▫️ ATR: {data['atr']:.4f}\n"
        f"▫️ 24H High/Low: ${data['24h_high']:.4f}/${data['24h_low']:.4f}"
    )
    
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    )

def main():
    print(f"\n🔍 Monitoring mulai @ {datetime.utcnow()}")
    pairs = get_top_pairs()
    
    for symbol in pairs:
        try:
            signal, data = analyze_pair(symbol)
            if signal:
                if signal == 'buy':
                    active_buys[symbol] = data
                elif signal == 'sell' and symbol in active_buys:
                    del active_buys[symbol]
                send_telegram_alert(symbol, signal, data)
        except Exception as e:
            print(f"Error processing {symbol}: {str(e)}")
            continue

if __name__ == "__main__":
    main()
