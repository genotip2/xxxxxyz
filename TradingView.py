import os
import requests
from tradingview_ta import TA_Handler, Interval
from datetime import datetime, timedelta
import json

# ==============================
# KONFIGURASI
# ==============================
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
ACTIVE_BUYS = {}
BUY_SCORE_THRESHOLD = 5
SELL_SCORE_THRESHOLD = 4
FILE_PATH = 'active_buys.json'

# Inisialisasi file JSON
if not os.path.exists(FILE_PATH):
    with open(FILE_PATH, 'w') as f:
        json.dump({}, f)
else:
    with open(FILE_PATH, 'r') as f:
        loaded = json.load(f)
        ACTIVE_BUYS = {
            pair: {
                'price': data['price'],
                'time': datetime.fromisoformat(data['time'])
            } 
            for pair, data in loaded.items()
        }

# ==============================
# FUNGSI UTILITAS
# ==============================
def escape_markdown(text):
    """Escape karakter khusus untuk format MarkdownV2 Telegram"""
    escape_chars = '_*[]()~`>#+-=|{}.!'
    return ''.join(['\\' + char if char in escape_chars else char for char in str(text)])

def save_active_buys_to_json():
    """Simpan data active buys ke file JSON"""
    try:
        to_save = {
            pair: {
                'price': data['price'],
                'time': data['time'].isoformat()
            }
            for pair, data in ACTIVE_BUYS.items()
        }
        
        with open(FILE_PATH, 'w') as f:
            json.dump(to_save, f, indent=4)
            
        print("✅ Berhasil menyimpan active_buys.json")
    except Exception as e:
        print(f"❌ Gagal menyimpan: {str(e)}")

def get_binance_top_pairs():
    """Ambil 50 pair teratas berdasarkan volume trading dari CoinGecko"""
    url = "https://api.coingecko.com/api/v3/exchanges/binance/tickers"
    params = {'include_exchange_logo': 'false', 'order': 'volume_desc'}
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if 'tickers' not in data:
            print("⚠️ Respons CoinGecko tidak valid")
            return []

        usdt_pairs = [t for t in data['tickers'] if t['target'] == 'USDT']
        sorted_pairs = sorted(usdt_pairs, 
                            key=lambda x: x.get('converted_volume', {}).get('usd', 0), 
                            reverse=True)[:50]
        return [f"{p['base']}USDT" for p in sorted_pairs]
    
    except Exception as e:
        print(f"❌ Error fetching data: {e}")
        return []

# ==============================
# FUNGSI ANALISIS TEKNIKAL
# ==============================
def calculate_fibonacci_levels(high, low):
    """Hitung level Fibonacci Retracement"""
    diff = high - low
    return {
        'level_23_6': high - 0.236 * diff,
        'level_38_2': high - 0.382 * diff,
        'level_50': high - 0.5 * diff,
        'level_61_8': high - 0.618 * diff,
        'level_78_6': high - 0.786 * diff
    }

def analyze_pair(symbol):
    """Analisis teknikal dengan indikator multiple"""
    try:
        handler = TA_Handler(
            symbol=symbol,
            exchange="BINANCE",
            screener="CRYPTO",
            interval=Interval.INTERVAL_4_HOURS
        )
        
        analysis = handler.get_analysis()
        indicators = analysis.indicators

        # Validasi data penting
        required_fields = ['close', 'high', 'low', 'RSI', 'MACD.macd', 'MACD.signal']
        if any(ind not in indicators for ind in required_fields):
            print(f"⚠️ Data indikator tidak lengkap untuk {symbol}")
            return None

        fib = calculate_fibonacci_levels(
            indicators['high'],
            indicators['low']
        )
        
        return {
            'recommendation': analysis.summary['RECOMMENDATION'],
            'price': indicators['close'],
            'rsi': indicators['RSI'],
            'macd': indicators['MACD.macd'],
            'signal': indicators['MACD.signal'],
            'adx': indicators.get('ADX', 0),
            'volume': indicators.get('volume', 0),
            'support': fib['level_61_8'],
            'resistance': fib['level_23_6'],
            'bb_upper': indicators.get('BB.upper'),
            'bb_lower': indicators.get('BB.lower'),
            'stoch_rsi_k': indicators.get('Stoch.RSI.K', 50),
            'stoch_rsi_d': indicators.get('Stoch.RSI.D', 50)
        }
        
    except Exception as e:
        print(f"⚠️ Error analisis {symbol}: {str(e)}")
        return None

