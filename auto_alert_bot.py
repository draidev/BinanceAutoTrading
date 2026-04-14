import ccxt
import pandas as pd
import time
import requests
from datetime import datetime, timedelta, timezone
import os
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# [설정] 환경 변수 및 옵션
# ==========================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET_KEY")

# 감시할 시간대
TARGET_TIMEFRAMES = ['15m', '1h', '4h', '1d']

# 거래대금 상위 코인 수
COIN_LIMIT = 100

# 스캔 주기 (초) - 이 간격마다 현재 가격으로 지표 돌파 여부 확인
SCAN_INTERVAL_SECONDS = 60

# 쿨다운 설정 (같은 신호 재알림 방지, 시간프레임별 자동 조절)
COOLDOWN_MAP = {
    '5m':  300,      # 5분
    '15m': 900,      # 15분
    '1h':  3600,     # 1시간
    '4h':  14400,    # 4시간
    '1d':  86400,    # 1일
}

# 한국 시간대 (UTC+9)
KST = timezone(timedelta(hours=9))

# 바이낸스 객체
binance = ccxt.binance({
    'apiKey': BINANCE_API_KEY,
    'secret': BINANCE_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})

# 쿨다운 기록: { "BTC/USDT_1h_골든크로스": timestamp }
alert_cooldown = {}


# ==========================================
# 텔레그램 전송
# ==========================================
def send_telegram_msg(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    try:
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print(f"❌ 텔레그램 전송 에러: {e}")


def is_cooled_down(symbol, tf, signal_name):
    """쿨다운 확인: 같은 (심볼, 시간프레임, 신호타입)에 대해 재알림 방지"""
    key = f"{symbol}_{tf}_{signal_name}"
    now = time.time()
    cooldown_sec = COOLDOWN_MAP.get(tf, 3600)

    if key in alert_cooldown:
        elapsed = now - alert_cooldown[key]
        if elapsed < cooldown_sec:
            return False  # 아직 쿨다운 중
    alert_cooldown[key] = now
    return True


# ==========================================
# 지표 계산
# ==========================================
def calculate_indicators(df):
    # EMA
    for period in [20, 60, 120, 200]:
        df[f'EMA_{period}'] = df['close'].ewm(span=period, adjust=False).mean()

    # 일목균형표
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

    # RSI (14)
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))

    # MACD (12, 26, 9)
    ema_12 = df['close'].ewm(span=12, adjust=False).mean()
    ema_26 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema_12 - ema_26
    df['MACD_signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_hist'] = df['MACD'] - df['MACD_signal']

    # 볼린저 밴드 (20, 2σ)
    df['BB_mid'] = df['close'].rolling(window=20).mean()
    bb_std = df['close'].rolling(window=20).std()
    df['BB_upper'] = df['BB_mid'] + 2 * bb_std
    df['BB_lower'] = df['BB_mid'] - 2 * bb_std

    return df


