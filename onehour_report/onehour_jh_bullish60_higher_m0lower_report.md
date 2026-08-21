# onehour_jh_bullish60_higher_m0lower_report.py 프로세스 및 기술 문서

## 1. 개요 (Overview)

`onehour_jh_bullish60_higher_m0lower_report.py` 모듈은 **빗썸(Bithumb) 원화(KRW) 마켓에 상장된 전체 암호화폐**를 대상으로 `onehour_jh_bullish60_higher_report` 로직을 기반으로 **1시간봉 MACD 지표 값이 0 이하(MACD <= 0)**인 제약 조건을 추가하여, **최근 10시간 중 체결가 > 전환선(9) 분포도가 60% 이상(6개 봉 이상)**이고 **전환선(9)의 기울기 각도가 0° 이상 5° 이하(수평~완만한 우상향)**이면서 **현재 1시간봉 MACD <= 0** 상태인 침체권 반등 초입 코인을 포착하고, 각 포착 코인별 **60분봉(1시간봉) 및 일봉(Daily) 기준 일목균형표(전환선9, 기준선26), MACD(12,26,9), RSI(14)** 지표를 계산하여 **코인당 한 페이지 듀얼 3단 시각화(좌측: 1시간봉, 우측: 일봉)** PDF 종합 리포트를 자동 생성하는 프로그램입니다.

생성된 PDF 리포트는 `onehour_report/report/` 디렉터리에 타임스탬프 파일명(`onehour_jh_bullish60_higher_m0lower_report_YYYYMMDDHHMMSS.pdf`) 형태로 자동 저장됩니다.

---

## 2. 수집 및 분석 규격

```
    [ 빗썸 1시간봉 체결가>전환선(9) 60%+ & 각도 0°~5° & MACD <= 0 포착 규격 ]
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. API 호출:                                                                │
│    - 1시간봉: https://api.bithumb.com/v1/candles/minutes/60?market={market}&count=200 │
│    - 일  봉: https://api.bithumb.com/v1/candles/days?market={market}&count=200       │
│ 2. 수집 대상: 빗썸 원화(KRW) 마켓 상장 전체 암호화폐 (약 480개)              │
│ 3. 포착 조건 (1시간봉 기준):                                               │
│    - 체결가 > 전환선 분포도: 최근 10시간 중 체결가(Close) > 전환선(9) 충족 봉 >= 6개 (60%+) │
│    - 전환선 기울기 각도: 0° <= tenkan_angle_deg <= 5.0°                      │
│    - 현재 1시간봉 체결가 > 전환선: 체결가(Close) > 전환선(9)                   │
│    - [추가 제약] 1시간봉 MACD 지표 값: 현재 1시간봉 MACD <= 0               │
│ 4. 지표 계산: 일목균형표 (9, 26, 52), MACD (12, 26, 9), RSI (14), 거래량         │
└─────────────────────────────────────────────────────────────────────────────┘
```

| 지표 항목 | 파라미터 및 설명 |
| :--- | :--- |
| **일목균형표** | `전환선(9봉)`, `기준선(26봉)`, `선행스팬1(26봉 시프트)`, `선행스팬2(52봉/26봉 시프트)` |
| **MACD** | `Short=12`, `Long=26`, `Signal=9` (MACD 선, Signal 선, Oscillator Histogram) |
| **RSI** | `Period=14` (RSI 선, 70/30 과매수/과매도 기준선) |
| **거래량** | `candle_acc_trade_volume` (진한 색상 거래량 막대 차트 TwinX Overlay) |

---

## 3. 프로세스 동작 흐름도 (Data & Execution Flow)

```mermaid
flowchart TD
    A[프로그램 시작: onehour_jh_bullish60_higher_m0lower_report.py] --> B[빗썸 API로 원화 KRW 전체 마켓 목록 조회]
    B --> C[ThreadPoolExecutor 멀티스레드 스캔 생성 max_workers=8]
    C --> D[각 코인별 1시간봉 수집: 체결가>전환선 분포도 >= 60% & 전환선 각도 0°~5° & MACD <= 0 검증]
    D -->|조건 만족 코인| E[일봉 추가 수집 및 60m/일봉 일목·MACD·RSI 지표 계산]
    E --> F[수집 데이터 검증 및 체결가>전환선 분포도/각도 정렬]
    F --> G[PdfPages 시작: onehour_report/report/onehour_jh_bullish60_higher_m0lower_report_YYYYMMDDHHMMSS.pdf]
    G --> H[Page 1~N: 종합 요약 표 Summary Table 페이지 렌더링]
    H --> I[Page N+1 ~ Final: 코인당 한 페이지 듀얼 3단 시각화 차트 렌더링]
    I --> J[PDF 파일 저장 완료]
```

---

## 4. PDF 리포트 구성 및 차트 시각화 레이아웃 (1 코인 1 페이지 듀얼 3단)

### 4.1. 표지 및 종합 요약 표 페이지
- 스캔 일시, 분석 조건, 포착 대상 코인 수 표기.
- 마켓코드, 한글명, 영문명, 현재가, 60m MACD, 10h 체결가>전환선 비율(%), 전환선 각도(°), 60m 전환선/기준선/이격률/RSI, 일봉 RSI 요약 표 수록.

### 4.2. 코인별 듀얼 3단 차트 레이아웃 (Page 2 ~ N)
한 코인당 **1개 페이지**에 3x2 서브플롯(좌: 1시간봉 / 우: 일봉)으로 구성됩니다.

```
┌──────────────────────────────────────────┬──────────────────────────────────────────┐
│ [좌측: 1시간봉(60m)]                     │ [우측: 일봉(Daily)]                      │
├──────────────────────────────────────────┼──────────────────────────────────────────┤
│ 1단: 1시간봉 가격+일목(9,26,52)+진한거래량│ 1단: 일봉 가격+일목(9,26,52)+진한거래량 │
├──────────────────────────────────────────┼──────────────────────────────────────────┤
│ 2단: 1시간봉 MACD (12, 26, 9)            │ 2단: 일봉 MACD (12, 26, 9)               │
├──────────────────────────────────────────┼──────────────────────────────────────────┤
│ 3단: 1시간봉 RSI (14)                    │ 3단: 일봉 RSI (14)                       │
└──────────────────────────────────────────┴──────────────────────────────────────────┘
```

---

## 5. 모듈 구조 및 파일 위치

```
d:\pyprj\coinsts\
├── onehour_jh_bullish60_higher_m0lower_report.py             # [루트 래퍼] 메인 실행 모듈
└── onehour_report/
    ├── onehour_jh_bullish60_higher_m0lower_report.py         # [메인 모듈] 체결가>전환선 60%+ & 각도 0°~5° & MACD<=0 검증 및 PDF 생성
    ├── onehour_jh_bullish60_higher_m0lower_report.md         # [기술 문서] 본 문서
    └── report/                                               # [PDF 저장 폴더]
        └── onehour_jh_bullish60_higher_m0lower_report_YYYYMMDDHHMMSS.pdf
```

---

## 6. 실행 방법

콘솔(터미널)에서 아래 명령어 중 하나를 실행합니다:

```bash
# 1. onehour_report 모듈 direct 실행
python onehour_report/onehour_jh_bullish60_higher_m0lower_report.py

# 2. 루트 래퍼 스크립트 실행
python onehour_jh_bullish60_higher_m0lower_report.py
```
