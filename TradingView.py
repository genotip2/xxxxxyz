import os
import requests
import json
from datetime import datetime, timedelta
from tradingview_ta import TA_Handler, Interval

# KONFIGURASI

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
CMC_API_KEY = os.getenv('CMC_API_KEY')  # API key untuk CoinMarketCap

ACTIVE_BUYS_FILE = 'active_buys.json'
ACTIVE_BUYS = {}

# File cache untuk menyimpan daftar pair top berdasarkan ranking CMC
CACHE_FILE = 'pairs_cache.json'
CACHE_EXPIRED_DAYS = 30  # Cache dianggap kadaluarsa jika lebih dari 30 hari

# Konfigurasi jumlah pair untuk cache dan analisis
TOP_PAIRS_CACHED = 100       # Jumlah pair teratas (berdasarkan ranking CMC) yang akan disimpan ke cache
PAIR_TO_ANALYZE = 100         # Dari cache, hanya analisis sejumlah pair tertentu

# Konfigurasi order analisis.
# Karena cache disimpan berdasarkan ranking CMC secara ascending (ranking 1 = terbaik),
# "top" mengambil dari awal, "bottom" mengambil dari akhir.
ANALYSIS_ORDER = "top"

# Parameter trading
TAKE_PROFIT_PERCENTAGE = 6    # Target take profit 6% (dihitung dari harga entry)
STOP_LOSS_PERCENTAGE = 3      # Stop loss 3% (dihitung dari harga entry)
TRAILING_STOP_PERCENTAGE = 3  # Trailing stop 3% (dari harga tertinggi setelah take profit tercapai)
MAX_HOLD_DURATION_HOUR = 48   # Durasi hold maksimum 48 jam

# Konfigurasi Timeframe
TIMEFRAME_TREND = Interval.INTERVAL_4_HOURS       # Timeframe untuk analisis tren utama (4H)
TIMEFRAME_ENTRY = Interval.INTERVAL_1_HOUR          # Timeframe untuk analisis entry/pullback (1H)