# =========================================================
# 🔍 [핵심] 실시간 멀티 전략 신호 감지
#    - prev: 직전 마감 봉 (df.iloc[-2])
#    - curr: 현재 진행 중인 봉 (df.iloc[-1], 실시간 가격 반영)
# =========================================================
def check_realtime_signals(df):
    if len(df) < 52:
        return []

    curr = df.iloc[-1]   # 현재 봉 (아직 마감되지 않은, 실시간 가격)
    prev = df.iloc[-2]   # 직전 마감 봉

    signals = []

    # 공통: 거래량 급증 (현재 봉의 거래량이 이전 마감 봉 대비 2배)
    volume_surge = curr['volume'] > prev['volume'] * 2.0

    # -------------------------------------------------
    # 1. 급등/급락 감지 (직전 마감가 대비 현재가)
    # -------------------------------------------------
    change_pct = (curr['close'] - prev['close']) / prev['close'] * 100
    if change_pct >= 10.0:
        signals.append(("급등", f"🚀 급등 발생 (+{change_pct:.1f}%)"))
    elif change_pct <= -10.0:
        signals.append(("급락", f"😱 급락 발생 ({change_pct:.1f}%)"))

    # -------------------------------------------------
    # 2. EMA 크로스 (20 vs 60)
    #    직전 봉까지 20<60이었는데 현재가 기준 20>60이면 골든크로스
    # -------------------------------------------------
    if prev['EMA_20'] < prev['EMA_60'] and curr['EMA_20'] > curr['EMA_60']:
        signals.append(("골든크로스", "✨ 골든 크로스 (EMA20 ↑ EMA60)"))
    if prev['EMA_20'] > prev['EMA_60'] and curr['EMA_20'] < curr['EMA_60']:
        signals.append(("데드크로스", "☠️ 데드 크로스 (EMA20 ↓ EMA60)"))

    # -------------------------------------------------
    # 3. 200EMA 돌파 (거래량 동반)
    # -------------------------------------------------
    if prev['close'] < prev['EMA_200'] and curr['close'] > curr['EMA_200'] and volume_surge:
        signals.append(("200EMA상향", "💥 200EMA 상향 돌파 (추세 전환)"))
    if prev['close'] > prev['EMA_200'] and curr['close'] < curr['EMA_200'] and volume_surge:
        signals.append(("200EMA하향", "📉 200EMA 하향 이탈 (추세 붕괴)"))

    # -------------------------------------------------
    # 4. 일목균형표 구름대 돌파 (거래량 동반)
    # -------------------------------------------------
    if pd.notna(curr['span_a']) and pd.notna(curr['span_b']):
        cloud_top = max(curr['span_a'], curr['span_b'])
        cloud_bottom = min(curr['span_a'], curr['span_b'])

        # 음운(저항) 상향 돌파
        if curr['span_a'] < curr['span_b'] and volume_surge:
            if prev['close'] <= cloud_top and curr['close'] > cloud_top:
                signals.append(("구름상향", "☁️ 구름대 상향 돌파 (매수 찬스)"))

        # 양운(지지) 하향 이탈
        if curr['span_a'] > curr['span_b'] and volume_surge:
            if prev['close'] >= cloud_bottom and curr['close'] < cloud_bottom:
                signals.append(("구름하향", "🌧 구름대 하향 이탈 (매도 주의)"))

    # -------------------------------------------------
    # 5. RSI 과매수/과매도
    # -------------------------------------------------
    if pd.notna(curr['RSI']):
        if curr['RSI'] > 70:
            signals.append(("RSI과매수", f"🔴 RSI 과매수 ({curr['RSI']:.0f})"))
        elif curr['RSI'] < 30:
            signals.append(("RSI과매도", f"🔵 RSI 과매도 ({curr['RSI']:.0f})"))

    # -------------------------------------------------
    # 6. MACD 크로스
    # -------------------------------------------------
    if pd.notna(prev['MACD']) and pd.notna(curr['MACD']):
        if prev['MACD'] < prev['MACD_signal'] and curr['MACD'] > curr['MACD_signal']:
            signals.append(("MACD골든", "📗 MACD 골든 크로스 (매수 신호)"))
        if prev['MACD'] > prev['MACD_signal'] and curr['MACD'] < curr['MACD_signal']:
            signals.append(("MACD데드", "📕 MACD 데드 크로스 (매도 신호)"))

    # -------------------------------------------------
    # 7. 볼린저 밴드 이탈
    # -------------------------------------------------
    if pd.notna(curr['BB_upper']) and pd.notna(curr['BB_lower']):
        if prev['close'] <= prev['BB_upper'] and curr['close'] > curr['BB_upper']:
            signals.append(("BB상단돌파", f"🔺 볼린저 상단 돌파 (과열 주의)"))
        if prev['close'] >= prev['BB_lower'] and curr['close'] < curr['BB_lower']:
            signals.append(("BB하단이탈", f"🔻 볼린저 하단 이탈 (반등 기대)"))

    return signals


