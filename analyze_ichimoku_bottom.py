import requests
import pandas as pd
import numpy as np
import time
import argparse
import sys

def get_krw_markets():
    """빗썸에서 거래되는 모든 원화(KRW) 마켓 목록 조회"""
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

def analyze_coin_cloud_bottom(market_info, timeframe='60', count=200, angle_window=10):
    """
    일목균형표 조건 검색:
    1. 음운(Senkou Span A < Senkou Span B)
    2. 음운 아래 위치 (현재가, 전환선, 기준선 모두 구름대 하단 아래)
    3. 전환선 < 기준선 (전환선이 기준선 아래에 위치)
    4. 전환선 <= 현재가 <= 기준선 (현재가가 전환선과 기준선 사이에서 등락)
    5. 전환선 각도 >= 0도 (우상향 또는 평행)
    """
    market_code = market_info['market']
    korean_name = market_info['korean_name']
    english_name = market_info['english_name']
    
    if timeframe == '24h':
        url = f"https://api.bithumb.com/v1/candles/days?market={market_code}&count={count}"
    else:
        url = f"https://api.bithumb.com/v1/candles/minutes/{timeframe}?market={market_code}&count={count}"
        
    headers = {"accept": "application/json"}
    
    try:
        res = requests.get(url, headers=headers)
        if res.status_code != 200:
            return None
        data = res.json()
        if not isinstance(data, list) or len(data) < 80:
            return None
            
        df = pd.DataFrame(data).iloc[::-1].reset_index(drop=True)
        for col in ['high_price', 'low_price', 'trade_price']:
            df[col] = df[col].astype(float)
        if 'candle_acc_trade_volume' in df.columns:
            df['candle_acc_trade_volume'] = df['candle_acc_trade_volume'].astype(float)
            
        # 1. 전환선 & 기준선 계산
        df['tenkan_sen'] = calc_mid_point(df['high_price'], df['low_price'], 9)
        df['kijun_sen'] = calc_mid_point(df['high_price'], df['low_price'], 26)
        
        # 2. 선행스팬 A & B (현재 봉 위치에서의 선행스팬 값은 26봉 전에서 계산하여 미래로 26봉 이동한 것)
        # 즉 i번째 봉에서의 선행스팬 A = i-26 시점의 (전환선 + 기준선)/2
        # i번째 봉에서의 선행스팬 B = i-26 시점의 52봉 중간값
        mid_52 = calc_mid_point(df['high_price'], df['low_price'], 52)
        df['senkou_span_a'] = ((df['tenkan_sen'] + df['kijun_sen']) / 2).shift(26)
        df['senkou_span_b'] = mid_52.shift(26)
        
        df['rsi'] = calc_rsi(df['trade_price'], 14)
        
        # 최신 봉 선택
        curr = df.iloc[-1]
        
        senkou_a = curr['senkou_span_a']
        senkou_b = curr['senkou_span_b']
        tenkan = curr['tenkan_sen']
        kijun = curr['kijun_sen']
        price = curr['trade_price']
        
        # 유효값 체크
        if pd.isna(senkou_a) or pd.isna(senkou_b) or pd.isna(tenkan) or pd.isna(kijun):
            return None
            
        # 구름대 상하단 및 음운 여부
        cloud_top = max(senkou_a, senkou_b)
        cloud_bottom = min(senkou_a, senkou_b)
        is_bearish_cloud = (senkou_a < senkou_b)  # 음운(Bearish Kumo)
        
        # 조건 1: 음운(Senkou Span A < Senkou Span B)
        cond1_bearish_cloud = is_bearish_cloud
        
        # 조건 2: 음운 아래에 위치 (현재가, 전환선, 기준선 모두 구름대 하단 아래)
        cond2_below_cloud = (price < cloud_bottom) and (tenkan < cloud_bottom) and (kijun < cloud_bottom)
        
        # 조건 3: 전환선이 기준선 아래에 위치 (tenkan < kijun)
        cond3_tenkan_below_kijun = (tenkan < kijun)
        
        # 조건 4: 현재가가 전환선과 기준선 사이에서 등락 (tenkan <= price <= kijun)
        cond4_price_between = (tenkan <= price) and (price <= kijun)
        
        # 조건 5: 전환선 각도가 0도 이상 (최근 angle_window 봉 기준)
        past_tenkan = df['tenkan_sen'].iloc[-angle_window:]
        _, tenkan_angle = get_slope_and_angle(past_tenkan.dropna())
        cond5_angle_ge_zero = (tenkan_angle >= 0.0)
        
        # 종합 매칭 여부
        is_matched = (
            cond1_bearish_cloud and
            cond2_below_cloud and
            cond3_tenkan_below_kijun and
            cond4_price_between and
            cond5_angle_ge_zero
        )
        
        # 부가 정보 계산
        price_to_tenkan_pct = ((price - tenkan) / tenkan) * 100 if tenkan > 0 else 0
        price_to_kijun_pct = ((price - kijun) / kijun) * 100 if kijun > 0 else 0
        kijun_tenkan_gap_pct = ((kijun - tenkan) / tenkan) * 100 if tenkan > 0 else 0
        dist_to_cloud_pct = ((cloud_bottom - price) / price) * 100 if price > 0 else 0
        
        return {
            'market': market_code,
            'korean_name': korean_name,
            'english_name': english_name,
            'price': price,
            'tenkan': tenkan,
            'kijun': kijun,
            'senkou_a': senkou_a,
            'senkou_b': senkou_b,
            'cloud_bottom': cloud_bottom,
            'tenkan_angle': round(tenkan_angle, 2),
            'rsi': round(curr['rsi'], 1) if not pd.isna(curr['rsi']) else 0.0,
            'price_to_tenkan_pct': round(price_to_tenkan_pct, 2),
            'price_to_kijun_pct': round(price_to_kijun_pct, 2),
            'kijun_tenkan_gap_pct': round(kijun_tenkan_gap_pct, 2),
            'dist_to_cloud_pct': round(dist_to_cloud_pct, 2),
            'is_bearish_cloud': is_bearish_cloud,
            'cond1_bearish_cloud': cond1_bearish_cloud,
            'cond2_below_cloud': cond2_below_cloud,
            'cond3_tenkan_below_kijun': cond3_tenkan_below_kijun,
            'cond4_price_between': cond4_price_between,
            'cond5_angle_ge_zero': cond5_angle_ge_zero,
            'is_matched': is_matched
        }
    except Exception as e:
        return None

