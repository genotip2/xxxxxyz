from tradingview_ta import TA_Handler

handler = TA_Handler(
            symbol=symbol,
            exchange="BINANCE",
            screener="CRYPTO",
            interval=Interval.INTERVAL_15_MINUTES
        ).get_analysis()

# Cetak semua key indikator
print(analysis.indicators.keys())
