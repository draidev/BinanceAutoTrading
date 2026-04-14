import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time
import os
from dotenv import load_dotenv

load_dotenv()

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET_KEY")

# ---------------------------------------------------------
# 1. 초기 설정
# ---------------------------------------------------------
st.set_page_config(page_title="Binance Pro Scanner", layout="wide", page_icon="📈")


@st.cache_resource
def init_exchange():
    return ccxt.binance({
        'apiKey': BINANCE_API_KEY,
        'secret': BINANCE_SECRET,
        'enableRateLimit': True,
        'options': {'defaultType': 'future'}
    })


binance = init_exchange()


# ---------------------------------------------------------
# 2. 지표 계산 (RSI, CCI, MACD, 볼린저 밴드)
# ---------------------------------------------------------
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


# ---------------------------------------------------------
# 3. 실시간 멀티 전략 신호 감지
#    curr = df.iloc[-1] : 현재 진행 중인 봉 (실시간 가격)
#    prev = df.iloc[-2] : 직전 마감 봉
# ---------------------------------------------------------
def check_multistrategy_signal(df, strategies):
    if len(df) < 52:
        return None

    curr = df.iloc[-1]   # 현재 봉 (실시간)
    prev = df.iloc[-2]   # 직전 마감 봉

    signals = []

    volume_surge = curr['volume'] > prev['volume'] * 2.0

    # 1. 급등/급락 (현재가 vs 직전 마감가)
    if strategies.get('surge'):
        change_pct = (curr['close'] - prev['close']) / prev['close'] * 100
        if change_pct >= 10.0:
            signals.append(f"🚀 급등 (+{change_pct:.1f}%)")
        elif change_pct <= -10.0:
            signals.append(f"😱 급락 ({change_pct:.1f}%)")

    # 2. EMA 크로스
    if strategies.get('cross'):
        if prev['EMA_20'] < prev['EMA_60'] and curr['EMA_20'] > curr['EMA_60']:
            signals.append("✨ 골든 크로스 (20/60)")
        if prev['EMA_20'] > prev['EMA_60'] and curr['EMA_20'] < curr['EMA_60']:
            signals.append("☠️ 데드 크로스 (20/60)")

    # 3. 200EMA 돌파
    if strategies.get('ma200'):
        if prev['close'] < prev['EMA_200'] and curr['close'] > curr['EMA_200'] and volume_surge:
            signals.append("💥 200EMA 상향 돌파")
        if prev['close'] > prev['EMA_200'] and curr['close'] < curr['EMA_200'] and volume_surge:
            signals.append("📉 200EMA 하향 이탈")

    # 4. 구름대 돌파
    if strategies.get('cloud'):
        if pd.notna(curr['span_a']) and pd.notna(curr['span_b']):
            cloud_top = max(curr['span_a'], curr['span_b'])
            cloud_bottom = min(curr['span_a'], curr['span_b'])

            if curr['span_a'] < curr['span_b'] and volume_surge:
                if prev['close'] <= cloud_top and curr['close'] > cloud_top:
                    signals.append("☁️ 구름대 상향 돌파")
            if curr['span_a'] > curr['span_b'] and volume_surge:
                if prev['close'] >= cloud_bottom and curr['close'] < cloud_bottom:
                    signals.append("🌧 구름대 하향 이탈")

    # 5. RSI / CCI 과매수·과매도
    if strategies.get('oscillators'):
        if pd.notna(curr['RSI']):
            if curr['RSI'] > 70:
                signals.append(f"🔴 RSI 과매수 ({curr['RSI']:.0f})")
            if curr['CCI'] > 100:
                signals.append(f"🔴 CCI 과매수 ({curr['CCI']:.0f})")
            if curr['RSI'] < 30:
                signals.append(f"🔵 RSI 과매도 ({curr['RSI']:.0f})")
            if curr['CCI'] < -100:
                signals.append(f"🔵 CCI 과매도 ({curr['CCI']:.0f})")

    # 6. MACD 크로스
    if strategies.get('macd'):
        if pd.notna(prev['MACD']) and pd.notna(curr['MACD']):
            if prev['MACD'] < prev['MACD_signal'] and curr['MACD'] > curr['MACD_signal']:
                signals.append("📗 MACD 골든 크로스")
            if prev['MACD'] > prev['MACD_signal'] and curr['MACD'] < curr['MACD_signal']:
                signals.append("📕 MACD 데드 크로스")

    # 7. 볼린저 밴드 이탈
    if strategies.get('bollinger'):
        if pd.notna(curr['BB_upper']) and pd.notna(curr['BB_lower']):
            if prev['close'] <= prev['BB_upper'] and curr['close'] > curr['BB_upper']:
                signals.append("🔺 볼린저 상단 돌파")
            if prev['close'] >= prev['BB_lower'] and curr['close'] < curr['BB_lower']:
                signals.append("🔻 볼린저 하단 이탈")

    return ", ".join(signals) if signals else None


