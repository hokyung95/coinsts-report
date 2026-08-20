import requests
import pandas as pd
import numpy as np
import time
import argparse
import sys

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
    """RSI (상대강도지수, Wilder's Smoothing) 계산"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def evaluate_coin_enhanced(market_code, korean_name, english_name, df, past_index=100, buy_amount_krw=100000, 
                          stop_loss_pct=-2.5, trailing_stop_pct=1.5, volume_filter=True):
    """
    [한글명 & 영문명 포함 분할 익절 전략 시뮬레이션]
    """
    if past_index < 20 or past_index >= len(df):
        return None

    past_trade = df['trade_price'].iloc[past_index-19 : past_index+1]
    past_tenkan = df['tenkan_sen'].iloc[past_index-19 : past_index+1]
    past_kijun = df['kijun_sen'].iloc[past_index-19 : past_index+1]
    
    tenkan_above_kijun_ratio = (past_tenkan > past_kijun).mean()
    trade_above_tenkan_ratio = (past_trade > past_tenkan).mean()
    
    is_tenkan_above_kijun_75 = tenkan_above_kijun_ratio >= 0.75
    is_trade_above_tenkan_80 = trade_above_tenkan_ratio >= 0.75
    
    macd_at_past = df['macd'].iloc[past_index]
    rsi_at_past = df['rsi'].iloc[past_index]
    
    is_macd_ge_0 = macd_at_past >= 0
    is_rsi_between_50_70 = (rsi_at_past >= 50) and (rsi_at_past <= 70)
    
    tenkan_slope, tenkan_angle = get_slope_and_angle(past_tenkan.dropna())
    kijun_slope, kijun_angle = get_slope_and_angle(past_kijun.dropna())
    
    is_tenkan_angle_ok = tenkan_angle <= 20.0
    is_kijun_angle_ok = kijun_angle <= 20.0
    
    is_vol_ok = True
    if volume_filter and 'candle_acc_trade_volume' in df.columns:
        vol_20_avg = df['candle_acc_trade_volume'].iloc[past_index-19 : past_index+1].mean()
        cur_vol = df['candle_acc_trade_volume'].iloc[past_index]
        is_vol_ok = cur_vol >= (vol_20_avg * 1.1) if vol_20_avg > 0 else True

    signal_triggered = (
        is_tenkan_above_kijun_75 and 
        is_trade_above_tenkan_80 and 
        is_macd_ge_0 and 
        is_rsi_between_50_70 and
        is_tenkan_angle_ok and
        is_kijun_angle_ok and
        is_vol_ok
    )
    
    buy_price = df['trade_price'].iloc[past_index]
    time_at_past = df['candle_date_time_kst'].iloc[past_index]
    
    if signal_triggered:
        half_amount = buy_amount_krw * 0.5
        pos1_qty = half_amount / buy_price
        pos2_qty = half_amount / buy_price
        
        sold_part1 = False
        sold_part2 = False
        
        part1_sell_price = buy_price
        part2_sell_price = buy_price
        part1_reason = ""
        part2_reason = ""
        
        highest_price = buy_price
        tenkan_below_count = 0
        holding_hours = 0
        
        for i in range(past_index + 1, len(df)):
            cur_price = df['trade_price'].iloc[i]
            cur_rsi = df['rsi'].iloc[i]
            cur_tenkan = df['tenkan_sen'].iloc[i]
            cur_kijun = df['kijun_sen'].iloc[i]
            
            if cur_price > highest_price:
                highest_price = cur_price
                
            cur_return_pct = ((cur_price - buy_price) / buy_price) * 100
            pullback_from_high_pct = ((highest_price - cur_price) / highest_price) * 100 if highest_price > 0 else 0
            
            # 1. 1차 익절 (RSI >= 65 -> 50% 분할 매도)
            if not sold_part1 and cur_rsi >= 65:
                sold_part1 = True
                part1_sell_price = cur_price
                part1_reason = "1차익절(RSI>=65)"
                
            # 2. 2차 익절 (RSI >= 73 -> 잔여 50% 익절 매도)
            if sold_part1 and not sold_part2 and cur_rsi >= 75:
                sold_part2 = True
                part2_sell_price = cur_price
                part2_reason = "2차익절(RSI>=73)"
                
            # 3. 손절선 체크 (-2.5% 손절)
            if cur_return_pct <= stop_loss_pct:
                if not sold_part1:
                    sold_part1 = True
                    part1_sell_price = cur_price
                    part1_reason = f"손절({stop_loss_pct}%)"
                if not sold_part2:
                    sold_part2 = True
                    part2_sell_price = cur_price
                    part2_reason = f"손절({stop_loss_pct}%)"
                    
            # 4. 트레일링 스탑 (고점 대비 1.5% 하락 시 남은 물량 청산)
            if highest_price > buy_price * 1.02 and pullback_from_high_pct >= trailing_stop_pct:
                if not sold_part1:
                    sold_part1 = True
                    part1_sell_price = cur_price
                    part1_reason = f"트레일링(-{trailing_stop_pct}%)"
                if not sold_part2:
                    sold_part2 = True
                    part2_sell_price = cur_price
                    part2_reason = f"트레일링(-{trailing_stop_pct}%)"

            # 5. 일목 이탈 (전환선 < 기준선 2봉 연속)
            if cur_tenkan < cur_kijun:
                tenkan_below_count += 1
            else:
                tenkan_below_count = 0
                
            if tenkan_below_count >= 2:
                if not sold_part1:
                    sold_part1 = True
                    part1_sell_price = cur_price
                    part1_reason = "이탈청산(전환<기준 2봉)"
                if not sold_part2:
                    sold_part2 = True
                    part2_sell_price = cur_price
                    part2_reason = "이탈청산(전환<기준 2봉)"

            if sold_part1 and sold_part2:
                holding_hours = i - past_index
                break
                
        if not sold_part1:
            sold_part1 = True
            part1_sell_price = df['trade_price'].iloc[-1]
            part1_reason = "만료청산"
        if not sold_part2:
            sold_part2 = True
            part2_sell_price = df['trade_price'].iloc[-1]
            part2_reason = "만료청산"
            
        if holding_hours == 0:
            holding_hours = len(df) - 1 - past_index
            
        sell_val_part1 = pos1_qty * part1_sell_price
        sell_val_part2 = pos2_qty * part2_sell_price
        total_sell_val = sell_val_part1 + sell_val_part2
        
        profit_krw = total_sell_val - buy_amount_krw
        profit_pct = (profit_krw / buy_amount_krw) * 100
        exit_reason = f"1차:{part1_reason} / 2차:{part2_reason}"
        sell_price_avg = (part1_sell_price + part2_sell_price) / 2
    else:
        sell_price_avg = buy_price
        total_sell_val = 0
        profit_krw = 0
        profit_pct = 0.0
        holding_hours = 0
        exit_reason = ""
        
    return {
        'market': market_code,
        'korean_name': korean_name,
        'english_name': english_name,
        'past_index': past_index,
        'time_at_past': time_at_past,
        'buy_price': buy_price,
        'tenkan_angle': round(tenkan_angle, 2),
        'kijun_angle': round(kijun_angle, 2),
        'macd_at_past': round(macd_at_past, 4) if not np.isnan(macd_at_past) else None,
        'rsi_at_past': round(rsi_at_past, 2) if not np.isnan(rsi_at_past) else None,
        'signal_triggered': signal_triggered,
        'buy_amount_krw': buy_amount_krw if signal_triggered else 0,
        'sell_price': round(sell_price_avg, 2),
        'holding_hours': holding_hours,
        'exit_reason': exit_reason,
        'sell_value_krw': round(total_sell_val, 0),
        'profit_krw': round(profit_krw, 0),
        'profit_pct': round(profit_pct, 2)
    }

def run_batch_simulation(start_idx=50, end_idx=180, step=10, max_coins=None, buy_amount_krw=100000, delay=0.03):
    """50번째부터 180번째까지 파라미터 인덱스를 구간별로 일괄 시뮬레이션 분석하는 함수"""
    markets = get_krw_markets()
    if max_coins:
        markets = markets[:max_coins]
        
    print(f"[1/2] 총 {len(markets)}개 원화 마켓 코인 시계열 데이터 프리패치(수집) 중...")
    coin_dfs = {}
    
    for idx, m in enumerate(markets, 1):
        market_code = m['market']
        korean_name = m.get('korean_name', market_code)
        english_name = m.get('english_name', market_code)
        url = f"https://api.bithumb.com/v1/candles/minutes/60?market={market_code}&count=200"
        headers = {"accept": "application/json"}
        
        try:
            res = requests.get(url, headers=headers)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and len(data) >= 200:
                    df = pd.DataFrame(data).iloc[::-1].reset_index(drop=True)
                    for col in ['high_price', 'low_price', 'trade_price']:
                        df[col] = df[col].astype(float)
                    if 'candle_acc_trade_volume' in df.columns:
                        df['candle_acc_trade_volume'] = df['candle_acc_trade_volume'].astype(float)
                        
                    df['tenkan_sen'] = calc_mid_point(df['high_price'], df['low_price'], 9)
                    df['kijun_sen'] = calc_mid_point(df['high_price'], df['low_price'], 26)
                    df['macd'], df['macd_signal'], df['macd_hist'] = calc_macd(df['trade_price'])
                    df['rsi'] = calc_rsi(df['trade_price'], period=14)
                    
                    coin_dfs[market_code] = (korean_name, english_name, df)
        except Exception as e:
            pass
            
        time.sleep(delay)
        
    print(f"데이터 수집 완료: 총 {len(coin_dfs)}개 코인 메모리 로드 (한글명/영문명 표기 반영).\n")
    print(f"[2/2] 인덱스 {start_idx} ~ {end_idx} (간격: {step}) 일괄 시뮬레이션 연산 실행 중...\n")
    
    summary_list = []
    
    indices = list(range(start_idx, end_idx + 1, step))
    for p_idx in indices:
        results_for_idx = []
        for m_code, (k_name, eng_name, df) in coin_dfs.items():
            res = evaluate_coin_enhanced(m_code, k_name, eng_name, df, past_index=p_idx, buy_amount_krw=buy_amount_krw)
            if res:
                results_for_idx.append(res)
                
        df_idx = pd.DataFrame(results_for_idx)
        triggered = df_idx[df_idx['signal_triggered']]
        n_triggered = len(triggered)
        
        if n_triggered > 0:
            tot_buy = n_triggered * buy_amount_krw
            tot_sell = triggered['sell_value_krw'].sum()
            tot_profit = tot_sell - tot_buy
            roi = (tot_profit / tot_buy) * 100
            win_rate = (triggered['profit_krw'] > 0).mean() * 100
            coin_names_str = ", ".join([f"{k}({e})" for k, e in zip(triggered['korean_name'], triggered['english_name'])])
        else:
            tot_buy = 0
            tot_sell = 0
            tot_profit = 0
            roi = 0.0
            win_rate = 0.0
            coin_names_str = "-"
            
        summary_list.append({
            'past_index': p_idx,
            'rem_bars': 200 - p_idx - 1,
            'triggered_coins': n_triggered,
            'coin_names': coin_names_str,
            'total_buy_krw': tot_buy,
            'total_sell_krw': tot_sell,
            'net_profit_krw': tot_profit,
            'roi_pct': round(roi, 2),
            'win_rate_pct': round(win_rate, 1)
        })
        
        print(f"▶ 인덱스 [{p_idx:3d}] - 포착({n_triggered:2d}개): [{coin_names_str}] | 총 순수익: {tot_profit:+10,.0f}원 | ROI: {roi:+6.2f}% | 승률: {win_rate:5.1f}%")
        
    df_summary = pd.DataFrame(summary_list)
    return df_summary

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="빗썸 코인 전략 시뮬레이터 (포착 코인 한글/영문명 표기)")
    parser.add_argument("index", type=int, nargs="?", default=None, help="단일 과거 인덱스 지정 (예: 100)")
    parser.add_argument("--batch", action="store_true", help="50~180 인덱스 일괄 시뮬레이션 실행")
    parser.add_argument("--start", type=int, default=50, help="일괄 시뮬레이션 시작 인덱스 (기본값: 50)")
    parser.add_argument("--end", type=int, default=180, help="일괄 시뮬레이션 종료 인덱스 (기본값: 180)")
    parser.add_argument("--step", type=int, default=10, help="일괄 시뮬레이션 간격 (기본값: 10)")
    parser.add_argument("--amount", type=int, default=100000, help="포착 코인당 매수 금액(원) (기본값: 100000)")
    parser.add_argument("--max_coins", type=int, default=None, help="분석할 마켓 코인 최대 수 (기본값: 전체)")
    
    args = parser.parse_args()
    
    start_i = args.start
    end_i = args.end
    step_i = args.step
    
    df_batch = run_batch_simulation(
        start_idx=start_i, 
        end_idx=end_i, 
        step=step_i, 
        max_coins=args.max_coins, 
        buy_amount_krw=args.amount
    )
    
    print("\n" + "="*120)
    print(f" [시뮬레이션 성과 및 포착 코인명 목록 (한글/영문) - 인덱스 {start_i} ~ {end_i}] ")
    print("="*120)
    pd.set_option('display.max_colwidth', None)
    print(df_batch[['past_index', 'rem_bars', 'triggered_coins', 'coin_names', 'total_buy_krw', 'net_profit_krw', 'roi_pct', 'win_rate_pct']].to_string(index=False))
    
    if not df_batch[df_batch['triggered_coins'] > 0].empty:
        best_row = df_batch.loc[df_batch['roi_pct'].idxmax()]
        print("\n" + "*"*80)
        print(f"★ 최고 성과 인덱스: [{best_row['past_index']}번째 봉]")
        print(f"  - 총 포착 코인 수: {best_row['triggered_coins']}개")
        # print(f"  - 포착 코인 목록: {best_row['coin_names']}")
        print(f"  - 총 투입 금액: {best_row['total_buy_krw']:,}원")
        print(f"  - 총 순수익금: {best_row['net_profit_krw']:+,}원")
        print(f"  - 전략 ROI: {best_row['roi_pct']:+.2f}%")
        print(f"  - 매매 승률: {best_row['win_rate_pct']}%")
        print("*"*80)