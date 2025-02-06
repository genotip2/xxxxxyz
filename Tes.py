from tradingview_ta import TA_Handler, Interval

symbol = "BTCUSDT"  # Ganti dengan simbol yang ingin dicek

handler = TA_Handler(
    symbol=symbol,
    exchange="BINANCE",
    screener="CRYPTO",
    interval=Interval.INTERVAL_15_MINUTES
)

analysis = handler.get_analysis()

# Cetak semua indikator yang tersedia
print(analysis.indicators.keys())