def main():
    parser = argparse.ArgumentParser(description="일목균형표 음운 아래 (전환선 < 현재가 < 기준선) & 전환선각도 >= 0 분석기")
    parser.add_argument("--timeframe", type=str, default="60", help="봉 타임프레임 (예: 60, 24h, 15, 240. 기본값: 60)")
    parser.add_argument("--window", type=int, default=10, help="전환선 각도 계산용 봉 개수 (기본값: 10)")
    parser.add_argument("--delay", type=float, default=0.03, help="API 호출 간격(초)")
    
    args = parser.parse_args()
    
    print("=" * 100)
    print(f" [일목균형표 패턴 분석] 음운 아래 전환선-기준선 사이 등락 & 전환선 각도 >= 0° 코인 탐색")
    print(f" - 타임프레임: {args.timeframe}분/일봉")
    print(f" - 전환선 각도 측정 기간: 최근 {args.window}봉")
    print("=" * 100)
    
    markets = get_krw_markets()
    print(f"빗썸 KRW 마켓 총 {len(markets)}개 코인 분석 중...\n")
    
    matched_coins = []
    all_results = []
    
    for idx, m in enumerate(markets, 1):
        res = analyze_coin_cloud_bottom(m, timeframe=args.timeframe, angle_window=args.window)
        if res:
            all_results.append(res)
            if res['is_matched']:
                matched_coins.append(res)
        time.sleep(args.delay)
        
    print(f"\n분석 완료! 전체 {len(all_results)}개 코인 중 조건 만족 코인: {len(matched_coins)}개 포착\n")
    
    if matched_coins:
        df_matched = pd.DataFrame(matched_coins)
        # 전환선 각도 내림차순 정렬
        df_matched = df_matched.sort_values(by='tenkan_angle', ascending=False).reset_index(drop=True)
        
        print("=" * 110)
        print("★ [조건 만족 코인 목록] ★")
        print("조건:")
        print(" 1) 음운(선행스팬1 < 선행스팬2)")
        print(" 2) 음운 아래 (현재가, 전환선, 기준선 모두 구름대 하단 미만)")
        print(" 3) 전환선 < 기준선")
        print(" 4) 전환선 <= 현재가 <= 기준선")
        print(" 5) 전환선 각도 >= 0.0° (우상향/평행)")
        print("=" * 110)
        
        display_cols = ['market', 'korean_name', 'price', 'tenkan', 'kijun', 'cloud_bottom', 'tenkan_angle', 'rsi', 'dist_to_cloud_pct']
        
        # 포맷팅 출력
        print(f"{'마켓코드':<12} {'코인명':<14} {'현재가':<12} {'전환선':<12} {'기준선':<12} {'구름대하단':<12} {'전환선각도':<10} {'RSI':<6} {'구름이격(%)':<10}")
        print("-" * 110)
        for _, row in df_matched.iterrows():
            print(f"{row['market']:<12} {row['korean_name']:<14} {row['price']:<12,.2f} {row['tenkan']:<12,.2f} {row['kijun']:<12,.2f} {row['cloud_bottom']:<12,.2f} {row['tenkan_angle']:<+10.2f}° {row['rsi']:<6.1f} {row['dist_to_cloud_pct']:<+10.2f}%")
        print("=" * 110)
    else:
        print("현재 조건(음운 아래 + 전환선<현재가<기준선 + 전환선각도 >= 0°)을 완전히 만족하는 코인이 없습니다.")
        
        # 부분 만족 코인 Top 5 소개 (예: 전환선 < 현재가 < 기준선 및 음운 조건 만족하는 코인 중 각도가 높은 코인)
        partial_matched = [r for r in all_results if r['cond2_below_cloud'] and r['cond3_tenkan_below_kijun'] and r['cond4_price_between']]
        if partial_matched:
            df_part = pd.DataFrame(partial_matched).sort_values(by='tenkan_angle', ascending=False).head(5)
            print("\n[참고] '음운 아래 + 전환선 <= 현재가 <= 기준선' 만족 코인 (각도 제한 미적용 Top 5):")
            print(f"{'마켓코드':<12} {'코인명':<14} {'현재가':<12} {'전환선':<12} {'기준선':<12} {'전환선각도':<10} {'RSI':<6}")
            print("-" * 80)
            for _, row in df_part.iterrows():
                print(f"{row['market']:<12} {row['korean_name']:<14} {row['price']:<12,.2f} {row['tenkan']:<12,.2f} {row['kijun']:<12,.2f} {row['tenkan_angle']:<+10.2f}° {row['rsi']:<6.1f}")

if __name__ == "__main__":
    main()
