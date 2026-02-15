import ccxt
import pandas as pd
import time


def compute_rsi(closes, period=14):
    """RSI(14) 계산 - Wilder 스무딩 방식"""
    if len(closes) < period + 1:
        return None
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [c if c > 0 else 0 for c in changes]
    losses = [-c if c < 0 else 0 for c in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def fetch_top_futures_coins():
    print("🔄 바이낸스 선물 데이터를 가져오는 중입니다...")
    
    # 1. 바이낸스 선물(Futures) 인스턴스 생성
    binance = ccxt.binance({
        'options': {
            'defaultType': 'future',  # 선물 마켓 기준
        }
    })

    try:
        # 2. 모든 티커(시세) 데이터 조회
        # fetch_tickers()는 모든 코인의 24시간 변동 데이터를 한 번에 가져옵니다.
        tickers = binance.fetch_tickers()
        
        data = []
        
        for symbol, ticker in tickers.items():
            # USDT 선물 페어만 필터링 (예: BTC/USDT)
            # COIN-M(코인 선물)이나 BUSD 선물 등은 제외
            if '/USDT' in symbol:
                quote_volume = ticker.get('quoteVolume') # 거래대금 (USDT 기준)
                
                # 거래량이 있는 것만 수집
                if quote_volume:
                    data.append({
                        'Symbol': symbol,
                        'Price': ticker['last'],           # 현재가
                        '24h_Volume(USDT)': quote_volume,  # 24시간 거래대금
                        'Change(%)': ticker['percentage']  # 24시간 변동률
                    })

        # 3. 데이터프레임 변환 및 정렬
        df = pd.DataFrame(data)
        
        # 거래대금(Volume) 기준으로 내림차순 정렬 (가장 핫한 코인 순서)
        df_sorted = df.sort_values(by='24h_Volume(USDT)', ascending=False)
        
        # 4. 보기 좋게 포맷팅 (USDT 단위 콤마 찍기 등) 및 상위 100개 자르기
        top_100 = df_sorted.head(100).reset_index(drop=True)
        
        # 5. RSI(14) 계산 - 1시간봉 기준
        print("\n🔄 RSI 지표 계산 중...")
        rsi_list = []
        for idx, row in top_100.iterrows():
            symbol = row['Symbol']
            try:
                ohlcv = binance.fetch_ohlcv(symbol, timeframe='1h', limit=20)
                if ohlcv and len(ohlcv) >= 15:
                    closes = [c[4] for c in ohlcv]
                    rsi = compute_rsi(closes, period=14)
                    rsi_list.append(rsi)
                else:
                    rsi_list.append(None)
            except Exception:
                rsi_list.append(None)
            time.sleep(0.1)  # API rate limit 완화
        top_100.insert(4, 'RSI(14)', rsi_list)
        
        # 숫자를 읽기 쉽게 포맷팅 (선택 사항)
        pd.options.display.float_format = '{:,.2f}'.format
        
        print("\n📊 [바이낸스 선물 거래대금 상위 100개 리스트]")
        print(top_100)
        
        # CSV 파일로 저장 (분석용)
        top_100.to_csv('binance_futures_top100.csv', index=False)
        print("\n✅ 'binance_futures_top100.csv' 파일로 저장되었습니다.")
        
        return top_100

    except Exception as e:
        print(f"❌ 에러 발생: {e}")

if __name__ == "__main__":
    fetch_top_futures_coins()
