import requests
import numpy as np
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_krw_markets():
    url = "https://api.bithumb.com/v1/market/all"
    headers = {"accept": "application/json"}
    res = requests.get(url, headers=headers).json()
    return [{'market': m['market'], 'korean_name': m.get('korean_name', m['market']), 'english_name': m.get('english_name', m['market'])} for m in res if m['market'].startswith('KRW-')]

def calc_mid_point(high, low, window):
    return (high.rolling(window=window).max() + low.rolling(window=window).min()) / 2

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_macd(series, short=12, long=26, signal=9):
    ema_short = series.ewm(span=short, adjust=False).mean()
    ema_long = series.ewm(span=long, adjust=False).mean()
    macd = ema_short - ema_long
    macd_signal = macd.ewm(span=signal, adjust=False).mean()
    return macd, macd_signal, macd - macd_signal

def process_daily_candle_df(data):
    df = pd.DataFrame(data).iloc[::-1].reset_index(drop=True)
    for col in ['high_price', 'low_price', 'trade_price']:
        df[col] = df[col].astype(float)
        
    df['Close'] = df['trade_price']
    df['Volume'] = df['candle_acc_trade_volume'].astype(float) if 'candle_acc_trade_volume' in df.columns else 0.0
    df['Vol_MA20'] = df['Volume'].rolling(20).mean()
    
    df['ConversionLine'] = calc_mid_point(df['high_price'], df['low_price'], 10)
    df['BaseLine'] = calc_mid_point(df['high_price'], df['low_price'], 30)
    df['Span1'] = ((df['ConversionLine'] + df['BaseLine']) / 2).shift(30)
    df['Span2'] = calc_mid_point(df['high_price'], df['low_price'], 60).shift(30)
    df['RSI'] = calc_rsi(df['Close'], 14)
    df['MACD'], df['MACD_Signal'], df['MACD_Hist'] = calc_macd(df['Close'])
    
    # Date string YYYY-MM-DD
    if 'candle_date_time_kst' in df.columns:
        df['date'] = df['candle_date_time_kst'].astype(str).str[:10]
    else:
        df['date'] = ''
    return df

def get_btc_df(count=200):
    url = f"https://api.bithumb.com/v1/candles/days?market=KRW-BTC&count={count}"
    res = requests.get(url, headers={"accept": "application/json"}).json()
    df_btc = process_daily_candle_df(res)
    # Calculate BTC Kijun angle and slope
    df_btc['Kijun_Diff'] = df_btc['BaseLine'].diff()
    df_btc['Kijun_Pct'] = (df_btc['BaseLine'] - df_btc['BaseLine'].shift(1)) / df_btc['BaseLine'].shift(1) * 100
    df_btc['Kijun_Angle'] = np.degrees(np.arctan(df_btc['Kijun_Pct']))
    df_btc['Tenkan_ge_Kijun'] = df_btc['ConversionLine'] >= df_btc['BaseLine']
    return df_btc.set_index('date')

