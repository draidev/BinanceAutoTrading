# 🚀 Binance Crypto Sentinel: 통합 대시보드 & 스마트 알림 시스템

바이낸스 선물(Futures) 시장을 실시간으로 감시하고, **일목균형표(Ichimoku Cloud)**와 **지수이동평균선(EMA)** 전략을 결합하여 최적의 매매 신호를 포착하는 통합 솔루션입니다. 본 프로젝트는 보안 강화 및 프로세스 자동 관리에 최적화되어 있습니다.

---

## 🛠 시스템 아키텍처 (Architecture)

본 시스템은 두 가지 핵심 모듈로 구성되며, 각각 최적화된 도구로 관리됩니다.

1. **`trading_dashboard.py`**: 실시간 차트 시각화 및 종목 스캔용 웹 앱 (Streamlit + Tmux 관리)
2. **`auto_alert_bot.py`**: 정기적 봉 갱신 주기 감시 및 텔레그램 알림 봇 (Python + PM2 관리)

---

## 📈 매매 전략 (Strategy)

* **핵심 지표**: 일목균형표(Span A/B), EMA(20, 60, 120, 200), 거래량(Volume)
* **신호 판정 (Strict Mode)**: 
    * **BUY**: 가격이 음운(저항) 상향 돌파 + 직전 대비 거래량 200% 이상 폭증
    * **SELL**: 가격이 양운(지지) 하향 이탈 + 직전 대비 거래량 200% 이상 폭증

---

## ⚙️ 보안 및 환경 설정 (Security & Environment)

본 프로젝트는 보안을 위해 API 키를 소스 코드에서 분리하여 관리합니다.

### 1. 환경 변수 설정 (`.env`)
프로젝트 루트에 `.env` 파일을 생성하고 아래 내용을 입력하십시오. **이 파일은 절대로 GitHub에 업로드하지 마십시오.**

```text
BINANCE_API_KEY=your_api_key
BINANCE_SECRET_KEY=your_secret_key
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

```

### 2. 업로드 제한 설정 (`.gitignore`)

GitHub에 중요한 정보가 유출되지 않도록 설정합니다.

```text
.env
venv/
__pycache__/
*.log
.DS_Store

```

---

## 🚀 설치 및 실행 가이드 (Installation)

### 1. 환경 구축 및 라이브러리 설치

```bash
# 가상환경 생성 및 활성화
python3 -m venv venv
source venv/bin/activate

# 필수 패키지 설치
pip install ccxt pandas streamlit plotly requests python-dotenv

```

### 2. 알림 봇 실행 (PM2 관리)

에러 시 자동 재시작 및 백그라운드 유지를 위해 PM2를 사용합니다.

```bash
# 봇 시작
pm2 start auto_alert_bot.py --name "binance-bot" --interpreter ./venv/bin/python3

# 관리 명령어
pm2 list              # 가동 상태 확인
pm2 logs binance-bot  # 실시간 로그 확인
pm2 restart binance-bot # 설정 변경 후 재시작

```

### 3. 대시보드 실행 (Tmux 관리)

UI 확인이 필요한 대시보드는 가상 터미널 세션인 Tmux에서 실행합니다.

```bash
# 세션 생성 및 실행
tmux new -s trading
streamlit run trading_dashboard.py

# 세션 나가기: Ctrl + B 누른 후 D
# 세션 복귀: tmux attach -t trading

```

---

## ⏰ 스마트 스케줄링 (KST 기준)

봇은 한국 시간(KST) 봉 마감 시점(+15초 버퍼)에만 정밀 검사를 수행하여 리소스를 최적화합니다.

* **15분봉**: 매시 00, 15, 30, 45분
* **1시간봉**: 매시 정각 (00분)
* **4시간봉**: 01:00, 05:00, 09:00, 13:00, 17:00, 21:00
* **1일봉**: 매일 아침 09:00

---

## 💻 시스템 유지 (Keep-Alive)

M2 MacBook Air 환경에서 시스템이 중단 없이 돌아가도록 터미널에서 다음 명령어를 실행하십시오.

```bash
caffeinate

```
