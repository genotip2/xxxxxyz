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

# Parameter trading
TAKE_PROFIT_PERCENTAGE = 6    # Target take profit 5% (dihitung dari harga entry)
STOP_LOSS_PERCENTAGE = 3      # Stop loss 2% (dihitung dari harga entry)
TRAILING_STOP_PERCENTAGE = 3  # Trailing stop 2% (dari harga tertinggi setelah take profit tercapai)
MAX_HOLD_DURATION_HOUR = 24   # Durasi hold maksimum 24 jam
PAIR_TO_ANALYZE = 100          # Jumlah pair yang akan dianalisis

# (Konfigurasi Recommend.MA masih disertakan meskipun tidak digunakan pada logika scoring baru)
BULLISH_RECOMMEND_MA_THRESHOLD = 0.7
BEARISH_RECOMMEND_MA_THRESHOLD = 0.3

# Konfigurasi Timeframe
TIMEFRAME_TREND = Interval.INTERVAL_4_HOURS       # Timeframe untuk analisis tren utama
TIMEFRAME_ENTRY = Interval.INTERVAL_1_HOUR     # Timeframe untuk analisis entry/pullback

# Konfigurasi Score Threshold
BUY_SCORE_THRESHOLD = 6
SELL_SCORE_THRESHOLD = 5

# ==============================
# FUNGSI UTITAS: LOAD & SAVE POSITION
# ==============================
def load_active_buys():
    """Muat posisi aktif dari file JSON."""
    global ACTIVE_BUYS
    if os.path.exists(ACTIVE_BUYS_FILE):
        try:
            with open(ACTIVE_BUYS_FILE, 'r') as f:
                data = json.load(f)
                ACTIVE_BUYS = {
                    pair: {
                        'price': d['price'],
                        'time': datetime.fromisoformat(d['time']),
                        'trailing_stop_active': d.get('trailing_stop_active', False),
                        'highest_price': d.get('highest_price', None)
                    }
                    for pair, d in data.items()
                }
            print("✅ Posisi aktif dimuat.")
        except Exception as e:
            print(f"❌ Gagal memuat posisi aktif: {e}")
    else:
        ACTIVE_BUYS = {}