# ---------------------------------------------------------
# 4. 데이터 스캔
# ---------------------------------------------------------
def scan_market(target_timeframes, start_rank, end_rank, active_strategies):
    progress_bar = st.progress(0, text="시장 데이터를 불러오는 중...")

    try:
        tickers = binance.fetch_tickers()
    except Exception as e:
        st.error(f"API 연결 에러: {e}")
        return []

    volume_list = [
        (symbol, ticker['quoteVolume'])
        for symbol, ticker in tickers.items()
        if '/USDT' in symbol and ticker.get('quoteVolume', 0) > 0
    ]
    sorted_coins = sorted(volume_list, key=lambda x: x[1], reverse=True)
    target_coins = sorted_coins[start_rank - 1: end_rank]

    results = []
    total_steps = len(target_coins) * len(target_timeframes)
    current_step = 0

    for symbol, _ in target_coins:
        for tf in target_timeframes:
            current_step += 1
            progress_bar.progress(
                current_step / total_steps,
                text=f"실시간 분석 중: {symbol} ({tf})"
            )
            try:
                ohlcv = binance.fetch_ohlcv(symbol, timeframe=tf, limit=120)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df = calculate_indicators(df)

                signal = check_multistrategy_signal(df, active_strategies)

                if signal:
                    results.append({
                        'symbol': symbol,
                        'timeframe': tf,
                        'signal': signal,
                        'price': df.iloc[-1]['close'],  # 현재가
                        'rsi': df.iloc[-1]['RSI'] if pd.notna(df.iloc[-1]['RSI']) else None,
                        'macd_hist': df.iloc[-1]['MACD_hist'] if pd.notna(df.iloc[-1]['MACD_hist']) else None,
                        'data': df
                    })
                time.sleep(0.05)
            except Exception:
                continue

    progress_bar.empty()
    return results