# ==============================
# LOGIKA TRADING
# ==============================
def calculate_scores(data):
    """Hitung skor trading dengan kriteria terbaru"""
    price = data['price']
    
    buy_conditions = [
        "BUY" in data['recommendation'],
        data['rsi'] < 60,
        data['macd'] > data['signal'],
        data['adx'] > 25,
        price > data['support'],
        data['volume'] > 1e5,
        price < data['bb_lower'] * 1.005,
        data['stoch_rsi_k'] > data['stoch_rsi_d'],
        data['stoch_rsi_k'] < 20
    ]
    
    sell_conditions = [
        "SELL" in data['recommendation'],
        data['rsi'] > 65,
        data['macd'] < data['signal'],
        data['adx'] < 20,
        price < data['support'] * 0.995,
        price > data['bb_upper'] * 0.995,
        data['stoch_rsi_k'] < data['stoch_rsi_d'],
        data['stoch_rsi_k'] > 80
    ]
    
    return sum(buy_conditions), sum(sell_conditions)

def generate_signal(pair, data):
    """Generate sinyal trading dengan logika terupdate"""
    price = data['price']
    buy_score, sell_score = calculate_scores(data)
    display_pair = f"{pair[:-4]}/USDT"

    print(f"{display_pair} - Price: {price:.8f} | Buy: {buy_score}/9 | Sell: {sell_score}/8")

    buy_signal = buy_score >= BUY_SCORE_THRESHOLD and pair not in ACTIVE_BUYS
    sell_signal = sell_score >= SELL_SCORE_THRESHOLD and pair in ACTIVE_BUYS
    take_profit = pair in ACTIVE_BUYS and price >= ACTIVE_BUYS[pair]['price'] * 1.05
    stop_loss = pair in ACTIVE_BUYS and price <= ACTIVE_BUYS[pair]['price'] * 0.98

    if buy_signal:
        return 'BUY', price
    elif take_profit:
        return 'TAKE PROFIT', price
    elif stop_loss:
        return 'STOP LOSS', price
    elif sell_signal:
        return 'SELL', ACTIVE_BUYS[pair]['price']
    
    return None, None

# ==============================
# NOTIFIKASI TELEGRAM
# ==============================
def send_telegram_alert(signal_type, pair, current_price, data, buy_price=None):
    """Kirim notifikasi ke Telegram"""
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
    base_msg += f"📊 Score: BUY {buy_score}/7 | SELL {sell_score}/6\n"

    if signal_type == 'BUY':
        message = f"{base_msg}▫️ Support: ${data['support']:.8f}\n"
        message += f"▫️ Resistance: ${data['resistance']:.8f}\n"
        message += f"🔍 RSI: {data['rsi']:.1f} | MACD: {data['macd']:.8f}\n"
        message += f"📉 BB Lower: ${data['bb_lower']:.8f}"
        ACTIVE_BUYS[pair] = {'price': current_price, 'time': datetime.now()}

    elif signal_type in ['TAKE PROFIT', 'STOP LOSS', 'SELL']:
        entry = ACTIVE_BUYS.get(pair)
        if entry:
            profit = ((current_price - entry['price'])/entry['price'])*100
            duration = str(datetime.now() - entry['time']).split('.')[0]
            
            message = f"{base_msg}▫️ Entry: ${entry['price']:.8f}\n"
            message += f"▫️ P/L: {profit:+.2f}%\n"
            message += f"📈 BB Upper: ${data['bb_upper']:.8f}\n"
            message += f"🕒 Durasi: {duration}"

            if signal_type in ['STOP LOSS', 'SELL']:
                del ACTIVE_BUYS[pair]

    print(f"📢 Mengirim alert: {message}")

    try:
        save_active_buys_to_json()
    except Exception as e:
        print(f"❌ Gagal menyimpan: {str(e)}")

    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    )

