import ccxt
import pandas as pd
import time
import requests
from datetime import datetime, timedelta, timezone
import sys
import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# ==========================================
# [설정] 환경 변수 로드
# ==========================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET_KEY")

# [설정] 감시할 시간대
TARGET_TIMEFRAMES = ['5m', '15m', '1h', '4h', '1d'] 
COIN_LIMIT = 100 
STRICT_MODE = True    
WAIT_BUFFER_SECONDS = 15 

# 한국 시간대 정의 (UTC+9)
KST = timezone(timedelta(hours=9))

# 바이낸스 객체 생성 (API 키 적용)
binance = ccxt.binance({
    'apiKey': BINANCE_API_KEY,
    'secret': BINANCE_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})

alert_history = {}

def send_telegram_msg(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    try:
        requests.post(url, data=data, timeout=5)
    except Exception as e:
        print(f"❌ 텔레그램 전송 에러: {e}")

def get_timeframes_to_check(current_utc):
    """
    현재 UTC 시간을 기준으로 갱신된 봉을 판단합니다.
    (UTC 0시 = KST 9시)
    """
    to_check = []
    
    minute = current_utc.minute
    hour = current_utc.hour # UTC 기준 시각 (0~23)
    
    # 1. 5분봉: 매 5분마다 실행되므로 항상 포함
    if '5m' in TARGET_TIMEFRAMES:
        to_check.append('5m')
        
    # 2. 15분봉: 0, 15, 30, 45분
    if '15m' in TARGET_TIMEFRAMES and minute % 15 == 0:
        to_check.append('15m')
        
    # 3. 1시간봉: 정각 (0분)
    if '1h' in TARGET_TIMEFRAMES and minute == 0:
        to_check.append('1h')
        
    # 4. 4시간봉: 정각이고, UTC 시간이 4의 배수일 때
    # UTC: 0, 4, 8, 12, 16, 20
    # KST: 9, 13, 17, 21, 1, 5 (말씀하신 1,5,9 패턴)
    if '4h' in TARGET_TIMEFRAMES and minute == 0 and hour % 4 == 0:
        to_check.append('4h')
        
    # 5. 1일봉: 정각이고, UTC 시간이 0시일 때
    # KST: 아침 9시
    if '1d' in TARGET_TIMEFRAMES and minute == 0 and hour == 0:
        to_check.append('1d')
        
    return to_check

def wait_for_next_slot():
    """
    다음 5분 단위까지 대기 (한국 시간 로그 출력)
    """
    now_utc = datetime.now(timezone.utc)
    
    # 다음 5분 단위 계산
    next_minute = (now_utc.minute // 5 + 1) * 5
    next_time_utc = now_utc.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=next_minute)
    
    # 데이터 생성 대기 시간 추가
    target_time_utc = next_time_utc + timedelta(seconds=WAIT_BUFFER_SECONDS)
    
    sleep_seconds = (target_time_utc - now_utc).total_seconds()
    
    if sleep_seconds < 0:
        sleep_seconds += 300
        target_time_utc += timedelta(minutes=5)

    # 로그용 한국 시간 변환
    target_kst = target_time_utc.astimezone(KST)
    print(f"\n💤 대기 중... 다음 실행: {target_kst.strftime('%H:%M:%S')} (KST)")
    
    time.sleep(sleep_seconds)
    return datetime.now(timezone.utc)

def calculate_indicators(df):
    for period in [20, 60, 120, 200]:
        df[f'EMA_{period}'] = df['close'].ewm(span=period, adjust=False).mean()

    high_9 = df['high'].rolling(window=9).max()
    low_9 = df['low'].rolling(window=9).min()
    df['tenkan_sen'] = (high_9 + low_9) / 2

    high_26 = df['high'].rolling(window=26).max()
    low_26 = df['low'].rolling(window=26).min()
    df['kijun_sen'] = (high_26 + low_26) / 2

    df['span_a'] = ((df['tenkan_sen'] + df['kijun_sen']) / 2).shift(26)
    high_52 = df['high'].rolling(window=52).max()
    low_52 = df['low'].rolling(window=52).min()
    df['span_b'] = ((high_52 + low_52) / 2).shift(26)
    return df

def check_signal(df):
    if len(df) < 52: return None
    curr = df.iloc[-2]
    prev = df.iloc[-3]
    cloud_top = max(curr['span_a'], curr['span_b'])
    cloud_bottom = min(curr['span_a'], curr['span_b'])
    
    signal = None
    volume_surge = curr['volume'] > prev['volume'] * 2.0
    
    if STRICT_MODE:
        if curr['span_a'] < curr['span_b'] and volume_surge:
            if prev['close'] <= cloud_top and curr['close'] > cloud_top:
                signal = "🔥 STRONG BUY (상승 돌파)"
        if curr['span_a'] > curr['span_b'] and volume_surge:
            if prev['close'] >= cloud_bottom and curr['close'] < cloud_bottom:
                signal = "💧 STRONG SELL (하락 이탈)"
    else:
        if curr['close'] > cloud_top: signal = "📈 BUY Trend (Test)"
        elif curr['close'] < cloud_bottom: signal = "📉 SELL Trend (Test)"
            
    return signal

def run_bot():
    print("="*50)
    print("🚀 바이낸스 한국 시간(KST) 맞춤 봇 시작")
    print(f"⏰ 현재 한국 시각: {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*50)
    send_telegram_msg("✅ **봇 시작됨** (KST 기준 1,5,9시 4시간봉 / 아침 9시 일봉 체크)")

    while True:
        try:
            current_utc = wait_for_next_slot()
            active_tfs = get_timeframes_to_check(current_utc)
            
            # 로그용 한국 시간
            current_kst_str = current_utc.astimezone(KST).strftime('%H:%M:%S')
            
            print(f"⏰ [{current_kst_str} KST] 검사 시작! 대상 봉: {active_tfs}")
            
            if not active_tfs:
                continue

            tickers = binance.fetch_tickers()
            volume_list = []
            for symbol, ticker in tickers.items():
                if '/USDT' in symbol and ticker['quoteVolume'] > 0:
                    volume_list.append((symbol, ticker['quoteVolume']))
            
            top_coins = sorted(volume_list, key=lambda x: x[1], reverse=True)[:COIN_LIMIT]
            
            scan_count = 0
            
            for symbol, _ in top_coins:
                for tf in active_tfs:
                    try:
                        ohlcv = binance.fetch_ohlcv(symbol, timeframe=tf, limit=100)
                        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                        df = calculate_indicators(df)
                        signal = check_signal(df)
                        scan_count += 1
                        
                        if signal:
                            last_candle_time = str(df.iloc[-2]['timestamp'])
                            alert_key = f"{symbol}_{tf}"
                            
                            if alert_history.get(alert_key) == last_candle_time:
                                continue 
                            
                            curr_price = df.iloc[-2]['close']
                            raw_symbol = symbol.replace("/", "")
                            link = f"https://www.binance.com/en/futures/{raw_symbol}"
                            
                            msg = (
                                f"🚨 **신호 포착 ({tf} 마감)** 🚨\n\n"
                                f"🪙 **{symbol}**\n"
                                f"📊 {signal}\n"
                                f"💰 Price: {curr_price}\n"
                                f"[👉 차트 이동]({link})"
                            )
                            
                            send_telegram_msg(msg)
                            print(f"   🔔 알림 전송: {symbol} ({tf})")
                            alert_history[alert_key] = last_candle_time
                            
                        time.sleep(0.05)
                    except Exception:
                        continue
            
            print(f"✅ 검사 완료 ({scan_count}회 조회).")
            
        except Exception as e:
            print(f"⚠️ 에러: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_bot()
