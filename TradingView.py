import os
import json
import requests
from tradingview_ta import TA_Handler, Interval
from datetime import datetime, timedelta

# ==============================
# KONFIGURASI
# ==============================
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
BUY_SCORE_THRESHOLD = 4
SELL_SCORE_THRESHOLD = 3
ACTIVE_BUYS_FILE = "active_buys.json"

# ==============================
# FUNGSI UTILITAS
# ==============================
def load_active_buys():
    """Membaca daftar aktif buy dari file JSON."""
    if os.path.exists(ACTIVE_BUYS_FILE):
        with open(ACTIVE_BUYS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_active_buys(active_buys):
    """Menyimpan daftar aktif buy ke file JSON."""
    with open(ACTIVE_BUYS_FILE, "w") as f:
        json.dump(active_buys, f, indent=4)

ACTIVE_BUYS = load_active_buys()

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

def analyze_pair(symbol):
    """Menganalisis pair menggunakan TradingView"""
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
            'price': analysis.indicators['close'],
            'adx': analysis.indicators.get('ADX', 0)
        }
        
    except Exception as e:
        print(f"Error analyzing {symbol}: {e}")
        return None

def calculate_scores(data):
    """Hitung score BUY dan SELL berdasarkan indikator"""
    current_price = data['price']
    buy_score = sum([
        "BUY" in data['recommendation'],
        data['rsi'] < 65,
        data['macd'] > data['signal'],
        data['adx'] > 25,
        current_price > data['resistance']*0.99
    ])
    
    sell_score = sum([
        "SELL" in data['recommendation'],
        data['rsi'] > 70,
        data['macd'] < data['signal'],
        data['adx'] < 25,
        current_price < data['support']
    ])
    
    return buy_score, sell_score

def generate_signal(pair, data):
    """Menentukan apakah ada sinyal BUY atau SELL"""
    current_price = data['price']
    buy_score, sell_score = calculate_scores(data)
    
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
    """Mengirim sinyal ke Telegram"""
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
        ACTIVE_BUYS[pair] = {'price': current_price, 'time': datetime.now().isoformat()}

    elif signal_type in ['TAKE PROFIT', 'STOP LOSS', 'SELL']:
        buy_data = ACTIVE_BUYS.pop(pair, {'price': buy_price, 'time': datetime.now().isoformat()})
        profit = ((current_price - buy_data['price']) / buy_data['price']) * 100
        message = f"{base_msg}▫️ Entry Price: ${buy_data['price']:.4f}\n"
        message += f"▫️ {'Profit' if profit > 0 else 'Loss'}: {profit:.2f}%\n"

    save_active_buys(ACTIVE_BUYS)

    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    )

def main():
    pairs = get_binance_top_pairs()
    print(f"🔍 Analyzing {len(pairs)} pairs @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    for pair in pairs:
        data = analyze_pair(pair)
        if not data:
            continue
                
        signal, price = generate_signal(pair, data)
        if signal:
            send_telegram_alert(signal, pair, data['price'], data, price)

if __name__ == "__main__":
    main()
