import requests
import time
from binance.client import Client
from tradingview_ta import TA_Handler, Interval, Exchange

# API Key Binance (Opsional)
BINANCE_API_KEY = "YOUR_BINANCE_API_KEY"
BINANCE_API_SECRET = "YOUR_BINANCE_API_SECRET"

# Telegram API
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID"

# Koneksi Binance API
client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

# Ambil 50 koin dengan volume tertinggi
def get_top_50_coins():
    tickers = client.get_ticker()
    sorted_tickers = sorted(tickers, key=lambda x: float(x['quoteVolume']), reverse=True)
    return [t['symbol'] for t in sorted_tickers if t['symbol'].endswith('USDT')][:50]

# Analisis teknikal dengan indikator tambahan di M15 & H1
def analyze_coin(symbol):
    try:
        handler_m15 = TA_Handler(
            symbol=symbol.replace("USDT", ""),
            exchange="BINANCE",
            screener="crypto",
            interval=Interval.INTERVAL_15_MINUTE
        )
        handler_h1 = TA_Handler(
            symbol=symbol.replace("USDT", ""),
            exchange="BINANCE",
            screener="crypto",
            interval=Interval.INTERVAL_1_HOUR
        )

        # Data indikator M15
        analysis_m15 = handler_m15.get_analysis()
        ema9_m15 = analysis_m15.indicators["EMA9"]
        ema21_m15 = analysis_m15.indicators["EMA21"]
        rsi_m15 = analysis_m15.indicators["RSI"]
        macd_m15 = analysis_m15.indicators["MACD.macd"]
        macd_signal_m15 = analysis_m15.indicators["MACD.signal"]
        bb_lower_m15 = analysis_m15.indicators["BB.lower"]
        bb_upper_m15 = analysis_m15.indicators["BB.upper"]
        close_price_m15 = analysis_m15.indicators["close"]
        adx_m15 = analysis_m15.indicators["ADX"]
        obv_m15 = analysis_m15.indicators["OBV"]
        candle_m15 = analysis_m15.summary["RECOMMENDATION"]

        # Data indikator H1
        analysis_h1 = handler_h1.get_analysis()
        ema9_h1 = analysis_h1.indicators["EMA9"]
        ema21_h1 = analysis_h1.indicators["EMA21"]
        rsi_h1 = analysis_h1.indicators["RSI"]
        macd_h1 = analysis_h1.indicators["MACD.macd"]
        macd_signal_h1 = analysis_h1.indicators["MACD.signal"]
        bb_lower_h1 = analysis_h1.indicators["BB.lower"]
        bb_upper_h1 = analysis_h1.indicators["BB.upper"]
        close_price_h1 = analysis_h1.indicators["close"]
        adx_h1 = analysis_h1.indicators["ADX"]
        obv_h1 = analysis_h1.indicators["OBV"]
        candle_h1 = analysis_h1.summary["RECOMMENDATION"]

        # Syarat beli (BUY)
        buy_signal = (
            ema9_m15 > ema21_m15 and ema9_h1 > ema21_h1 and  # EMA 9 cross up EMA 21 di M15 & H1
            rsi_m15 < 30 and rsi_h1 < 50 and  # RSI M15 oversold, RSI H1 belum overbought
            macd_m15 > macd_signal_m15 and macd_h1 > macd_signal_h1 and  # MACD bullish crossover di M15 & H1
            close_price_m15 <= bb_lower_m15 and close_price_h1 <= bb_lower_h1 and  # Harga di lower Bollinger Band
            adx_m15 > 25 and adx_h1 > 25 and  # ADX menunjukkan tren kuat di M15 & H1
            obv_m15 > 0 and obv_h1 > 0 and  # OBV meningkat di M15 & H1
            ("BUY" in candle_m15 or "STRONG_BUY" in candle_m15) and  # Candlestick reversal di M15
            ("BUY" in candle_h1 or "STRONG_BUY" in candle_h1)  # Candlestick reversal di H1
        )

        # Syarat jual (SELL)
        sell_signal = (
            ema9_m15 < ema21_m15 and ema9_h1 < ema21_h1 and  # EMA 9 cross down EMA 21 di M15 & H1
            rsi_m15 > 70 and rsi_h1 > 50 and  # RSI M15 overbought, RSI H1 belum oversold
            macd_m15 < macd_signal_m15 and macd_h1 < macd_signal_h1 and  # MACD bearish crossover di M15 & H1
            close_price_m15 >= bb_upper_m15 and close_price_h1 >= bb_upper_h1 and  # Harga di upper Bollinger Band
            adx_m15 > 25 and adx_h1 > 25 and  # ADX menunjukkan tren kuat di M15 & H1
            obv_m15 < 0 and obv_h1 < 0 and  # OBV menurun di M15 & H1
            ("SELL" in candle_m15 or "STRONG_SELL" in candle_m15) and  # Candlestick reversal di M15
            ("SELL" in candle_h1 or "STRONG_SELL" in candle_h1)  # Candlestick reversal di H1
        )

        return buy_signal, sell_signal
    except Exception as e:
        print(f"Error analyzing {symbol}: {e}")
        return False, False

