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
ACTIVE_BUYS_FILE = 'active_buys.json'
MAX_HOLD_HOURS = 24
STOP_LOSS = -2  # -2%
TAKE_PROFIT = 5  # +5%
BUY_SCORE_THRESHOLD = 6
SELL_SCORE_THRESHOLD = 6

# ==============================
# FUNGSI UTILITAS
# ==============================
def load_active_buys():
    """Load data dari file dengan konversi waktu"""
    try:
        with open(ACTIVE_BUYS_FILE, 'r') as f:
            data = json.load(f)
        return {
            k: {
                'price': v['price'],
                'time': datetime.strptime(v['time'], '%Y-%m-%d %H:%M:%S')
            } for k, v in data.items()
        }
    except:
        return {}

def save_active_buys():
    """Simpan data ke file dengan konversi waktu"""
    converted = {
        k: {
            'price': v['price'],
            'time': v['time'].strftime('%Y-%m-%d %H:%M:%S')
        } for k, v in ACTIVE_BUYS.items()
    }
    with open(ACTIVE_BUYS_FILE, 'w') as f:
        json.dump(converted, f, indent=4)

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
                            reverse=True)[:100]
        return [f"{p['base']}USDT" for p in sorted_pairs]
    except Exception as e:
        print(f"❌ Error fetching data: {e}")
        return []

# ==============================
# FUNGSI ANALISIS
# ==============================
def analyze_pair(symbol):
    try:
        handler_m15 = TA_Handler(
            symbol=symbol,
            exchange="BINANCE",
            screener="CRYPTO",
            interval=Interval.INTERVAL_15_MINUTES
        )
        handler_h1 = TA_Handler(
            symbol=symbol,
            exchange="BINANCE",
            screener="CRYPTO",
            interval=Interval.INTERVAL_1_HOUR
        )

        analysis_m15 = handler_m15.get_analysis()
        analysis_h1 = handler_h1.get_analysis()

        return {
            'ema10_m15': analysis_m15.indicators.get('EMA10'),
            'ema20_m15': analysis_m15.indicators.get('EMA20'),
            'rsi_m15': analysis_m15.indicators.get('RSI'),
            'macd_m15': analysis_m15.indicators.get('MACD.macd'),
            'macd_signal_m15': analysis_m15.indicators.get('MACD.signal'),
            'bb_lower_m15': analysis_m15.indicators.get('BB.lower'),
            'bb_upper_m15': analysis_m15.indicators.get('BB.upper'),
            'close_price_m15': analysis_m15.indicators.get('close'),
            'adx_m15': analysis_m15.indicators.get('ADX'),
            'candle_m15': analysis_m15.summary['RECOMMENDATION'],

            'ema10_h1': analysis_h1.indicators.get('EMA10'),
            'ema20_h1': analysis_h1.indicators.get('EMA20'),
            'rsi_h1': analysis_h1.indicators.get('RSI'),
            'macd_h1': analysis_h1.indicators.get('MACD.macd'),
            'macd_signal_h1': analysis_h1.indicators.get('MACD.signal'),
            'bb_lower_h1': analysis_h1.indicators.get('BB.lower'),
            'bb_upper_h1': analysis_h1.indicators.get('BB.upper'),
            'close_price_h1': analysis_h1.indicators.get('close'),
            'adx_h1': analysis_h1.indicators.get('ADX'),
            'candle_h1': analysis_h1.summary['RECOMMENDATION'],

            'stoch_rsi_m15': analysis_m15.indicators.get('Stoch.RSI'),
            'williams_r_m15': analysis_m15.indicators.get('Williams %R'),
            'awesome_oscillator_m15': analysis_m15.indicators.get('Awesome Oscillator')
        }
    except Exception as e:
        print(f"⚠️ Error analisis {symbol}: {str(e)}")
        return None

# ==============================
# FUNGSI TRADING
# ==============================
def safe_compare(val1, val2, operator='>'):
    """Helper untuk membandingkan nilai dengan handling None"""
    if val1 is None or val2 is None:
        return False
    if operator == '>':
        return val1 > val2
    elif operator == '<':
        return val1 < val2
    return False

