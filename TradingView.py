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
TOP_PAIRS_FILE = 'top_pairs.json'  # File untuk menyimpan daftar top pair
TOP_PAIRS = 250
BUY_SCORE_THRESHOLD = 5
SELL_SCORE_THRESHOLD = 4
PROFIT_TARGET_PERCENTAGE = 5    # Target profit 5%
STOP_LOSS_PERCENTAGE = 2        # Stop loss 2%
MAX_HOLD_DURATION_HOUR = 24     # Durasi hold maksimum 24 jam

# Inisialisasi file active_buys.json dengan handling datetime
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
            } 
            for pair, data in loaded.items()
        }

# ==============================
# FUNGSI UTILITAS
# ==============================
def save_active_buys_to_json():
    """Simpan data active buys dengan mengonversi datetime ke string."""
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

def get_binance_usdt_pairs():
    """
    Ambil daftar pair dari Binance dengan quote asset USDT dan status TRADING.
    Jika terjadi error (misalnya karena IP terblokir), kembalikan None sehingga proses filtering diabaikan.
    """
    url = "https://api.binance.com/api/v3/exchangeInfo"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        binance_symbols = {
            s["symbol"] for s in data["symbols"]
            if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"
        }
        return binance_symbols
    except Exception as e:
        print(f"❌ Error fetching Binance exchange info: {e}")
        return None

def get_binance_top_pairs():
    """
    Ambil 50 coin dengan penurunan harga terbesar (24 jam) dari CoinGecko
    menggunakan endpoint /coins/markets.
    Jika memungkinkan, filter hanya coin yang tersedia di Binance (berdasarkan pair misalnya 'BTCUSDT').
    Apabila pemanggilan API Binance gagal, gunakan seluruh coin dari CoinGecko.
    Data diurutkan berdasarkan price_change_percentage_24h secara ascending (nilai paling negatif artinya penurunan terbesar).
    """
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",  # Urutkan awal berdasarkan kapitalisasi pasar
        "per_page": 250,
        "page": 1,
        "price_change_percentage": "24h"
    }
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Pastikan respons OK (status 200)
        data = response.json()
        
        # Filter coin yang memiliki informasi perubahan harga 24 jam
        coins_with_change = [coin for coin in data if coin.get("price_change_percentage_24h") is not None]
        if not coins_with_change:
            print("Tidak ada coin dengan informasi perubahan harga 24 jam.")
            return []
        
        # Urutkan coin berdasarkan price_change_percentage_24h secara ascending 
        sorted_coins = sorted(coins_with_change, key=lambda coin: coin["price_change_percentage_24h"])
        
        # Ambil daftar pair yang tersedia di Binance (jika API Binance berhasil)
        binance_pairs = get_binance_usdt_pairs()
        if binance_pairs:
            available_coins = [
                coin for coin in sorted_coins
                if f"{coin['symbol'].upper()}USDT" in binance_pairs
            ]
        else:
            # Jika gagal mendapatkan daftar pair dari Binance, gunakan semua coin dari CoinGecko
            available_coins = sorted_coins
        
        # Ambil 50 coin teratas dari yang tersedia
        top_dropped = available_coins[:TOP_PAIRS]
        return [f"{coin['symbol'].upper()}USDT" for coin in top_dropped]
    except Exception as e:
        print(f"❌ Error fetching data dari CoinGecko: {e}")
        return []

