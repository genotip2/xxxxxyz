import os
import requests
import json
from datetime import datetime, timedelta

# ================================
# KONFIGURASI
# ================================
# Pastikan environment variable CMC_API_KEY sudah diset
CMC_API_KEY = os.getenv('CMC_API_KEY')  

# File cache untuk menyimpan daftar pair top berdasarkan ranking CMC
CACHE_FILE = 'pairs_cache.json'
CACHE_EXPIRED_DAYS = 30  # Cache dianggap kadaluarsa jika lebih dari 30 hari

# Konfigurasi jumlah pair untuk cache
TOP_PAIRS_CACHED = 100   # Jumlah pair teratas (berdasarkan ranking CMC) yang akan disimpan ke cache

# ================================
# FUNGSI PENGAMBILAN DATA
# ================================
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
        response.raise_for_status()  # Raise exception untuk HTTP error
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
            response.raise_for_status()
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
    print(f"🔍 Mengambil data ranking CMC untuk {len(symbols)} simbol unik...")

    # Ambil data ranking dari CMC
    ranking_mapping = get_cmc_rankings(symbols)

    # Urutkan tickers berdasarkan ranking CMC secara ascending (ranking 1 = terbaik)
    # Jika simbol tidak ditemukan di CMC, berikan nilai infinity agar masuk ke urutan paling belakang
    sorted_tickers = sorted(usdt_tickers, key=lambda x: ranking_mapping.get(x.get('base').upper(), float('inf')))

    # Ambil TOP_PAIRS_CACHED pair teratas berdasarkan ranking CMC
    top_pairs = sorted_tickers[:TOP_PAIRS_CACHED]

    # Bentuk daftar pair dengan format "BASEUSDT"
    pairs_list = [f"{ticker.get('base').upper()}USDT" for ticker in top_pairs]

    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(pairs_list, f, indent=4)
        print("✅ File cache pair berhasil diperbarui dan disimpan.")
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

# ================================
# PROGRAM UTAMA
# ================================
def main():
    print("🚀 Memulai proses pengambilan pair dari ranking CMC...\n")
    
    # Ambil daftar pair dari file cache (akan otomatis update jika perlu)
    pairs = get_pairs_from_cache()
    
    print("\n📋 Daftar Pair Top Berdasarkan Ranking CMC:")
    for i, pair in enumerate(pairs, 1):
        print(f"{i:3d}. {pair}")
        
    print(f"\n✅ Selesai. Total {len(pairs)} pair tersimpan di '{CACHE_FILE}'")

if __name__ == "__main__":
    main()
