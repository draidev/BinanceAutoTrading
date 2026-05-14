import ccxt
import pandas as pd
import time
import requests
from datetime import datetime, timedelta, timezone
import os
from dotenv import load_dotenv
from common import calculate_indicators, check_signals, FETCH_LIMIT

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET_KEY")

TARGET_TIMEFRAMES = ['15m', '1h', '4h', '1d']
COIN_LIMIT = 100
SCAN_INTERVAL_SECONDS = 60

COOLDOWN_MAP = {
    '5m':  300,
    '15m': 900,
    '1h':  3600,
    '4h':  14400,
    '1d':  86400,
}

KST = timezone(timedelta(hours=9))

binance = ccxt.binance({
    'apiKey': BINANCE_API_KEY,
    'secret': BINANCE_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})

alert_cooldown: dict[str, float] = {}


def send_telegram_msg(message: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    try:
        resp = requests.post(url, data=data, timeout=10)
        resp.raise_for_status()
        return True
    except requests.exceptions.HTTPError as e:
        print(f"❌ 텔레그램 HTTP 에러: {e} — 응답: {resp.text}")
    except requests.exceptions.ConnectionError as e:
        print(f"❌ 텔레그램 연결 에러: {e}")
    except requests.exceptions.Timeout:
        print("❌ 텔레그램 타임아웃")
    except Exception as e:
        print(f"❌ 텔레그램 전송 에러: {e}")
    return False


def is_cooled_down(symbol: str, tf: str, signal_name: str) -> bool:
    key = f"{symbol}_{tf}_{signal_name}"
    now = time.time()
    cooldown_sec = COOLDOWN_MAP.get(tf, 3600)

    if key in alert_cooldown and now - alert_cooldown[key] < cooldown_sec:
        return False
    alert_cooldown[key] = now
    return True


def run_bot():
    if not BINANCE_API_KEY or not TELEGRAM_TOKEN:
        print("❌ .env 설정 오류: API 키를 확인하세요.")
        return

    print("=" * 55)
    print("🚀 실시간 멀티 전략 봇 시작")
    print(f"   스캔 주기: {SCAN_INTERVAL_SECONDS}초")
    print(f"   시간대: {TARGET_TIMEFRAMES}")
    print(f"   상위 코인: {COIN_LIMIT}개")
    print(f"   OHLCV 봉 수: {FETCH_LIMIT}")
    print(f"⏰ 시작 시간: {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')} KST")
    print("=" * 55)

    send_telegram_msg(
        "✅ **실시간 멀티 전략 봇 시작**\n"
        f"⏱ 스캔 주기: {SCAN_INTERVAL_SECONDS}초\n"
        f"📊 시간대: {', '.join(TARGET_TIMEFRAMES)}\n"
        f"🔍 전략: 급등/크로스/200EMA/구름대/RSI/CCI/MACD/볼린저"
    )

    while True:
        try:
            scan_start = time.time()
            now_kst = datetime.now(KST).strftime('%H:%M:%S')
            print(f"\n⏰ [{now_kst} KST] 스캔 시작...")

            try:
                tickers = binance.fetch_tickers()
            except Exception as e:
                print(f"⚠️ fetch_tickers 에러: {e}")
                time.sleep(30)
                continue

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
                        ohlcv = binance.fetch_ohlcv(symbol, timeframe=tf, limit=FETCH_LIMIT)
                        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                        df = calculate_indicators(df)
                        scan_count += 1

                        signals = check_signals(df)

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
                            if send_telegram_msg(msg):
                                print(f"   🔔 {clean_symbol} [{tf}] → {signal_msg}")
                                alert_count += 1
                            else:
                                print(f"   ⚠️ 텔레그램 전송 실패: {clean_symbol} [{tf}] {signal_msg}")

                        time.sleep(0.05)

                    except ccxt.RateLimitExceeded as e:
                        print(f"⚠️ Rate limit 초과 ({symbol} {tf}): {e} — 10초 대기")
                        time.sleep(10)
                    except ccxt.NetworkError as e:
                        print(f"⚠️ 네트워크 에러 ({symbol} {tf}): {e}")
                    except ccxt.ExchangeError as e:
                        print(f"⚠️ 거래소 에러 ({symbol} {tf}): {e}")
                    except Exception as e:
                        print(f"⚠️ 예상치 못한 에러 ({symbol} {tf}): {e}")

            elapsed = time.time() - scan_start
            print(f"✅ 스캔 완료 ({scan_count}건 분석, {alert_count}건 알림, {elapsed:.1f}초 소요)")

            sleep_time = max(0, SCAN_INTERVAL_SECONDS - elapsed)
            if sleep_time > 0:
                print(f"💤 {sleep_time:.0f}초 대기...")
                time.sleep(sleep_time)

        except KeyboardInterrupt:
            print("\n🛑 봇 종료됨.")
            send_telegram_msg("🛑 **봇이 종료되었습니다.**")
            break
        except Exception as e:
            print(f"⚠️ 메인 루프 에러: {e}")
            time.sleep(30)


if __name__ == "__main__":
    run_bot()
