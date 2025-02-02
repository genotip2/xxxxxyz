import os
import requests
from tradingview_ta import TA_Handler, Interval
from datetime import datetime, timedelta

# ==============================
# KONFIGURASI
# ==============================
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
ACTIVE_BUYS = {}  # Format: {pair: {'price': x, 'time': y}}

def get_top_pairs():
    """Ambil 50 pair teratas dari CoinGecko"""
    url = "https://api.coingecko.com/api/v3/exchanges/binance/tickers"
    try:
        response = requests.get(url, params={'order': 'volume_desc'})
        usdt_pairs = [t for t in response.json()['tickers'] if t['target'] == 'USDT']
        return sorted([f"{p['base']}USDT" for p in usdt_pairs], 
                     key=lambda x: float(x.volume), reverse=True)[:50]
    except:
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT"]  # Fallback

def analyze_pair(pair):
    analysis = TA_Handler(
        symbol=pair,
        exchange="BINANCE",
        screener="CRYPTO",
        interval=Interval.INTERVAL_4_HOURS
    ).get_analysis()
    
    indicators = analysis.indicators
    summary = analysis.summary
    
    return {
        'price': indicators['close'],
        'rsi': indicators['RSI'],
        'macd': indicators['MACD.macd'],
        'signal': indicators['MACD.signal'],
        'adx': indicators['ADX'],
        'volume': indicators['volume'],
        'recommendation': summary['RECOMMENDATION'],
        'support': indicators.get('Pivot.M.S1', indicators['low']),
        'resistance': indicators.get('Pivot.M.R1', indicators['high'])
    }

def generate_signal(pair, data):
    current_price = data['price']
    
    # Kondisi Buy
    buy_conditions = (
        "BUY" in data['recommendation'] and
        data['rsi'] < 65 and
        data['macd'] > data['signal'] and
        data['adx'] > 25 and
        current_price > data['resistance'] * 0.99 and
        data['volume'] > 1000000  # Volume > $1 juta
    )
    
    # Kondisi Sell
    sell_conditions = (
        "SELL" in data['recommendation'] and
        pair in ACTIVE_BUYS and
        current_price < ACTIVE_BUYS[pair]['price'] * 0.98  # Stop loss 2%
    )
    
    if buy_conditions and pair not in ACTIVE_BUYS:
        return 'BUY', current_price
    elif sell_conditions:
        return 'SELL', ACTIVE_BUYS[pair]['price']
    return None, None

def send_telegram_alert(signal_type, pair, current_price, buy_price=None):
    if signal_type == 'BUY':
        message = f"""🚀 **BUY {pair}**
▫️ Entry Price: ${current_price:.4f}
▫️ Support: ${data['support']:.4f}
▫️ Resistance: ${data['resistance']:.4f}
🔍 RSI: {data['rsi']:.1f} | MACD: {data['macd']:.4f}"""
        ACTIVE_BUYS[pair] = {'price': current_price, 'time': datetime.now()}
        
    elif signal_type == 'SELL':
        message = f"""⚠️ **SELL {pair}**
▫️ Exit Price: ${current_price:.4f}
▫️ Buy Price: ${buy_price:.4f}
▫️ Profit: {((current_price - buy_price)/buy_price)*100:.2f}%
🕒 Hold Duration: {str(datetime.now() - ACTIVE_BUYS[pair]['time']).split('.')[0]}"""
        del ACTIVE_BUYS[pair]
        
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    )

def main():
    pairs = get_top_pairs()
    print(f"Analisis {len(pairs)} pair @ {datetime.now()}")
    
    for pair in pairs:
        try:
            data = analyze_pair(pair)
            signal, price = generate_signal(pair, data)
            
            if signal:
                send_telegram_alert(signal, pair, data['price'], price)
                
            # Auto-sell jika profit > 5% atau 24 jam
            if pair in ACTIVE_BUYS:
                buy_price = ACTIVE_BUYS[pair]['price']
                hold_time = datetime.now() - ACTIVE_BUYS[pair]['time']
                
                if (data['price'] > buy_price * 1.05) or (hold_time > timedelta(hours=24)):
                    send_telegram_alert('SELL', pair, data['price'], buy_price)
                    
        except Exception as e:
            print(f"Error {pair}: {str(e)}")
            continue

if __name__ == "__main__":
    main()
