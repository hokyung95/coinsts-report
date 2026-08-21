# onehour_rsi60_75_ratio80_report_v2.py 프로세스 및 기술 문서

## 1. 개요 (Overview)

`onehour_rsi60_75_ratio80_report_v2.py` 모듈은 **빗썸(Bithumb) 원화(KRW) 마켓 상장 전체 암호화폐**를 대상으로 **1시간봉(60분봉) 최근 20개봉 RSI(14) 60~75 범위 조건 80% 이상(16개봉 이상)**을 포착하는 v2 포착 프로그램입니다.

v2 버전에서는 코인의 **체결가(종가) vs 일목균형표 전환선(9) 이격도 및 이탈 상태(전환선 상위 / 전환선 이탈)** 정보를 추가로 분석하여 서머리 표 및 PDF 리포트에 함께 표기합니다.

생성된 PDF 리포트는 `onehour_report/report/` 디렉터리에 타임스탬프 파일명(`onehour_rsi60_75_ratio80_report_v2_YYYYMMDDHHMMSS.pdf`) 형태로 자동 저장됩니다.

---

## 2. 수집 및 분석 규격 (v2)

```
                [ 빗썸 1시간봉 최근 20개봉 RSI 60~75 비율 80%+ 포착 v2 규격 ]
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. API 호출:                                                                │
│    - 1시간봉: https://api.bithumb.com/v1/candles/minutes/60?market={market}&count=200 │
│    - 일  봉: https://api.bithumb.com/v1/candles/days?market={market}&count=200       │
│ 2. 수집 대상: 빗썸 원화(KRW) 마켓 상장 전체 암호화폐                          │
│ 3. 포착 조건 (1시간봉 기준):                                               │
│    - 최근 20개 캔들 중 60.0 <= RSI(14) <= 75.0 충족 봉 >= 16개 (80% 이상)    │
│ 4. v2 추가 정보:                                                           │
│    - 체결가 vs 일목 전환선(9) 이탈 위치 (상위 / 이탈) 및 이격률(%)            │
└─────────────────────────────────────────────────────────────────────────────┘
```

| 지표 항목 | 파라미터 및 설명 |
| :--- | :--- |
| **RSI (14)** | `Period=14` (RSI 선, 60~75 목표 구간 주황색 음영 하이라이트 및 75 기준선) |
| **일목 전환선(9)** | `ConversionLine(9)` (체결가가 전환선 위인가 아래 이탈인가 검증) |
| **일목균형표** | `전환선(9봉)`, `기준선(26봉)`, `선행스팬1(26봉 시프트)`, `선행스팬2(52봉/26봉 시프트)` |
| **MACD** | `Short=12`, `Long=26`, `Signal=9` (MACD 선, Signal 선, Oscillator Histogram) |

---

## 3. 프로세스 동작 흐름도

```mermaid
flowchart TD
    A[프로그램 시작: onehour_rsi60_75_ratio80_report_v2.py] --> B[빗썸 API로 원화 KRW 전체 마켓 목록 조회]
    B --> C[ThreadPoolExecutor 멀티스레드 스캔 생성 max_workers=8]
    C --> D[각 코인별 1시간봉 수집: 최근 20개봉 중 60<=RSI<=75 충족 봉 >= 16개 검증]
    D -->|조건 만족 코인| E[체결가 vs 전환선9 이격률 계산 & 일봉 추가 수집]
    E --> F[수집 데이터 검증 및 RSI 60~75 비율 / 현재 RSI 순 정렬]
    F --> G[PdfPages 시작: onehour_report/report/onehour_rsi60_75_ratio80_report_v2_YYYYMMDDHHMMSS.pdf]
    G --> H[Page 1~N: 종합 요약 표 Summary Table 페이지 렌더링]
    H --> I[Page N+1 ~ Final: 코인당 한 페이지 듀얼 3단 시각화 차트 렌더링]
    I --> J[PDF 파일 저장 완료]
```

---

## 4. 실행 방법

```bash
# 1. 루트 래퍼 실행
python onehour_rsi60_75_ratio80_report_v2.py

# 2. direct 실행
python onehour_report/onehour_rsi60_75_ratio80_report_v2.py
```
