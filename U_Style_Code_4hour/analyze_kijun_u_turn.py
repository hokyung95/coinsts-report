"""
========================================================================================
 [모듈 명]: U_Style_Code_4hour/analyze_kijun_u_turn.py
 [구현 목적]:
   - 빗썸 240분봉(4시간봉, 240m Candles) 시계열 데이터를 수집하여
     240분봉 일목균형표 기준선(Kijun-sen, 30봉) 자체의 U자형 턴어라운드
     (1단계 하락 ➔ 2단계 수평 횡보/바닥 ➔ 3단계 우상향 전환)를 그리는 코인을 탐색합니다.
   - 최근 6봉 이내(최근 24시간 범위) 발생한 240분봉 U자 턴어라운드를 동적으로 스캔합니다.

 [240분봉 전용 일목 지표 파라미터]:
   - 240분봉 캔들: 1일 = 6개 봉
   - 전환선: 10봉 (40시간 고저 중간값)
   - 기준선: 30봉 (120시간 / 5일 고저 중간값)
   - 선행스팬2: 60봉 (240시간 / 10일 고저 중간값)
   - 선행 시프트: 30봉 선행

 [240분봉 기준선 U자형 턴어라운드 4대 조건]:
   1. 1단계 (하락 구간): 과거 30봉 전 대비 15봉 전 240분봉 기준선(30봉) 수치가 하향 추세였을 것.
   2. 2단계 (수평 구간): 최근 5~15봉 동안 기준선(30) 수치가 변하지 않거나 평행(Flat)을 유지.
   3. 3단계 (우상향 전환): 최근 1~3봉 이내에 수평이던 기준선의 수치가 상승 전환 (Kijun[t] > Kijun[t-1]).
   4. 현재가 조건: 현재 종가가 우상향으로 꺾인 240분봉 기준선 위에 위치 (Price >= Kijun).

 [사용 방법]:
   - 터미널 실행: python U_Style_Code_4hour/analyze_kijun_u_turn.py
========================================================================================
"""

import requests
import pandas as pd
import numpy as np
import time
import argparse
import os

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
    """지정 기간 동안의 (최고가 + 최저가) / 2 계산"""
    return (high.rolling(window=window).max() + low.rolling(window=window).min()) / 2

