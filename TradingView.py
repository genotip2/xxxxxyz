import os
import requests
from tradingview_ta import TA_Handler, Interval

# ==============================
# KONFIGURASI
# ==============================
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def get_binance_top_pairs():
    """Ambil top 50 coin di Binance berdasarkan volume trading"""
    url = "https://api.coingecko.com/api/v3/exchanges/binance/tickers"
    params = {
        'include_exchange_logo': 'false',
        'order': 'volume_desc',
        'depth': 'false'
    }
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        
        # Filter USDT pairs dan urutkan berdasarkan volume
        usdt_pairs = [t for t in data['tickers'] if t['target'] == 'USDT']
        sorted_pairs = sorted(usdt_pairs, 
                            key=lambda x: x['converted_volume']['usd'], 
                            reverse=True)[:50]
        
        return [f"{p['base']}USDT" for p in sorted_pairs]
    
    except Exception as e:
        print(f"Error fetching data: {e}")
        return []

def analyze_pair(symbol):
    try:
        handler = TA_Handler(
            symbol=symbol,
            exchange="BINANCE",
            screener="CRYPTO",
            interval=Interval.INTERVAL_4_HOURS
        )
        
        analysis = handler.get_analysis()
        
        # Support & Resistance dari TradingView
        support = analysis.indicators.get('pivotPoints.standard.S1', 'N/A')
        resistance = analysis.indicators.get('pivotPoints.standard.R1', 'N/A')
        
        return {
            'recommendation': analysis.summary['RECOMMENDATION'],
            'rsi': analysis.indicators['RSI'],
            'macd': analysis.indicators['MACD.macd'],
            'signal': analysis.indicators['MACD.signal'],
            'support': support,
            'resistance': resistance,
            'price': analysis.indicators['close']
        }
        
    except Exception as e:
        print(f"Error analyzing {symbol}: {e}")
        return None

def generate_signal(data):
    if "BUY" in data['recommendation']:
        if data['rsi'] < 65 and data['macd'] > data['signal']:
            return 'BUY'
    elif "SELL" in data['recommendation']:
        if data['rsi'] > 35 and data['macd'] < data['signal']:
            return 'SELL'
    return None

def main():
    pairs = get_binance_top_pairs()
    print(f"Top 50 pairs: {pairs}")
    
    for symbol in pairs:
        try:
            data = analyze_pair(symbol)
            if not data:
                continue
                
            signal = generate_signal(data)
            if signal:
                # Kirim notifikasi ke Telegram
                message = (
                    f"🚨 **{signal} {symbol}**\n"
                    f"▫️ Harga: ${data['price']}\n"
                    f"▫️ RSI: {data['rsi']:.1f}\n"
                    f"▫️ Support: {data['support']}\n"
                    f"▫️ Resistance: {data['resistance']}\n"
                    f"▫️ Rekomendasi: {data['recommendation']}"
                )
                
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
                )
                
        except Exception as e:
            print(f"Error processing {symbol}: {e}")
            continue

if __name__ == "__main__":
    main()
