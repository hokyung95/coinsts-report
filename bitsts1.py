import requests
import pandas as pd
import numpy as np
import time

def calc_mid_point(high, low, window):
    """지정된 기간 동안의 (최고가 + 최저가) / 2 계산"""
    return (high.rolling(window=window).max() + low.rolling(window=window).min()) / 2

def is_upward_trend(arr, slope_threshold=0.0):
    """배열의 기울기를 이용한 우상향 판단 함수"""
    if len(arr) < 2:
        return False, 0.0
    x = np.arange(len(arr))
    slope, _ = np.polyfit(x, arr, 1)
    return slope > slope_threshold, slope

def get_slope_and_angle(arr):
    """배열의 정규화 기울기 및 각도(도, Degree) 계산"""
    if len(arr) < 2 or arr.iloc[0] == 0:
        return 0.0, 0.0
    x = np.arange(len(arr))
    norm_arr = arr.values / arr.values[0]
    slope, _ = np.polyfit(x, norm_arr, 1)
    angle_deg = np.degrees(np.arctan(slope))
    return slope, angle_deg

def calc_macd(series, short=12, long=26, signal=9):
    """MACD, Signal, Histogram 계산"""
    ema_short = series.ewm(span=short, adjust=False).mean()
    ema_long = series.ewm(span=long, adjust=False).mean()
    macd = ema_short - ema_long
    macd_signal = macd.ewm(span=signal, adjust=False).mean()
    macd_hist = macd - macd_signal
    return macd, macd_signal, macd_hist

def calc_rsi(series, period=14):
    """RSI (상대강도지수) 계산"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def analyze_fusionist(market_code="KRW-ACE", count=200):
    """퓨저니스트(KRW-ACE) 단일 코인 지표 및 조건 분석"""
    url = f"https://api.bithumb.com/v1/candles/minutes/60?market={market_code}&count={count}"
    headers = {"accept": "application/json"}
    
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print(f"API 호출 실패 (상태 코드: {response.status_code})")
        return None
        
    data = response.json()
    if not isinstance(data, list) or len(data) < 50:
        print("수집된 데이터가 부족하거나 잘못되었습니다.")
        return None

    # 데이터프레임 변환 및 과거 순 정렬
    df = pd.DataFrame(data).iloc[::-1].reset_index(drop=True)
    
    for col in ['high_price', 'low_price', 'trade_price']:
        df[col] = df[col].astype(float)
        
    # 1. 일목균형표 계산
    df['tenkan_sen'] = calc_mid_point(df['high_price'], df['low_price'], 9)    # 전환선
    df['kijun_sen'] = calc_mid_point(df['high_price'], df['low_price'], 26)    # 기준선
    df['senkou_span_a'] = ((df['tenkan_sen'] + df['kijun_sen']) / 2).shift(26) # 선행스팬 1
    df['senkou_span_b'] = calc_mid_point(df['high_price'], df['low_price'], 52).shift(26) # 선행스팬 2
    df['chikou_span'] = df['trade_price'].shift(-26)                         # 후행스팬
    
    # 2. MACD & RSI 계산
    df['macd'], df['macd_signal'], df['macd_hist'] = calc_macd(df['trade_price'])
    df['rsi'] = calc_rsi(df['trade_price'], period=14)
    
    # 3. 최근 20개 봉 지표 판정
    recent_20_trade = df['trade_price'].tail(20)
    recent_20_tenkan = df['tenkan_sen'].tail(20)
    recent_20_kijun = df['kijun_sen'].tail(20)
    
    kijun_is_up, kijun_slope = is_upward_trend(df['kijun_sen'].dropna())
    tenkan_is_up, tenkan_slope = is_upward_trend(df['tenkan_sen'].dropna())
    
    tenkan_slope_val, tenkan_angle = get_slope_and_angle(recent_20_tenkan.dropna())
    kijun_slope_val, kijun_angle = get_slope_and_angle(recent_20_kijun.dropna())
    
    tenkan_above_kijun_ratio = (recent_20_tenkan > recent_20_kijun).mean()
    is_tenkan_above_kijun_75 = tenkan_above_kijun_ratio >= 0.75
    
    trade_above_tenkan_ratio = (recent_20_trade > recent_20_tenkan).mean()
    is_trade_above_tenkan_80 = trade_above_tenkan_ratio >= 0.80
    
    last_price = df['trade_price'].iloc[-1]
    last_rsi = df['rsi'].iloc[-1]
    last_macd = df['macd'].iloc[-1]
    last_macd_hist = df['macd_hist'].iloc[-1]
    
    is_macd_ge_0 = last_macd >= 0
    is_rsi_between_50_70 = (last_rsi >= 50) and (last_rsi <= 70)
    is_tenkan_angle_ok = tenkan_angle <= 30.0
    is_kijun_angle_ok = kijun_angle <= 30.0
    
    # 전략 최종 매수 조건 만족 여부
    buy_signal = (
        is_tenkan_above_kijun_75 and 
        is_trade_above_tenkan_80 and 
        is_macd_ge_0 and 
        is_rsi_between_50_70 and
        is_tenkan_angle_ok and
        is_kijun_angle_ok
    )
    
    print("\n" + "="*80)
    print(f" [퓨저니스트 (Fusionist / {market_code}) 기술적 지표 분석 결과] ")
    print("="*80)
    print(f"▶ 현재 종가: {last_price:,.2f} 원")
    print(f"▶ 기준선 우상향: {kijun_is_up} (기울기: {kijun_slope:.4f})")
    print(f"▶ 전환선 우상향: {tenkan_is_up} (기울기: {tenkan_slope:.4f})")
    print(f"▶ 전환선 각도: {tenkan_angle:.2f}° (30도 이하 만족: {is_tenkan_angle_ok})")
    print(f"▶ 기준선 각도: {kijun_angle:.2f}° (30도 이하 만족: {is_kijun_angle_ok})")
    print(f"▶ 최근 20봉 전환선 > 기준선 비율: {tenkan_above_kijun_ratio*100:.1f}% (75% 이상 만족: {is_tenkan_above_kijun_75})")
    print(f"▶ 최근 20봉 종가 > 전환선 비율: {trade_above_tenkan_ratio*100:.1f}% (80% 이상 만족: {is_trade_above_tenkan_80})")
    print(f"▶ 현재 MACD: {last_macd:.4f} (0 이상 만족: {is_macd_ge_0})")
    print(f"▶ 현재 RSI: {last_rsi:.2f} (50~70 사이 만족: {is_rsi_between_50_70})")
    print("-" * 80)
    print(f"★ 최종 매수 신호 발생 여부: {'포착 (BUY)' if buy_signal else '미포착 (SKIP)'}")
    print("="*80)
    
    print("\n[최신 10개 봉 세부 데이터 데이터프레임]")
    print(df[['candle_date_time_kst', 'trade_price', 'tenkan_sen', 'kijun_sen', 'macd', 'macd_hist', 'rsi']].tail(10).to_string(index=False))
    
    return df

if __name__ == "__main__":
    analyze_fusionist("KRW-ACE")