def calc_rsi(series, period=14):
    """RSI 지수 계산"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_macd(series, short=12, long=26, signal=9):
    """MACD 지수 계산"""
    ema_short = series.ewm(span=short, adjust=False).mean()
    ema_long = series.ewm(span=long, adjust=False).mean()
    macd = ema_short - ema_long
    macd_signal = macd.ewm(span=signal, adjust=False).mean()
    macd_hist = macd - macd_signal
    return macd, macd_signal, macd_hist

def check_kijun_u_turn_pattern_240m(df, max_lookback_bars=6, flat_tolerance_pct=0.010):
    """
    240분봉 200개 시계열 데이터를 바탕으로 최근 max_lookback_bars(최근 6봉, 약 24시간) 범위 내
    240분봉 기준선 U자형 턴어라운드 검증
    """
    n = len(df)
    if n < 60:
        return False, None
        
    kijun = df['BaseLine']  # 240분봉 30봉 기준선
    close = df['Close']
    
    # offset=0 (현재 240m 봉), offset=1 (1봉 전), ... offset=5 (5봉 전)
    for offset in range(max_lookback_bars):
        idx = n - 1 - offset
        if idx < 35:
            continue
            
        curr_k = kijun.iloc[idx]
        prev1_k = kijun.iloc[idx-1]
        prev2_k = kijun.iloc[idx-2]
        
        mid15_k = kijun.iloc[idx-15]
        past30_k = kijun.iloc[idx-30]
        
        if pd.isna(curr_k) or pd.isna(prev1_k) or pd.isna(mid15_k) or pd.isna(past30_k):
            continue

        # 1단계: 하락 구간 (30봉전 대비 15봉전 기준선 하향)
        cond1_downstream = (mid15_k < past30_k)
        
        # 2단계: 최근 수평(Flat) 바닥 (idx-15 ~ idx-2 구간 변동폭 <= 1.0%)
        flat_window = kijun.iloc[idx-15 : idx-2]
        if len(flat_window) < 5:
            continue
            
        flat_min = flat_window.min()
        flat_max = flat_window.max()
        flat_diff_pct = (flat_max - flat_min) / flat_min if flat_min > 0 else 1.0
        cond2_flat_bottom = (flat_diff_pct <= flat_tolerance_pct)
        
        # 3단계: 240분봉 기준선 상승 전환
        turn_up_recent1 = (curr_k > prev1_k)
        turn_up_recent2 = (prev1_k > prev2_k)
        cond3_turn_around = (turn_up_recent1 or turn_up_recent2)
        
        # 4단계: 주가 안착 (현재 종가 >= 240분봉 기준선)
        curr_price = close.iloc[-1]
        event_price = close.iloc[idx]
        cond4_price_above = (curr_price >= curr_k or event_price >= curr_k)
        
        if cond1_downstream and cond2_flat_bottom and cond3_turn_around and cond4_price_above:
            candle_time = str(df['candle_date_time_kst'].iloc[idx]).replace('T', ' ')[:16] if 'candle_date_time_kst' in df.columns else f"{offset}봉 전"
            day_desc = f"현재 240m봉" if offset == 0 else f"{offset}봉 전 ({candle_time})"
            return True, {
                'offset': offset,
                'candle_time': candle_time,
                'day_desc': day_desc,
                'curr_price': curr_price,
                'event_price': event_price,
                'curr_kijun': round(curr_k, 2),
                'rsi': round(df['RSI'].iloc[-1], 1) if not pd.isna(df['RSI'].iloc[-1]) else 0.0,
                'macd': round(df['MACD'].iloc[-1], 2) if not pd.isna(df['MACD'].iloc[-1]) else 0.0,
            }
            
    return False, None

def analyze_all_coins_4hour(lookback_bars=6, count=200):
    markets = get_krw_markets()
    print("=" * 90)
    print(f" [240분봉(4시간봉) 기준선(30) U자형 턴어라운드 코인 탐색]")
    print(f" 대상: 빗썸 원화(KRW) 마켓 총 {len(markets)}개 코인 | 탐색 범위: 최근 {lookback_bars}봉(24시간) 이내")
    print("=" * 90 + "\n")
    
    matched_list = []
    headers = {"accept": "application/json"}
    
    for m in markets:
        market_code = m['market']
        # 빗썸 240분봉 API 호출
        url = f"https://api.bithumb.com/v1/candles/minutes/240?market={market_code}&count={count}"
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and len(data) >= 60:
                    df = pd.DataFrame(data).iloc[::-1].reset_index(drop=True)
                    for col in ['high_price', 'low_price', 'trade_price']:
                        df[col] = df[col].astype(float)
                    df['Close'] = df['trade_price']
                    
                    # 240분봉 일목 지표 계산 (10, 30, 60, 30)
                    df['ConversionLine'] = calc_mid_point(df['high_price'], df['low_price'], 10)
                    df['BaseLine'] = calc_mid_point(df['high_price'], df['low_price'], 30)
                    df['RSI'] = calc_rsi(df['Close'], 14)
                    df['MACD'], _, _ = calc_macd(df['Close'])
                    
                    is_matched, info = check_kijun_u_turn_pattern_240m(df, max_lookback_bars=lookback_bars)
                    if is_matched:
                        info['market'] = market_code
                        info['korean_name'] = m['korean_name']
                        info['english_name'] = m['english_name']
                        matched_list.append(info)
                        print(f" ★ 240m 포착 [{info['day_desc']}]: {m['korean_name']}({market_code}) | 현재가: {info['curr_price']:,}원 | 240m기준선: {info['curr_kijun']:,}원")
        except Exception:
            pass
        time.sleep(0.03)
        
    print(f"\n[240분봉 스캔 완료] 총 {len(matched_list)}개 코인 포착!\n")
    return matched_list

if __name__ == "__main__":
    analyze_all_coins_4hour(lookback_bars=6)
