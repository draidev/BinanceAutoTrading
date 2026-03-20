import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time
import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# 환경 변수 로드
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
# 2. 지표 계산 (RSI, CCI 추가)
# ---------------------------------------------------------
def calculate_indicators(df):
    # 1. EMA
    for period in [20, 60, 120, 200]:
        df[f'EMA_{period}'] = df['close'].ewm(span=period, adjust=False).mean()

    # 2. 일목균형표
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

    # 3. RSI (Relative Strength Index, 14)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))

    # 4. CCI (Commodity Channel Index, 20)
    tp = (df['high'] + df['low'] + df['close']) / 3
    sma_tp = tp.rolling(window=20).mean()
    mean_dev = (tp - sma_tp).abs().rolling(window=20).mean()
    df['CCI'] = (tp - sma_tp) / (0.015 * mean_dev)
    
    return df

def check_multistrategy_signal(df, strategies):
    if len(df) < 52: return None
    
    curr = df.iloc[-2]
    prev = df.iloc[-3]
    
    signals = [] 

    # 공통: 거래량 급증
    volume_surge = curr['volume'] > prev['volume'] * 2.0
    
    # -----------------------------------------------------
    # 1. 급등/급락 감지 (10% 이상)
    # -----------------------------------------------------
    if strategies.get('surge'):
        change_pct = (curr['close'] - prev['close']) / prev['close'] * 100
        if change_pct >= 10.0:
            signals.append(f"🚀 급등 (+{change_pct:.1f}%)")
        elif change_pct <= -10.0:
            signals.append(f"😱 급락 ({change_pct:.1f}%)")

    # -----------------------------------------------------
    # 2. 이평선 크로스
    # -----------------------------------------------------
    if strategies.get('cross'):
        if prev['EMA_20'] < prev['EMA_60'] and curr['EMA_20'] > curr['EMA_60']:
            signals.append("❌ 골든 크로스 (20/60)")
        if prev['EMA_20'] > prev['EMA_60'] and curr['EMA_20'] < curr['EMA_60']:
            signals.append("☠️ 데드 크로스 (20/60)")

    # -----------------------------------------------------
    # 3. 200EMA 돌파
    # -----------------------------------------------------
    if strategies.get('ma200'):
        if prev['close'] < prev['EMA_200'] and curr['close'] > curr['EMA_200'] and volume_surge:
            signals.append("💥 200EMA 상향 돌파")
        if prev['close'] > prev['EMA_200'] and curr['close'] < curr['EMA_200'] and volume_surge:
            signals.append("📉 200EMA 하향 이탈")

    # -----------------------------------------------------
    # 4. 구름대 돌파
    # -----------------------------------------------------
    if strategies.get('cloud'):
        cloud_top = max(curr['span_a'], curr['span_b'])
        cloud_bottom = min(curr['span_a'], curr['span_b'])
        
        if curr['span_a'] < curr['span_b'] and volume_surge:
            if prev['close'] <= cloud_top and curr['close'] > cloud_top:
                signals.append("☁️ 구름대 상향 돌파")
        if curr['span_a'] > curr['span_b'] and volume_surge:
            if prev['close'] >= cloud_bottom and curr['close'] < cloud_bottom:
                signals.append("🌧 구름대 하향 이탈")

    # -----------------------------------------------------
    # 5. [NEW] 과매수 / 과매도 (RSI & CCI)
    # -----------------------------------------------------
    if strategies.get('oscillators'):
        rsi = curr['RSI']
        cci = curr['CCI']

        # 과매수 (Overbought) -> 매도 관점
        if rsi > 70:
            signals.append(f"🔴 RSI 과매수 ({rsi:.0f})")
        if cci > 100:
            signals.append(f"🔴 CCI 과매수 ({cci:.0f})")
            
        # 과매도 (Oversold) -> 매수 관점
        if rsi < 30:
            signals.append(f"🔵 RSI 과매도 ({rsi:.0f})")
        if cci < -100:
            signals.append(f"🔵 CCI 과매도 ({cci:.0f})")

    if signals:
        return ", ".join(signals)
    else:
        return None

# ---------------------------------------------------------
# 3. 데이터 스캔
# ---------------------------------------------------------
def scan_market(target_timeframes, start_rank, end_rank, active_strategies):
    progress_bar = st.progress(0, text="시장 데이터를 불러오는 중...")
    
    try:
        tickers = binance.fetch_tickers()
    except Exception as e:
        st.error(f"API 연결 에러: {e}")
        return []

    volume_list = []
    for symbol, ticker in tickers.items():
        if '/USDT' in symbol and ticker['quoteVolume'] > 0:
            volume_list.append((symbol, ticker['quoteVolume']))
    
    sorted_coins = sorted(volume_list, key=lambda x: x[1], reverse=True)
    target_coins = sorted_coins[start_rank-1 : end_rank]
    
    results = []
    total_steps = len(target_coins) * len(target_timeframes)
    current_step = 0
    
    for symbol, _ in target_coins:
        for tf in target_timeframes:
            current_step += 1
            progress_bar.progress(current_step / total_steps, text=f"분석 중: {symbol} ({tf})")
            
            try:
                ohlcv = binance.fetch_ohlcv(symbol, timeframe=tf, limit=100)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                
                df = calculate_indicators(df)
                signal = check_multistrategy_signal(df, active_strategies)
                
                if signal:
                    results.append({
                        'symbol': symbol,
                        'timeframe': tf,
                        'signal': signal,
                        'price': df.iloc[-2]['close'],
                        'data': df 
                    })
                time.sleep(0.05) 
            except Exception:
                continue

    progress_bar.empty()
    return results

