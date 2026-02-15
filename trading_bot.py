import ccxt
import pandas as pd
import time

# --- 설정 파트 ---
API_KEY = '1tOkIHA83jxiSnGvILSKDABwf2jZEf6UssHNo4xGRrTT53E95Yh7Thi9lRFyHgtI'       
SECRET_KEY = '0lhXBUJiGtnt0xeMRfcuFP2z7QqCkTESk8RM5sHoiJsSZdm2TRhjipRLczxe1cQU' 

# 분석할 코인 개수 (50개로 축소)
TOP_COIN_LIMIT = 50 

binance = ccxt.binance({
    'apiKey': API_KEY,
    'secret': SECRET_KEY,
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})

def calculate_ichimoku(df):
    """ 일목균형표 계산 (선행스팬 shift 적용) """
    high_9 = df['high'].rolling(window=9).max()
    low_9 = df['low'].rolling(window=9).min()
    df['tenkan_sen'] = (high_9 + low_9) / 2

    high_26 = df['high'].rolling(window=26).max()
    low_26 = df['low'].rolling(window=26).min()
    df['kijun_sen'] = (high_26 + low_26) / 2

    # 선행스팬 1, 2 (26일 앞으로 이동하여 현재 시점의 구름대 형성)
    df['span_a'] = ((df['tenkan_sen'] + df['kijun_sen']) / 2).shift(26)
    
    high_52 = df['high'].rolling(window=52).max()
    low_52 = df['low'].rolling(window=52).min()
    df['span_b'] = ((high_52 + low_52) / 2).shift(26)
    
    return df

def calculate_ema(df):
    """ 지수이동평균(EMA) 계산 """
    ema_periods = [20, 60, 120, 200]
    for period in ema_periods:
        # adjust=False로 설정해야 일반적인 EMA 공식과 일치합니다.
        df[f'EMA_{period}'] = df['close'].ewm(span=period, adjust=False).mean()
    return df

def check_breakout_signal(df):
    """
    핵심 로직: 구름대 돌파 + 거래량 급증 포착
    """
    # 현재 캔들 (확정된 최신 캔들: -2, 진행중 캔들: -1)
    # 안전한 매매를 위해 '마감된 봉(-2)'을 기준으로 판단합니다.
    curr = df.iloc[-2]  
    prev = df.iloc[-3]  # 그 이전 봉

    # 구름대 상단과 하단 정의
    cloud_top = max(curr['span_a'], curr['span_b'])
    cloud_bottom = min(curr['span_a'], curr['span_b'])
    
    # 거래량 조건: 현재 봉 거래량이 이전 봉보다 커야 함
    volume_surge = curr['volume'] > prev['volume']

    signal = None

    # 1. [상승 돌파] 하락 구름대(파란/붉은 구름)를 뚫고 올라감
    # 조건: 구름이 하락추세(Span A < Span B) AND 가격이 구름대 상단을 돌파
    is_bearish_cloud = curr['span_a'] < curr['span_b']
    
    if is_bearish_cloud and volume_surge:
        # 이전에는 구름 아래 or 구름 안에 있다가 -> 현재 구름 위로 종가 마감
        if prev['close'] <= max(prev['span_a'], prev['span_b']) and curr['close'] > cloud_top:
            signal = "BUY_BREAKOUT"

    # 2. [하락 돌파] 상승 구름대(초록 구름)를 뚫고 내려감
    # 조건: 구름이 상승추세(Span A > Span B) AND 가격이 구름대 하단을 하향 돌파
    is_bullish_cloud = curr['span_a'] > curr['span_b']
    
    if is_bullish_cloud and volume_surge:
        # 이전에는 구름 위 or 구름 안에 있다가 -> 현재 구름 아래로 종가 마감
        if prev['close'] >= min(prev['span_a'], prev['span_b']) and curr['close'] < cloud_bottom:
            signal = "SELL_BREAKDOWN"

    return signal, curr['volume'], prev['volume']

def analyze_market():
    print(f"🔄 상위 {TOP_COIN_LIMIT}개 코인 스캔 시작...")
    
    # 1. 거래대금 상위 50개 선정
    tickers = binance.fetch_tickers()
    volume_list = []
    for symbol, ticker in tickers.items():
        if '/USDT' in symbol and ticker['quoteVolume'] > 0:
            volume_list.append((symbol, ticker['quoteVolume']))
    
    top_coins = sorted(volume_list, key=lambda x: x[1], reverse=True)[:TOP_COIN_LIMIT]
    top_symbols = [coin[0] for coin in top_coins]

    detected_signals = []

    # 2. 각 코인 분석
    for symbol in top_symbols:
        try:
            # 1시간봉 기준 (원하는 타임프레임으로 변경 가능: 15m, 4h, 1d)
            ohlcv = binance.fetch_ohlcv(symbol, timeframe='1h', limit=100)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            if len(df) < 52: continue # 데이터 부족 시 패스

            df = calculate_ema(df)
            df = calculate_ichimoku(df)
            
            # 신호 포착
            signal, curr_vol, prev_vol = check_breakout_signal(df)
            
            if signal:
                print(f"🚨 신호 발견! [{symbol}] : {signal}")
                print(f"   - 거래량 변화: {prev_vol:.1f} -> {curr_vol:.1f} (증가)")
                
                # 결과 리스트에 저장
                curr_price = df.iloc[-2]['close']
                detected_signals.append({
                    'coin': symbol,
                    'signal': signal,
                    'price': curr_price,
                    'ema_200': df.iloc[-2]['EMA_200']
                })
            else:
                # 진행 상황 표시 (점 찍기)
                print(".", end="", flush=True)

            time.sleep(0.1) # API 제한 준수

        except Exception as e:
            print(f"Error {symbol}: {e}")

    # 3. 최종 리포트
    print("\n\n====== 📋 분석 결과 리포트 ======")
    if not detected_signals:
        print("현재 조건에 맞는 강력한 돌파 신호가 없습니다.")
    else:
        for item in detected_signals:
            side = "🔥 매수(롱)" if item['signal'] == "BUY_BREAKOUT" else "💧 매도(숏)"
            print(f"[{item['coin']}] {side} 기회 포착!")
            print(f"   현재가: {item['price']} | 200 EMA: {item['ema_200']:.4f}")

if __name__ == "__main__":
    analyze_market()