def save_active_buys():
    """Simpan posisi aktif ke file JSON."""
    try:
        data = {}
        for pair, d in ACTIVE_BUYS.items():
            data[pair] = {
                'price': d['price'],
                'time': d['time'].isoformat(),
                'trailing_stop_active': d.get('trailing_stop_active', False),
                'highest_price': d.get('highest_price', None)
            }
        with open(ACTIVE_BUYS_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        print("✅ Posisi aktif disimpan.")
    except Exception as e:
        print(f"❌ Gagal menyimpan posisi aktif: {e}")

# ==============================
# FUNGSI MENDAPATKAN PAIR TERATAS
# ==============================
def get_binance_top_pairs():
    """
    Ambil pasangan (pair) teratas berdasarkan volume trading dari Binance melalui CoinGecko.
    Hanya pair dengan target USDT yang diambil.
    """
    url = "https://api.coingecko.com/api/v3/exchanges/binance/tickers"
    params = {'include_exchange_logo': 'false', 'order': 'volume_desc'}
    try:
        response = requests.get(url, params=params)
        data = response.json()
        usdt_pairs = [t for t in data['tickers'] if t['target'] == 'USDT']
        sorted_pairs = sorted(usdt_pairs, key=lambda x: x['converted_volume']['usd'], reverse=True)[:PAIR_TO_ANALYZE]
        return [f"{p['base']}USDT" for p in sorted_pairs]
    except Exception as e:
        print(f"❌ Gagal mengambil pair: {e}")
        return []

# ==============================
# FUNGSI ANALISIS: MULTI-TIMEFRAME
# ==============================
def analyze_pair_interval(pair, interval):
    """
    Lakukan analisis teknikal untuk pair pada timeframe tertentu menggunakan tradingview_ta.
    """
    try:
        handler = TA_Handler(
            symbol=pair,
            exchange="BINANCE",
            screener="CRYPTO",
            interval=interval
        )
        analysis = handler.get_analysis()
        return analysis
    except Exception as e:
        print(f"⚠️ Gagal menganalisis {pair} pada interval {interval}: {e}")
        return None

# ==============================
# FUNGSI PEMBANTU UNTUK SCORING
# ==============================
def safe_compare(a, b, op):
    """Bandingkan dua nilai secara aman; kembalikan False jika salah satunya bernilai None."""
    if a is None or b is None:
        return False
    if op == '>':
        return a > b
    elif op == '<':
        return a < b
    else:
        raise ValueError("Operator tidak didukung.")

def calculate_scores(data):
    """
    Hitung skor beli dan jual berdasarkan indikator teknikal dan kembalikan juga
    daftar indikator yang terpenuhi untuk masing-masing kondisi.
    Pastikan data sudah menyertakan 'current_price' dari timeframe entry.
    """
    current_price = data.get('current_price')

    # Data timeframe entry (M15)
    ema10_entry = data.get('ema10_entry')  
    ema20_entry = data.get('ema20_entry')  
    rsi_entry = data.get('rsi_entry')  
    macd_entry = data.get('macd_entry')  
    macd_signal_entry = data.get('macd_signal_entry')  
    bb_lower_entry = data.get('bb_lower_entry')  
    bb_upper_entry = data.get('bb_upper_entry')  
    adx_entry = data.get('adx_entry')  
    obv_entry = data.get('obv_entry')  
    candle_entry = data.get('candle_entry')  
    stoch_k_entry = data.get('stoch_k_entry')
    stoch_d_entry = data.get('stoch_d_entry')

    # Data timeframe tren (H1)
    ema10_trend = data.get('ema10_trend')  
    ema20_trend = data.get('ema20_trend')  
    rsi_trend = data.get('rsi_trend')  
    macd_trend = data.get('macd_trend')  
    macd_signal_trend = data.get('macd_signal_trend')  
    bb_lower_trend = data.get('bb_lower_trend')  
    bb_upper_trend = data.get('bb_upper_trend')  
    adx_trend = data.get('adx_trend')  
    obv_trend = data.get('obv_trend')  
    candle_trend = data.get('candle_trend')  

    # Kondisi beli: tiap tuple berisi (kondisi_boolean, deskripsi indikator)
    buy_conditions = [
        (safe_compare(ema10_entry, ema20_entry, '>'), "EMA10 entry > EMA20 entry"),
        (safe_compare(ema10_trend, ema20_trend, '>'), "EMA10 trend > EMA20 trend"),
        ((rsi_entry is not None and rsi_entry < 75), "RSI < 75"),
        (safe_compare(macd_entry, macd_signal_entry, '>'), "MACD > Signal"),
        ((bb_lower_entry is not None and current_price is not None and current_price <= bb_lower_entry), "Price <= BB Lower"),
        ((adx_entry is not None and adx_entry > 35), "ADX > 35"),
        ((candle_entry is not None and ("BUY" in candle_entry or "STRONG_BUY" in candle_entry)), "Rekomendasi BUY"),
        ((stoch_k_entry is not None and stoch_k_entry < 20 and stoch_d_entry is not None and stoch_d_entry < 20), "Stoch RSI < 20")
    ]

    # Kondisi jual
    sell_conditions = [
        (safe_compare(ema10_entry, ema20_entry, '<'), "EMA10 entry < EMA20 entry"),
        (safe_compare(ema10_trend, ema20_trend, '<'), "EMA10 trend < EMA20 trend "),
        ((rsi_entry is not None and rsi_entry > 85), "RSI > 70"),
        (safe_compare(macd_entry, macd_signal_entry, '<'), "MACD < Signal "),
        ((bb_upper_entry is not None and current_price is not None and current_price >= bb_upper_entry), "Price >= BB Upper"),
        ((adx_entry is not None and adx_entry < 45), "ADX < 45"),
        ((candle_entry is not None and ("SELL" in candle_entry or "STRONG_SELL" in candle_entry)), "Rekomendasi SELL"),
        ((stoch_k_entry is not None and stoch_k_entry > 80 and stoch_d_entry is not None and stoch_d_entry > 80), "Stoch RSI  > 80")
    ]

    buy_score = sum(1 for cond, _ in buy_conditions if cond)
    sell_score = sum(1 for cond, _ in sell_conditions if cond)
    buy_met = [desc for cond, desc in buy_conditions if cond]
    sell_met = [desc for cond, desc in sell_conditions if cond]

    return buy_score, sell_score, buy_met, sell_met

# ==============================
# GENERATE SINYAL TRADING DENGAN SCORING
# ==============================
def generate_signal(pair):
    """
    Hasilkan sinyal trading berdasarkan skor indikator.
    - Jika posisi belum aktif: sinyal BUY dihasilkan apabila buy_score minimal BUY_SCORE_THRESHOLD dan lebih tinggi dari sell_score.
    - Jika posisi sudah aktif: cek exit berdasarkan stop loss, take profit, trailing stop, durasi hold,
      atau jika sell_score minimal SELL_SCORE_THRESHOLD dan melebihi buy_score.
    """
    # Analisis timeframe tren (H1)
    trend_analysis = analyze_pair_interval(pair, TIMEFRAME_TREND)
    if trend_analysis is None:
        return None, None, "Analisis tren gagal."

    # Analisis timeframe entry (M15)
    entry_analysis = analyze_pair_interval(pair, TIMEFRAME_ENTRY)
    if entry_analysis is None:
        return None, None, "Analisis entry gagal."

    current_price = entry_analysis.indicators.get('close')
    if current_price is None:
        return None, None, "Harga close tidak tersedia pada timeframe entry."

    # Bangun dictionary data untuk perhitungan skor
    data = {
        'current_price': current_price,
        'ema10_entry': entry_analysis.indicators.get('EMA10'),
        'ema20_entry': entry_analysis.indicators.get('EMA20'),
        'rsi_entry': entry_analysis.indicators.get('RSI'),
        'macd_entry': entry_analysis.indicators.get('MACD.macd'),
        'macd_signal_entry': entry_analysis.indicators.get('MACD.signal'),
        'bb_lower_entry': entry_analysis.indicators.get('BB.lower'),
        'bb_upper_entry': entry_analysis.indicators.get('BB.upper'),
        'adx_entry': entry_analysis.indicators.get('ADX'),
        'obv_entry': entry_analysis.indicators.get('OBV'),
        'candle_entry': entry_analysis.summary.get('RECOMMENDATION'),
        'stoch_k_entry': entry_analysis.indicators.get('Stoch.K'),
        'stoch_d_entry': entry_analysis.indicators.get('Stoch.D'),

        'ema10_trend': trend_analysis.indicators.get('EMA10'),
        'ema20_trend': trend_analysis.indicators.get('EMA20'),
        'rsi_trend': trend_analysis.indicators.get('RSI'),
        'macd_trend': trend_analysis.indicators.get('MACD.macd'),
        'macd_signal_trend': trend_analysis.indicators.get('MACD.signal'),
        'bb_lower_trend': trend_analysis.indicators.get('BB.lower'),
        'bb_upper_trend': trend_analysis.indicators.get('BB.upper'),
        'adx_trend': trend_analysis.indicators.get('ADX'),
        'obv_trend': trend_analysis.indicators.get('OBV'),
        'candle_trend': trend_analysis.summary.get('RECOMMENDATION')
    }

    # Hitung skor beli dan jual
    buy_score, sell_score, buy_met, sell_met = calculate_scores(data)

    # Jika belum ada posisi aktif, evaluasi entry BUY
    if pair not in ACTIVE_BUYS:
        if buy_score >= BUY_SCORE_THRESHOLD and buy_score > sell_score:
            details = f"{', '.join(buy_met)}"
            return "BUY", current_price, details

    # Jika posisi sudah aktif, cek kondisi exit/management posisi
    else:
        data_active = ACTIVE_BUYS[pair]
        holding_duration = datetime.now() - data_active['time']
        if holding_duration > timedelta(hours=MAX_HOLD_DURATION_HOUR):
            return "EXPIRED", current_price, f"Durasi hold: {str(holding_duration).split('.')[0]}"

        entry_price = data_active['price']
        profit_from_entry = (current_price - entry_price) / entry_price * 100

        if profit_from_entry <= -STOP_LOSS_PERCENTAGE:
            return "STOP LOSS", current_price, "Stop loss tercapai."

        if not data_active.get('trailing_stop_active', False) and profit_from_entry >= TAKE_PROFIT_PERCENTAGE:
            ACTIVE_BUYS[pair]['trailing_stop_active'] = True
            ACTIVE_BUYS[pair]['highest_price'] = current_price
            return "TAKE PROFIT", current_price, "Target take profit tercapai, trailing stop diaktifkan."

        if data_active.get('trailing_stop_active', False):
            prev_high = data_active.get('highest_price')
            if prev_high is None or current_price > prev_high:
                ACTIVE_BUYS[pair]['highest_price'] = current_price
                send_telegram_alert(
                    "NEW HIGH",
                    pair,
                    current_price,
                    f"New highest price (sebelumnya: {prev_high:.8f})" if prev_high else "New highest price set."
                )
            trailing_stop_price = ACTIVE_BUYS[pair]['highest_price'] * (1 - TRAILING_STOP_PERCENTAGE / 100)
            if current_price < trailing_stop_price:
                return "TRAILING STOP", current_price, f"Harga turun ke trailing stop: {trailing_stop_price:.8f}"

        # Evaluasi exit berdasarkan sinyal SELL dari skor
        if sell_score >= SELL_SCORE_THRESHOLD and sell_score > buy_score:
            details = f"{', '.join(sell_met)}"
            return "SELL", current_price, details

    return None, current_price, "Tidak ada sinyal."

# ==============================
# KIRIM ALERT TELEGRAM
# ==============================
def send_telegram_alert(signal_type, pair, current_price, details=""):
    """
    Mengirim notifikasi ke Telegram.
    Untuk sinyal BUY, posisi disimpan ke ACTIVE_BUYS.
    Untuk sinyal exit seperti SELL, STOP LOSS, EXPIRED, atau TRAILING STOP, posisi dihapus.
    Sementara untuk sinyal TAKE PROFIT, hanya mengaktifkan trailing stop tanpa menghapus posisi.
    Untuk sinyal "NEW HIGH", posisi tidak dihapus.
    
    Informasi tambahan mengenai Entry Price, Profit/Loss, dan Duration akan ditambahkan untuk semua jenis sinyal kecuali BUY.
    """
    display_pair = f"{pair[:-4]}/USDT"
    emoji = {
        'BUY': '🚀',
        'SELL': '⚠️',
        'TAKE PROFIT': '✅',
        'STOP LOSS': '🛑',
        'EXPIRED': '⌛',
        'TRAILING STOP': '📉',
        'NEW HIGH': '📈'
    }.get(signal_type, 'ℹ️')

    message = f"{emoji} *{signal_type}*\n"
    message += f"💱 *Pair:* {display_pair}\n"
    message += f"💲 *Price:* ${current_price:.8f}\n"
    message += f"📊 *Score:* Buy {buy_score}/8 | Sell {sell_score}/8\n"
    if details:
        message += f"📝 *Kondisi:* {details}\n"

    # Jika sinyal BUY, simpan entry baru tanpa menambahkan info tambahan
    if signal_type == "BUY":
        ACTIVE_BUYS[pair] = {
            'price': current_price,
            'time': datetime.now(),
            'trailing_stop_active': False,
            'highest_price': None
        }
    else:
        # Tambahkan info tambahan untuk semua jenis sinyal kecuali BUY
        if pair in ACTIVE_BUYS:
            entry_price = ACTIVE_BUYS[pair]['price']
            profit = (current_price - entry_price) / entry_price * 100
            duration = datetime.now() - ACTIVE_BUYS[pair]['time']
            message += f"▫️ *Entry Price:* ${entry_price:.8f}\n"
            message += f"💰 *{'Profit' if profit > 0 else 'Loss'}:* {profit:+.2f}%\n"
            message += f"🕒 *Duration:* {str(duration).split('.')[0]}\n"
        # Untuk sinyal exit, hapus posisi setelah menambahkan info
        if signal_type in ["SELL", "STOP LOSS", "EXPIRED", "TRAILING STOP"]:
            if pair in ACTIVE_BUYS:
                del ACTIVE_BUYS[pair]

    print(f"📢 Mengirim alert:\n{message}")
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
        )
    except Exception as e:
        print(f"❌ Gagal mengirim alert Telegram: {e}")

