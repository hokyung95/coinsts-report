import requests
import pandas as pd
import matplotlib.pyplot as plt

# matplotlib 한글 폰트 설정 (Windows: 맑은 고딕)
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

# 1. 빗썸 API 데이터 수집 (카르테시 1시간 봉 150개)
url = "https://api.bithumb.com/v1/candles/minutes/60?market=KRW-ACE&count=150"
response = requests.get(url, headers={"accept": "application/json"})
df = pd.DataFrame(response.json()).iloc[::-1].reset_index(drop=True)

# 숫자형 변환 및 시계열 설정
for col in ['high_price', 'low_price', 'trade_price']:
    df[col] = df[col].astype(float)
df['candle_date_time_kst'] = pd.to_datetime(df['candle_date_time_kst'])

# 2. 일목균형표 지표 계산
def calc_mid_point(high, low, window):
    return (high.rolling(window=window).max() + low.rolling(window=window).min()) / 2

df['tenkan_sen'] = calc_mid_point(df['high_price'], df['low_price'], 9)    # 전환선
df['kijun_sen'] = calc_mid_point(df['high_price'], df['low_price'], 26)    # 기준선

# 미래 구름대 표현을 위한 26시간 시간축 확장
last_date = df['candle_date_time_kst'].iloc[-1]
future_dates = pd.date_range(start=last_date + pd.Timedelta(hours=1), periods=26, freq='h')
df_future = pd.DataFrame({'candle_date_time_kst': future_dates})
df_combined = pd.concat([df, df_future], ignore_index=True)

df_combined['senkou_span_a'] = ((df_combined['tenkan_sen'] + df_combined['kijun_sen']) / 2).shift(26)
df_combined['senkou_span_b'] = calc_mid_point(df_combined['high_price'], df_combined['low_price'], 52).shift(26)
df_combined['chikou_span'] = df_combined['trade_price'].shift(-26)

# 3. 차트 그리기
plt.figure(figsize=(14, 7))

# 종가 / 전환선 / 기준선 / 후행스팬
plt.plot(df_combined['candle_date_time_kst'], df_combined['trade_price'], label='종가', color='black', linewidth=1.5)
plt.plot(df_combined['candle_date_time_kst'], df_combined['tenkan_sen'], label='전환선(9)', color='red', linewidth=1)
plt.plot(df_combined['candle_date_time_kst'], df_combined['kijun_sen'], label='기준선(26)', color='blue', linewidth=1)
plt.plot(df_combined['candle_date_time_kst'], df_combined['chikou_span'], label='후행스팬(-26)', color='green', linestyle='--', alpha=0.7)

# 선행스팬1, 2 경계선
plt.plot(df_combined['candle_date_time_kst'], df_combined['senkou_span_a'], color='lightgreen', alpha=0.5)
plt.plot(df_combined['candle_date_time_kst'], df_combined['senkou_span_b'], color='lightpink', alpha=0.5)

# 구름대 영역 채우기 (양운: 초록색 / 음운: 붉은색)
plt.fill_between(
    df_combined['candle_date_time_kst'],
    df_combined['senkou_span_a'],
    df_combined['senkou_span_b'],
    where=(df_combined['senkou_span_a'] >= df_combined['senkou_span_b']),
    color='lightgreen', alpha=0.3, label='양운'
)
plt.fill_between(
    df_combined['candle_date_time_kst'],
    df_combined['senkou_span_a'],
    df_combined['senkou_span_b'],
    where=(df_combined['senkou_span_a'] < df_combined['senkou_span_b']),
    color='lightpink', alpha=0.3, label='음운'
)

plt.title('KRW-CTSI 일목균형표 차트 (1시간 봉)')
plt.xlabel('시간')
plt.ylabel('가격 (KRW)')
plt.legend(loc='upper left')
plt.grid(True, linestyle=':', alpha=0.6)
plt.tight_layout()

plt.show()