def calculate_scores(data):
    """Hitung skor beli/jual berdasarkan indikator"""
    price = data['close_price_m15']
    buy_conditions = [
        safe_compare(data['ema10_m15'], data['ema20_m15'], '>'),
        safe_compare(data['ema10_h1'], data['ema20_h1'], '>'),
        data['rsi_m15'] < 30 if data['rsi_m15'] else False,
        safe_compare(data['macd_m15'], data['macd_signal_m15'], '>'),
        price <= data['bb_lower_m15'],
        data['adx_h1'] > 25 if data['adx_h1'] else False,
        any(x in data['candle_m15'] for x in ['BUY', 'STRONG_BUY']),
        data['stoch_rsi_m15'] < 20 if data['stoch_rsi_m15'] else False,
        data['williams_r_m15'] < -80 if data['williams_r_m15'] else False,
        data['awesome_oscillator_m15'] > 0 if data['awesome_oscillator_m15'] else False
    ]

    sell_conditions = [
        safe_compare(data['ema10_m15'], data['ema20_m15'], '<'),
        safe_compare(data['ema10_h1'], data['ema20_h1'], '<'),
        data['rsi_h1'] > 70 if data['rsi_h1'] else False,
        safe_compare(data['macd_h1'], data['macd_signal_h1'], '<'),
        price >= data['bb_upper_h1'],
        data['adx_h1'] > 25 if data['adx_h1'] else False,
        any(x in data['candle_m15'] for x in ['SELL', 'STRONG_SELL']),
        data['stoch_rsi_m15'] > 80 if data['stoch_rsi_m15'] else False,
        data['williams_r_m15'] > -20 if data['williams_r_m15'] else False,
        data['awesome_oscillator_m15'] < 0 if data['awesome_oscillator_m15'] else False
    ]

    return sum(buy_conditions), sum(sell_conditions)

def generate_signal(pair, data):
    """Generate sinyal trading"""
    current_price = data['close_price_m15']
    buy_score, sell_score = calculate_scores(data)

    buy_signal = buy_score >= BUY_SCORE_THRESHOLD and pair not in ACTIVE_BUYS
    sell_signal = sell_score >= SELL_SCORE_THRESHOLD and pair in ACTIVE_BUYS

    if buy_signal:
        return 'BUY', current_price
    elif sell_signal:
        return 'SELL', current_price
    return None, None

def send_telegram_alert(signal_type, pair, current_price, entry_price=None,
                       profit_pct=None, hold_duration=None, data=None,
                       buy_score=None, sell_score=None):
    """Kirim notifikasi ke Telegram"""
    display_pair = f"{pair[:-4]}/USDT"
    emoji = {
        'BUY': '🚀',
        'SELL': '⚠️',
        'TAKE PROFIT': '✅',
        'STOP LOSS': '🛑',
        'EXPIRED': '⌛'
    }.get(signal_type.split()[0], 'ℹ️')

    message = f"{emoji} *{signal_type}*\n"
    message += f"💱 *Pair:* {display_pair}\n"
    
    if current_price is not None:  
        message += f"💰 *Price:* ${current_price:.8f}\n"  

    if entry_price:
        message += f"🔹 *Entry Price:* ${entry_price:.8f}\n"
        message += f"📈 *{'Profit' if profit_pct > 0 else 'Loss'}:* {profit_pct:+.2f}%\n"
        message += f"⏳ *Hold Duration:* {hold_duration}\n"

    if buy_score is not None and sell_score is not None:
        message += f"📊 *Buy Score:* {buy_score}/10 📉 *Sell Score:* {sell_score}/10"
    elif buy_score is not None:
        message += f"📊 *Buy Score:* {buy_score}/10"
    elif sell_score is not None:
        message += f"📉 *Sell Score:* {sell_score}/10"

    if data and signal_type == 'BUY':
        message += f"📌 *RSI:*M15 = {data['rsi_m15']:.1f} | H1 = {data['rsi_h1']:.1f}\n"
        message += f"🎯 *MACD Cross:* {'Bullish' if data['macd_m15'] > data['macd_signal_m15'] else 'Bearish'}\n"
        message += f"🔍 *Stoch RSI:* {data['stoch_rsi_m15']:.1f}\n"
        message += f"🔍 *Williams %R:* {data['williams_r_m15']:.1f}\n"
        message += f"🔍 *Awesome Oscillator:* {data['awesome_oscillator_m15']:.1f}\n"

    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                'chat_id': TELEGRAM_CHAT_ID,
                'text': message,
                'parse_mode': 'Markdown'
            }
        )

        print(f"📢 Mengirim alert: {signal_type} - {pair}")

        # Handle removal of ACTIVE_BUYS based on signal type
        if signal_type in ['SELL', 'STOP LOSS', 'EXPIRED']:
            if pair in ACTIVE_BUYS:
                del ACTIVE_BUYS[pair]
                save_active_buys()

    except Exception as e:
        print(f"❌ Gagal mengirim alert: {str(e)}")

