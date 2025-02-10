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
ACTIVE_BUYS_FILE = 'active_buys.json'
BUY_SCORE_THRESHOLD = 5
SELL_SCORE_THRESHOLD = 5
PROFIT_TARGET_PERCENTAGE = 5    # Target profit 5%
STOP_LOSS_PERCENTAGE = 2        # Stop loss 2%
MAX_HOLD_DURATION_HOUR = 24     # Durasi hold maksimum 24 jam
PAIR = 50

# Inisialisasi file JSON dengan handling datetime
if not os.path.exists(ACTIVE_BUYS_FILE):
    with open(ACTIVE_BUYS_FILE, 'w') as f:
        json.dump({}, f)
else:
    with open(ACTIVE_BUYS_FILE, 'r') as f:
        loaded = json.load(f)
    ACTIVE_BUYS = {
        pair: {
            'price': data['price'],
            'time': datetime.fromisoformat(data['time'])
        } for pair, data in loaded.items()
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
        with open(ACTIVE_BUYS_FILE, 'w') as f:
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
                              reverse=True)[:PAIR]
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
            'recommendation': analysis.summary.get('RECOMMENDATION'),
            'price': indicators.get('close'),
            'rsi': indicators.get('RSI'),
            'macd': indicators.get('MACD.macd'),
            'signal': indicators.get('MACD.signal'),
            'adx': indicators.get('ADX'),
            'volume': indicators.get('volume'),
            # Dua level support dan resistance
            'support_1': fib['level_61_8'],
            'support_2': fib['level_78_6'],
            'resistance_1': fib['level_23_6'],
            'resistance_2': fib['level_38_2'],
            'bb_upper': bb_upper,
            'bb_lower': bb_lower
        }
    except Exception as e:
        print(f"⚠️ Error analisis {symbol}: {str(e)}")
        return None

def calculate_scores(data):
    """
    Hitung skor trading dengan menggabungkan kedua level support/resistance menjadi satu kondisi.
    Mengembalikan:
      - buy_score, sell_score
      - daftar indikator yang terpenuhi untuk kondisi BUY (buy_met)
      - daftar indikator yang terpenuhi untuk kondisi SELL (sell_met)
    """
    current_price = data['price']

    # Kondisi resistance untuk sinyal BUY (jika harga mendekati salah satu resistance)
    resistance_condition = (current_price > data['resistance_1'] * 0.99) or (current_price > data['resistance_2'] * 0.99)
    # Kondisi support untuk sinyal SELL (jika harga berada di bawah salah satu support)
    support_condition = (current_price < data['support_1']) or (current_price < data['support_2'])

    buy_conditions = [
        (((("BUY" in data['recommendation']) or ("STRONG_BUY" in data['recommendation'])) if data['recommendation'] else False),
         "Recommendation indicates BUY"),
        (data['rsi'] < 60, f"RSI < 60 (current: {data['rsi']})"),
        (data['macd'] > data['signal'], f"MACD ({data['macd']}) > Signal ({data['signal']})"),
        (data['adx'] > 25, f"ADX > 25 (current: {data['adx']})"),
        (resistance_condition, "Price near one of the Resistance Levels"),
        (data['volume'] > 1e6, f"Volume > 1,000,000 (current: {data['volume']})"),
        (current_price < data['bb_lower'], f"Price < Bollinger Lower ({data['bb_lower']})")
    ]

    sell_conditions = [
        (((("SELL" in data['recommendation']) or ("STRONG_SELL" in data['recommendation'])) if data['recommendation'] else False),
         "Recommendation indicates SELL"),
        (data['rsi'] > 65, f"RSI > 65 (current: {data['rsi']})"),
        (data['macd'] < data['signal'], f"MACD ({data['macd']}) < Signal ({data['signal']})"),
        (data['adx'] < 20, f"ADX < 20 (current: {data['adx']})"),
        (support_condition, "Price below one of the Support Levels"),
        (current_price > data['bb_upper'], f"Price > Bollinger Upper ({data['bb_upper']})")
    ]

    buy_score = sum(1 for cond, _ in buy_conditions if cond)
    sell_score = sum(1 for cond, _ in sell_conditions if cond)
    buy_met = [desc for cond, desc in buy_conditions if cond]
    sell_met = [desc for cond, desc in sell_conditions if cond]

    return buy_score, sell_score, buy_met, sell_met

# ==============================
# FUNGSI TRADING
# ==============================

