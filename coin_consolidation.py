import requests
import numpy as np
import pandas as pd
import time

def get_krw_markets():
    """빗썸에서 거래되는 모든 원화(KRW) 마켓 목록 및 한글명/영문명 조회"""
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

def check_ichimoku_consolidation(df, threshold_pct=0.02):
    """
    일목균형표 기준선, 전환선, 구름대 위에 있으면서
    지표선 근처(밀착)에 머무르는 종목/시점을 필터링하는 조건식

    Parameters:
    - df: DataFrame (OHLCV 및 일목균형표 계산 값이 포함된 데이터프레임)
          필요 컬럼: 'Close', 'ConversionLine' (전환선), 'BaseLine' (기준선),
                    'Span1' (선행스팬1), 'Span2' (선행스팬2)
    - threshold_pct: 지표선과의 밀착 허용 오차 범위 (예: 0.02 = 2% 이내)
    """
    # 1. 구름대 상단(Leading Span 중 더 높은 값) 계산
    cloud_top = np.maximum(df["Span1"], df["Span2"])

    # 2. 조건 A: 종가가 기준선, 전환선, 구름대 '위'에 위치
    above_conversion = df["Close"] >= df["ConversionLine"]
    above_base = df["Close"] >= df["BaseLine"]
    above_cloud = df["Close"] >= cloud_top

    is_above_all = above_conversion & above_base & above_cloud

    # 3. 조건 B: 급등하지 않고 기준선 혹은 전환선 근처에 밀착 (괴리율이 threshold_pct 이내)
    dist_from_base = np.abs(df["Close"] - df["BaseLine"]) / df["BaseLine"]
    dist_from_conversion = (
        np.abs(df["Close"] - df["ConversionLine"]) / df["ConversionLine"]
    )

    is_near_lines = (dist_from_base <= threshold_pct) | (
        dist_from_conversion <= threshold_pct
    )

    # 4. 조건 C: 최근 급등(예: 당일 장대양봉 또는 단기간 과도한 상승) 제외
    pct_change = df["Close"].pct_change()
    is_not_spiking = pct_change <= 0.05

    # 최종 조건 결합
    df["Condition"] = is_above_all & is_near_lines & is_not_spiking
    df["DistBase_Pct"] = dist_from_base * 100
    df["DistConversion_Pct"] = dist_from_conversion * 100

    return df

def analyze_all_coins_consolidation(threshold_pct=0.02, count=200, delay=0.04, max_coins=None):
    """
    빗썸 전체 원화 코인을 수집 및 분석하여
    일목균형표 지표선 밀착 횡보/정배열 조건(Check Ichimoku Consolidation)에 부합하는 코인 포착
    """
    markets = get_krw_markets()
    if max_coins:
        markets = markets[:max_coins]

    print(f"총 {len(markets)}개 원화 마켓 코인 대상 [일목균형표 지표선 밀착/횡보 조건] 분석을 시작합니다...\n")
    results = []

    for idx, m in enumerate(markets, 1):
        market_code = m['market']
        korean_name = m['korean_name']
        english_name = m['english_name']
        
        url = f"https://api.bithumb.com/v1/candles/minutes/60?market={market_code}&count={count}"
        headers = {"accept": "application/json"}

        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and len(data) >= 60:
                    df = pd.DataFrame(data).iloc[::-1].reset_index(drop=True)

                    for col in ['high_price', 'low_price', 'trade_price']:
                        df[col] = df[col].astype(float)

                    df['Close'] = df['trade_price']
                    df['ConversionLine'] = calc_mid_point(df['high_price'], df['low_price'], 9)
                    df['BaseLine'] = calc_mid_point(df['high_price'], df['low_price'], 26)
                    df['Span1'] = ((df['ConversionLine'] + df['BaseLine']) / 2).shift(26)
                    df['Span2'] = calc_mid_point(df['high_price'], df['low_price'], 52).shift(26)

                    # 조건 분석 수행
                    df_analyzed = check_ichimoku_consolidation(df, threshold_pct=threshold_pct)
                    
                    # 가장 최근 봉(마지막 행) 조건 포착 여부 판단
                    last_row = df_analyzed.iloc[-1]
                    if last_row['Condition']:
                        results.append({
                            'market': market_code,
                            'korean_name': korean_name,
                            'english_name': english_name,
                            'close_price': last_row['Close'],
                            'conversion_line': round(last_row['ConversionLine'], 2),
                            'base_line': round(last_row['BaseLine'], 2),
                            'dist_base_pct': round(last_row['DistBase_Pct'], 2),
                            'dist_conversion_pct': round(last_row['DistConversion_Pct'], 2),
                            'time_kst': last_row.get('candle_date_time_kst', '')
                        })
                        print(f"[{idx}/{len(markets)}] ★ 포착! {korean_name}({english_name}) - 종가: {last_row['Close']:,}원 (기준선괴리: {last_row['DistBase_Pct']:.2f}%, 전환선괴리: {last_row['DistConversion_Pct']:.2f}%)")
                    else:
                        print(f"[{idx}/{len(markets)}] {korean_name}({market_code}) 미부합")
        except Exception as e:
            print(f"[{idx}/{len(markets)}] {korean_name}({market_code}) 에러: {e}")

        time.sleep(delay)

    df_res = pd.DataFrame(results)
    return df_res

if __name__ == "__main__":
    # 허용 괴리율 2% (0.02) 기준 빗썸 전체 코인 분석
    df_found = analyze_all_coins_consolidation(threshold_pct=0.02, delay=0.04)

    print("\n" + "="*95)
    print(" [일목균형표 지표선 밀착/상승 횡보 포착 코인 결과 요약] ")
    print("="*95)
    print(f"포착 코인 개수: {len(df_found)}개\n")

    if not df_found.empty:
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', 1000)
        print(df_found[['market', 'korean_name', 'english_name', 'close_price', 'conversion_line', 'base_line', 'dist_conversion_pct', 'dist_base_pct']].to_string(index=False))
    else:
        print("현재 일목 지표선 2% 이내에 밀착하면서 구름대/전환선/기준선 위에 위치한 코인이 없습니다.")