# ==========================================
# 메인 봇 루프
# ==========================================
def run_bot():
    if not BINANCE_API_KEY or not TELEGRAM_TOKEN:
        print("❌ .env 설정 오류: API 키를 확인하세요.")
        return

    print("=" * 55)
    print("🚀 실시간 멀티 전략 봇 시작")
    print(f"   스캔 주기: {SCAN_INTERVAL_SECONDS}초")
    print(f"   시간대: {TARGET_TIMEFRAMES}")
    print(f"   상위 코인: {COIN_LIMIT}개")
    print(f"⏰ 시작 시간: {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')} KST")
    print("=" * 55)

    send_telegram_msg(
        "✅ **실시간 멀티 전략 봇 시작**\n"
        f"⏱ 스캔 주기: {SCAN_INTERVAL_SECONDS}초\n"
        f"📊 시간대: {', '.join(TARGET_TIMEFRAMES)}\n"
        f"🔍 전략: 급등/크로스/200EMA/구름대/RSI/MACD/볼린저"
    )

    while True:
        try:
            scan_start = time.time()
            now_kst = datetime.now(KST).strftime('%H:%M:%S')
            print(f"\n⏰ [{now_kst} KST] 스캔 시작...")

            # 거래대금 상위 코인 조회
            tickers = binance.fetch_tickers()
            volume_list = [
                (symbol, ticker['quoteVolume'])
                for symbol, ticker in tickers.items()
                if '/USDT' in symbol and ticker.get('quoteVolume', 0) > 0
            ]
            top_coins = sorted(volume_list, key=lambda x: x[1], reverse=True)[:COIN_LIMIT]

            scan_count = 0
            alert_count = 0

            for symbol, _ in top_coins:
                for tf in TARGET_TIMEFRAMES:
                    try:
                        ohlcv = binance.fetch_ohlcv(symbol, timeframe=tf, limit=120)
                        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                        df = calculate_indicators(df)
                        scan_count += 1

                        signals = check_realtime_signals(df)

                        for signal_name, signal_msg in signals:
                            if not is_cooled_down(symbol, tf, signal_name):
                                continue

                            curr_price = df.iloc[-1]['close']
                            clean_symbol = symbol.split(':')[0]
                            url_symbol = clean_symbol.replace("/", "")
                            link = f"https://www.binance.com/en/futures/{url_symbol}"

                            msg = (
                                f"🚨 **실시간 신호 ({tf})** 🚨\n\n"
                                f"🪙 **{clean_symbol}**\n"
                                f"{signal_msg}\n\n"
                                f"💰 현재가: {curr_price:,.4f}\n"
                                f"📊 거래량: {df.iloc[-1]['volume']:.1f}\n"
                                f"🕐 감지 시각: {datetime.now(KST).strftime('%H:%M:%S')} KST\n"
                                f"[👉 차트 보기]({link})"
                            )
                            send_telegram_msg(msg)
                            print(f"   🔔 {clean_symbol} [{tf}] → {signal_msg}")
                            alert_count += 1

                        time.sleep(0.05)
                    except Exception:
                        continue

            elapsed = time.time() - scan_start
            print(f"✅ 스캔 완료 ({scan_count}건 분석, {alert_count}건 알림, {elapsed:.1f}초 소요)")

            # 다음 스캔까지 대기
            sleep_time = max(0, SCAN_INTERVAL_SECONDS - elapsed)
            if sleep_time > 0:
                print(f"💤 {sleep_time:.0f}초 대기...")
                time.sleep(sleep_time)

        except KeyboardInterrupt:
            print("\n🛑 봇 종료됨.")
            send_telegram_msg("🛑 **봇이 종료되었습니다.**")
            break
        except Exception as e:
            print(f"⚠️ 에러 발생: {e}")
            time.sleep(30)


if __name__ == "__main__":
    run_bot()