# ---------------------------------------------------------
# 5. 차트 그리기 (RSI + MACD 4행 구조)
# ---------------------------------------------------------
def plot_chart(item):
    df = item['data']
    clean_symbol = item['symbol'].split(':')[0]
    tf = item['timeframe']
    signal_type = item['signal']

    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True,
        vertical_spacing=0.025,
        row_heights=[0.45, 0.15, 0.2, 0.2],
        subplot_titles=["", "Volume", "RSI", "MACD"]
    )

    # --- Row 1: 캔들 + EMA + 구름대 + 볼린저 ---
    fig.add_trace(go.Candlestick(
        x=df['timestamp'],
        open=df['open'], high=df['high'],
        low=df['low'], close=df['close'],
        name='Price'
    ), row=1, col=1)

    # 구름대
    fill_color = 'rgba(0, 255, 0, 0.08)'
    if any(kw in signal_type for kw in ['하향', '데드', '과매수', '급락']):
        fill_color = 'rgba(255, 0, 0, 0.08)'

    fig.add_trace(go.Scatter(
        x=df['timestamp'], y=df['span_a'],
        line=dict(color='rgba(0,0,0,0)'), showlegend=False
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=df['timestamp'], y=df['span_b'],
        fill='tonexty', fillcolor=fill_color,
        line=dict(color='rgba(0,0,0,0)'), name='Cloud'
    ), row=1, col=1)

    # EMA
    ema_styles = {
        'EMA_20': ('yellow', 1),
        'EMA_60': ('orange', 1),
        'EMA_200': ('dodgerblue', 1.5),
    }
    for name, (color, width) in ema_styles.items():
        fig.add_trace(go.Scatter(
            x=df['timestamp'], y=df[name],
            line=dict(color=color, width=width), name=name
        ), row=1, col=1)

    # 볼린저 밴드
    fig.add_trace(go.Scatter(
        x=df['timestamp'], y=df['BB_upper'],
        line=dict(color='rgba(173,216,230,0.5)', width=1, dash='dot'),
        name='BB Upper'
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=df['timestamp'], y=df['BB_lower'],
        line=dict(color='rgba(173,216,230,0.5)', width=1, dash='dot'),
        fill='tonexty', fillcolor='rgba(173,216,230,0.05)',
        name='BB Lower'
    ), row=1, col=1)

    # --- Row 2: Volume ---
    vol_colors = [
        'rgba(0,200,100,0.6)' if df['close'].iloc[i] >= df['open'].iloc[i]
        else 'rgba(255,80,80,0.6)'
        for i in range(len(df))
    ]
    fig.add_trace(go.Bar(
        x=df['timestamp'], y=df['volume'],
        marker_color=vol_colors, name='Volume', showlegend=False
    ), row=2, col=1)

    # --- Row 3: RSI ---
    fig.add_trace(go.Scatter(
        x=df['timestamp'], y=df['RSI'],
        line=dict(color='mediumpurple', width=1.5), name='RSI'
    ), row=3, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red", line_width=0.8, row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", line_width=0.8, row=3, col=1)
    fig.add_hrect(y0=30, y1=70, fillcolor="rgba(128,128,128,0.05)",
                  line_width=0, row=3, col=1)

    # --- Row 4: MACD ---
    fig.add_trace(go.Scatter(
        x=df['timestamp'], y=df['MACD'],
        line=dict(color='deepskyblue', width=1.5), name='MACD'
    ), row=4, col=1)
    fig.add_trace(go.Scatter(
        x=df['timestamp'], y=df['MACD_signal'],
        line=dict(color='orange', width=1), name='Signal'
    ), row=4, col=1)

    hist_colors = [
        'rgba(0,200,100,0.7)' if v >= 0 else 'rgba(255,80,80,0.7)'
        for v in df['MACD_hist'].fillna(0)
    ]
    fig.add_trace(go.Bar(
        x=df['timestamp'], y=df['MACD_hist'],
        marker_color=hist_colors, name='Histogram', showlegend=False
    ), row=4, col=1)
    fig.add_hline(y=0, line_color="gray", line_width=0.5, row=4, col=1)

    fig.update_layout(
        title=f"📊 {clean_symbol} [{tf}] — {signal_type}",
        xaxis_rangeslider_visible=False,
        height=950,
        template="plotly_dark",
        margin=dict(l=20, r=20, t=50, b=20),
        legend=dict(orientation="h", y=1.02, x=0.5, xanchor="center")
    )

    # Y축 레이블
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Vol", row=2, col=1)
    fig.update_yaxes(title_text="RSI", range=[0, 100], row=3, col=1)
    fig.update_yaxes(title_text="MACD", row=4, col=1)

    return fig


# ---------------------------------------------------------
# 6. UI 구성
# ---------------------------------------------------------
st.title("🚀 Binance Futures 실시간 Scanner")
st.caption("현재 진행 중인 봉의 실시간 가격 기준으로 지표 돌파를 감지합니다.")

