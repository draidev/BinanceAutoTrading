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
# 2. 지표 계산 및 신호 감지
# ---------------------------------------------------------
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

def check_signal(df, strict_mode=False):
    if len(df) < 52: return None
    
    curr = df.iloc[-2] 
    prev = df.iloc[-3]

    cloud_top = max(curr['span_a'], curr['span_b'])
    cloud_bottom = min(curr['span_a'], curr['span_b'])
    
    signal = None

    if strict_mode:
        # [엄격 모드]
        volume_surge = curr['volume'] > prev['volume'] * 2.0
        
        is_bearish_cloud = curr['span_a'] < curr['span_b']
        breakout_up = prev['close'] <= cloud_top and curr['close'] > cloud_top
        
        if is_bearish_cloud and breakout_up and volume_surge:
            signal = "🔥 STRONG BUY (Breakout)"

        is_bullish_cloud = curr['span_a'] > curr['span_b']
        breakdown_down = prev['close'] >= cloud_bottom and curr['close'] < cloud_bottom
        
        if is_bullish_cloud and breakdown_down and volume_surge:
            signal = "💧 STRONG SELL (Breakdown)"

    else:
        # [일반 모드]
        if curr['close'] > cloud_top:
            signal = "📈 BUY Trend"
        elif curr['close'] < cloud_bottom:
            signal = "📉 SELL Trend"
            
    return signal

# ---------------------------------------------------------
# 3. 데이터 스캔
# ---------------------------------------------------------
def scan_market(target_timeframes, start_rank, end_rank, strict_mode):
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
                signal = check_signal(df, strict_mode)
                
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
# 4. 차트 그리기
# ---------------------------------------------------------
def plot_chart(item):
    df = item['data']
    clean_symbol = item['symbol'].split(':')[0]
    tf = item['timeframe']
    signal_type = item['signal']
    
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.03, row_heights=[0.7, 0.3])

    fig.add_trace(go.Candlestick(x=df['timestamp'],
                open=df['open'], high=df['high'],
                low=df['low'], close=df['close'], name='Price'), row=1, col=1)

    fill_color = 'rgba(0, 255, 0, 0.1)' if 'BUY' in signal_type else 'rgba(255, 0, 0, 0.1)'
    
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['span_a'], 
                             line=dict(color='rgba(0,0,0,0)'), showlegend=False), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['span_b'], 
                             fill='tonexty', fillcolor=fill_color,
                             line=dict(color='rgba(0,0,0,0)'), name='Cloud'), row=1, col=1)

    colors = {'EMA_20': 'yellow', 'EMA_60': 'orange', 'EMA_120': 'purple', 'EMA_200': 'blue'}
    for name, color in colors.items():
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df[name], 
                                 line=dict(color=color, width=1), name=name), row=1, col=1)

    fig.add_trace(go.Bar(x=df['timestamp'], y=df['volume'], marker_color='gray', name='Volume'), row=2, col=1)

    fig.update_layout(
        title=f"📊 {clean_symbol} [{tf}] - {signal_type}",
        xaxis_rangeslider_visible=False,
        height=600,
        template="plotly_dark",
        margin=dict(l=20, r=20, t=50, b=20)
    )
    return fig

# ---------------------------------------------------------
# 5. UI 구성
# ---------------------------------------------------------
st.title("🚀 Binance Futures AI Scanner")

with st.sidebar:
    st.header("⚙️ 스캔 설정")
    
    strict_mode = st.toggle("🔒 엄격한 돌파 모드 (Strict Mode)", value=False)
    
    if strict_mode:
        st.caption("✅ 조건: 거래량 2배 폭등 + 구름대 돌파 (신호가 적게 나옵니다)")
    else:
        st.caption("✅ 조건: 현재 가격이 구름대 위에 있으면 표시 (신호가 많이 나옵니다)")

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
    count = end_rank - start_rank + 1
    
    st.divider()
    
    if st.button("🚨 스캔 시작 (START)", type="primary"):
        if not selected_tfs:
            st.error("시간대를 선택해주세요.")
        else:
            st.session_state['scan_results'] = []
            st.session_state['scan_results'] = scan_market(selected_tfs, start_rank, end_rank, strict_mode)

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
            is_buy = 'BUY' in item['signal']
            emoji = "🔥" if "STRONG" in item['signal'] else ("📈" if is_buy else "📉")
            
            with st.container(border=True):
                st.markdown(f"**{clean_symbol}** &nbsp; ` {timeframe} `")
                st.caption(f"{emoji} {item['signal']}")
                
                btn_col1, btn_col2 = st.columns(2)
                
                # 차트 버튼 (일반 버튼은 key 필요)
                with btn_col1:
                    if st.button(f"차트 📊", key=f"btn_chart_{i}_{clean_symbol}_{timeframe}"):
                        st.session_state['selected_item'] = item
                
                # 거래소 링크 (key 인자 제거됨)
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
