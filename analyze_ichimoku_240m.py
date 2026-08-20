import requests
import pandas as pd
import numpy as np
import time
import argparse
import sys

def get_krw_markets():
    """빗썸 원화(KRW) 마켓 목록 조회"""
    url = "https://api.bithumb.com/v1/market/all"
    headers = {"accept": "application/json"}
    response = requests.get(url, headers=headers)
    markets = response.json()
    krw_markets = [
        {
            'market': m['market'],
            'korean_name': m.get('korean_name', m['market']),
            'english_name': m.get('english_name', m['market'])
        }
        for m in markets if m['market'].startswith('KRW-')
    ]
    return krw_markets

def calc_mid_point(high, low, window):
    """지정된 기간 동안의 (최고가 + 최저가) / 2 계산"""
    return (high.rolling(window=window).max() + low.rolling(window=window).min()) / 2

def get_slope_and_angle(arr):
    """배열의 정규화 기울기 및 각도(도, Degree) 계산"""
    if len(arr) < 2 or arr.iloc[0] == 0:
        return 0.0, 0.0
    x = np.arange(len(arr))
    norm_arr = arr.values / arr.values[0]
    slope, _ = np.polyfit(x, norm_arr, 1)
    angle_deg = np.degrees(np.arctan(slope))
    return slope, angle_deg