with st.sidebar:
    st.header("⚙️ 스캔 설정")

    st.subheader("📡 전략 선택")
    use_cloud = st.toggle("☁️ 일목균형표 구름대 돌파", value=True)
    use_surge = st.toggle("🚀 급등/급락 (10% 이상)", value=True)
    use_cross = st.toggle("✨ EMA 골든/데드 크로스", value=False)
    use_ma200 = st.toggle("💥 200EMA 돌파", value=False)
    use_osc = st.toggle("🌊 RSI/CCI 과매수·과매도", value=True)
    use_macd = st.toggle("📗 MACD 크로스", value=True)
    use_bb = st.toggle("📐 볼린저 밴드 이탈", value=True)

    active_strategies = {
        'cloud': use_cloud,
        'surge': use_surge,
        'cross': use_cross,
        'ma200': use_ma200,
        'oscillators': use_osc,
        'macd': use_macd,
        'bollinger': use_bb,
    }

    st.divider()

    selected_tfs = st.multiselect(
        "분석할 시간대",
        ['5m', '15m', '1h', '4h', '1d'],
        default=['15m', '1h']
    )

    rank_range = st.slider(
        "분석할 순위 범위 (거래대금 순)",
        min_value=1,
        max_value=200,
        value=(10, 50),
        step=1
    )
    start_rank, end_rank = rank_range

    st.divider()

    if st.button("🚨 실시간 스캔 시작", type="primary"):
        if not selected_tfs:
            st.error("시간대를 선택해주세요.")
        elif not any(active_strategies.values()):
            st.error("최소 한 가지 이상의 전략을 선택해주세요.")
        else:
            st.session_state['scan_results'] = scan_market(
                selected_tfs, start_rank, end_rank, active_strategies
            )

# ---------------------------------------------------------
# 7. 결과 표시
# ---------------------------------------------------------
if 'scan_results' in st.session_state and st.session_state['scan_results']:
    results = st.session_state['scan_results']

    st.success(f"✅ 검색 완료! **{len(results)}개** 신호 발견 (현재 봉 실시간 기준)")

    col_list, col_chart = st.columns([1, 2])

    with col_list:
        st.subheader("📋 신호 리스트")
        for i, item in enumerate(results):
            clean_symbol = item['symbol'].split(':')[0]
            timeframe = item['timeframe']
            signal_text = item['signal']

            emoji = "⚡️"
            if any(kw in signal_text for kw in ["과매수", "급락", "하향", "데드"]):
                emoji = "📉"
            elif any(kw in signal_text for kw in ["과매도", "급등", "상향", "골든"]):
                emoji = "📈"

            with st.container(border=True):
                st.markdown(f"**{clean_symbol}** &nbsp; `{timeframe}`")

                # 부가 정보 표시
                info_parts = [f"{emoji} {signal_text}"]
                if item.get('rsi') is not None:
                    st.caption(f"RSI: {item['rsi']:.1f} | MACD Hist: {item['macd_hist']:.4f}" if item.get('macd_hist') else f"RSI: {item['rsi']:.1f}")
                st.info(info_parts[0])

                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    if st.button("차트 📊", key=f"btn_{i}_{clean_symbol}_{timeframe}"):
                        st.session_state['selected_item'] = item
                with btn_col2:
                    raw_symbol = clean_symbol.replace("/", "")
                    url = f"https://www.binance.com/en/futures/{raw_symbol}"
                    st.link_button("거래소 🔗", url)

    with col_chart:
        if 'selected_item' in st.session_state:
            item = st.session_state['selected_item']
            fig = plot_chart(item)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("👈 왼쪽 리스트에서 [차트] 버튼을 눌러보세요.")

elif 'scan_results' in st.session_state:
    st.warning("조건에 맞는 신호가 없습니다. 전략 설정이나 순위 범위를 조정해보세요.")
