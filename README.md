# 🚀 Binance Crypto Sentinel: 실시간 통합 대시보드 & 스마트 알림 시스템

바이낸스 선물(Futures) 시장을 **실시간으로** 감시하고, 다중 기술적 지표 전략을 결합하여 최적의 매매 신호를 포착하는 통합 솔루션입니다.

---

## 🛠 시스템 아키텍처 (Architecture)

1. **`trading_dashboard.py`**: 실시간 차트 시각화 및 종목 스캔용 웹 앱 (Streamlit + Tmux 관리)
2. **`auto_alert_bot.py`**: 고정 주기(기본 60초) 폴링 방식 실시간 감시 및 텔레그램 알림 봇 (Python + PM2 관리)

---

## 📈 매매 전략 (Strategy)

### 핵심 변경: 실시간 감지 방식
- **기존**: 봉 마감 시점에만 확인 → 대응이 느림
- **변경**: 현재 진행 중인 봉의 실시간 가격으로 지표 돌파 여부를 매 스캔 주기마다 확인

### 지원 전략 (7가지)
| 전략 | 신호 | 설명 |
|------|------|------|
| 급등/급락 | 🚀 / 😱 | 직전 마감가 대비 ±10% 이상 변동 |
| EMA 크로스 | ✨ / ☠️ | EMA20과 EMA60 교차 (골든/데드) |
| 200EMA 돌파 | 💥 / 📉 | 장기 추세선 돌파 (거래량 동반 필수) |
| 구름대 돌파 | ☁️ / 🌧 | 일목균형표 구름 돌파/이탈 (거래량 동반) |
| RSI/CCI | 🔴 / 🔵 | 과매수(RSI>70)/과매도(RSI<30) |
| MACD | 📗 / 📕 | MACD-Signal 라인 교차 |
| 볼린저 밴드 | 🔺 / 🔻 | 상단/하단 밴드 이탈 |

### 쿨다운 시스템
동일 신호의 반복 알림을 방지하기 위해 시간프레임별 자동 쿨다운이 적용됩니다.
- 15m봉: 15분 / 1h봉: 1시간 / 4h봉: 4시간 / 1d봉: 24시간

---

## ⚙️ 보안 및 환경 설정 (Security & Environment)

### 1. 환경 변수 설정 (`.env`)
프로젝트 루트에 `.env` 파일을 생성하십시오. **이 파일은 절대로 GitHub에 업로드하지 마십시오.**

```text
BINANCE_API_KEY=your_api_key
BINANCE_SECRET_KEY=your_secret_key
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### 2. `.gitignore`

```text
.env
venv/
__pycache__/
*.log
.DS_Store
```

---

## 🚀 설치 및 실행 가이드 (Installation)

### 1. 환경 구축

```bash
python3 -m venv venv
source venv/bin/activate
pip install ccxt pandas streamlit plotly requests python-dotenv
```

### 2. 알림 봇 실행 (PM2)

```bash
pm2 start auto_alert_bot.py --name "binance-bot" --interpreter ./venv/bin/python3

# 관리 명령어
pm2 list
pm2 logs binance-bot
pm2 restart binance-bot
```

### 3. 대시보드 실행 (Tmux)

```bash
tmux new -s trading
streamlit run trading_dashboard.py
# Ctrl+B → D (세션 나가기)
# tmux attach -t trading (복귀)
```

---

## ⏰ 스캔 방식

### 알림 봇 (`auto_alert_bot.py`)
- **폴링 주기**: 기본 60초 (`SCAN_INTERVAL_SECONDS`로 조절 가능)
- 매 주기마다 설정된 모든 시간프레임의 현재 봉 가격으로 지표 돌파 여부를 확인
- 쿨다운 시스템으로 중복 알림 자동 방지

### 대시보드 (`trading_dashboard.py`)
- 수동 스캔 버튼으로 현재 시점의 실시간 가격 기준 신호 탐색
- 4행 차트: 캔들+EMA+구름대+볼린저 / 거래량 / RSI / MACD

---

## 💻 시스템 유지 (Keep-Alive)

M2 MacBook Air 환경:
```bash
caffeinate
```