def load_top_pairs_from_file():
    """
    Muat daftar pair dari file TOP_PAIRS_FILE.
    Jika file tidak ada atau tanggal 'last_updated' tidak sama dengan hari UTC saat ini,
    maka perbarui daftar pair dengan memanggil get_binance_top_pairs() dan simpan ke file.
    """
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if os.path.exists(TOP_PAIRS_FILE):
        try:
            with open(TOP_PAIRS_FILE, "r") as f:
                data = json.load(f)
            last_updated = data.get("last_updated")
            pairs = data.get("pairs", [])
            if last_updated == today and pairs:
                print(f"🔄 Menggunakan daftar pair cached dari {last_updated}")
                return pairs
            else:
                print("ℹ️ Data top pairs sudah usang. Memperbarui daftar...")
        except Exception as e:
            print("❌ Error membaca file top pairs:", e)
    
    # Jika file tidak ada atau data sudah usang, ambil data baru dan simpan
    pairs = get_binance_top_pairs()
    data_to_save = {"last_updated": today, "pairs": pairs}
    try:
        with open(TOP_PAIRS_FILE, "w") as f:
            json.dump(data_to_save, f, indent=4)
        print(f"✅ Disimpan daftar pair untuk {today} ke {TOP_PAIRS_FILE}")
    except Exception as e:
        print("❌ Error menyimpan file top pairs:", e)
    return pairs

def analyze_pair(symbol):
    """Lakukan analisis teknikal pada pair dengan berbagai time frame.
       Jika terjadi error (misalnya pair tidak tersedia di Binance), kembalikan None.
    """
    try:
        handler_m1 = TA_Handler(
            symbol=symbol,
            exchange="BINANCE",
            screener="CRYPTO",
            interval=Interval.INTERVAL_1_MINUTE
        )
        handler_m5 = TA_Handler(
            symbol=symbol,
            exchange="BINANCE",
            screener="CRYPTO",
            interval=Interval.INTERVAL_5_MINUTES
        )
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

        analysis_m1 = handler_m1.get_analysis()
        analysis_m5 = handler_m5.get_analysis()
        analysis_m15 = handler_m15.get_analysis()
        analysis_h1 = handler_h1.get_analysis()

        return {
            'current_price': analysis_m5.indicators.get('close'),
            'ema5_m5': analysis_m5.indicators.get('EMA5'),
            'ema10_m5': analysis_m5.indicators.get('EMA10'),
            'rsi_m5': analysis_m5.indicators.get('RSI'),
            'macd_m5': analysis_m5.indicators.get('MACD.macd'),
            'macd_signal_m5': analysis_m5.indicators.get('MACD.signal'),
            'bb_lower_m5': analysis_m5.indicators.get('BB.lower'),
            'bb_upper_m5': analysis_m5.indicators.get('BB.upper'),
            'adx_m5': analysis_m5.indicators.get('ADX'),
            'obv_m5': analysis_m5.indicators.get('OBV'),
            'candle_m5': analysis_m5.summary.get('RECOMMENDATION'),
            'stoch_k_m5': analysis_m5.indicators.get('Stoch.K'),
            'stoch_d_m5': analysis_m5.indicators.get('Stoch.D'),

            'ema10_m15': analysis_m15.indicators.get('EMA10'),
            'ema20_m15': analysis_m15.indicators.get('EMA20'),
            'rsi_m15': analysis_m15.indicators.get('RSI'),
            'macd_m15': analysis_m15.indicators.get('MACD.macd'),
            'macd_signal_m15': analysis_m15.indicators.get('MACD.signal'),
            'bb_lower_m15': analysis_m15.indicators.get('BB.lower'),
            'bb_upper_m15': analysis_m15.indicators.get('BB.upper'),
            'adx_m15': analysis_m15.indicators.get('ADX'),
            'obv_m15': analysis_m15.indicators.get('OBV'),
            'candle_m15': analysis_m15.summary.get('RECOMMENDATION'),
            'stoch_k_m15': analysis_m15.indicators.get('Stoch.K'),
            'stoch_d_m15': analysis_m15.indicators.get('Stoch.D'),

            'ema10_h1': analysis_h1.indicators.get('EMA10'),
            'ema20_h1': analysis_h1.indicators.get('EMA20'),
            'rsi_h1': analysis_h1.indicators.get('RSI'),
            'macd_h1': analysis_h1.indicators.get('MACD.macd'),
            'macd_signal_h1': analysis_h1.indicators.get('MACD.signal'),
            'bb_lower_h1': analysis_h1.indicators.get('BB.lower'),
            'bb_upper_h1': analysis_h1.indicators.get('BB.upper'),
            'adx_h1': analysis_h1.indicators.get('ADX'),
            'obv_h1': analysis_h1.indicators.get('OBV'),
            'candle_h1': analysis_h1.summary.get('RECOMMENDATION')
        }
    except Exception as e:
        print(f"⚠️ Error analisis {symbol}: {str(e)}")
        return None

