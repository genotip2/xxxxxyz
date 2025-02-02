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
ACTIVE_BUYS = {}  # Menyimpan posisi BUY yang sedang aktif
BUY_SCORE_THRESHOLD = 4
SELL_SCORE_THRESHOLD = 3
FILE_PATH = 'active_buys.json'

# Inisialisasi file JSON jika belum ada
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
    """Ambil top 50 coin di Binance berdasarkan volume trading"""
    url = "https://api.coingecko.com/api/v3/exchanges/binance/tickers"
    params = {'include_exchange_logo': 'false', 'order': 'volume_desc'}
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        
        # Filter hanya USDT pairs dan urutkan berdasarkan volume
        usdt_pairs = [t for t in data['tickers'] if t['target'] == 'USDT']
        sorted_pairs = sorted(usdt_pairs, 
                              key=lambda x: x['converted_volume']['usd'], 
                              reverse=True)[:50]
        
        return [f"{p['base']}USDT" for p in sorted_pairs]
    
    except Exception as e:
        print(f"❌ Error fetching Binance data: {e}")
        return []

# ==============================
# FUNGSI ANALISIS TEKNIKAL (REVISI)
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
        
        return {
            'recommendation': analysis.summary['RECOMMENDATION'],
            'rsi': analysis.indicators.get('RSI', 0),
            'macd': analysis.indicators.get('MACD.macd', 0),
            'signal': analysis.indicators.get('MACD.signal', 0),
            'support': analysis.indicators.get('Pivot.M.S1', 0),
            'resistance': analysis.indicators.get('Pivot.M.R1', 0),
            'price': analysis.indicators.get('close', 0),
            'volume': analysis.indicators.get('volume', 0),
            'adx': analysis.indicators.get('ADX', 0)
        }
        
    except Exception as e:
        print(f"⚠️ Error analyzing {symbol}: {str(e)}")
        return None

# ==============================
# FUNGSI PENGHITUNGAN SKOR SINYAL (REVISI)
# ==============================
def calculate_scores(data):
    """Hitung score BUY dan SELL berdasarkan indikator"""
    current_price = data['price']
    
    buy_score = sum([
        "BUY" in data['recommendation'],
        data['rsi'] < 65,
        data['macd'] > data['signal'],
        data['adx'] > 25,
        current_price > data['resistance'] * 0.99 if data['resistance'] else False,
        data['volume'] > 1e6
    ])
    
    sell_score = sum([
        "SELL" in data['recommendation'],
        data['rsi'] > 70,
        data['macd'] < data['signal'],
        data['adx'] < 25,
        current_price < data['support'] if data['support'] else False
    ])
    
    return buy_score, sell_score

# ==============================
# FUNGSI MENYIMPAN DATA KE FILE JSON (REVISI)
# ==============================
def save_active_buys_to_json():
    """Simpan data ACTIVE_BUYS ke dalam file JSON"""
    try:
        with open(FILE_PATH, 'w') as f:
            json.dump(ACTIVE_BUYS, f, indent=4, default=str)
        print("✅ Berhasil menyimpan active_buys.json")
    except Exception as e:
        print(f"❌ Gagal menyimpan JSON: {str(e)}")

# ==============================
# FUNGSI COMMIT DAN PUSH KE GITHUB
# ==============================
def commit_and_push_changes():
    """Commit dan push perubahan file JSON ke GitHub"""
    try:
        subprocess.run(['git', 'add', FILE_PATH], check=True)
        commit_message = f"Update active buys data @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        subprocess.run(['git', 'commit', '-m', commit_message], check=True)
        subprocess.run(['git', 'push', 'origin', 'main'], check=True)
        print(f"Successfully committed and pushed to GitHub: {commit_message}")
    except subprocess.CalledProcessError as e:
        print(f"Error occurred during git commit/push: {e}")

# ==============================
# FUNGSI GENERATOR SINYAL
# ==============================
def generate_signal(pair, data):
    current_price = data['price']
    buy_score, sell_score = calculate_scores(data)

    print(f"{pair} - Price: {current_price:.4f} | Buy Score: {buy_score}/6 | Sell Score: {sell_score}/5")

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

# ==============================
# FUNGSI KIRIM NOTIFIKASI TELEGRAM
# ==============================
def send_telegram_alert(signal_type, pair, current_price, data, buy_price=None):
    message = ""
    buy_score, sell_score = calculate_scores(data)
    emoji = {
        'BUY': '🚀', 
        'SELL': '⚠️', 
        'TAKE PROFIT': '✅', 
        'STOP LOSS': '🛑'
    }.get(signal_type, 'ℹ️')

    base_msg = f"{emoji} **{signal_type} {pair}**\n"
    base_msg += f"▫️ Price: ${current_price:.4f}\n"
    base_msg += f"📊 Buy Score: {buy_score}/6 | Sell Score: {sell_score}/5\n"

    if signal_type == 'BUY':
        message = f"{base_msg}▫️ Support: ${data['support']:.2f}\n"
        message += f"▫️ Resistance: ${data['resistance']:.2f}\n"
        message += f"🔍 RSI: {data['rsi']:.1f} | MACD: {data['macd']:.4f}"
        ACTIVE_BUYS[pair] = {'price': current_price, 'time': datetime.now()}

    elif signal_type in ['TAKE PROFIT', 'STOP LOSS', 'SELL']:
        buy_data = ACTIVE_BUYS.get(pair, {'price': buy_price, 'time': datetime.now()})
        profit = ((current_price - buy_data['price'])/buy_data['price'])*100
        duration = str(datetime.now() - buy_data['time']).split('.')[0]
        
        message = f"{base_msg}▫️ Entry Price: ${buy_data['price']:.4f}\n"
        message += f"▫️ {'Profit' if profit > 0 else 'Loss'}: {profit:.2f}%\n"
        message += f"🕒 Hold Duration: {duration}"

        if signal_type in ['STOP LOSS', 'SELL']:
            del ACTIVE_BUYS[pair]

    print(f"📢 Sending Telegram alert: {message}")

    try:
        save_active_buys_to_json()
        commit_and_push_changes()
    except Exception as e:
        print(f"❌ Gagal menyimpan/commit: {str(e)}")

    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    )

# ==============================
# FUNGSI UTAMA
# ==============================
def main():
    pairs = get_binance_top_pairs()
    print(f"🔍 Analysing {len(pairs)} pairs @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    for pair in pairs:
        try:
            formatted_pair = pair.replace('USDT', '/USDT')
            data = analyze_pair(formatted_pair)
            
            if not data:
                print(f"⚠️ Tidak ada data untuk {pair}")
                continue

            print(f"\n🔎 {formatted_pair} Analysis:")
            print(f"Support: {data['support']} | Resistance: {data['resistance']}")
            print(f"RSI: {data['rsi']} | MACD: {data['macd']:.4f}")
            
            signal, price = generate_signal(pair, data)
            if signal:
                send_telegram_alert(signal, pair, data['price'], data, price)
                
            if pair in ACTIVE_BUYS:
                buy_data = ACTIVE_BUYS[pair]
                hold_time = datetime.now() - buy_data['time']
                current_profit = (data['price'] - buy_data['price'])/buy_data['price']*100
                
                if hold_time > timedelta(hours=24) or abs(current_profit) > 5:
                    send_telegram_alert('SELL', pair, data['price'], data, buy_data['price'])
                    
        except Exception as e:
            print(f"⚠️ Error processing {pair}: {str(e)}")
            continue

if __name__ == "__main__":
    main()
