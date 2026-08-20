# export_4hour_ichimoku_pdf.py 프로세스 및 기술 문서

## 1. 개요 (Overview)

`export_4hour_ichimoku_pdf.py` 스크립트는 **빗썸(Bithumb) 원화(KRW) 마켓에 상장된 전 코인**을 대상으로 **240분봉(4시간봉)**과 **일봉(Daily)**의 일목균형표 및 MACD 지표를 시계열 수집하고 분석하여, **멀티 타임프레임 정배열 조건**을 만족하는 강세 코인들을 자동으로 포착하고 PDF 리포트로 자동 생성하는 프로그램입니다.

생성된 PDF 리포트는 `report_4hour/` 디렉터리에 타임스탬프 파일명 형태로 저장되며, 구글 드라이브 업로드 연동도 포함되어 있습니다.

---

## 2. 코인 포착 4대 핵심 필터 조건

스캔 시 다음 4가지 조건이 **모두 동시에 만족(AND)**되는 코인만 선별하여 리포트에 수록합니다.

```
                  [ 멀티 타임프레임 정배열 조건 ]
┌─────────────────────────────────────────────────────────────┐
│ 1. 240분봉 전환선(9) > 240분봉 기준선(26)                     │
│ 2. 최근 10봉 240분봉 기준선 각도 >= 0.0° (우상향/평행)         │
│ 3. 일봉 전환선(9) > 일봉 기준선(26)                          │
│ 4. 일봉 현재가(종가) > 일봉 전환선(9)                        │
└─────────────────────────────────────────────────────────────┘
```

| 구분 | 검증 지표 | 상세 조건 및 매매 전략적 의미 |
| :--- | :--- | :--- |
| **240분봉** | **단기/중기 정배열** | `240m 전환선 > 240m 기준선` : 4시간봉 차원에서 단기 상승 추세 형성 |
| **240분봉** | **기준선 각도 지지** | `240m 기준선 각도 >= 0.0°` : 지지선 역할을 하는 기준선이 우상향/평행 유지 |
| **일봉** | **대세 정배열** | `일봉 전환선 > 일봉 기준선` : 상위 타임프레임인 일봉 차원에서도 상승장 유지 |
| **일봉** | **추세 모멘텀** | `일봉 현재가 > 일봉 전환선` : 일봉 단기 이평선(전환선) 위에서 가격이 주도 |

---

## 3. 프로세스 동작 흐름도 (Data & Execution Flow)

```mermaid
flowchart TD
    A[프로그램 시작] --> B[빗썸 API로 원화 KRW 전체 마켓 조회]
    B --> C[ThreadPoolExecutor 병렬 스레드 풀 생성 (max_workers=6)]
    C --> D[각 코인별 240분봉 200개 시계열 데이터 수집]
    D --> E{240분봉 조건 검사\n1) 전환선 > 기준선\n2) 기준선각도 >= 0°}
    E -- No --> Z[탈락]
    E -- Yes --> F[해당 코인 일봉 200개 시계열 데이터 수집]
    F --> G{일봉 조건 검사\n1) 일봉 전환선 > 기준선\n2) 일봉 현재가 > 전환선}
    G -- No --> Z
    G -- Yes --> H[최종 포착 코인 리스트에 저장]
    H --> I[240m 기준선 각도 내림차순 정렬]
    I --> J[PdfPages 시작: report_4hour/report_4hour_YYYYMMDDHHMMSS.pdf]
    J --> K[Page 1: 종합 요약 표 페이지 렌더링]
    K --> L[Page 2~N: 개별 코인당 4단 서브플롯 차트 렌더링]
    L --> M[PDF 파일 닫기 및 최종 저장]
    M --> N[upload_to_gdrive 호출 - 구글 드라이브 업로드]
    N --> O[프로세스 종료]
```

---

## 4. 주요 함수 및 모듈 구조

