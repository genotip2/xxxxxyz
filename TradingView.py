import os
import json
import requests
import subprocess
from tradingview_ta import TA_Handler, Interval
from datetime import datetime, timedelta

# ==============================
# KONFIGURASI
# ==============================
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
BUY_SCORE_THRESHOLD = 4
SELL_SCORE_THRESHOLD = 3

# ==============================
# FUNGSI LOAD & SAVE ACTIVE BUYS
# ==============================
def load_active_buys():
    """Membaca daftar aktiv buy dari JSON"""
    if os.path.exists("active_buys.json"):
        with open("active_buys.json", "r") as file:
            return json.load(file)
    return {}

def save_active_buys(data):
    """Menyimpan daftar aktiv buy ke JSON"""
    with open("active_buys.json", "w") as file:
        json.dump(data, file, indent=4)

ACTIVE_BUYS = load_active_buys()

# ==============================
# AMBIL 50 PAIR TERATAS DARI BINANCE
# ==============================
def get_binance_top_pairs():
    """Ambil top 50 coin di Binance berdasarkan volume trading"""
    url = "https://api.coingecko.com/api/v3/exchanges/binance/tickers"
    params = {'include_exchange_logo': 'false', 'order': 'volume_desc'}

    try:
        response = requests.get(url, params=params)
        data = response.json()
        usdt_pairs = [t for t in data['tickers'] if t['target'] == 'USDT']
        sorted_pairs = sorted(usdt_pairs, key=lambda x: x['converted_volume']['usd'], reverse=True)[:50]
        return [f"{p['base']}USDT" for p in sorted_pairs]
    except Exception as e:
        print(f"Error fetching data: {e}")
        return []

# ==============================
# ANALISIS TEKNIKAL
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
            'rsi': analysis.indicators['RSI'],
            'macd': analysis.indicators['MACD.macd'],
            'signal': analysis.indicators['MACD.signal'],
            'support': analysis.indicators.get('pivotPoints.standard.S1', 0),
            'resistance': analysis.indicators.get('pivotPoints.standard.R1', 0),
            'price': analysis.indicators['close']
        }
    except Exception as e:
        print(f"Error analyzing {symbol}: {e}")
        return None

# ==============================
# HITUNG SKOR BUY/SELL
# ==============================
def calculate_scores(data):
    buy_score = sum([
        "BUY" in data['recommendation'],
        data['rsi'] < 65,
        data['macd'] > data['signal']
    ])
    
    sell_score = sum([
        "SELL" in data['recommendation'],
        data['rsi'] > 70,
        data['macd'] < data['signal']
    ])
    
    return buy_score, sell_score

# ==============================
# GENERATE SINYAL
# ==============================
def generate_signal(pair, data):
    buy_score, sell_score = calculate_scores(data)
    
    buy_signal = buy_score >= BUY_SCORE_THRESHOLD and pair not in ACTIVE_BUYS
    sell_signal = sell_score >= SELL_SCORE_THRESHOLD and pair in ACTIVE_BUYS
    take_profit = pair in ACTIVE_BUYS and data['price'] > ACTIVE_BUYS[pair]['price'] * 1.05
    stop_loss = pair in ACTIVE_BUYS and data['price'] < ACTIVE_BUYS[pair]['price'] * 0.98

    if buy_signal:
        return 'BUY', data['price']
    elif take_profit:
        return 'TAKE PROFIT', data['price']
    elif stop_loss:
        return 'STOP LOSS', data['price']
    elif sell_signal:
        return 'SELL', ACTIVE_BUYS[pair]['price']
    
    return None, None

# ==============================
# KIRIM SINYAL KE TELEGRAM
# ==============================
def send_telegram_alert(signal_type, pair, current_price, data):
    global ACTIVE_BUYS

    message = f"🚨 **{signal_type} {pair}**\n"
    message += f"▫️ Price: ${current_price:.4f}\n"
    
    if signal_type == 'BUY':
        ACTIVE_BUYS[pair] = {'price': current_price, 'time': datetime.now().isoformat()}
    elif signal_type in ['TAKE PROFIT', 'STOP LOSS', 'SELL']:
        ACTIVE_BUYS.pop(pair, None)

    save_active_buys(ACTIVE_BUYS)
    commit_active_buys()

    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                  json={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'})

# ==============================
# COMMIT KE GITHUB
# ==============================
def commit_active_buys():
    """Commit & push perubahan active_buys.json ke GitHub"""
    try:
        subprocess.run(["git", "config", "--global", "user.name", "GitHub Actions"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "actions@github.com"], check=True)
        subprocess.run(["git", "add", "active_buys.json"], check=True)
        subprocess.run(["git", "commit", "-m", "Update active buys"], check=True)
        subprocess.run(["git", "push"], check=True)
    except Exception as e:
        print(f"Failed to push active buys: {e}")

# ==============================
# MAIN FUNCTION
# ==============================
def main():
    pairs = get_binance_top_pairs()
    
    for pair in pairs:
        data = analyze_pair(pair)
        if not data:
            continue
        
        signal, price = generate_signal(pair, data)
        if signal:
            send_telegram_alert(signal, pair, price, data)

if __name__ == "__main__":
    main()
