import os
import requests
import json
from datetime import datetime, timedelta
from tradingview_ta import TA_Handler, Interval

# KONFIGURASI

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
CMC_API_KEY = os.getenv('CMC_API_KEY')  # API key untuk CoinMarketCap

# File cache untuk menyimpan daftar pair top berdasarkan ranking CMC
CACHE_FILE = 'pairs_cache.json'
CACHE_EXPIRED_DAYS = 30  # Cache dianggap kadaluarsa jika lebih dari 30 hari

# Konfigurasi jumlah pair untuk cache dan analisis
TOP_PAIRS_CACHED = 100       # Jumlah pair teratas (berdasarkan ranking CMC) yang akan disimpan ke cache
PAIR_TO_ANALYZE = 100         # Dari cache, hanya analisis sejumlah pair tertentu

# Konfigurasi order analisis.
# Untuk cache yang diurutkan berdasarkan ranking CMC secara ascending (ranking 1 = terbaik),
# "top" mengambil dari awal (ranking terbaik), "bottom" mengambil dari akhir.
ANALYSIS_ORDER = "top"

# Konfigurasi Timeframe
TIMEFRAME_TREND = Interval.INTERVAL_4_HOURS       # Timeframe untuk analisis tren utama (4H)
TIMEFRAME_ENTRY = Interval.INTERVAL_1_HOUR          # Timeframe untuk analisis entry/pullback (1H)

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
    Evaluasi apakah kondisi entri terbaik terpenuhi berdasarkan data indikator dari timeframe entry dan trend.
    Kondisi Best Entry:
      - Rekomendasi candle harus mengandung "BUY" atau "STRONG_BUY"
      - EMA10 entry > EMA20 entry
      - MACD entry > Signal entry
      - MACD trend > Signal trend
    Mengembalikan tuple: (boolean, pesan evaluasi)
    """
    # Kondisi 1: EMA entry
    ema10_entry = data.get('ema10_entry')
    ema20_entry = data.get('ema20_entry')
    if ema10_entry is None or ema20_entry is None or ema10_entry <= ema20_entry:
        return False, "EMA entry tidak memenuhi (EMA10 <= EMA20)."

    # Kondisi 2: Rekomendasi candle harus mengandung "BUY" atau "STRONG_BUY"
    candle_entry = data.get('candle_entry')
    if candle_entry is None or not any(x in candle_entry.upper() for x in ["BUY", "STRONG_BUY"]):
        return False, "Rekomendasi candle tidak mendukung (tidak ada 'BUY' atau 'STRONG_BUY')."

    # Kondisi 3: MACD entry > Signal entry
    macd_entry = data.get('macd_entry')
    macd_signal_entry = data.get('macd_signal_entry')
    if macd_entry is None or macd_signal_entry is None or macd_entry <= macd_signal_entry:
        return False, "MACD entry tidak memenuhi (MACD entry <= Signal entry)."

    # Kondisi 4: MACD trend > Signal trend
    macd_trend = data.get('macd_trend')
    macd_signal_trend = data.get('macd_signal_trend')
    if macd_trend is None or macd_signal_trend is None or macd_trend <= macd_signal_trend:
        return False, "MACD trend tidak memenuhi (MACD trend <= Signal trend)."

    return True, "Best Entry Condition terpenuhi."

##############################
# GENERATE SINYAL TRADING DENGAN BEST ENTRY
##############################
def generate_signal(pair):
    """
    Hasilkan sinyal trading berdasarkan kondisi Best Entry.
    Hanya menghasilkan sinyal BUY jika Best Entry Condition terpenuhi.
    Tidak menghasilkan notifikasi exit.
    Mengembalikan tuple: (signal, current_price, details)
    """
    # Analisis timeframe tren (TIMEFRAME_TREND, yaitu 4H)
    trend_analysis = analyze_pair_interval(pair, TIMEFRAME_TREND)
    if trend_analysis is None:
        return None, None, "Analisis tren gagal."

    # Analisis timeframe entry (TIMEFRAME_ENTRY, yaitu 1H)
    entry_analysis = analyze_pair_interval(pair, TIMEFRAME_ENTRY)
    if entry_analysis is None:
        return None, None, "Analisis entry gagal."

    current_price = entry_analysis.indicators.get('close')
    if current_price is None:
        return None, None, "Harga close tidak tersedia pada timeframe entry."

    # Kumpulkan data indikator untuk evaluasi best entry
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

    best_entry_ok, best_entry_msg = is_best_entry_from_data(data)
    if best_entry_ok:
        details = f"BEST ENTRY: {best_entry_msg}"
        return "BUY", current_price, details
    else:
        return None, current_price, best_entry_msg

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
    Hanya mengirim notifikasi BUY.
    """
    display_pair = f"{pair[:-4]}/USDT"
    emoji = {
        'BUY': '🚀'
    }.get(signal_type, 'ℹ️')
    
    binance_url = get_binance_url(pair)   # Link Binance
    tradingview_url = get_tradingview_url(pair)  # Link TradingView

    message = f"{emoji} *{signal_type}*\n"
    message += f"💱 *Pair:* [{display_pair}]({binance_url}) ==> [TradingView]({tradingview_url})\n"
    message += f"💲 *Price:* ${current_price:.8f}\n"
    if details:
        message += f"📝 *Kondisi:* {details}\n"

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

##############################
# PROGRAM UTAMA
##############################
def main():
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
                print(f"ℹ️ Tidak ada sinyal untuk pair ini. ({details})")
        except Exception as e:
            print(f"⚠️ Error di {pair}: {e}")
            continue

if __name__ == "__main__":
    main()
