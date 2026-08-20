import requests
import pandas as pd
import numpy as np
import time

def get_krw_markets():
    """빗썸에서 거래되는 모든 원화(KRW) 마켓 목록 조회"""
    url = "https://api.bithumb.com/v1/market/all"
    headers = {"accept": "application/json"}
    response = requests.get(url, headers=headers)
    markets = response.json()
    # KRW- 마켓만 필터링
    krw_markets = [m for m in markets if m['market'].startswith('KRW-')]
    return krw_markets

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

def calc_macd(series, short=12, long=26, signal=9):
    """MACD, Signal, Histogram 계산"""
    ema_short = series.ewm(span=short, adjust=False).mean()
    ema_long = series.ewm(span=long, adjust=False).mean()
    macd = ema_short - ema_long
    macd_signal = macd.ewm(span=signal, adjust=False).mean()
    macd_hist = macd - macd_signal
    return macd, macd_signal, macd_hist

def calc_rsi(series, period=14):
    """RSI (상대강도지수, Wilder's Smoothing) 계산"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def analyze_coin(market_code, count=200):
    """단일 코인 기술적 지표 및 조건 분석"""
    url = f"https://api.bithumb.com/v1/candles/minutes/60?market={market_code}&count={count}"
    headers = {"accept": "application/json"}
    
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        return None
        
    data = response.json()
    if not isinstance(data, list) or len(data) < 50:
        return None

    df = pd.DataFrame(data).iloc[::-1].reset_index(drop=True)
    
    for col in ['high_price', 'low_price', 'trade_price']:
        df[col] = df[col].astype(float)
        
    # 1. 일목균형표
    df['tenkan_sen'] = calc_mid_point(df['high_price'], df['low_price'], 9)
    df['kijun_sen'] = calc_mid_point(df['high_price'], df['low_price'], 26)
    df['senkou_span_a'] = ((df['tenkan_sen'] + df['kijun_sen']) / 2).shift(26)
    df['senkou_span_b'] = calc_mid_point(df['high_price'], df['low_price'], 52).shift(26)
    
    # 2. MACD & RSI
    df['macd'], df['macd_signal'], df['macd_hist'] = calc_macd(df['trade_price'])
    df['rsi'] = calc_rsi(df['trade_price'], period=14)
    
    # 분석 지표 계산
    kijun_is_up, kijun_slope = is_upward_trend(df['kijun_sen'].dropna())
    tenkan_is_up, tenkan_slope = is_upward_trend(df['tenkan_sen'].dropna())
    
    recent_20_trade = df['trade_price'].tail(20)
    recent_20_tenkan = df['tenkan_sen'].tail(20)
    recent_20_kijun = df['kijun_sen'].tail(20)
    
    # 조건 체크
    tenkan_above_kijun_ratio = (recent_20_tenkan > recent_20_kijun).mean()
    is_tenkan_above_kijun_75 = tenkan_above_kijun_ratio >= 0.75
    
    trade_above_tenkan_ratio = (recent_20_trade > recent_20_tenkan).mean()
    is_trade_above_tenkan_80 = trade_above_tenkan_ratio >= 0.80
    
    last_price = df['trade_price'].iloc[-1]
    last_rsi = df['rsi'].iloc[-1]
    last_macd_hist = df['macd_hist'].iloc[-1]
    
    return {
        'market': market_code,
        'current_price': last_price,
        'kijun_is_up': kijun_is_up,
        'kijun_slope': round(kijun_slope, 4),
        'tenkan_is_up': tenkan_is_up,
        'tenkan_slope': round(tenkan_slope, 4),
        'tenkan_above_kijun_pct': round(tenkan_above_kijun_ratio * 100, 1),
        'tenkan_above_kijun_75': is_tenkan_above_kijun_75,
        'trade_above_tenkan_pct': round(trade_above_tenkan_ratio * 100, 1),
        'trade_above_tenkan_80': is_trade_above_tenkan_80,
        'rsi': round(last_rsi, 2) if not np.isnan(last_rsi) else None,
        'macd_hist': round(last_macd_hist, 4) if not np.isnan(last_macd_hist) else None
    }

def analyze_all_coins(delay=0.05, max_coins=None):
    """모든 원화 코인을 루프로 분석"""
    markets = get_krw_markets()
    if max_coins:
        markets = markets[:max_coins]
        
    print(f"총 {len(markets)}개 원화 마켓 코인 분석을 시작합니다...")
    results = []
    
    for idx, m in enumerate(markets, 1):
        market_code = m['market']
        korean_name = m.get('korean_name', market_code)
        
        try:
            res = analyze_coin(market_code)
            if res:
                res['korean_name'] = korean_name
                results.append(res)
                print(f"[{idx}/{len(markets)}] {korean_name}({market_code}) 분석 완료 - 종가: {res['current_price']}, 전환선>기준선(75%): {res['tenkan_above_kijun_75']}, 종가>전환선(80%): {res['trade_above_tenkan_80']}")
            else:
                print(f"[{idx}/{len(markets)}] {korean_name}({market_code}) 데이터 부족/오류로 스킵")
        except Exception as e:
            print(f"[{idx}/{len(markets)}] {korean_name}({market_code}) 에러: {e}")
            
        time.sleep(delay)
        
    df_results = pd.DataFrame(results)
    return df_results

if __name__ == "__main__":
    # 전체 코인 분석 실행 (테스트용으로 상위 20개 실행 원할 시 max_coins=20 전달 가능)
    df_res = analyze_all_coins(delay=0.05)
    
    print("\n" + "="*80)
    print(" [전체 분석 결과 요약] ")
    print("="*80)
    print(f"분석 완료 코인 수: {len(df_res)}")
    
    # 조건 만족하는 코인 필터링 예시 (전환선>기준선 75% 이상 & 종가>전환선 80% 이상)
    filtered = df_res[df_res['tenkan_above_kijun_75'] & df_res['trade_above_tenkan_80']]
    print(f"\n[전환선>기준선(75%이상) AND 종가>전환선(80%이상) 만족 코인: {len(filtered)}개]")
    if not filtered.empty:
        print(filtered[['market', 'korean_name', 'current_price', 'tenkan_above_kijun_pct', 'trade_above_tenkan_pct', 'rsi', 'macd_hist']])