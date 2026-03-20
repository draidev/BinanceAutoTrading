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
# [설정] 환경 변수 및 옵션
# ==========================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET_KEY")

# 감시할 시간대
# TARGET_TIMEFRAMES = ['15m', '1h', '4h', '1d'] 
TARGET_TIMEFRAMES = ['1h', '4h', '1d'] 
COIN_LIMIT = 100       

# 데이터 갱신 대기 시간 (초)
WAIT_BUFFER_SECONDS = 15 

# 한국 시간대 정의 (UTC+9)
KST = timezone(timedelta(hours=9))

# 바이낸스 객체
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
    to_check = []
    minute = current_utc.minute
    hour = current_utc.hour 
    
    # 5m은 제외하고 15m, 1h, 4h, 1d 위주로 다양한 전략 감시 추천
    if '15m' in TARGET_TIMEFRAMES and minute % 15 == 0: to_check.append('15m')
    if '1h' in TARGET_TIMEFRAMES and minute == 0: to_check.append('1h')
    if '4h' in TARGET_TIMEFRAMES and minute == 0 and hour % 4 == 0: to_check.append('4h')
    if '1d' in TARGET_TIMEFRAMES and minute == 0 and hour == 0: to_check.append('1d')
        
    return to_check

def wait_for_next_slot():
    now_utc = datetime.now(timezone.utc)
    next_minute = (now_utc.minute // 5 + 1) * 5
    next_time_utc = now_utc.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=next_minute)
    target_time_utc = next_time_utc + timedelta(seconds=WAIT_BUFFER_SECONDS)
    
    sleep_seconds = (target_time_utc - now_utc).total_seconds()
    if sleep_seconds < 0:
        sleep_seconds += 300
        target_time_utc += timedelta(minutes=5)

    target_kst = target_time_utc.astimezone(KST)
    print(f"\n💤 대기 중... 다음 실행: {target_kst.strftime('%H:%M:%S')} (KST)")
    time.sleep(sleep_seconds)
    return datetime.now(timezone.utc)

def calculate_indicators(df):
    # EMA 계산
    for period in [20, 60, 120, 200]:
        df[f'EMA_{period}'] = df['close'].ewm(span=period, adjust=False).mean()

    # 일목균형표 계산
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

# =========================================================
# 🔍 [핵심] 멀티 전략 신호 감지 함수
# =========================================================
def check_multistrategy_signal(df):
    if len(df) < 52: return None
    
    # 현재 확정된 봉(Close된 봉) 기준
    curr = df.iloc[-2]
    prev = df.iloc[-3]
    
    signals = [] # 발생한 모든 신호를 담을 리스트

    # 공통 조건: 거래량 급증 (평소의 2배 이상)
    # 거래량이 너무 적은 봉의 신호는 속임수일 확률이 높음
    volume_surge = curr['volume'] > prev['volume'] * 2.0
    
    # -----------------------------------------------------
    # 전략 1: 급등/급락 감지 (10% 이상 변동)
    # -----------------------------------------------------
    change_pct = (curr['close'] - prev['close']) / prev['close'] * 100
    if change_pct >= 10.0:
        signals.append(f"🚀 급등 발생 (+{change_pct:.1f}%)")
    elif change_pct <= -10.0:
        signals.append(f"😱 급락 발생 ({change_pct:.1f}%)")

    # -----------------------------------------------------
    # 전략 2: 이평선 크로스 (EMA 20 vs EMA 60)
    # -----------------------------------------------------
    # 골든 크로스: 이전엔 20 < 60 이었는데, 지금은 20 > 60
    if prev['EMA_20'] < prev['EMA_60'] and curr['EMA_20'] > curr['EMA_60']:
        signals.append("❌ 골든 크로스 (20 돌파 60)")
    
    # 데드 크로스
    if prev['EMA_20'] > prev['EMA_60'] and curr['EMA_20'] < curr['EMA_60']:
        signals.append("☠️ 데드 크로스 (20 하향 60)")

    # -----------------------------------------------------
    # 전략 3: 장기 이평선(200EMA) 강력 돌파
    # -----------------------------------------------------
    # 상향 돌파 (거래량 동반 필수)
    if prev['close'] < prev['EMA_200'] and curr['close'] > curr['EMA_200'] and volume_surge:
        signals.append("💥 200EMA 상향 돌파 (강한 추세 전환)")
    
    # 하향 돌파
    if prev['close'] > prev['EMA_200'] and curr['close'] < curr['EMA_200'] and volume_surge:
        signals.append("📉 200EMA 하향 이탈 (추세 붕괴)")

    # -----------------------------------------------------
    # 전략 4: 구름대 (일목균형표) 돌파 - 기존 전략
    # -----------------------------------------------------
    cloud_top = max(curr['span_a'], curr['span_b'])
    cloud_bottom = min(curr['span_a'], curr['span_b'])
    
    # 구름대 상향 돌파 (저항 구름 뚫음)
    if curr['span_a'] < curr['span_b'] and volume_surge: # 음운일 때
        if prev['close'] <= cloud_top and curr['close'] > cloud_top:
            signals.append("☁️ 구름대 상향 돌파 (매수 찬스)")

    # 구름대 하향 이탈 (지지 구름 뚫림)
    if curr['span_a'] > curr['span_b'] and volume_surge: # 양운일 때
        if prev['close'] >= cloud_bottom and curr['close'] < cloud_bottom:
            signals.append("🌧 구름대 하향 이탈 (매도 주의)")

    # 신호가 하나라도 있으면 합쳐서 리턴
    if signals:
        return "\n".join(signals)
    else:
        return None