def safe_compare(val1, val2, operator='>'):
    """Bandingkan dua nilai secara aman (jika keduanya tidak None)."""
    if val1 is not None and val2 is not None:
        if operator == '>':
            return val1 > val2
        elif operator == '<':
            return val1 < val2
    return False

def calculate_scores(data):
    """
    Hitung skor beli dan jual berdasarkan indikator teknikal.
    Gunakan current_price untuk harga saat ini, sedangkan entry harga tersimpan di ACTIVE_BUYS.
    """
    current_price = data['current_price']
    ema5_m5 = data['ema5_m5']
    ema10_m5 = data['ema10_m5']
    rsi_m5 = data['rsi_m5']
    macd_m5 = data['macd_m5']
    macd_signal_m5 = data['macd_signal_m5']
    bb_lower_m5 = data['bb_lower_m5']
    bb_upper_m5 = data['bb_upper_m5']
    adx_m5 = data['adx_m5']
    obv_m5 = data['obv_m5']
    candle_m5 = data['candle_m5']
    stoch_k_m5 = data['stoch_k_m5']
    stoch_d_m5 = data['stoch_d_m5']

    ema10_m15 = data['ema10_m15']
    ema20_m15 = data['ema20_m15']
    rsi_m15 = data['rsi_m15']
    macd_m15 = data['macd_m15']
    macd_signal_m15 = data['macd_signal_m15']
    bb_lower_m15 = data['bb_lower_m15']
    bb_upper_m15 = data['bb_upper_m15']
    adx_m15 = data['adx_m15']
    obv_m15 = data['obv_m15']
    candle_m15 = data['candle_m15']
    stoch_k_m15 = data['stoch_k_m15']
    stoch_d_m15 = data['stoch_d_m15']

    ema10_h1 = data['ema10_h1']
    ema20_h1 = data['ema20_h1']
    rsi_h1 = data['rsi_h1']
    macd_h1 = data['macd_h1']
    macd_signal_h1 = data['macd_signal_h1']
    bb_lower_h1 = data['bb_lower_h1']
    bb_upper_h1 = data['bb_upper_h1']
    adx_h1 = data['adx_h1']
    obv_h1 = data['obv_h1']
    candle_h1 = data['candle_h1']

    buy_conditions = [
        safe_compare(ema10_m15, ema20_m15, '>'),
        (rsi_m5 is not None and rsi_m5 < 35),
        safe_compare(macd_m15, macd_signal_m15, '>'),
        (current_price <= bb_lower_m5 if bb_lower_m5 is not None else False),
        (("BUY" in candle_m5 or "STRONG_BUY" in candle_m5) if candle_m5 else False),
        (stoch_k_m5 is not None and stoch_k_m5 < 20 and stoch_d_m5 is not None and stoch_d_m5 < 20)
    ]

    sell_conditions = [
        safe_compare(ema10_m15, ema20_m15, '<'),
        (rsi_m5 is not None and rsi_m5 > 65),
        safe_compare(macd_m15, macd_signal_m15, '<'),
        (current_price >= bb_upper_m5 if bb_upper_m5 is not None else False),
        (("SELL" in candle_m5 or "STRONG_SELL" in candle_m5) if candle_m5 else False),
        (stoch_k_m5 is not None and stoch_k_m5 > 80 and stoch_d_m5 is not None and stoch_d_m5 > 80)
    ]

    return sum(buy_conditions), sum(sell_conditions)

