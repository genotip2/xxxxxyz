import os
import requests
import json
from datetime import datetime, timedelta
from tradingview_ta import TA_Handler, Interval

# ==============================
# KONFIGURASI
# ==============================
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

ACTIVE_BUYS_FILE = 'active_buys.json'
ACTIVE_BUYS = {}

# Parameter Trading
RISK_REWARD_RATIO = 3.0
ATR_MULTIPLIER = 1.5
MAX_HOLD_DURATION_HOURS = 48
PAIR_TO_ANALYZE = 100
RSI_LIMIT = 60
# Jika data volume dari TradingView tidak sesuai (misal, format berbeda), Anda bisa menonaktifkan cek volume
MIN_VOLUME = 0  

# ==============================
# FUNGSI UTILITAS
# ==============================
def load_active_buys():
    global ACTIVE_BUYS
    try:
        if os.path.exists(ACTIVE_BUYS_FILE):
            with open(ACTIVE_BUYS_FILE, 'r') as f:
                data = json.load(f)
            ACTIVE_BUYS = {
                pair: {
                    'entry_price': float(d['entry_price']),
                    'stop_loss': float(d['stop_loss']),
                    'take_profit': float(d['take_profit']),
                    'highest_price': float(d['highest_price']),
                    'entry_time': datetime.fromisoformat(d['entry_time']),
                    'atr': float(d['atr'])
                }
                for pair, d in data.items()
            }
            print("Active positions loaded.")
    except Exception as e:
        print(f"Error loading active buys: {e}")

