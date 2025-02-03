            display_pair = f"{pair[:-4]}/USDT"
            print(f"\n📈 {display_pair}:")
            print(f"Support: {data['support']:.8f} | Resistance: {data['resistance']:.8f}")
            print(f"BB: {data['bb_lower']:.8f} - {data['bb_upper']:.8f}")
            
            signal, price = generate_signal(pair, data)
            if signal:
                send_telegram_alert(signal, pair, data['price'], data, price)
                
            # Auto close position
            if pair in ACTIVE_BUYS:
                position = ACTIVE_BUYS[pair]
                duration = datetime.now() - position['time']
                profit = (data['price'] - position['price'])/position['price']*100
                
                if duration > timedelta(hours=24) or abs(profit) > 8:
                    send_telegram_alert('SELL', pair, data['price'], data, position['price'])
                    
        except Exception as e:
            print(f"⚠️ Error di {pair}: {str(e)}")
            continue

if __name__ == "__main__":
    main()