def generate_signal(pair, data):
    """Generate trading signal berdasarkan skor dan posisi aktif."""
    current_price = data['current_price']
    buy_score, sell_score = calculate_scores(data)
    display_pair = f"{pair[:-4]}/USDT"

    print(f"{display_pair} - Price: {current_price:.8f} | Buy: {buy_score}/6 | Sell: {sell_score}/6")

    buy_signal = buy_score >= BUY_SCORE_THRESHOLD and pair not in ACTIVE_BUYS
    sell_signal = sell_score >= SELL_SCORE_THRESHOLD and pair in ACTIVE_BUYS

    # Perhitungan take profit dan stop loss
    take_profit = pair in ACTIVE_BUYS and current_price > ACTIVE_BUYS[pair]['price'] * (1 + PROFIT_TARGET_PERCENTAGE / 100)
    stop_loss = pair in ACTIVE_BUYS and current_price < ACTIVE_BUYS[pair]['price'] * (1 - STOP_LOSS_PERCENTAGE / 100)

    if buy_signal:
        return 'BUY', current_price
    elif take_profit:
        return 'TAKE PROFIT', current_price
    elif stop_loss:
        return 'STOP LOSS', current_price
    elif sell_signal:
        return 'SELL', current_price

    return None, None

def send_telegram_alert(signal_type, pair, current_price, data, buy_price=None):
    """Kirim notifikasi ke Telegram dan perbarui active buys."""
    display_pair = f"{pair[:-4]}/USDT"
    message = ""
    buy_score, sell_score = calculate_scores(data)
    
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
    base_msg += f"📊 *Score:* Buy {buy_score}/6 | Sell {sell_score}/6\n"

    if signal_type == 'BUY':
        message = f"{base_msg}🔍 *RSI:* {data['rsi_m15']:.2f}\n"
        message += f"*Stoch RSI:* {data['stoch_k_m15']:.2f}\n"
        ACTIVE_BUYS[pair] = {'price': current_price, 'time': datetime.now()}

    elif signal_type in ['TAKE PROFIT', 'STOP LOSS', 'SELL']:
        entry = ACTIVE_BUYS.get(pair)
        if entry:
            profit = ((current_price - entry['price']) / entry['price']) * 100
            duration = str(datetime.now() - entry['time']).split('.')[0]
            message = f"{base_msg}▫️ *Entry:* ${entry['price']:.8f}\n"
            message += f"💰 *{'Profit' if profit > 0 else 'Loss'}:* {profit:+.2f}%\n"
            message += f"🕒 *Durasi:* {duration}"
            if pair in ACTIVE_BUYS:
                del ACTIVE_BUYS[pair]

    elif signal_type == 'EXPIRED':
        entry = ACTIVE_BUYS.get(pair)
        if entry:
            profit = ((current_price - entry['price']) / entry['price']) * 100
            duration = str(datetime.now() - entry['time']).split('.')[0]
            message = f"{base_msg}▫️ *Entry:* ${entry['price']:.8f}\n"
            message += f"⌛ *Order Expired After:* {duration}\n"
            message += f"💰 *{'Profit' if profit > 0 else 'Loss'}:* {profit:+.2f}%"
            if pair in ACTIVE_BUYS:
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

def main():
    """Program utama"""
    # Ambil daftar pair dari file top_pairs.json (cached selama 24 jam, diupdate setelah jam 00 UTC)
    pairs = load_top_pairs_from_file()
    print(f"🔍 Memulai analisis {len(pairs)} pair - {datetime.now().strftime('%d/%m %H:%M')}")

    for pair in pairs:
        try:
            data = analyze_pair(pair)
            if not data:
                continue

            display_pair = f"{pair[:-4]}/USDT"
            print(f"\n📈 {display_pair}:")

            signal, current_price = generate_signal(pair, data)
            if signal:
                send_telegram_alert(signal, pair, current_price, data, buy_price=current_price)
                
            # Auto-close posisi berdasarkan durasi hold maksimum
            if pair in ACTIVE_BUYS:
                entry = ACTIVE_BUYS.get(pair)
                duration = datetime.now() - entry['time']
                if duration > timedelta(hours=MAX_HOLD_DURATION_HOUR):
                    send_telegram_alert('EXPIRED', pair, data['current_price'], data, entry['price'])
                    
        except Exception as e:
            print(f"⚠️ Error di {pair}: {str(e)}")
            continue

if __name__ == "__main__":
    main()
