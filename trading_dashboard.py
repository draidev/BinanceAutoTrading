import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time
import os
from dotenv import load_dotenv
from common import calculate_indicators, check_signals, filter_signals, FETCH_LIMIT

load_dotenv()

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET_KEY")

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
# 데이터 스캔
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
                ohlcv = binance.fetch_ohlcv(symbol, timeframe=tf, limit=FETCH_LIMIT)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df = calculate_indicators(df)

                signals = check_signals(df)
                signal_str = filter_signals(signals, active_strategies)

                if signal_str:
                    results.append({
                        'symbol': symbol,
                        'timeframe': tf,
                        'signal': signal_str,
                        'price': df.iloc[-1]['close'],
                        'rsi': df.iloc[-1]['RSI'] if pd.notna(df.iloc[-1]['RSI']) else None,
                        'macd_hist': df.iloc[-1]['MACD_hist'] if pd.notna(df.iloc[-1]['MACD_hist']) else None,
                        'data': df
                    })
                time.sleep(0.05)
            except Exception as e:
                st.warning(f"⚠️ {symbol} [{tf}] 데이터 오류: {e}")
                continue

    progress_bar.empty()
    return results


# ---------------------------------------------------------
# 차트 그리기
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

    # Row 1: 캔들 + EMA + 구름대 + 볼린저
    fig.add_trace(go.Candlestick(
        x=df['timestamp'],
        open=df['open'], high=df['high'],
        low=df['low'], close=df['close'],
        name='Price'
    ), row=1, col=1)

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

    # Row 2: Volume
    vol_colors = [
        'rgba(0,200,100,0.6)' if df['close'].iloc[i] >= df['open'].iloc[i]
        else 'rgba(255,80,80,0.6)'
        for i in range(len(df))
    ]
    fig.add_trace(go.Bar(
        x=df['timestamp'], y=df['volume'],
        marker_color=vol_colors, name='Volume', showlegend=False
    ), row=2, col=1)

    # Row 3: RSI
    fig.add_trace(go.Scatter(
        x=df['timestamp'], y=df['RSI'],
        line=dict(color='mediumpurple', width=1.5), name='RSI'
    ), row=3, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red", line_width=0.8, row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", line_width=0.8, row=3, col=1)
    fig.add_hrect(y0=30, y1=70, fillcolor="rgba(128,128,128,0.05)",
                  line_width=0, row=3, col=1)

    # Row 4: MACD
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

    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Vol", row=2, col=1)
    fig.update_yaxes(title_text="RSI", range=[0, 100], row=3, col=1)
    fig.update_yaxes(title_text="MACD", row=4, col=1)

    return fig


# ---------------------------------------------------------
# UI 구성
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
# 결과 표시
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
