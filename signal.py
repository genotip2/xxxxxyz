from binance.client import Client
import pandas as pd
import numpy as np
import talib
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

def get_top_pairs():
    """Mendapatkan pair dengan volume dan likuiditas tinggi"""
    tickers = client.get_ticker()
    usdt_pairs = [t for t in tickers if t['symbol'].endswith('USDT')]
    
    # Filter volume dan likuiditas
    filtered = [
        p for p in usdt_pairs 
        if float(p['quoteVolume']) > MIN_VOLUME 
        and float(p['count']) > 1000  # Jumlah transaksi
    ]
    
    sorted_pairs = sorted(filtered, 
                        key=lambda x: float(x['quoteVolume']), 
                        reverse=True)[:50]
    return [p['symbol'] for p in sorted_pairs]

def calculate_indicators(df):
    """Menghitung semua indikator teknis"""
    try:
        # Price-based indicators
        df['ema12'] = talib.EMA(df['close'], timeperiod=12)
        df['ema26'] = talib.EMA(df['close'], timeperiod=26)
        df['macd'], df['signal'], _ = talib.MACD(df['close'], 
                                               fastperiod=12, 
                                               slowperiod=26, 
                                               signalperiod=9)
        
        # Volatility
        df['atr'] = talib.ATR(df['high'], df['low'], df['close'], timeperiod=14)
        
        # Momentum
        df['rsi'] = talib.RSI(df['close'], timeperiod=14)
        df['adx'] = talib.ADX(df['high'], df['low'], df['close'], timeperiod=14)
        
        # Trend
        df['ema200'] = talib.EMA(df['close'], timeperiod=200)
        df['sma50'] = talib.SMA(df['close'], timeperiod=50)
        
        # Volume
        df['volume_ma'] = talib.SMA(df['volume'], timeperiod=20)
        
        # Price Action
        df['24h_high'] = df['high'].rolling(6).max()  # 4h * 6 = 24 jam
        df['24h_low'] = df['low'].rolling(6).min()
        
        return df.dropna()
    except Exception as e:
        print(f"Error calculating indicators: {e}")
        return df

def adaptive_macd_params(volatility):
    """Menyesuaikan parameter MACD berdasarkan volatilitas"""
    if volatility > 7:   # High volatility
        return 8, 16, 6
    elif volatility > 4: # Medium volatility
        return 12, 24, 8
    else:                # Low volatility
        return 14, 28, 9

def dynamic_rsi_thresholds(adx_value):
    """Menyesuaikan level RSI berdasarkan kekuatan tren"""
    if adx_value > 25:  # Strong trend
        return 70, 30   # Lebih longgar
    else:               # Weak trend
        return 65, 35   # Lebih ketat

def analyze_pair(symbol):
    try:
        # Ambil data historis
        klines = client.get_klines(
            symbol=symbol,
            interval=INTERVAL,
            limit=300  # Untuk indikator jangka panjang
        )
        
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
            'taker_buy_quote', 'ignore'
        ]).apply(pd.to_numeric)
        
        df = calculate_indicators(df)
        if len(df) < 100:  # Pastikan data cukup
            return None
            
        current = df.iloc[-1]
        prev = df.iloc[-2]
        
        # Analisis kondisi pasar
        volatility = df['close'].pct_change().std() * 100
        market_trend = 'trending' if current['adx'] > 25 else 'ranging'
# Parameter dinamis
        fast, slow, signal = adaptive_macd_params(volatility)
        df['macd'], df['signal'], _ = talib.MACD(df['close'], 
                                               fastperiod=fast,
                                               slowperiod=slow,
                                               signalperiod=signal)
        
        overbought, oversold = dynamic_rsi_thresholds(current['adx'])
        
        # Kondisi masuk
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
        
        if buy_conditions:
            return 'buy'
        elif sell_conditions:
            return 'sell'
        return None
        
    except Exception as e:
        print(f"Error analyzing {symbol}: {e}")
        return None

def send_telegram_alert(symbol, signal, data):
    """Mengirim laporan lengkap ke Telegram"""
    message = (
        f"🚨 {signal.upper()} {symbol}\n"
        f"▫️ Harga: ${data['close']:.4f}\n"
        f"▫️ RSI: {data['rsi']:.1f} | ADX: {data['adx']:.1f}\n"
        f"▫️ EMA200: ${data['ema200']:.4f}\n"
        f"▫️ Volume: {data['volume']:.2f} vs MA: {data['volume_ma']:.2f}\n"
        f"▫️ ATR: {data['atr']:.4f} ({'High Vol' if data['atr'] > 0.02 else 'Low Vol'})\n"
        f"▫️ 24H High/Low: ${data['24h_high']:.4f}/${data['24h_low']:.4f}"
    )
    
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    )

def market_hours_filter():
    """Filter waktu trading optimal (UTC)"""
    hour = datetime.utcnow().hour
    return 8 <= hour < 22  # Waktu pasar aktif global

def main():
    print(f"\n🔍 Monitoring mulai @ {datetime.utcnow()}")
    if market_hours_filter():
        pairs = get_top_pairs()
        
        for symbol in pairs:
            try:
                signal = analyze_pair(symbol)
                if signal:
                    df = client.get_klines(symbol=symbol, interval=INTERVAL, limit=1)
                    last_data = df[0] if df else None
                    
                    if signal == 'buy':
                        active_buys[symbol] = last_data
                        send_telegram_alert(symbol, signal, last_data)
                    elif signal == 'sell':
                        del active_buys[symbol]
                        send_telegram_alert(symbol, signal, last_data)
            except Exception as e:
                print(f"Error processing {symbol}: {str(e)}")
                continue

if name == "main":
    main()
