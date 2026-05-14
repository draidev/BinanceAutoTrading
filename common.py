"""
공통 지표 계산 및 신호 감지 모듈
"""
import pandas as pd

# 바이낸스 OHLCV 요청 봉 수
# EMA_200 초기 편향이 0.7% 이하가 되려면 500봉 이상 필요
# (1 - 2/201)^n < 0.01 → n ≥ 460, 여유분 포함해 500으로 설정)
FETCH_LIMIT = 500


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
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

    # CCI (20)
    tp = (df['high'] + df['low'] + df['close']) / 3
    sma_tp = tp.rolling(window=20).mean()
    mean_dev = (tp - sma_tp).abs().rolling(window=20).mean()
    df['CCI'] = (tp - sma_tp) / (0.015 * mean_dev)

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


def check_signals(df: pd.DataFrame) -> list[tuple[str, str]]:
    """
    (signal_name, signal_msg) 튜플 리스트 반환.
    signal_name: 쿨다운 키로 사용
    signal_msg: 텔레그램/UI 표시 문자열
    """
    if len(df) < 52:
        return []

    curr = df.iloc[-1]
    prev = df.iloc[-2]

    signals = []
    volume_surge = curr['volume'] > prev['volume'] * 2.0

    # 1. 급등/급락
    change_pct = (curr['close'] - prev['close']) / prev['close'] * 100
    if change_pct >= 10.0:
        signals.append(("급등", f"🚀 급등 발생 (+{change_pct:.1f}%)"))
    elif change_pct <= -10.0:
        signals.append(("급락", f"😱 급락 발생 ({change_pct:.1f}%)"))

    # 2. EMA 크로스 (20 vs 60)
    if prev['EMA_20'] < prev['EMA_60'] and curr['EMA_20'] > curr['EMA_60']:
        signals.append(("골든크로스", "✨ 골든 크로스 (EMA20 ↑ EMA60)"))
    if prev['EMA_20'] > prev['EMA_60'] and curr['EMA_20'] < curr['EMA_60']:
        signals.append(("데드크로스", "☠️ 데드 크로스 (EMA20 ↓ EMA60)"))

    # 3. 200EMA 돌파 (거래량 동반)
    if prev['close'] < prev['EMA_200'] and curr['close'] > curr['EMA_200'] and volume_surge:
        signals.append(("200EMA상향", "💥 200EMA 상향 돌파 (추세 전환)"))
    if prev['close'] > prev['EMA_200'] and curr['close'] < curr['EMA_200'] and volume_surge:
        signals.append(("200EMA하향", "📉 200EMA 하향 이탈 (추세 붕괴)"))

    # 4. 일목균형표 구름대 돌파 (거래량 동반)
    if pd.notna(curr['span_a']) and pd.notna(curr['span_b']):
        cloud_top = max(curr['span_a'], curr['span_b'])
        cloud_bottom = min(curr['span_a'], curr['span_b'])

        if curr['span_a'] < curr['span_b'] and volume_surge:
            if prev['close'] <= cloud_top and curr['close'] > cloud_top:
                signals.append(("구름상향", "☁️ 구름대 상향 돌파 (매수 찬스)"))
        if curr['span_a'] > curr['span_b'] and volume_surge:
            if prev['close'] >= cloud_bottom and curr['close'] < cloud_bottom:
                signals.append(("구름하향", "🌧 구름대 하향 이탈 (매도 주의)"))

    # 5. RSI / CCI 과매수·과매도
    if pd.notna(curr['RSI']):
        if curr['RSI'] > 70:
            signals.append(("RSI과매수", f"🔴 RSI 과매수 ({curr['RSI']:.0f})"))
        elif curr['RSI'] < 30:
            signals.append(("RSI과매도", f"🔵 RSI 과매도 ({curr['RSI']:.0f})"))
    if pd.notna(curr['CCI']):
        if curr['CCI'] > 100:
            signals.append(("CCI과매수", f"🔴 CCI 과매수 ({curr['CCI']:.0f})"))
        elif curr['CCI'] < -100:
            signals.append(("CCI과매도", f"🔵 CCI 과매도 ({curr['CCI']:.0f})"))

    # 6. MACD 크로스
    if pd.notna(prev['MACD']) and pd.notna(curr['MACD']):
        if prev['MACD'] < prev['MACD_signal'] and curr['MACD'] > curr['MACD_signal']:
            signals.append(("MACD골든", "📗 MACD 골든 크로스 (매수 신호)"))
        if prev['MACD'] > prev['MACD_signal'] and curr['MACD'] < curr['MACD_signal']:
            signals.append(("MACD데드", "📕 MACD 데드 크로스 (매도 신호)"))

    # 7. 볼린저 밴드 이탈
    if pd.notna(curr['BB_upper']) and pd.notna(curr['BB_lower']):
        if prev['close'] <= prev['BB_upper'] and curr['close'] > curr['BB_upper']:
            signals.append(("BB상단돌파", "🔺 볼린저 상단 돌파 (과열 주의)"))
        if prev['close'] >= prev['BB_lower'] and curr['close'] < curr['BB_lower']:
            signals.append(("BB하단이탈", "🔻 볼린저 하단 이탈 (반등 기대)"))

    return signals


# dashboard용 전략 필터 키 매핑
STRATEGY_SIGNAL_MAP = {
    'surge':       {'급등', '급락'},
    'cross':       {'골든크로스', '데드크로스'},
    'ma200':       {'200EMA상향', '200EMA하향'},
    'cloud':       {'구름상향', '구름하향'},
    'oscillators': {'RSI과매수', 'RSI과매도', 'CCI과매수', 'CCI과매도'},
    'macd':        {'MACD골든', 'MACD데드'},
    'bollinger':   {'BB상단돌파', 'BB하단이탈'},
}


def filter_signals(signals: list[tuple[str, str]], strategies: dict) -> str | None:
    """dashboard 전략 토글 기준으로 필터링 후 쉼표 구분 문자열 반환"""
    active_keys = {
        key
        for strategy, enabled in strategies.items()
        if enabled
        for key in STRATEGY_SIGNAL_MAP.get(strategy, set())
    }
    filtered = [msg for name, msg in signals if name in active_keys]
    return ", ".join(filtered) if filtered else None