### 4.1. 데이터 수집 및 지표 계산 모듈
* **`get_krw_markets()`**: 빗썸 REST API(`https://api.bithumb.com/v1/market/all`)에서 `KRW-`로 시작하는 모든 원화 마켓의 마켓코드, 한글명, 영문명을 가져옵니다.
* **`calc_mid_point(high, low, window)`**: $N$기간(9, 26, 52) 동안의 $(\text{최고가} + \text{최저가}) / 2$ 지표선(전환선, 기준선, 선행스팬2 기본)을 산출합니다.
* **`calc_rsi(series, period=14)`**: Wilder's Smoothing 기법 기반 상대강도지수(RSI)를 산출합니다.
* **`calc_macd(series, short=12, long=26, signal=9)`**: EMA 기반 MACD Line, Signal Line, MACD Histogram(오실레이터)을 산출합니다.
* **`get_slope_and_angle(arr)`**: 최근 $N$개 봉 시계열을 $t=0$ 시점 대비 정규화($arr[t] / arr[0]$)한 후 선형 회귀(`np.polyfit`)를 수행하여 기울기 각도(도, Degree)를 계산합니다.
* **`process_candle_df(data)`**: REST API JSON 수집 데이터를 Pandas DataFrame으로 변환하고 일목균형표(전환선, 기준선, 선행스팬1/2), RSI, MACD 지표를 일괄 계산합니다.

### 4.2. 분석 및 시각화 리포트 모듈
* **`fetch_and_analyze_single_coin_240m(m, count=200, kijun_window=10)`**:
  * 단일 코인에 대해 240분봉 수집 $\rightarrow$ 240m 일목 조건 1, 2 검사 $\rightarrow$ 부합 시 일봉 데이터 수집 $\rightarrow$ 일봉 조건 3, 4 검사 후 최종 데이터 딕셔너리를 반환합니다.
* **`generate_4hour_pdf_report(pdf_path, max_coins, max_workers, upload_gdrive)`**:
  * `ThreadPoolExecutor(max_workers=6)`를 통해 전 마켓을 고속 병렬 처리합니다.
  * `matplotlib.backends.backend_pdf.PdfPages`를 이용하여 PDF 문서 구조를 생성합니다.

---

## 5. PDF 리포트 출력 디자인 사양

| 페이지 레이아웃 | 구성 요소 | 상세 레이아웃 내용 |
| :--- | :--- | :--- |
| **요약 표 페이지** | **전체 통계 표 (Table)** | • 문서 제목, 분석 일시, 총 포착 코인 수 표기<br>• 컬럼: 마켓코드, 한글명, 영문명, 현재가, 240m전환선, 240m기준선, 240m각도, 일봉전환선, 일봉기준선, 240m MACD, 240m RSI, 구름위치 |
| **개별 코인 차트 페이지**<br>*(1코인 1페이지)* | **[1행 서브플롯] 240분봉 일목 차트** | • 종가 선, 전환선(Red), 기준선(Blue), 선행스팬1(Green), 선행스팬2(Orange)<br>• 양운(녹색)/음운(분홍) 구름대 영역 음영 fill<br>• 헤더 타이틀: 현재가, 240m 기준선 각도, RSI |
| | **[2행 서브플롯] 240분봉 MACD 차트** | • MACD Line(Blue), Signal Line(Red Line)<br>• Oscillator Histogram (양수: Red, 음수: Blue), 0선 기준선 |
| | **[3행 서브플롯] 일봉 일목 차트** | • 일봉 시계열 캔들/종가, 전환선, 기준선, 구름대 영역 음영 fill |
| | **[4행 서브플롯] 일봉 MACD 차트** | • 일봉 MACD Line, Signal Line, Oscillator Histogram 바 차트 |

---

## 6. 실행 방법 (Usage)

### 6.1. 기본 PDF 리포트 생성
터미널에서 스크립트를 직접 실행합니다.

```bash
python export_4hour_ichimoku_pdf.py
```

### 6.2. 스크립트 모듈 임포트 사용
다른 파이썬 코드에서 함수를 직접 호출하여 리포트를 생성할 수 있습니다.

```python
from export_4hour_ichimoku_pdf import generate_4hour_pdf_report

# 전체 마켓 분석 및 PDF 생성
pdf_file_path = generate_4hour_pdf_report(max_workers=6, upload_gdrive=False)
print(f"생성 완료: {pdf_file_path}")
```

---

## 7. 저장 경로 및 결과물 파일

* **디렉터리**: `d:/pyprj/coinsts/report_4hour/`
* **파일명 포맷**: `report_4hour_YYYYMMDDHHMMSS.pdf` (예: `report_4hour_20260810131316.pdf`)