def generate_signal(pair, data):
    """Generate trading signal berdasarkan perhitungan skor"""
    current_price = data['price']
    buy_score, sell_score, buy_met, sell_met = calculate_scores(data)
    display_pair = f"{pair[:-4]}/USDT"

    print(f"{display_pair} - Price: {current_price:.8f} | Buy: {buy_score}/7 | Sell: {sell_score}/6")
    print(f"  Triggered Buy Indicators: {', '.join(buy_met) if buy_met else 'None'}")
    print(f"  Triggered Sell Indicators: {', '.join(sell_met) if sell_met else 'None'}")

    buy_signal = buy_score >= BUY_SCORE_THRESHOLD and pair not in ACTIVE_BUYS
    sell_signal = sell_score >= SELL_SCORE_THRESHOLD and pair in ACTIVE_BUYS
    take_profit = pair in ACTIVE_BUYS and current_price > ACTIVE_BUYS[pair]['price'] * 1.05
    stop_loss = pair in ACTIVE_BUYS and current_price < ACTIVE_BUYS[pair]['price'] * 0.98

    if buy_signal:
        return 'BUY', current_price
    elif take_profit:
        return 'TAKE PROFIT', current_price
    elif stop_loss:
        return 'STOP LOSS', current_price
    elif sell_signal:
        return 'SELL', ACTIVE_BUYS[pair]['price']

    return None, None

def send_telegram_alert(signal_type, pair, current_price, data, buy_price=None):
    """Kirim notifikasi ke Telegram"""
    display_pair = f"{pair[:-4]}/USDT"
    message = ""
    buy_score, sell_score, buy_met, sell_met = calculate_scores(data)

    emoji = {
        'BUY': '🚀',
        'SELL': '⚠️',
        'TAKE PROFIT': '✅',
        'STOP LOSS': '🛑',
        'EXPIRED': '⌛'
    }.get(signal_type, 'ℹ️')

    base_msg = f"{emoji} *{signal_type}*\n"
    base_msg += f"💱 *{display_pair}*\n"
    base_msg += f"💲 *Price:* ${current_price:.8f}\n"
    base_msg += f"📊 *Score:* Buy {buy_score}/7 | Sell {sell_score}/6\n"

    if signal_type == 'BUY':
        indicators_msg = "\n*Triggered Buy Indicators:*\n" + ("\n".join(f"- {i}" for i in buy_met) if buy_met else "None")
        message = base_msg + f"🔍 *RSI:* {data['rsi']:.2f}\n" + indicators_msg
        ACTIVE_BUYS[pair] = {'price': current_price, 'time': datetime.now()}
    elif signal_type == 'EXPIRED':
        entry = ACTIVE_BUYS.get(pair)
        if entry:
            profit = ((current_price - entry['price']) / entry['price']) * 100
            duration = str(datetime.now() - entry['time']).split('.')[0]
            message = base_msg + f"▫️ *Entry:* ${entry['price']:.8f}\n"
            message += f"💰 *{'Profit' if profit > 0 else 'Loss'}:* {profit:+.2f}%\n"
            message += f"🕒 *Durasi:* {duration}\n"
            message += "\n*Posisi sudah melebihi durasi maksimal, EXPIRED*"
            del ACTIVE_BUYS[pair]
    elif signal_type in ['TAKE PROFIT', 'STOP LOSS', 'SELL']:
        entry = ACTIVE_BUYS.get(pair)
        if entry:
            profit = ((current_price - entry['price']) / entry['price']) * 100
            duration = str(datetime.now() - entry['time']).split('.')[0]
            indicators_msg = "\n*Triggered Sell Indicators:*\n" + ("\n".join(f"- {i}" for i in sell_met) if sell_met else "None")
            message = base_msg + f"▫️ *Entry:* ${entry['price']:.8f}\n"
            message += f"💰 *{'Profit' if profit > 0 else 'Loss'}:* {profit:+.2f}%\n"
            message += f"🕒 *Durasi:* {duration}\n"
            message += indicators_msg
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
    """Program utama untuk analisis dan pengiriman sinyal"""
    pairs = get_binance_top_pairs()
    print(f"🔍 Memulai analisis {len(pairs)} pair - {datetime.now().strftime('%d/%m %H:%M')}")

    for pair in pairs:
        try:
            data = analyze_pair(pair)
            if not data:
                continue

            display_pair = f"{pair[:-4]}/USDT"
            print(f"\n📈 {display_pair}:")
            print(f"Support Levels: {data['support_1']:.8f} & {data['support_2']:.8f} | Resistance Levels: {data['resistance_1']:.8f} & {data['resistance_2']:.8f}")
            print(f"BB: {data['bb_lower']:.8f} - {data['bb_upper']:.8f}")

            current_price = data['price']
            signal, signal_price = generate_signal(pair, data)
            if signal:
                send_telegram_alert(signal, pair, current_price, data, signal_price)

            # Auto close posisi jika sudah terlalu lama atau profit/loss melebihi batas
            if pair in ACTIVE_BUYS:
                position = ACTIVE_BUYS[pair]
                duration = datetime.now() - position['time']
                current_price = data['price']
                profit = (current_price - position['price']) / position['price'] * 100

                if duration > timedelta(hours=MAX_HOLD_DURATION_HOUR):
                    send_telegram_alert('EXPIRED', pair, current_price, data, position['price'])
                elif abs(profit) > 8:
                    send_telegram_alert('SELL', pair, current_price, data, position['price'])

        except Exception as e:
            print(f"⚠️ Error di {pair}: {str(e)}")
            continue

if __name__ == "__main__":
    main()
