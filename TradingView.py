import os
import requests
from tradingview_ta import TA_Handler, Interval
from datetime import datetime, timedelta
import json
import subprocess

# ==============================
# KONFIGURASI
# ==============================
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
ACTIVE_BUYS = {}
BUY_SCORE_THRESHOLD = 5  # Naikkan threshold karena tambahan indikator
SELL_SCORE_THRESHOLD = 4
FILE_PATH = 'active_buys.json'

# Inisialisasi file JSON
if not os.path.exists(FILE_PATH):
    with open(FILE_PATH, 'w') as f:
        json.dump({}, f)
else:
    with open(FILE_PATH, 'r') as f:
        ACTIVE_BUYS = json.load(f)

# ==============================
# FUNGSI PENGAMBILAN DATA PAIR
# ==============================
def get_binance_top_pairs():
    url = "https://api.coingecko.com/api/v3/exchanges/binance/tickers"
    params = {'include_exchange_logo': 'false', 'order': 'volume_desc'}
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        usdt_pairs = [t for t in data['tickers'] if t['target'] == 'USDT']
        sorted_pairs = sorted(usdt_pairs, 
                            key=lambda x: x['converted_volume']['usd'], 
                            reverse=True)[:50]
        return [f"{p['base']}USDT" for p in sorted_pairs]
    
    except Exception as e:
        print(f"❌ Error fetching Binance data: {e}")
        return []

# ==============================
# FUNGSI ANALISIS TEKNIKAL (+ BOLLINGER BANDS)
# ==============================
def analyze_pair(symbol):
    try:
        handler = TA_Handler(
            symbol=symbol,
            exchange="BINANCE",
            screener="CRYPTO",
            interval=Interval.INTERVAL_4_HOURS
        )
        
        analysis = handler.get_analysis()
        indicators = analysis.indicators

        # Bollinger Bands
        bb_upper = indicators.get('BB.upper', 0)
        bb_middle = indicators.get('BB.middle', 0)
        bb_lower = indicators.get('BB.lower', 0)

        # Fibonacci Retracement
        high = indicators.get('high', 0)
        low = indicators.get('low', 0)
        fibonacci_levels = calculate_fibonacci_levels(high, low)
        
        return {
            'recommendation': analysis.summary['RECOMMENDATION'],
            'rsi': indicators.get('RSI', 0),
            'macd': indicators.get('MACD.macd', 0),
            'signal': indicators.get('MACD.signal', 0),
            'support': fibonacci_levels['level_61_8'],
            'resistance': fibonacci_levels['level_23_6'],
            'price': indicators.get('close', 0),
            'volume': indicators.get('volume', 0),
            'adx': indicators.get('ADX', 0),
            'bb_upper': bb_upper,
            'bb_middle': bb_middle,
            'bb_lower': bb_lower
        }
        
    except Exception as e:
        print(f"⚠️ Error analyzing {symbol}: {str(e)}")
        return None

# ==============================
# FUNGSI PENGHITUNGAN SKOR (+ BOLLINGER BANDS)
# ==============================
def calculate_scores(data):
    current_price = data['price']
    
    # Kondisi BUY (+ Bollinger Bands)
    buy_conditions = [
        "BUY" in data['recommendation'],
        data['rsi'] < 60,  # Lebih konservatif
        data['macd'] > data['signal'],
        data['adx'] > 25,
        current_price > data['resistance'] * 0.99,
        data['volume'] > 1e6,
        current_price < data['bb_lower']  # Harga menyentuh lower band
    ]
    
    # Kondisi SELL (+ Bollinger Bands)
    sell_conditions = [
        "SELL" in data['recommendation'],
        data['rsi'] > 65,  # Lebih responsif
        data['macd'] < data['signal'],
        data['adx'] < 20,
        current_price < data['support'],
        current_price > data['bb_upper']  # Harga menyentuh upper band
    ]
    
    return sum(buy_conditions), sum(sell_conditions)

# ==============================
# FUNGSI KIRIM NOTIFIKASI (+ INFO BOLLINGER BANDS)
# ==============================
def send_telegram_alert(signal_type, pair, current_price, data, buy_price=None):
    display_pair = f"{pair[:-4]}/USDT"
    message = ""
    buy_score, sell_score = calculate_scores(data)
    emoji = {
        'BUY': '🚀', 
        'SELL': '⚠️', 
        'TAKE PROFIT': '✅', 
        'STOP LOSS': '🛑'
    }.get(signal_type, 'ℹ️')

    base_msg = f"{emoji} **{signal_type} {display_pair}**\n"
    base_msg += f"▫️ Price: ${current_price:.8f}\n"
    base_msg += f"📊 Buy Score: {buy_score}/7 | Sell Score: {sell_score}/6\n"

    if signal_type == 'BUY':
        message = f"{base_msg}▫️ Support: ${data['support']:.8f}\n"
        message += f"▫️ Resistance: ${data['resistance']:.8f}\n"
        message += f"🔍 RSI: {data['rsi']:.1f} | MACD: {data['macd']:.8f}\n"
        message += f"📉 BB Lower: ${data['bb_lower']:.8f}"  # Info Bollinger Bands
        ACTIVE_BUYS[pair] = {'price': current_price, 'time': datetime.now()}

    elif signal_type in ['TAKE PROFIT', 'STOP LOSS', 'SELL']:
        buy_data = ACTIVE_BUYS.get(pair, {'price': buy_price, 'time': datetime.now()})
        profit = ((current_price - buy_data['price'])/buy_data['price'])*100
        duration = str(datetime.now() - buy_data['time']).split('.')[0]
        
        message = f"{base_msg}▫️ Entry Price: ${buy_data['price']:.8f}\n"
        message += f"▫️ {'Profit' if profit > 0 else 'Loss'}: {profit:.2f}%\n"
        message += f"📈 BB Upper: ${data['bb_upper']:.8f}\n"  # Info Bollinger Bands
        message += f"🕒 Hold Duration: {duration}"

        if signal_type in ['STOP LOSS', 'SELL']:
            del ACTIVE_BUYS[pair]

    print(f"📢 Sending Telegram alert: {message}")
    
    try:
        save_active_buys_to_json()
    except Exception as e:
        print(f"❌ Gagal menyimpan/commit: {str(e)}")

    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    )

# ... (Fungsi lainnya tetap sama seperti sebelumnya, hanya tambah BB di analisis)

if __name__ == "__main__":
    main()
