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
        
        # Debug: Print all available indicators
        # print(json.dumps(analysis.indicators, indent=2))
        
        return {
            'recommendation': analysis.summary['RECOMMENDATION'],
            'rsi': analysis.indicators.get('RSI', 0),
            'macd': analysis.indicators.get('MACD.macd', 0),
            'signal': analysis.indicators.get('MACD.signal', 0),
            'support': analysis.indicators.get('Pivot.M.S1', 0),  # Key yang diperbaiki
            'resistance': analysis.indicators.get('Pivot.M.R1', 0),  # Key yang diperbaiki
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

# ... (Fungsi lainnya tetap sama, pastikan semua pemanggilan save_active_buys_to_json() ada)

def send_telegram_alert(signal_type, pair, current_price, data, buy_price=None):
    # ... (Kode sebelumnya)
    
    # Simpan data ke JSON dan commit ke GitHub
    try:
        save_active_buys_to_json()
        commit_and_push_changes()
    except Exception as e:
        print(f"❌ Gagal menyimpan/commit: {str(e)}")
    
    # ... (Kode sebelumnya)

def main():
    pairs = get_binance_top_pairs()
    print(f"🔍 Analysing {len(pairs)} pairs @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    for pair in pairs:
        try:
            # Perbaikan format pair (BTCUSDT -> BTC/USDT)
            formatted_pair = pair.replace('USDT', '/USDT')
            data = analyze_pair(formatted_pair)
            
            if not data:
                print(f"⚠️ Tidak ada data untuk {pair}")
                continue

            print(f"\n🔎 {formatted_pair} Analysis:")
            print(f"Support: {data['support']} | Resistance: {data['resistance']}")
            print(f"RSI: {data['rsi']} | MACD: {data['macd']:.4f}")
            
            signal, price = generate_signal(pair, data)
            # ... (Kode sebelumnya)

if __name__ == "__main__":
    main()