# ==============================
# INISIALISASI DATA
# ==============================
ACTIVE_BUYS = load_active_buys()

# ==============================
# FUNGSI UTAMA
# ==============================
def main():
    """Program utama"""
    top_pairs = get_binance_top_pairs()
    active_pairs = list(ACTIVE_BUYS.keys())
    all_pairs = list(set(top_pairs + active_pairs))
    current_prices = {}

    print(f"🔍 Memulai analisis {len(all_pairs)} pair - {datetime.now().strftime('%d/%m %H:%M')}")

    for pair in all_pairs:
        try:
            data = analyze_pair(pair)
            if not data:
                continue

            current_price = data['close_price_m15']
            current_prices[pair] = current_price
            buy_score, sell_score = calculate_scores(data)

            print(f"\n📊 {pair[:-4]}/USDT - Price: {current_price:.8f} | Buy Score: {buy_score}/10 | Sell Score: {sell_score}/10")
            print(f"📌 RSI M15: {data['rsi_m15']:.1f} | RSI H1: {data['rsi_h1']:.1f}")

            signal, price = generate_signal(pair, data)
            buy_score, sell_score = calculate_scores(data)

            if signal == 'BUY':
                ACTIVE_BUYS[pair] = {'price': price, 'time': datetime.now()}
                send_telegram_alert(
                    signal_type='BUY',
                    pair=pair,
                    current_price=price,
                    data=data,
                    buy_score=buy_score,
                    sell_score=sell_score
                )
                save_active_buys()

            elif signal == 'SELL':
                entry_price = ACTIVE_BUYS[pair]['price']
                profit_pct = ((price - entry_price)/entry_price)*100
                hold_duration = str(datetime.now() - ACTIVE_BUYS[pair]['time']).split('.')[0]
                send_telegram_alert(
                    signal_type='SELL',
                    pair=pair,
                    current_price=price,
                    entry_price=entry_price,
                    profit_pct=profit_pct,
                    hold_duration=hold_duration,
                    buy_score=buy_score,
                    sell_score=sell_score
                )

            # Check for TAKE PROFIT, STOP LOSS, and EXPIRED conditions
            if pair in ACTIVE_BUYS:
                entry_price = ACTIVE_BUYS[pair]['price']
                profit_pct = ((current_price - entry_price)/entry_price)*100
                hold_duration = str(datetime.now() - ACTIVE_BUYS[pair]['time']).split('.')[0]

                if profit_pct >= TAKE_PROFIT:
                    send_telegram_alert(
                        signal_type='TAKE PROFIT',
                        pair=pair,
                        current_price=current_price,
                        entry_price=entry_price,
                        profit_pct=profit_pct,
                        hold_duration=hold_duration
                    )
                elif profit_pct <= STOP_LOSS:
                    send_telegram_alert(
                        signal_type='STOP LOSS',
                        pair=pair,
                        current_price=current_price,
                        entry_price=entry_price,
                        profit_pct=profit_pct,
                        hold_duration=hold_duration
                    )
                elif (datetime.now() - ACTIVE_BUYS[pair]['time']) > timedelta(hours=MAX_HOLD_HOURS):
                    send_telegram_alert(
                        signal_type='EXPIRED',
                        pair=pair,
                        current_price=current_price,
                        entry_price=entry_price,
                        profit_pct=profit_pct,
                        hold_duration=hold_duration
                    )

        except Exception as e:
            print(f"⚠️ Error di {pair}: {str(e)}")
            continue

if __name__ == "__main__":
    main()