# ==============================
# FUNGSI UTAMA
# ==============================
def main():
    """Program utama dengan error handling improved"""
    print(f"🚀 Memulai analisis - {datetime.now().strftime('%d/%m %H:%M')}")
    
    try:
        pairs = get_binance_top_pairs()
        if not pairs:
            print("⚠️ Tidak ada pair yang ditemukan")
            return

        print(f"🔍 Analisis {len(pairs)} pair...")
        
        for pair in pairs:
            try:
                data = analyze_pair(pair)
                if not data:
                    continue

                signal, price = generate_signal(pair, data)
                if signal:
                    send_telegram_alert(signal, pair, data['price'], data, price)
                
                # Auto close position setelah 24 jam atau profit >8%
                if pair in ACTIVE_BUYS:
                    entry = ACTIVE_BUYS[pair]
                    duration = datetime.now() - entry['time']
                    profit = (data['price'] - entry['price'])/entry['price']*100
                    
                    if duration > timedelta(hours=24) or profit >= 8:
                        send_telegram_alert('TAKE PROFIT', pair, data['price'], data)
                    elif profit <= -5:
                        send_telegram_alert('STOP LOSS', pair, data['price'], data)
                        
            except Exception as e:
                print(f"⚠️ Error di {pair}: {str(e)}")
                continue
                
    except KeyboardInterrupt:
        print("\n🛑 Program dihentikan pengguna")
    except Exception as e:
        print(f"🔥 Error kritis: {str(e)}")
    finally:
        save_active_buys_to_json()

if __name__ == "__main__":
    main()
 tradingview_ta import TA_Handler, Interval
from datetime import datetime, timedelta
import json

# ==============================
# KONFIGURASI
# ==============================
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
ACTIVE_BUYS = {}
BUY_SCORE_THRESHOLD = 5
SELL_SCORE_THRESHOLD = 4
FILE_PATH = 'active_buys.json'

# Inisialisasi file JSON dengan handling datetime
if not os.path.exists(FILE_PATH):
    with open(FILE_PATH, 'w') as f:
        json.dump({}, f)
else:
    with open(FILE_PATH, 'r') as f:
        loaded = json.load(f)
        ACTIVE_BUYS = {
            pair: {
                'price': data['price'],
                'time': datetime.fromisoformat(data['time'])
            } 
            for pair, data in loaded.items()
        }

# ==============================
# FUNGSI UTILITAS
# ==============================
def save_active_buys_to_json():
    """Simpan data dengan konversi datetime ke string"""
    try:
        to_save = {}
        for pair, data in ACTIVE_BUYS.items():
            to_save[pair] = {
                'price': data['price'],
                'time': data['time'].isoformat()
            }
            
        with open(FILE_PATH, 'w') as f:
            json.dump(to_save, f, indent=4)
            
        print("✅ Berhasil menyimpan active_buys.json")
    except Exception as e:
        print(f"❌ Gagal menyimpan: {str(e)}")

def get_binance_top_pairs():
    """Ambil 50 pair teratas berdasarkan volume trading"""
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
        print(f"❌ Error fetching data: {e}")
        return []

def calculate_fibonacci_levels(high, low):
    """Hitung level Fibonacci Retracement"""
    diff = high - low
    return {
        'level_23_6': high - 0.236 * diff,
        'level_38_2': high - 0.382 * diff,
        'level_50': high - 0.5 * diff,
        'level_61_8': high - 0.618 * diff,
        'level_78_6': high - 0.786 * diff
    }

# ==============================
# FUNGSI ANALISIS
# ==============================
def analyze_pair(symbol):
    """Analisis teknikal dengan Fibonacci dan Bollinger Bands"""
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
        bb_upper = indicators.get('BB.upper')
        bb_lower = indicators.get('BB.lower')

        # Fibonacci Levels
        high = indicators.get('high')
        low = indicators.get('low')
        fib = calculate_fibonacci_levels(high, low)
        
        return {
            'recommendation': analysis.summary['RECOMMENDATION'],
            'price': indicators.get('close'),
            'rsi': indicators.get('RSI'),
            'macd': indicators.get('MACD.macd'),
            'signal': indicators.get('MACD.signal'),
            'adx': indicators.get('ADX'),
            'volume': indicators.get('volume'),
            'support': fib['level_61_8'],
            'resistance': fib['level_23_6'],
            'bb_upper': bb_upper,
            'bb_lower': bb_lower
        }
        
    except Exception as e:
        print(f"⚠️ Error analisis {symbol}: {str(e)}")
        return None

def calculate_scores(data):
    """Hitung skor trading dengan Bollinger Bands"""
    price = data['price']
    
    buy_conditions = [
        "BUY" in data['recommendation'],
        data['rsi'] < 60,
        data['macd'] > data['signal'],
        data['adx'] > 25,
        price > data['resistance'] * 0.99,
        data['volume'] > 1e6,
        price < data['bb_lower']
    ]
    
    sell_conditions = [
        "SELL" in data['recommendation'],
        data['rsi'] > 65,
        data['macd'] < data['signal'],
        data['adx'] < 20,
        price < data['support'],
        price > data['bb_upper']
    ]
    
    return sum(buy_conditions), sum(sell_conditions)

