import os
import requests
import json
import logging
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
RSI_LIMIT = 40
MIN_VOLUME_MA = 1000000  # $1 juta

# Setup Logging
logging.basicConfig(
    filename='trading_bot.log',
    filemode='w'
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

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
            logging.info("Loaded active positions")
    except Exception as e:
        logging.error(f"Error loading active buys: {e}")

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
        logging.info("Saved active positions")
    except Exception as e:
        logging.error(f"Error saving active buys: {e}")

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
            if t.get('target') == 'USDT' and t.get('converted_volume', {}).get('usd', 0) > MIN_VOLUME_MA
        ]
        
        # Urutkan berdasarkan converted_volume secara menurun
        sorted_pairs = sorted(
            usdt_pairs,
            key=lambda p: p.get('converted_volume', {}).get('usd', 0),
            reverse=True
        )[:PAIR_TO_ANALYZE]
        
        # Ubah ke format string misalnya "BTCUSDT"
        return [f"{p.get('base')}USDT" for p in sorted_pairs]
        
    except Exception as e:
        logging.error(f"Error fetching pairs: {e}")
        return []

def analyze_pair(pair, interval):
    """Analisis teknikal dengan multiple indikator"""
    try:
        handler = TA_Handler(
            symbol=pair,
            exchange="BINANCE",
            screener="CRYPTO",
            interval=interval
        )
        analysis = handler.get_analysis()
        # Pastikan data analisis tersedia dan memiliki atribut summary
        if analysis is None or not hasattr(analysis, 'summary'):
            logging.error(f"Tidak ada data analisis untuk {pair}")
            return None

        return {
            'recommendation': analysis.summary.get('RECOMMENDATION'),
            'close': analysis.indicators.get('close'),
            'rsi': analysis.indicators.get('RSI'),
            'rsi_prev': analysis.indicators.get('RSI[1]'),
            'macd': analysis.indicators.get('MACD.macd'),
            'signal': analysis.indicators.get('MACD.signal'),
            'atr': analysis.indicators.get('ATR'),
            'volume': analysis.indicators.get('volume'),
            'volume_ma': analysis.indicators.get('volume_ma')
        }
    except Exception as e:
        logging.error(f"Analysis error for {pair}: {e}")
        return None

# ==============================
# LOGIKA TRADING
# ==============================
def calculate_risk(current_price, atr):
    """Menghitung parameter risiko dinamis"""
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

def generate_signal(pair):
    """Generasi sinyal dengan manajemen risiko dinamis"""
    # Analisis trend 1-jam
    trend = analyze_pair(pair, Interval.INTERVAL_1_HOUR)
    if not trend or trend.get('close') is None:
        return None
    
    # Filter volume: pastikan volume_ma tersedia dan memenuhi syarat
    if trend.get('volume_ma') is None or trend['volume_ma'] < MIN_VOLUME_MA:
        return None
    
    # Analisis entry 15-menit
    entry = analyze_pair(pair, Interval.INTERVAL_15_MINUTES)
    if not entry or entry.get('close') is None:
        return None
    
    current_price = entry['close']
    
    # Jika posisi sudah aktif, cek kondisi exit dan update trailing stop
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
        if trend.get('recommendation') in ['SELL', 'STRONG_SELL']:
            return 'TREND_REVERSAL', current_price
    else:
        # Kondisi entry: cek indikator dan validasi kondisi teknikal
        if (trend.get('recommendation') in ['BUY', 'STRONG_BUY'] and
            entry.get('rsi') is not None and entry.get('rsi_prev') is not None and
            entry['rsi'] < RSI_LIMIT and entry['rsi'] > entry['rsi_prev'] and
            entry.get('macd') is not None and entry.get('signal') is not None and
            entry['macd'] > entry['signal'] and
            entry.get('volume') is not None and entry.get('volume_ma') is not None and
            entry['volume'] > entry['volume_ma'] * 0.8):
            
            risk_data = calculate_risk(current_price, entry.get('atr'))
            if risk_data['risk'] > 5:  # Batasi risiko maksimal 5%
                return None
            return 'BUY', current_price, risk_data
    
    return None

# ==============================
# NOTIFIKASI & EXECUTION
# ==============================
def send_telegram_alert(signal, pair, price, details=None):
    """Mengirim notifikasi lengkap ke Telegram"""
    emoji_map = {
        'BUY': '🚀',
        'TAKE_PROFIT': '✅',
        'STOP_LOSS': '🛑',
        'HOLD_EXPIRED': '⌛',
        'TREND_REVERSAL': '🔄',
        'NO_SIGNAL': 'ℹ️'
    }
    
    # Jika sinyal adalah NO_SIGNAL, buat pesan tersendiri
    if signal == 'NO_SIGNAL':
        message = f"{emoji_map.get(signal)} **No Signal**\nTidak ada sinyal trading untuk saat ini."
    else:
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
            logging.warning("Telegram configuration is missing.")
        logging.info(f"Sent alert: {signal} for {pair}")
    except Exception as e:
        logging.error(f"Telegram error: {e}")

# ==============================
# MAIN LOGIC
# ==============================
def main():
    load_active_buys()
    pairs = get_binance_top_pairs()
    
    if not pairs:
        logging.info("No pairs fetched.")
        print("No pairs fetched.")
        return
    
    any_signal = False
    for pair in pairs:
        # Tampilkan pair yang sedang dicek di console dan log
        print(f"Checking pair: {pair}")
        logging.info(f"Checking pair: {pair}")
        
        result = generate_signal(pair)
        if not result:
            print(f"No signal for {pair}")
            logging.info(f"No signal for {pair}")
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
    
    # Jika tidak ada sinyal sama sekali, kirim notifikasi NO_SIGNAL
    if not any_signal:
        send_telegram_alert("NO_SIGNAL", "ALL", 0)
        logging.info("No signals triggered for any pair")
    
    # Cleanup posisi yang sudah melewati batas waktu
    for pair in list(ACTIVE_BUYS.keys()):
        pos = ACTIVE_BUYS[pair]
        if (datetime.now() - pos['entry_time']).total_seconds() > MAX_HOLD_DURATION_HOURS * 3600:
            send_telegram_alert('HOLD_EXPIRED', pair, pos['entry_price'])
            del ACTIVE_BUYS[pair]
    
    save_active_buys()

if __name__ == "__main__":
    main()