def run_bot():
    if not BINANCE_API_KEY or not TELEGRAM_TOKEN:
        print("❌ .env 설정 오류: API 키를 확인하세요.")
        return

    print("="*50)
    print("🚀 바이낸스 멀티 전략 봇 시작 (급등/크로스/돌파/구름대)")
    print(f"⏰ 시작 시간: {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*50)
    send_telegram_msg("✅ **멀티 전략 봇 시작됨**\n다양한 신호를 감시합니다.")

    while True:
        try:
            current_utc = wait_for_next_slot()
            active_tfs = get_timeframes_to_check(current_utc)
            current_kst_str = current_utc.astimezone(KST).strftime('%H:%M:%S')
            
            print(f"⏰ [{current_kst_str} KST] 스캔 시작: {active_tfs}")
            
            if not active_tfs:
                continue

            tickers = binance.fetch_tickers()
            volume_list = []
            for symbol, ticker in tickers.items():
                if '/USDT' in symbol and ticker['quoteVolume'] > 0:
                    volume_list.append((symbol, ticker['quoteVolume']))
            
            # 거래대금 상위 코인 선정
            top_coins = sorted(volume_list, key=lambda x: x[1], reverse=True)[:COIN_LIMIT]
            
            scan_count = 0
            
            for symbol, _ in top_coins:
                for tf in active_tfs:
                    try:
                        ohlcv = binance.fetch_ohlcv(symbol, timeframe=tf, limit=100)
                        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                        df = calculate_indicators(df)
                        
                        # [변경] 멀티 전략 함수 호출
                        signal_msg = check_multistrategy_signal(df)
                        scan_count += 1
                        
                        if signal_msg:
                            last_candle_time = str(df.iloc[-2]['timestamp'])
                            alert_key = f"{symbol}_{tf}"
                            
                            # 중복 알림 방지
                            if alert_history.get(alert_key) == last_candle_time:
                                continue 
                            
                            curr_price = df.iloc[-2]['close']
                            
                            # URL 생성 (심볼 정리)
                            clean_symbol = symbol.split(':')[0]       # 'BTC/USDT:USDT' -> 'BTC/USDT'
                            url_symbol = clean_symbol.replace("/", "") # 'BTC/USDT' -> 'BTCUSDT'
                            link = f"https://www.binance.com/en/futures/{url_symbol}"
                            
                            msg = (
                                f"🚨 **신호 포착 ({tf})** 🚨\n\n"
                                f"🪙 **{clean_symbol}**\n"
                                f"{signal_msg}\n\n"  # 여러 신호가 있을 수 있음
                                f"💰 현재가: {curr_price}\n"
                                f"📊 거래량: {df.iloc[-2]['volume']:.1f}\n"
                                f"[👉 차트 보기]({link})"
                            )
                            
                            send_telegram_msg(msg)
                            print(f"   🔔 알림: {symbol} -> {signal_msg.replace(chr(10), ', ')}")
                            alert_history[alert_key] = last_candle_time
                            
                        time.sleep(0.05)
                    except Exception:
                        continue
            
            print(f"✅ 스캔 완료 ({scan_count}회).")
            
        except Exception as e:
            print(f"⚠️ 에러 발생: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_bot()