##############################
# FUNGSI UTILITY: LOAD & SAVE POSITION
##############################
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
                        'highest_price': d.get('highest_price', None),
                        'exit_flag': d.get('exit_flag', None)
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
                'highest_price': d.get('highest_price', None),
                'exit_flag': d.get('exit_flag', None)
            }
        with open(ACTIVE_BUYS_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        print("✅ Posisi aktif disimpan.")
    except Exception as e:
        print(f"❌ Gagal menyimpan posisi aktif: {e}")

##############################
# FUNGSI MEMPERBARUI DAN MEMUAT CACHE PAIR
##############################
def get_cmc_rankings(symbols):
    """
    Mengambil data ranking dari CoinMarketCap untuk daftar simbol yang diberikan.
    Mengembalikan dictionary dengan key = simbol, value = cmc_rank.
    """
    print("🔄 Mengambil data ranking dari CoinMarketCap...")
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    headers = {
        "X-CMC_PRO_API_KEY": CMC_API_KEY
    }
    params = {
        "start": "1",
        "limit": "5000",
        "convert": "USD"
    }
    try:
        response = requests.get(url, headers=headers, params=params)
        data = response.json()
        ranking_mapping = {}
        for coin in data.get("data", []):
            symbol = coin.get("symbol")
            rank = coin.get("cmc_rank")
            if symbol and rank:
                ranking_mapping[symbol.upper()] = rank
        print("✅ Data ranking CMC berhasil diambil.")
        return ranking_mapping
    except Exception as e:
        print(f"❌ Gagal mengambil data ranking CMC: {e}")
        return {}

def update_pairs_cache():
    """
    Mengambil semua halaman dari CoinGecko untuk pair Binance,
    memfilter pair dengan target USDT, lalu mengurutkan berdasarkan ranking dari CoinMarketCap,
    dan menyimpannya ke file cache.
    """
    print("🔄 Memperbarui file cache pair...")
    all_tickers = []
    page = 1
    while True:
        url = "https://api.coingecko.com/api/v3/exchanges/binance/tickers"
        params = {'include_exchange_logo': 'false', 'order': 'volume_desc', 'page': page}
        try:
            print(f"🔍 Mengambil halaman {page} dari CoinGecko...")
            response = requests.get(url, params=params)
            data = response.json()
            tickers = data.get('tickers', [])
            if not tickers:
                print(f"ℹ️ Halaman {page} tidak memiliki tickers, menghentikan proses pengambilan.")
                break
            print(f"✅ Halaman {page} berhasil diambil, jumlah tickers: {len(tickers)}")
            all_tickers.extend(tickers)
            page += 1
        except Exception as e:
            print(f"❌ Gagal mengambil halaman {page}: {e}")
            break

    # Filter pair dengan target USDT
    usdt_tickers = [t for t in all_tickers if t.get('target') == 'USDT']
    print(f"🔍 Total tickers yang diambil: {len(all_tickers)}, setelah difilter USDT: {len(usdt_tickers)}")

    # Ambil daftar simbol unik dari tickers
    symbols = list({t.get('base').upper() for t in usdt_tickers if t.get('base')})
    print(f"🔍 Mengambil data ranking CMC untuk {len(symbols)} simbol: {symbols}")

    # Ambil data ranking dari CMC
    ranking_mapping = get_cmc_rankings(symbols)

    # Urutkan tickers berdasarkan ranking CMC secara ascending (ranking 1 = terbaik)
    sorted_tickers = sorted(usdt_tickers, key=lambda x: ranking_mapping.get(x.get('base').upper(), float('inf')))

    # Ambil TOP_PAIRS_CACHED pair teratas berdasarkan ranking CMC
    top_pairs = sorted_tickers[:TOP_PAIRS_CACHED]

    # Bentuk daftar pair dengan format "BASEUSDT"
    pairs_list = [f"{ticker.get('base').upper()}USDT" for ticker in top_pairs]

    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(pairs_list, f, indent=4)
        print("✅ File cache pair berhasil diperbarui.")
    except Exception as e:
        print(f"❌ Gagal menyimpan file cache pair: {e}")

def get_pairs_from_cache():
    """
    Memuat daftar pair dari file cache.
    Jika file cache tidak ada atau sudah kadaluarsa berdasarkan konfigurasi CACHE_EXPIRED_DAYS,
    maka file cache akan diperbarui terlebih dahulu.
    """
    now = datetime.now()
    update_cache = False

    if not os.path.exists(CACHE_FILE):
        update_cache = True
        print("ℹ️ File cache pair tidak ditemukan. Memperbarui cache...")
    else:
        try:
            mtime = os.path.getmtime(CACHE_FILE)
            mod_time = datetime.fromtimestamp(mtime)
            if now - mod_time > timedelta(days=CACHE_EXPIRED_DAYS):
                update_cache = True
                print("ℹ️ File cache pair kadaluarsa. Memperbarui cache...")
        except Exception as e:
            print(f"⚠️ Gagal mendapatkan waktu modifikasi cache: {e}")
            update_cache = True

    if update_cache:
        update_pairs_cache()

    try:
        with open(CACHE_FILE, 'r') as f:
            pairs = json.load(f)
        print(f"✅ Cache pair dimuat. Jumlah pair: {len(pairs)}")
        return pairs
    except Exception as e:
        print(f"❌ Gagal memuat file cache pair: {e}")
        return []

##############################
# FUNGSI ANALISIS: MULTI-TIMEFRAME
##############################
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

##############################
# FUNGSI BEST ENTRY
##############################
def is_best_entry_from_data(data):
    """
    Evaluasi apakah kondisi best entry terpenuhi.
    Kondisi Best Entry:
      - Rekomendasi candle adalah BUY atau STRONG_BUY
      - EMA10 entry > EMA20 entry
      - MACD entry > Signal entry
      - MACD entry > 0
      - MACD trend > Signal trend
    Mengembalikan tuple: (boolean, pesan evaluasi)
    """
    candle_entry = data.get('candle_entry')
    if candle_entry is None or (("BUY" not in candle_entry.upper()) and ("STRONG_BUY" not in candle_entry.upper())):
        return False, "Rekomendasi candle tidak mendukung (tidak ada BUY/STRONG_BUY)."

    ema10_entry = data.get('ema10_entry')
    ema20_entry = data.get('ema20_entry')
    if ema10_entry is None or ema20_entry is None or ema10_entry <= ema20_entry:
        return False, "EMA entry tidak memenuhi (EMA10 <= EMA20)."

    macd_entry = data.get('macd_entry')
    macd_signal_entry = data.get('macd_signal_entry')
    if macd_entry is None or macd_signal_entry is None or macd_entry <= macd_signal_entry or macd_entry <= 0:
        return False, "MACD entry tidak memenuhi (tidak > signal atau tidak > 0)."

    macd_trend = data.get('macd_trend')
    macd_signal_trend = data.get('macd_signal_trend')
    if macd_trend is None or macd_signal_trend is None or macd_trend <= macd_signal_trend:
        return False, "MACD trend tidak memenuhi (MACD trend <= signal trend)."

    return True, "OK"

##############################
# FUNGSI BEST EXIT
##############################
def is_best_exit_from_data(data):
    """
    Evaluasi apakah kondisi best exit terpenuhi.
    Kondisi Best Exit:
      - Rekomendasi candle adalah SELL atau STRONG_SELL
      - EMA10 entry < EMA20 entry
      - MACD entry < Signal entry
    Mengembalikan tuple: (boolean, pesan evaluasi)
    """
    candle_entry = data.get('candle_entry')
    if candle_entry is None or (("SELL" not in candle_entry.upper()) and ("STRONG_SELL" not in candle_entry.upper())):
        return False, "Rekomendasi candle tidak mendukung exit (tidak ada SELL/STRONG_SELL)."

    ema10_entry = data.get('ema10_entry')
    ema20_entry = data.get('ema20_entry')
    if ema10_entry is None or ema20_entry is None or ema10_entry >= ema20_entry:
        return False, "EMA entry tidak mendukung exit (EMA10 >= EMA20)."

    macd_entry = data.get('macd_entry')
    macd_signal_entry = data.get('macd_signal_entry')
    if macd_entry is None or macd_signal_entry is None or macd_entry >= macd_signal_entry:
        return False, "MACD entry tidak mendukung exit (tidak < signal)."

    return True, "Best Exit Condition terpenuhi."

##############################
# GENERATE SINYAL TRADING DENGAN BEST ENTRY & BEST EXIT
##############################
def generate_signal(pair):
    """
    Hasilkan sinyal trading berdasarkan evaluasi best entry atau best exit.
    Jika posisi belum aktif: sinyal BUY dihasilkan apabila best entry terpenuhi.
    Jika posisi sudah aktif: sinyal SELL dihasilkan apabila best exit terpenuhi,
    atau berdasarkan kondisi manajemen posisi (stop loss, take profit, trailing stop, expired).
    Perubahan:
      - Jika posisi sudah memiliki exit_flag (STOP LOSS atau TRAILING STOP), tidak mengembalikan sinyal baru kecuali sinyal SELL/EXPIRED.
      - Untuk sinyal BUY, ditambahkan informasi nilai RSI, ADX, dan Stoch K.
    Mengembalikan tuple: (signal, current_price, details)
    """
    # Analisis timeframe tren (4H)
    trend_analysis = analyze_pair_interval(pair, TIMEFRAME_TREND)
    if trend_analysis is None:
        return None, None, "Analisis tren gagal."
    
    # Analisis timeframe entry (1H)
    entry_analysis = analyze_pair_interval(pair, TIMEFRAME_ENTRY)
    if entry_analysis is None:
        return None, None, "Analisis entry gagal."
    
    current_price = entry_analysis.indicators.get('close')
    if current_price is None:
        return None, None, "Harga close tidak tersedia pada timeframe entry."

    # Kumpulkan data indikator yang diperlukan
    data = {
        'current_price': current_price,
        'ema10_entry': entry_analysis.indicators.get('EMA10'),
        'ema20_entry': entry_analysis.indicators.get('EMA20'),
        'macd_entry': entry_analysis.indicators.get('MACD.macd'),
        'macd_signal_entry': entry_analysis.indicators.get('MACD.signal'),
        'candle_entry': entry_analysis.summary.get('RECOMMENDATION'),
        'macd_trend': trend_analysis.indicators.get('MACD.macd'),
        'macd_signal_trend': trend_analysis.indicators.get('MACD.signal')
    }

    # Ambil nilai tambahan untuk sinyal BUY
    rsi_value = entry_analysis.indicators.get('RSI')
    adx_value = entry_analysis.indicators.get('ADX')
    stoch_k_value = entry_analysis.indicators.get('Stoch.K')
    extra_info = f"*RSI:* {rsi_value}, *ADX:* {adx_value}, *Stoch K:* {stoch_k_value}"

    if pair not in ACTIVE_BUYS:
        best_entry_ok, best_entry_msg = is_best_entry_from_data(data)
        if best_entry_ok:
            details = f"BEST ENTRY: {best_entry_msg} | {extra_info}"
            return "BUY", current_price, details
        else:
            return None, current_price, f"Tidak memenuhi best entry: {best_entry_msg} | {extra_info}"
    else:
        data_active = ACTIVE_BUYS[pair]
        # Jika sudah ada exit_flag (STOP LOSS atau TRAILING STOP), jangan berikan sinyal baru kecuali SELL/EXPIRED.
        if data_active.get('exit_flag') is not None:
            return None, current_price, "Sinyal exit sudah ditandai, menunggu sinyal SELL/EXPIRED."
        
        # Evaluasi kondisi best exit
        best_exit_ok, best_exit_msg = is_best_exit_from_data(data)
        if best_exit_ok:
            return "SELL", current_price, f"BEST EXIT: {best_exit_msg}"
        
        holding_duration = datetime.now() - data_active['time']
        if holding_duration > timedelta(hours=MAX_HOLD_DURATION_HOUR):
            return "EXPIRED", current_price, f"Durasi hold: {str(holding_duration).split('.')[0]}"
        
        entry_price = data_active['price']
        profit_from_entry = (current_price - entry_price) / entry_price * 100
        
        # Jika kondisi stop loss terpenuhi dan belum ada exit_flag, kembalikan sinyal STOP LOSS
        if profit_from_entry <= -STOP_LOSS_PERCENTAGE:
            return "STOP LOSS", current_price, "Stop loss tercapai."
        
        # Jika target take profit tercapai, aktifkan trailing stop (tanpa menghapus posisi)
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
        
        return None, current_price, "Tidak ada sinyal."

##############################
# FUNGSI PEMBANTU UNTUK MENGHADIRKAN LINK BINANCE
##############################
def get_binance_url(pair):
    """
    Membangun URL Binance untuk pair.
    Misalnya, jika pair = "BTCUSDT", maka URL yang dihasilkan adalah:
    https://www.binance.com/en/trade/BTC_USDT
    """
    base = pair[:-4]
    quote = pair[-4:]
    return f"https://www.binance.com/en/trade/{base}_{quote}"

##############################
# FUNGSI PEMBANTU UNTUK MENGHADIRKAN LINK TRADINGVIEW
##############################
def get_tradingview_url(pair):
    """
    Membangun URL TradingView untuk pair.
    Misalnya, jika pair = "BTCUSDT", maka URL yang dihasilkan adalah:
    https://www.tradingview.com/chart/?symbol=BINANCE:BTCUSDT
    """
    return f"https://www.tradingview.com/chart/?symbol=BINANCE:{pair}"

##############################
# KIRIM ALERT TELEGRAM
##############################
def send_telegram_alert(signal_type, pair, current_price, details=""):
    """
    Mengirim notifikasi ke Telegram.
    Perubahan:
      - Untuk sinyal BUY, posisi disimpan ke ACTIVE_BUYS dengan field exit_flag = None.
      - Untuk sinyal STOP LOSS dan TRAILING STOP, posisi tidak dihapus melainkan hanya ditandai (exit_flag),
        dan notifikasi dikirim jika ini adalah sinyal pertama.
      - Untuk sinyal SELL dan EXPIRED:
            * Jika posisi sudah memiliki exit_flag, notifikasi tidak dikirim (posisi dihapus secara diam-diam).
            * Jika posisi tidak memiliki exit_flag, notifikasi tetap dikirim dan posisi dihapus setelahnya.
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
    
    binance_url = get_binance_url(pair)
    tradingview_url = get_tradingview_url(pair)
    
    # Penanganan khusus untuk sinyal SELL dan EXPIRED
    if signal_type in ["SELL", "EXPIRED"]:
        if pair in ACTIVE_BUYS:
            # Jika sudah ada exit_flag, hapus posisi tanpa mengirim notifikasi.
            if ACTIVE_BUYS[pair].get("exit_flag") is not None:
                del ACTIVE_BUYS[pair]
                print(f"✅ Posisi {pair} ditutup tanpa notifikasi (exit flag sudah ada) dengan sinyal {signal_type}.")
                return
    # Untuk sinyal BUY, tambahkan entry baru ke ACTIVE_BUYS.
    if signal_type == "BUY":
        ACTIVE_BUYS[pair] = {
            'price': current_price,
            'time': datetime.now(),
            'trailing_stop_active': False,
            'highest_price': None,
            'exit_flag': None
        }
    
    # Untuk sinyal STOP LOSS dan TRAILING STOP, tandai posisi aktif dengan exit_flag.
    if signal_type in ["STOP LOSS", "TRAILING STOP"]:
        if pair in ACTIVE_BUYS:
            ACTIVE_BUYS[pair]['exit_flag'] = signal_type

    message = f"{emoji} *{signal_type}*\n"
    message += f"💱 *Pair:* [{display_pair}]({binance_url}) ==> [TradingView]({tradingview_url})\n"
    message += f"💲 *Price:* ${current_price:.8f}\n"
    if details:
        message += f"📝 *Kondisi:* {details}\n"
    
    # Untuk sinyal selain BUY, tambahkan info posisi (Entry Price, Profit/Loss, Duration) jika masih aktif.
    if signal_type != "BUY" and pair in ACTIVE_BUYS:
        entry_price = ACTIVE_BUYS[pair]['price']
        profit = (current_price - entry_price) / entry_price * 100
        duration = datetime.now() - ACTIVE_BUYS[pair]['time']
        message += f"▫️ *Entry Price:* ${entry_price:.8f}\n"
        message += f"💰 *{'Profit' if profit > 0 else 'Loss'}:* {profit:+.2f}%\n"
        message += f"🕒 *Duration:* {str(duration).split('.')[0]}\n"
    
    print(f"📢 Mengirim alert:\n{message}")
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                'chat_id': TELEGRAM_CHAT_ID,
                'text': message,
                'parse_mode': 'Markdown',
                'disable_web_page_preview': True
            }
        )
    except Exception as e:
        print(f"❌ Gagal mengirim alert Telegram: {e}")
    
    # Untuk sinyal SELL dan EXPIRED tanpa exit_flag, hapus posisi setelah mengirim notifikasi.
    if signal_type in ["SELL", "EXPIRED"]:
        if pair in ACTIVE_BUYS:
            del ACTIVE_BUYS[pair]

##############################
# PROGRAM UTAMA
##############################
def main():
    load_active_buys()

    # Ambil daftar pair dari file cache
    pairs = get_pairs_from_cache()

    # Sesuaikan order analisis berdasarkan konfigurasi ANALYSIS_ORDER.
    if PAIR_TO_ANALYZE > 0 and PAIR_TO_ANALYZE < len(pairs):
        if ANALYSIS_ORDER.lower() == "top":
            pairs = pairs[:PAIR_TO_ANALYZE]
        elif ANALYSIS_ORDER.lower() == "bottom":
            pairs = pairs[-PAIR_TO_ANALYZE:]

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