# Kirim sinyal ke Telegram
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    requests.post(url, json=payload)

# Loop utama untuk memantau sinyal
def main():
    while True:
        top_coins = get_top_50_coins()
        for coin in top_coins:
            try:
                buy, sell = analyze_coin(coin)
                if buy:
                    send_telegram_message(f"ðŸš€ BUY SIGNAL: {coin}\nâœ… Semua indikator konfirmasi sinyal beli!")
                elif sell:
                    send_telegram_message(f"âš ï¸ SELL SIGNAL: {coin}\nâ— Semua indikator konfirmasi sinyal jual!")
            except Exception as e:
                print(f"Error processing {coin}: {e}")
        
        time.sleep(900)  # Cek setiap 15 menit

if __name__ == "__main__":
    main()
    
    
    def analyze_coin(symbol):
    try:
        handler_m15 = TA_Handler(
            symbol=symbol.replace("USDT", ""),
            exchange="BINANCE",
            screener="crypto",
            interval=Interval.INTERVAL_15_MINUTE
        )
        handler_h1 = TA_Handler(
            symbol=symbol.replace("USDT", ""),
            exchange="BINANCE",
            screener="crypto",
            interval=Interval.INTERVAL_1_HOUR
        )

        # Data indikator M15
        analysis_m15 = handler_m15.get_analysis()
        analysis_h1 = handler_h1.get_analysis()

        data = {
            "symbol": symbol,
            "M15": {
                "EMA9": analysis_m15.indicators["EMA9"],
                "EMA21": analysis_m15.indicators["EMA21"],
                "RSI": analysis_m15.indicators["RSI"],
                "MACD": analysis_m15.indicators["MACD.macd"],
                "MACD_signal": analysis_m15.indicators["MACD.signal"],
                "BB_lower": analysis_m15.indicators["BB.lower"],
                "BB_upper": analysis_m15.indicators["BB.upper"],
                "close_price": analysis_m15.indicators["close"],
                "ADX": analysis_m15.indicators["ADX"],
                "OBV": analysis_m15.indicators["OBV"],
                "candle": analysis_m15.summary["RECOMMENDATION"]
            },
            "H1": {
                "EMA9": analysis_h1.indicators["EMA9"],
                "EMA21": analysis_h1.indicators["EMA21"],
                "RSI": analysis_h1.indicators["RSI"],
                "MACD": analysis_h1.indicators["MACD.macd"],
                "MACD_signal": analysis_h1.indicators["MACD.signal"],
                "BB_lower": analysis_h1.indicators["BB.lower"],
                "BB_upper": analysis_h1.indicators["BB.upper"],
                "close_price": analysis_h1.indicators["close"],
                "ADX": analysis_h1.indicators["ADX"],
                "OBV": analysis_h1.indicators["OBV"],
                "candle": analysis_h1.summary["RECOMMENDATION"]
            }
        }

        return data  # Mengembalikan data indikator

    except Exception as e:
        print(f"Error analyzing {symbol}: {e}")
        return None  # Mengembalikan None jika terjadi error