# ==============================
# PROGRAM UTAMA
# ==============================
def main():
    load_active_buys()
    pairs = get_binance_top_pairs()
    print(f"🔍 Memulai analisis {len(pairs)} pair pada {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    for pair in pairs:
        print(f"\n🔎 Sedang menganalisis pair: {pair}")
        try:
            signal, current_price, details = generate_signal(pair)
            if signal:
                print(f"💡 Sinyal: {signal}, Harga: {current_price:.8f}")
                print(f"📝 Details: {details}")
                send_telegram_alert(signal, pair, current_price, details)
            else:
                print("ℹ️ Tidak ada sinyal untuk pair ini.")
        except Exception as e:
            print(f"⚠️ Error di {pair}: {e}")
            continue

    # Auto-close posisi jika durasi hold melebihi batas (cek ulang posisi aktif)
    for pair in list(ACTIVE_BUYS.keys()):
        holding_duration = datetime.now() - ACTIVE_BUYS[pair]['time']
        if holding_duration > timedelta(hours=MAX_HOLD_DURATION_HOUR):
            entry_analysis = analyze_pair_interval(pair, TIMEFRAME_ENTRY)
            current_price = entry_analysis.indicators.get('close') if entry_analysis else 0
            send_telegram_alert("EXPIRED", pair, current_price, f"Durasi hold: {str(holding_duration).split('.')[0]}")

    save_active_buys()

if __name__ == "__main__":
    main()