def save_active_buys():
    try:
        data = {}
        for pair, pos in ACTIVE_BUYS.items():
            data[pair] = {
                'entry_price': pos['entry_price'],
                'stop_loss': pos['stop_loss'],
                'take_profit': pos['take_profit'],
                'highest_price': pos['highest_price'],
                'entry_time': pos['entry_time'].isoformat(),
                'atr': pos['atr']
            }
        with open(ACTIVE_BUYS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        print("Active positions saved.")
    except Exception as e:
        print(f"Error saving active buys: {e}")

# ==============================
# FUNGSI ANALISIS PASAR
# ==============================
def get_binance_top_pairs():
    """Mengambil pair dengan volume tinggi dan likuiditas baik"""
    try:
        url = "https://api.coingecko.com/api/v3/exchanges/binance/tickers"
        response = requests.get(url, params={'order': 'volume_desc'})
        data = response.json()
        
        usdt_pairs = [
            t for t in data.get('tickers', [])
            if t.get('target') == 'USDT'
        ]
        
        sorted_pairs = sorted(
            usdt_pairs,
            key=lambda p: p.get('converted_volume', {}).get('usd', 0),
            reverse=True
        )[:PAIR_TO_ANALYZE]
        
        return [f"{p.get('base')}USDT" for p in sorted_pairs]
        
    except Exception as e:
        print(f"Error fetching pairs: {e}")
        return []

def analyze_pair(pair, interval):
    """
    Mengambil data analisis dari TradingView menggunakan tradingview_ta.
    Fungsi ini mengembalikan dictionary dengan key sesuai dengan format data contoh.
    """
    try:
        handler = TA_Handler(
            symbol=pair,
            exchange="BINANCE",
            screener="CRYPTO",
            interval=interval
        )
        analysis = handler.get_analysis()
        if analysis is None or not hasattr(analysis, 'summary'):
            print(f"Tidak ada data analisis untuk {pair}")
            return None

        # Pastikan key sesuai dengan format data contoh (misalnya, 'RECOMMENDATION' dengan huruf besar)
        return {
            'RECOMMENDATION': analysis.summary.get('RECOMMENDATION'),
            'close': analysis.indicators.get('close'),
            'RSI': analysis.indicators.get('RSI'),
            'MACD.macd': analysis.indicators.get('MACD.macd'),
            'MACD.signal': analysis.indicators.get('MACD.signal'),
            'ATR': analysis.indicators.get('ATR'),
            'volume': analysis.indicators.get('volume')
        }
    except Exception as e:
        print(f"Analysis error for {pair}: {e}")
        return None

# ==============================
# FUNGSI RISK MANAGEMENT
# ==============================
def calculate_risk(current_price, atr):
    """Menghitung parameter risiko dinamis.
       Jika ATR tidak tersedia, gunakan fallback 2% dari harga saat ini.
    """
    if atr is None or atr <= 0:
        atr = 0.02 * current_price  # Fallback 2% jika ATR tidak tersedia
    stop_loss = current_price - (atr * ATR_MULTIPLIER)
    take_profit = current_price + (atr * ATR_MULTIPLIER * RISK_REWARD_RATIO)
    risk_percentage = ((current_price - stop_loss) / current_price) * 100
    return {
        'stop_loss': stop_loss,
        'take_profit': take_profit,
        'risk': risk_percentage,
        'atr': atr
    }

# ==============================
# LOGIKA TRADING
# ==============================
def generate_signal(pair):
    """
    Menghasilkan sinyal trading berdasarkan data 1H (trend) dan 15M (entry).
    Modifikasi: tidak lagi bergantung pada 'volume_ma' karena data contoh tidak memilikinya.
    """
    # Analisis trend dari data 1H
    trend = analyze_pair(pair, Interval.INTERVAL_1_HOUR)
    if not trend or trend.get('close') is None:
        return None

    # Opsional: cek volume (jika diperlukan)
    if trend.get('volume') is None or trend['volume'] < MIN_VOLUME:
        return None
    
    # Analisis entry dari data 15M
    entry = analyze_pair(pair, Interval.INTERVAL_15_MINUTES)
    if not entry or entry.get('close') is None:
        return None

    current_price = entry['close']

    # Jika sudah ada posisi aktif untuk pair ini
    if pair in ACTIVE_BUYS:
        position = ACTIVE_BUYS[pair]
        position['highest_price'] = max(position['highest_price'], current_price)
        new_stop = position['highest_price'] - (position['atr'] * ATR_MULTIPLIER)
        position['stop_loss'] = max(position['stop_loss'], new_stop)
        
        if current_price >= position['take_profit']:
            return 'TAKE_PROFIT', current_price
        if current_price <= position['stop_loss']:
            return 'STOP_LOSS', current_price
        if (datetime.now() - position['entry_time']).total_seconds() > MAX_HOLD_DURATION_HOURS * 3600:
            return 'HOLD_EXPIRED', current_price
        if trend.get('RECOMMENDATION') in ['SELL', 'STRONG_SELL']:
            return 'TREND_REVERSAL', current_price
    else:
        # Syarat untuk sinyal BUY:
        # - Rekomendasi 1H: BUY/STRONG_BUY
        # - RSI pada data 15M kurang dari RSI_LIMIT
        # - MACD pada data 15M: MACD.macd > MACD.signal
        if (trend.get('RECOMMENDATION') in ['BUY', 'STRONG_BUY'] and
            entry.get('RSI') is not None and entry['RSI'] < RSI_LIMIT and
            entry.get('MACD.macd') is not None and entry.get('MACD.signal') is not None and
            entry['MACD.macd'] > entry['MACD.signal']):
            
            risk_data = calculate_risk(current_price, entry.get('ATR'))
            if risk_data['risk'] > 5:  # Batasi risiko maksimal 5%
                return None
            return 'BUY', current_price, risk_data

    return None

# ==============================
# NOTIFIKASI & EKSEKUSI
# ==============================
def send_telegram_alert(signal, pair, price, details=None):
    """Mengirim notifikasi ke Telegram"""
    emoji_map = {
        'BUY': '🚀',
        'TAKE_PROFIT': '✅',
        'STOP_LOSS': '🛑',
        'HOLD_EXPIRED': '⌛',
        'TREND_REVERSAL': '🔄'
    }
    
    message = f"{emoji_map.get(signal, 'ℹ️')} **{signal.replace('_', ' ')}**\n"
    message += f"• Pair: `{pair}`\n"
    message += f"• Price: ${price:.4f}\n"
    if signal == 'BUY' and details:
        message += f"• Stop Loss: ${details['stop_loss']:.4f}\n"
        message += f"• Take Profit: ${details['take_profit']:.4f}\n"
        message += f"• Risk: {details['risk']:.2f}%\n"
        message += f"• ATR: ${details['atr']:.4f}\n"
    elif pair in ACTIVE_BUYS:
        pos = ACTIVE_BUYS[pair]
        profit = ((price - pos['entry_price']) / pos['entry_price']) * 100
        duration = datetime.now() - pos['entry_time']
        message += f"• Entry Price: ${pos['entry_price']:.4f}\n"
        message += f"• Profit: {profit:.2f}%\n"
        message += f"• Duration: {str(duration).split('.')[0]}\n"
    
    try:
        if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
            )
        else:
            print("Telegram configuration is missing.")
    except Exception as e:
        print(f"Telegram error: {e}")

# ==============================
# MAIN LOGIC
# ==============================
def main():
    load_active_buys()
    pairs = get_binance_top_pairs()
    
    if not pairs:
        print("No pairs fetched.")
        return
    
    any_signal = False
    for pair in pairs:
        print(f"Checking pair: {pair}")
        
        result = generate_signal(pair)
        if not result:
            print(f"No signal for {pair}")
            continue
        else:
            any_signal = True
            if result[0] == 'BUY':
                signal, price, risk_data = result
                ACTIVE_BUYS[pair] = {
                    'entry_price': price,
                    'stop_loss': risk_data['stop_loss'],
                    'take_profit': risk_data['take_profit'],
                    'highest_price': price,
                    'entry_time': datetime.now(),
                    'atr': risk_data['atr']
                }
                send_telegram_alert(signal, pair, price, risk_data)
            else:
                signal, price = result
                send_telegram_alert(signal, pair, price)
                if pair in ACTIVE_BUYS:
                    del ACTIVE_BUYS[pair]
    
    # Hapus posisi jika sudah melewati batas durasi
    for pair in list(ACTIVE_BUYS.keys()):
        pos = ACTIVE_BUYS[pair]
        if (datetime.now() - pos['entry_time']).total_seconds() > MAX_HOLD_DURATION_HOURS * 3600:
            send_telegram_alert('HOLD_EXPIRED', pair, pos['entry_price'])
            del ACTIVE_BUYS[pair]
    
    save_active_buys()

if __name__ == "__main__":
    main()
