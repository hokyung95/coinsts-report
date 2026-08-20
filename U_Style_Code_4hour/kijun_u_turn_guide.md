# 240분봉(4시간봉) 일목균형표 기준선(30) U자형 턴어라운드 분석 및 시뮬레이션 가이드

## 1. 목표 및 개요 (Goal & Overview)

본 프로젝트는 24시간 365일 연중무휴 거래되는 암호화폐 마켓의 **240분봉(4시간봉 / 240m Candles)** 시계열 데이터를 기준으로 **240분봉 일목균형표 기준선(Kijun-sen, 30봉)**이 그리는 **U자형 턴어라운드 (1단계 하락 ➔ 2단계 수평 바닥 ➔ 3단계 우상향 전환)** 패턴을 포착하고, **과거 200개 240분봉을 1봉씩 타임 슬라이딩 시뮬레이션(Rolling Backtest)**하여 **거래량 상관성** 및 **발생 이후 주가 상승 성과(6봉, 12봉, 24봉 후 수익률 및 승률)**를 정량 검증하는 시스템입니다.

---

## 2. 240분봉 전용 일목 지표 파라미터 및 U자형 패턴 원리

### 2.1. 240분봉 지표 수식
$$\text{240분봉 기준선(Kijun-sen)} = \frac{\text{최근 30개 240m봉 최고가} + \text{최근 30개 240m봉 최저가}}{2}$$

* **240분봉 캔들 특징**: 1일 = 6개 240분봉
* **전환선**: **10봉** (최근 40시간 고저 중간값)
* **기준선**: **30봉** (최근 120시간 / 5일 고저 중간값 - 수급 축)
* **선행스팬 1**: `(전환선 + 기준선) / 2` 를 **미래 30봉** 앞으로 시프트
* **선행스팬 2**: **60봉** (최근 240시간 / 10일 고저 중간값)을 **미래 30봉** 앞으로 시프트

---

## 3. 소스 파일 및 실행 방법

| 모듈 파일명 | 기능 및 핵심 설명 | 실행 명령어 |
| :--- | :--- | :--- |
| **`U_Style_Code_4hour/analyze_kijun_u_turn.py`** | 최근 6봉(24시간) 이내 240분봉 기준선 U자형 턴어라운드 종목 스캔 | `python U_Style_Code_4hour/analyze_kijun_u_turn.py` |
| **`U_Style_Code_4hour/export_kijun_u_turn_pdf.py`** | 240분봉 U자형 턴어라운드 포착 코인 탐색 및 일목+거래량+MACD+RSI 차트 PDF 리포트 생성 | `python U_Style_Code_4hour/export_kijun_u_turn_pdf.py` |
| **`U_Style_Code_4hour/simulate_kijun_u_turn.py`** | 240분봉 200봉 타임롤링 시뮬레이션, 거래량 상관성 검증, 20봉후 성과분석 PDF 리포트 생성 | `python U_Style_Code_4hour/simulate_kijun_u_turn.py` |

---

## 4. 리포트 저장 위치

* **PDF 저장 경로**: `d:/pyprj/coinsts/U_Style_Code_4hour/report/`
* **시뮬레이션 리포트 파일명**: `report_240m_u_turn_simulation_YYYYMMDDHHMMSS.pdf`
* **최근 턴어라운드 리포트 파일명**: `report_240m_kijun_u_turn_YYYYMMDDHHMMSS.pdf`