# ==============================
# FUNGSI TRADING
# ==============================
def generate_signal(pair, data):
    """Generate trading signal"""
    price = data['price']
    buy_score, sell_score = calculate_scores(data)
    display_pair = f"{pair[:-4]}/USDT"

    print(f"{display_pair} - Price: {price:.8f} | Buy: {buy_score}/7 | Sell: {sell_score}/6")

    buy_signal = buy_score >= BUY_SCORE_THRESHOLD and pair not in ACTIVE_BUYS
    sell_signal = sell_score >= SELL_SCORE_THRESHOLD and pair in ACTIVE_BUYS
    take_profit = pair in ACTIVE_BUYS and price > ACTIVE_BUYS[pair]['price'] * 1.05
    stop_loss = pair in ACTIVE_BUYS and price < ACTIVE_BUYS[pair]['price'] * 0.98

    if buy_signal:
        return 'BUY', price
    elif take_profit:
        return 'TAKE PROFIT', price
    elif stop_loss:
        return 'STOP LOSS', price
    elif sell_signal:
        return 'SELL', ACTIVE_BUYS[pair]['price']
    
    return None, None

def send_telegram_alert(signal_type, pair, current_price, data, buy_price=None):
    """Kirim notifikasi ke Telegram"""
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
    base_msg += f"📊 Score: BUY {buy_score}/7 | SELL {sell_score}/6\n"

    if signal_type == 'BUY':
        message = f"{base_msg}▫️ Support: ${data['support']:.8f}\n"
        message += f"▫️ Resistance: ${data['resistance']:.8f}\n"
        message += f"🔍 RSI: {data['rsi']:.1f} | MACD: {data['macd']:.8f}\n"
        message += f"📉 BB Lower: ${data['bb_lower']:.8f}"
        ACTIVE_BUYS[pair] = {'price': current_price, 'time': datetime.now()}

    elif signal_type in ['TAKE PROFIT', 'STOP LOSS', 'SELL']:
        entry = ACTIVE_BUYS.get(pair)
        if entry:
            profit = ((current_price - entry['price'])/entry['price'])*100
            duration = str(datetime.now() - entry['time']).split('.')[0]
            
            message = f"{base_msg}▫️ Entry: ${entry['price']:.8f}\n"
            message += f"▫️ P/L: {profit:+.2f}%\n"
            message += f"📈 BB Upper: ${data['bb_upper']:.8f}\n"
            message += f"🕒 Durasi: {duration}"

            if signal_type in ['STOP LOSS', 'SELL']:
                del ACTIVE_BUYS[pair]

    print(f"📢 Mengirim alert: {message}")

    try:
        save_active_buys_to_json()
    except Exception as e:
        print(f"❌ Gagal menyimpan: {str(e)}")

    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    )

# ==============================
# FUNGSI UTAMA
# ==============================
def main():
    """Program utama"""
    pairs = get_binance_top_pairs()
    print(f"🔍 Memulai analisis {len(pairs)} pair - {datetime.now().strftime('%d/%m %H:%M')}")

    for pair in pairs:
        try:
            data = analyze_pair(pair)
            if not data:
                continue

            display_pair = f"{pair[:-4]}/USDT"
            print(f"\n📈 {display_pair}:")
            print(f"Support: {data['support']:.8f} | Resistance: {data['resistance']:.8f}")
            print(f"BB: {data['bb_lower']:.8f} - {data['bb_upper']:.8f}")
            
            signal, price = generate_signal(pair, data)
            if signal:
                send_telegram_alert(signal, pair, data['price'], data, price)
                
            # Auto close position
            if pair in ACTIVE_BUYS:
                position = ACTIVE_BUYS[pair]
                duration = datetime.now() - position['time']
                profit = (data['price'] - position['price'])/position['price']*100
                
                if duration > timedelta(hours=24) or abs(profit) > 8:
                    send_telegram_alert('SELL', pair, data['price'], data, position['price'])
                    
        except Exception as e:
            print(f"⚠️ Error di {pair}: {str(e)}")
            continue

if __name__ == "__main__":
    main()
