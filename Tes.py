from tradingview_ta import TA_Handler

analysis = TA_Handler(
    symbol="BTCUSD",
    screener="crypto",
    exchange="Binance",
    interval="1d"
).get_analysis()

# Cetak semua key indikator
print(analysis.indicators.keys())