def run_simulation():
    btc_map = get_btc_df(200)
    markets = get_krw_markets()
    
    all_events = []
    def scan_coin(m):
        url = f"https://api.bithumb.com/v1/candles/days?market={m['market']}&count=200"
        try:
            res = requests.get(url, headers={"accept": "application/json"}, timeout=5)
            if res.status_code != 200: return []
            data = res.json()
            if not isinstance(data, list) or len(data) < 60: return []
            df = process_daily_candle_df(data)
            n = len(df)
            events = []
            for i in range(35, n - 3):
                kijun = df['BaseLine']
                close = df['Close']
                volume = df['Volume']
                vol_ma20 = df['Vol_MA20']
                
                curr_k = kijun.iloc[i]
                prev1_k = kijun.iloc[i-1]
                mid15_k = kijun.iloc[i-15]
                past30_k = kijun.iloc[i-30]
                
                if pd.isna(curr_k) or pd.isna(prev1_k) or pd.isna(mid15_k) or pd.isna(past30_k): continue

                cond1_down = (mid15_k < past30_k)
                flat_window = kijun.iloc[i-15 : i-2]
                if len(flat_window) < 5: continue
                flat_diff = (flat_window.max() - flat_window.min()) / flat_window.min() if flat_window.min() > 0 else 1.0
                cond2_flat = (flat_diff <= 0.012)
                cond3_turn = (curr_k > prev1_k) or (prev1_k > kijun.iloc[i-2])
                curr_p = close.iloc[i]
                cond4_price = (curr_p >= curr_k)
                
                if cond1_down and cond2_flat and cond3_turn and cond4_price:
                    date_str = df['date'].iloc[i]
                    cur_vol = volume.iloc[i]
                    avg_vol = vol_ma20.iloc[i] if not pd.isna(vol_ma20.iloc[i]) and vol_ma20.iloc[i] > 0 else 1.0
                    vol_ratio = cur_vol / avg_vol
                    
                    future_window = close.iloc[i+1 : min(i+21, n)]
                    if len(future_window) > 0:
                        ret_5d = ((close.iloc[min(i+5, n-1)] - curr_p) / curr_p) * 100
                        ret_10d = ((close.iloc[min(i+10, n-1)] - curr_p) / curr_p) * 100
                        ret_20d = ((close.iloc[min(i+20, n-1)] - curr_p) / curr_p) * 100
                        max_ret_20d = ((future_window.max() - curr_p) / curr_p) * 100
                    else:
                        ret_5d, ret_10d, ret_20d, max_ret_20d = 0.0, 0.0, 0.0, 0.0
                    
                    # BTC Condition Check at date_str
                    btc_info = btc_map.loc[date_str] if date_str in btc_map.index else None
                    btc_angle = btc_info['Kijun_Angle'] if btc_info is not None and not pd.isna(btc_info['Kijun_Angle']) else 0.0
                    btc_pct = btc_info['Kijun_Pct'] if btc_info is not None and not pd.isna(btc_info['Kijun_Pct']) else 0.0
                    btc_tenkan_ge_kijun = bool(btc_info['Tenkan_ge_Kijun']) if btc_info is not None and not pd.isna(btc_info['Tenkan_ge_Kijun']) else False
                    
                    events.append({
                        'market': m['market'],
                        'korean_name': m['korean_name'],
                        'event_date': date_str,
                        'vol_ratio': vol_ratio,
                        'ret_5d': ret_5d,
                        'ret_10d': ret_10d,
                        'ret_20d': ret_20d,
                        'max_ret_20d': max_ret_20d,
                        'is_win': max_ret_20d >= 5.0,
                        'btc_angle': btc_angle,
                        'btc_pct': btc_pct,
                        'btc_tenkan_ge_kijun': btc_tenkan_ge_kijun,
                        # Condition: BTC angle >= 2 deg AND BTC Tenkan >= Kijun
                        'cond_btc_angle_2deg': btc_angle >= 2.0 or btc_pct >= 2.0,
                        'cond_both': (btc_angle >= 2.0 or btc_pct >= 2.0) and btc_tenkan_ge_kijun
                    })
            return events
        except Exception as e:
            return []

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(scan_coin, m) for m in markets]
        for f in as_completed(futures):
            res = f.result()
            if res: all_events.extend(res)
            
    df_ev = pd.DataFrame(all_events)
    print(f"Total events captured: {len(df_ev)}")
    
    print("\n--- BTC Conditions Breakdown ---")
    print(f"BTC Tenkan >= Kijun count: {df_ev['btc_tenkan_ge_kijun'].sum()} / {len(df_ev)}")
    print(f"BTC Angle >= 2 deg (or Pct >= 2%) count: {df_ev['cond_btc_angle_2deg'].sum()} / {len(df_ev)}")
    print(f"BOTH conditions met count: {df_ev['cond_both'].sum()} / {len(df_ev)}")
    
    # Statistical comparison
    g_both = df_ev[df_ev['cond_both']]
    g_other = df_ev[~df_ev['cond_both']]
    
    g_tenkan = df_ev[df_ev['btc_tenkan_ge_kijun']]
    g_no_tenkan = df_ev[~df_ev['btc_tenkan_ge_kijun']]
    
    g_angle = df_ev[df_ev['cond_btc_angle_2deg']]
    g_no_angle = df_ev[~df_ev['cond_btc_angle_2deg']]

    def print_grp_stats(name, g):
        if len(g) == 0:
            print(f"[{name}] No cases")
            return
        win_rate = (g['is_win'].mean()) * 100
        avg_max_ret = g['max_ret_20d'].mean()
        avg_5d = g['ret_5d'].mean()
        avg_10d = g['ret_10d'].mean()
        avg_20d = g['ret_20d'].mean()
        print(f"[{name}] 건수: {len(g)}건 | 승률(+5%이상): {win_rate:.1f}% | 20일최고평균: {avg_max_ret:+.2f}% | 5일후: {avg_5d:+.2f}% | 10일후: {avg_10d:+.2f}% | 20일후: {avg_20d:+.2f}%")

    print("\n=== [1] 조건 충족 여부별 성과 비교 ===")
    print_grp_stats("전체 포착 사례", df_ev)
    print_grp_stats("BTC 조건 만족 (각도>=2도 AND 전환선>=기준선)", g_both)
    print_grp_stats("BTC 조건 미만족 (기타)", g_other)

    print("\n=== [2] 세부 조건별 성과 비교 ===")
    print_grp_stats("BTC 전환선 >= 기준선만 만족", g_tenkan)
    print_grp_stats("BTC 전환선 < 기준선", g_no_tenkan)
    print_grp_stats("BTC 기준선 각도 >= 2도만 만족", g_angle)
    print_grp_stats("BTC 기준선 각도 < 2도", g_no_angle)

if __name__ == "__main__":
    run_simulation()