# ---------------------------------------------------------
# 4. 차트 그리기 (RSI 추가)
# ---------------------------------------------------------
def plot_chart(item):
    df = item['data']
    clean_symbol = item['symbol'].split(':')[0]
    tf = item['timeframe']
    signal_type = item['signal']
    
    # 3행 구조로 변경 (가격 / 거래량 / RSI)
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.03, 
                        row_heights=[0.6, 0.2, 0.2])

    # 1. Price Chart
    fig.add_trace(go.Candlestick(x=df['timestamp'],
                open=df['open'], high=df['high'],
                low=df['low'], close=df['close'], name='Price'), row=1, col=1)

    fill_color = 'rgba(0, 255, 0, 0.1)'
    if '하락' in signal_type or '데드' in signal_type or '과매수' in signal_type:
        fill_color = 'rgba(255, 0, 0, 0.1)'
    
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['span_a'], 
                             line=dict(color='rgba(0,0,0,0)'), showlegend=False), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['span_b'], 
                             fill='tonexty', fillcolor=fill_color,
                             line=dict(color='rgba(0,0,0,0)'), name='Cloud'), row=1, col=1)

    colors = {'EMA_20': 'yellow', 'EMA_60': 'orange', 'EMA_200': 'blue'}
    for name, color in colors.items():
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df[name], 
                                 line=dict(color=color, width=1), name=name), row=1, col=1)

    # 2. Volume Chart
    fig.add_trace(go.Bar(x=df['timestamp'], y=df['volume'], marker_color='gray', name='Volume'), row=2, col=1)

    # 3. RSI Chart
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['RSI'], 
                             line=dict(color='purple', width=2), name='RSI'), row=3, col=1)
    
    # RSI 기준선 (30, 70)
    fig.add_hline(y=70, line_dash="dash", line_color="red", row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", row=3, col=1)

    fig.update_layout(
        title=f"📊 {clean_symbol} [{tf}] - {signal_type}",
        xaxis_rangeslider_visible=False,
        height=800, # 차트 높이 증가
        template="plotly_dark",
        margin=dict(l=20, r=20, t=50, b=20)
    )
    return fig

# ---------------------------------------------------------
# 5. UI 구성
# ---------------------------------------------------------
st.title("🚀 Binance Futures AI Scanner (RSI/CCI Included)")

with st.sidebar:
    st.header("⚙️ 스캔 설정")
    
    st.subheader("📡 감시할 전략 선택")
    use_cloud = st.toggle("☁️ 일목균형표 구름대 돌파", value=True)
    use_surge = st.toggle("🚀 급등/급락 (10% 이상)", value=True)
    use_cross = st.toggle("❌ EMA 골든/데드 크로스", value=False)
    use_ma200 = st.toggle("💥 200EMA 돌파 (추세전환)", value=False)
    use_osc = st.toggle("🌊 RSI/CCI 과매수·과매도", value=True)

    active_strategies = {
        'cloud': use_cloud,
        'surge': use_surge,
        'cross': use_cross,
        'ma200': use_ma200,
        'oscillators': use_osc
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
    
    if st.button("🚨 스캔 시작 (START)", type="primary"):
        if not selected_tfs:
            st.error("시간대를 선택해주세요.")
        elif not any(active_strategies.values()):
            st.error("최소 한 가지 이상의 전략을 선택해주세요.")
        else:
            st.session_state['scan_results'] = []
            st.session_state['scan_results'] = scan_market(
                selected_tfs, start_rank, end_rank, active_strategies
            )

# 결과 화면
if 'scan_results' in st.session_state and st.session_state['scan_results']:
    results = st.session_state['scan_results']
    
    st.success(f"검색 완료! {len(results)}개의 신호 발견")
    
    col_list, col_chart = st.columns([1, 2])
    
    with col_list:
        st.subheader("📋 신호 리스트")
        for i, item in enumerate(results):
            clean_symbol = item['symbol'].split(':')[0]
            timeframe = item['timeframe']
            signal_text = item['signal']
            
            # 이모지 로직
            emoji = "⚡️"
            if "과매수" in signal_text or "급락" in signal_text or "하향" in signal_text:
                emoji = "📉"
            elif "과매도" in signal_text or "급등" in signal_text or "상향" in signal_text:
                emoji = "📈"

            with st.container(border=True):
                st.markdown(f"**{clean_symbol}** &nbsp; ` {timeframe} `")
                st.info(f"{emoji} {signal_text}")
                
                btn_col1, btn_col2 = st.columns(2)
                
                with btn_col1:
                    if st.button(f"차트 📊", key=f"btn_chart_{i}_{clean_symbol}_{timeframe}"):
                        st.session_state['selected_item'] = item
                
                with btn_col2:
                    raw_symbol = clean_symbol.replace("/", "") 
                    url = f"https://www.binance.com/en/futures/{raw_symbol}"
                    st.link_button("거래소 🔗", url)

    with col_chart:
        if 'selected_item' in st.session_state:
            item = st.session_state['selected_item']
            fig = plot_chart(item)
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("👈 왼쪽 리스트에서 [차트] 버튼을 눌러보세요.")
elif 'scan_results' in st.session_state:
    st.warning("조건에 맞는 신호가 없습니다.")