def calc_rsi(series, period=14):
    """RSI 지수 계산"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def process_candle_df(data):
    """캔들 데이터 프레임 변환"""
    df = pd.DataFrame(data).iloc[::-1].reset_index(drop=True)
    for col in ['high_price', 'low_price', 'trade_price']:
        df[col] = df[col].astype(float)
    df['Close'] = df['trade_price']
    df['ConversionLine'] = calc_mid_point(df['high_price'], df['low_price'], 9)
    df['BaseLine'] = calc_mid_point(df['high_price'], df['low_price'], 26)
    df['Span1'] = ((df['ConversionLine'] + df['BaseLine']) / 2).shift(26)
    df['Span2'] = calc_mid_point(df['high_price'], df['low_price'], 52).shift(26)
    df['RSI'] = calc_rsi(df['Close'], 14)
    return df

def analyze_coin_240m_multi_tf(market_info, kijun_window=10):
    """
    240분봉 + 일봉 듀얼 정배열 분석:
    - 240분봉 조건: 전환선 > 기준선 AND 기준선 각도 >= 0도
    - 일봉 조건: 일봉 전환선 > 일봉 기준선 AND 일봉 현재가 > 일봉 전환선
    """
    market_code = market_info['market']
    korean_name = market_info['korean_name']
    english_name = market_info['english_name']
    
    headers = {"accept": "application/json"}
    url_240m = f"https://api.bithumb.com/v1/candles/minutes/240?market={market_code}&count=200"
    url_daily = f"https://api.bithumb.com/v1/candles/days?market={market_code}&count=200"
    
    try:
        res_240m = requests.get(url_240m, headers=headers, timeout=5)
        if res_240m.status_code != 200: return None
        data_240m = res_240m.json()
        if not isinstance(data_240m, list) or len(data_240m) < 60: return None
            
        df_240m = process_candle_df(data_240m)
        last_240m = df_240m.iloc[-1]
        
        tenkan_240m = last_240m['ConversionLine']
        kijun_240m = last_240m['BaseLine']
        price = last_240m['Close']
        
        if pd.isna(tenkan_240m) or pd.isna(kijun_240m): return None
            
        # 240분봉 조건 1 & 2
        cond1_240m_tenkan_above_kijun = (tenkan_240m > kijun_240m)
        _, kijun_angle_240m = get_slope_and_angle(df_240m['BaseLine'].iloc[-kijun_window:].dropna())
        _, tenkan_angle_240m = get_slope_and_angle(df_240m['ConversionLine'].iloc[-kijun_window:].dropna())
        cond2_240m_kijun_angle_ge_zero = (kijun_angle_240m >= 0.0)
        
        if cond1_240m_tenkan_above_kijun and cond2_240m_kijun_angle_ge_zero:
            # 일봉 데이터 수집
            res_daily = requests.get(url_daily, headers=headers, timeout=5)
            if res_daily.status_code == 200:
                data_daily = res_daily.json()
                if isinstance(data_daily, list) and len(data_daily) >= 30:
                    df_daily = process_candle_df(data_daily)
                    last_daily = df_daily.iloc[-1]
                    
                    daily_tenkan = last_daily['ConversionLine']
                    daily_kijun = last_daily['BaseLine']
                    daily_price = last_daily['Close']
                    
                    if pd.isna(daily_tenkan) or pd.isna(daily_kijun): return None
                        
                    # 일봉 조건 1: 일봉 전환선 > 일봉 기준선
                    cond3_daily_tenkan_above_kijun = (daily_tenkan > daily_kijun)
                    # 일봉 조건 2: 일봉 현재가 > 일봉 전환선
                    cond4_daily_price_above_tenkan = (daily_price > daily_tenkan)
                    
                    is_matched = cond3_daily_tenkan_above_kijun and cond4_daily_price_above_tenkan
                    
                    span1, span2 = last_240m['Span1'], last_240m['Span2']
                    cloud_pos = "-"
                    if not pd.isna(span1) and not pd.isna(span2):
                        cloud_top, cloud_bottom = max(span1, span2), min(span1, span2)
                        cloud_pos = "구름위(양호)" if price > cloud_top else ("구름아래(주의)" if price < cloud_bottom else "구름내부")

                    return {
                        'market': market_code,
                        'korean_name': korean_name,
                        'english_name': english_name,
                        'price': price,
                        'tenkan_240m': tenkan_240m,
                        'kijun_240m': kijun_240m,
                        'kijun_angle_240m': round(kijun_angle_240m, 2),
                        'tenkan_angle_240m': round(tenkan_angle_240m, 2),
                        'daily_tenkan': round(daily_tenkan, 2),
                        'daily_kijun': round(daily_kijun, 2),
                        'daily_price': round(daily_price, 2),
                        'rsi_240m': round(last_240m['RSI'], 1) if not pd.isna(last_240m['RSI']) else 0.0,
                        'cloud_pos': cloud_pos,
                        'is_matched': is_matched
                    }
    except Exception:
        pass
    return None

def main():
    parser = argparse.ArgumentParser(description="240분봉 (전환>기준 & 기준선각도>=0°) AND 일봉 (전환>기준 & 현재가>전환선) 코인 분석기")
    parser.add_argument("--window", type=int, default=10, help="240분봉 각도 측정 기간 (기본값: 10봉)")
    parser.add_argument("--delay", type=float, default=0.03, help="API 호출 간격")
    args = parser.parse_args()
    
    print("=" * 115)
    print(" [일목균형표 멀티 타임프레임 분석]")
    print(" 1) 240분봉: 전환선 > 기준선 & 기준선 각도 >= 0°")
    print(" 2) 일봉    : 전환선 > 기준선 & 현재가 > 전환선")
    print("=" * 115)
    
    markets = get_krw_markets()
    print(f"빗썸 KRW 마켓 총 {len(markets)}개 코인 분석 중...\n")
    
    matched_coins = []
    for m in markets:
        res = analyze_coin_240m_multi_tf(m, kijun_window=args.window)
        if res and res['is_matched']:
            matched_coins.append(res)
        time.sleep(args.delay)
        
    print(f"\n분석 완료! 전체 코인 중 최종 조건 만족 코인: {len(matched_coins)}개 포착\n")
    
    if matched_coins:
        df_matched = pd.DataFrame(matched_coins)
        df_matched = df_matched.sort_values(by=['kijun_angle_240m', 'tenkan_angle_240m'], ascending=[False, False]).reset_index(drop=True)
        
        print("=" * 125)
        print("★ [최종 멀티 타임프레임 조건 만족 코인 목록] ★")
        print("=" * 125)
        print(f"{'마켓코드':<12} {'코인명':<14} {'현재가':<12} {'240m전환선':<12} {'240m기준선':<12} {'240m기준선각도':<12} {'일봉전환선':<12} {'일봉기준선':<12} {'240m RSI':<8}")
        print("-" * 125)
        for _, row in df_matched.iterrows():
            print(f"{row['market']:<12} {row['korean_name']:<14} {row['price']:<12,.2f} {row['tenkan_240m']:<12,.2f} {row['kijun_240m']:<12,.2f} {row['kijun_angle_240m']:<+12.2f}° {row['daily_tenkan']:<12,.2f} {row['daily_kijun']:<12,.2f} {row['rsi_240m']:<8.1f}")
        print("=" * 125)
    else:
        print("모든 조건(240분봉 정배열+기준선각도>=0° AND 일봉 전환>기준 & 현재가>전환선)을 동시 만족하는 코인이 없습니다.")

if __name__ == "__main__":
    main()
