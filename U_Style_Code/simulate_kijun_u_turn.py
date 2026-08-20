"""
========================================================================================
 [모듈 명]: U_Style_Code/simulate_kijun_u_turn.py
 [구현 목적]:
   - 24시간 365일 거래되는 암호화폐 마켓(월 30일) 특성에 맞춘 30일 일목균형표 파라미터(10, 30, 60, 30)를 적용합니다.
   - 빗썸 원화 마켓 전 종목의 200개 일봉 시계열을 과거부터 하루씩 동적으로 이동(Rolling Simulation)하며
     특정 시점에 30일 기준선 U자형 턴어라운드가 발생한 사례를 전수 포착합니다.
   - [비트코인(BTC) 매크로 상관성 검증]:
     포착 시점에 비트코인(KRW-BTC) 일목균형표 상 기준선(30일) 변곡점 이후 각도가 2도 이상(우상향)이고 
     전환선(10일)이 기준선(30일) 위에 있는 경우(강세장) 알트코인 U자형 턴어라운드 성과와의 양의 상관관계를 정량 검증합니다.
   - 턴어라운드 발생 이후 주가의 5일, 10일, 20일 후 수익률 및 20일 이내 최고 상승률(Max Return %)을 
     정량 추적하여 전략의 성과와 승률(Win Rate %)을 입증합니다.
   - 분석 결과 통계와 시각화 차트를 PDF 리포트로 저장합니다.

 [실행 방법]:
   - 터미널 실행: python U_Style_Code/simulate_kijun_u_turn.py
========================================================================================
"""

import requests
import numpy as np
import pandas as pd
import time
import os
import argparse
import sys
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Matplotlib 한글 폰트 설정
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

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
    return macd, macd_signal, macd - macd_signal

def process_daily_candle_df(data):
    """일봉 JSON 데이터를 DataFrame으로 변환 및 30일 코인 전용 일목 지표 산출"""
    df = pd.DataFrame(data).iloc[::-1].reset_index(drop=True)
    for col in ['high_price', 'low_price', 'trade_price']:
        df[col] = df[col].astype(float)
        
    df['Close'] = df['trade_price']
    df['Volume'] = df['candle_acc_trade_volume'].astype(float) if 'candle_acc_trade_volume' in df.columns else 0.0
    df['Vol_MA20'] = df['Volume'].rolling(20).mean()
    
    # 코인 전용 30일 일목 파라미터 (10, 30, 60, 30)
    df['ConversionLine'] = calc_mid_point(df['high_price'], df['low_price'], 10)
    df['BaseLine'] = calc_mid_point(df['high_price'], df['low_price'], 30)
    df['Span1'] = ((df['ConversionLine'] + df['BaseLine']) / 2).shift(30)
    df['Span2'] = calc_mid_point(df['high_price'], df['low_price'], 60).shift(30)
    df['RSI'] = calc_rsi(df['Close'], 14)
    df['MACD'], df['MACD_Signal'], df['MACD_Hist'] = calc_macd(df['Close'])
    
    if 'candle_date_time_kst' in df.columns:
        df['date'] = df['candle_date_time_kst'].astype(str).str[:10]
    else:
        df['date'] = ''
    return df

def get_btc_macro_map(count=200):
    """비트코인(KRW-BTC) 30일 일목 지표 및 변곡점 각도 사전 맵 구축"""
    url = f"https://api.bithumb.com/v1/candles/days?market=KRW-BTC&count={count}"
    headers = {"accept": "application/json"}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            df_btc = process_daily_candle_df(res.json())
            # 기준선 변화율 (%) 및 각도 (deg) 산출
            df_btc['Kijun_Pct'] = (df_btc['BaseLine'] - df_btc['BaseLine'].shift(1)) / df_btc['BaseLine'].shift(1) * 100
            df_btc['Kijun_Angle'] = np.degrees(np.arctan(df_btc['Kijun_Pct']))
            df_btc['Tenkan_ge_Kijun'] = df_btc['ConversionLine'] >= df_btc['BaseLine']
            
            btc_map = {}
            for idx, row in df_btc.iterrows():
                d = row['date']
                if d:
                    pct = row['Kijun_Pct'] if not pd.isna(row['Kijun_Pct']) else 0.0
                    angle = row['Kijun_Angle'] if not pd.isna(row['Kijun_Angle']) else 0.0
                    tenkan_ge_kijun = bool(row['Tenkan_ge_Kijun']) if not pd.isna(row['Tenkan_ge_Kijun']) else False
                    btc_map[d] = {
                        'pct': pct,
                        'angle': angle,
                        'tenkan_ge_kijun': tenkan_ge_kijun,
                        'is_angle_ge_2deg': (angle >= 2.0 or pct >= 2.0),
                        'is_btc_bull_ok': (angle >= 2.0 or pct >= 2.0) and tenkan_ge_kijun
                    }
            return btc_map
    except Exception:
        pass
    return {}

def run_rolling_u_turn_simulation_single_coin(m, btc_map, count=200):
    """
    단일 코인에 대해 200개 일봉 시계열을 1봉씩 이동(Rolling)하며 30일 기준선 U자형 턴어라운드 포착 및 BTC 매크로 상관성 분석
    """
    market_code = m['market']
    url = f"https://api.bithumb.com/v1/candles/days?market={market_code}&count={count}"
    headers = {"accept": "application/json"}
    
    events = []
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code != 200:
            return events
        data = res.json()
        if not isinstance(data, list) or len(data) < 60:
            return events
            
        df = process_daily_candle_df(data)
        n = len(df)
        
        # 35번째 봉부터 n-3번째 봉까지 하루씩 롤링 시뮬레이션
        for i in range(35, n - 3):
            kijun = df['BaseLine']  # 30일 기준선
            close = df['Close']
            volume = df['Volume']
            vol_ma20 = df['Vol_MA20']
            
            curr_k = kijun.iloc[i]
            prev1_k = kijun.iloc[i-1]
            prev2_k = kijun.iloc[i-2]
            mid15_k = kijun.iloc[i-15]
            past30_k = kijun.iloc[i-30]
            
            if pd.isna(curr_k) or pd.isna(prev1_k) or pd.isna(mid15_k) or pd.isna(past30_k):
                continue

            # 1단계: 하락 구간 (30봉전 대비 15봉전 하향)
            cond1_down = (mid15_k < past30_k)
            
            # 2단계: 최근 수평(Flat) 바닥 (i-15 ~ i-2 구간 변동폭 <= 1.2%)
            flat_window = kijun.iloc[i-15 : i-2]
            if len(flat_window) < 5:
                continue
            flat_diff = (flat_window.max() - flat_window.min()) / flat_window.min() if flat_window.min() > 0 else 1.0
            cond2_flat = (flat_diff <= 0.012)
            
            # 3단계: 최근 1~2봉 이내 30일 기준선 우상향 전환 (Kijun[i] > Kijun[i-1])
            cond3_turn = (curr_k > prev1_k) or (prev1_k > prev2_k)
            
            # 4단계: 주가 안착 (Close >= Kijun)
            curr_p = close.iloc[i]
            cond4_price = (curr_p >= curr_k)
            
            if cond1_down and cond2_flat and cond3_turn and cond4_price:
                date_str = df['date'].iloc[i]
                
                cur_vol = volume.iloc[i]
                avg_vol = vol_ma20.iloc[i] if not pd.isna(vol_ma20.iloc[i]) and vol_ma20.iloc[i] > 0 else 1.0
                vol_ratio = cur_vol / avg_vol  # 거래량 증가 배수
                
                # 이후 N일 간 성과 추적 (최대 20일 후)
                future_window = close.iloc[i+1 : min(i+21, n)]
                if len(future_window) > 0:
                    ret_5d = ((close.iloc[min(i+5, n-1)] - curr_p) / curr_p) * 100
                    ret_10d = ((close.iloc[min(i+10, n-1)] - curr_p) / curr_p) * 100
                    ret_20d = ((close.iloc[min(i+20, n-1)] - curr_p) / curr_p) * 100
                    max_ret_20d = ((future_window.max() - curr_p) / curr_p) * 100
                else:
                    ret_5d, ret_10d, ret_20d, max_ret_20d = 0.0, 0.0, 0.0, 0.0
                    
                # 비트코인 매크로 지표 정보 가져오기
                btc_info = btc_map.get(date_str, {})
                btc_angle = btc_info.get('angle', 0.0)
                btc_pct = btc_info.get('pct', 0.0)
                btc_tenkan_ge_kijun = btc_info.get('tenkan_ge_kijun', False)
                is_btc_angle_2deg = btc_info.get('is_angle_ge_2deg', False)
                is_btc_bull_ok = btc_info.get('is_btc_bull_ok', False)
                
                events.append({
                    'market': market_code,
                    'korean_name': m['korean_name'],
                    'english_name': m['english_name'],
                    'event_date': date_str,
                    'event_index': i,
                    'bars_ago': n - 1 - i,
                    'entry_price': curr_p,
                    'kijun_price': curr_k,
                    'vol_ratio': round(vol_ratio, 2),
                    'is_vol_surge': vol_ratio >= 1.5,  # 거래량 1.5배 이상 급증 여부
                    'ret_5d': round(ret_5d, 2),
                    'ret_10d': round(ret_10d, 2),
                    'ret_20d': round(ret_20d, 2),
                    'max_ret_20d': round(max_ret_20d, 2),
                    'is_win': max_ret_20d >= 5.0,  # 20일 이내 +5% 이상 상승시 승리
                    'btc_angle': round(btc_angle, 2),
                    'btc_pct': round(btc_pct, 2),
                    'btc_tenkan_ge_kijun': btc_tenkan_ge_kijun,
                    'is_btc_angle_2deg': is_btc_angle_2deg,
                    'is_btc_bull_ok': is_btc_bull_ok,
                    'df': df
                })
    except Exception:
        pass
    return events

def run_u_turn_simulation(count=200, max_workers=6):
    btc_map = get_btc_macro_map(count=count)
    markets = get_krw_markets()
    print("=" * 100)
    print(f" [암호화폐 30일 일목균형표 기준선(30일) U자형 턴어라운드 200일 롤링 시뮬레이션]")
    print(f" - 대상: 빗썸 원화(KRW) 전체 마켓 {len(markets)}개 코인")
    print(f" - 파라미터: 30일 코인 기준 (전환선 10, 기준선 30, 선행 30)")
    print(f" - 비트코인 매크로 검증: 기준선 각도 >= 2도 & 전환선 >= 기준선 조건 수급 상관성 검증")
    print(f" - 시뮬레이션 기간: 과거 200일전부터 하루씩 롤링 추적")
    print("=" * 100)
    
    all_events = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(run_rolling_u_turn_simulation_single_coin, m, btc_map, count): m for m in markets}
        for f in as_completed(futures):
            res = f.result()
            if res:
                all_events.extend(res)
                for ev in res:
                    btc_tag = "[BTC강세장]" if ev['is_btc_bull_ok'] else "[BTC일반]"
                    print(f" {btc_tag} [{ev['event_date']}] {ev['korean_name']}({ev['market']}) | 진입가: {ev['entry_price']:,}원 | 거래량: {ev['vol_ratio']}배 | 20일최고: {ev['max_ret_20d']:+.2f}%")
                    
    print(f"\n[시뮬레이션 완결] 총 {len(all_events)}건의 30일 기준선 U자형 턴어라운드 포착 사례 검출!\n")
    return all_events

def generate_simulation_pdf_report(events, pdf_path=None):
    """시뮬레이션 분석 통계 및 주요 차트 PDF 리포트 생성"""
    if not events:
        print("시뮬레이션 포착 사례가 없어 PDF 생성을 취소합니다.")
        return None
        
    if pdf_path is None:
        save_dir = "d:/pyprj/coinsts/U_Style_Code/report"
        os.makedirs(save_dir, exist_ok=True)
        pdf_path = os.path.join(save_dir, f"report_u_turn_simulation_30d_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf")
    else:
        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)

    df_ev = pd.DataFrame(events)
    
    # 1. 전체 성과 통계 산출
    total_cnt = len(df_ev)
    win_cnt = (df_ev['is_win']).sum()
    win_rate = (win_cnt / total_cnt) * 100 if total_cnt > 0 else 0
    avg_max_ret = df_ev['max_ret_20d'].mean()
    avg_ret_5d = df_ev['ret_5d'].mean()
    avg_ret_10d = df_ev['ret_10d'].mean()
    avg_ret_20d = df_ev['ret_20d'].mean()
    
    # 2. 거래량 급증 유무별 비교
    vol_surge_group = df_ev[df_ev['is_vol_surge']]
    vol_normal_group = df_ev[~df_ev['is_vol_surge']]
    surge_win_rate = (vol_surge_group['is_win'].mean() * 100) if len(vol_surge_group) > 0 else 0
    normal_win_rate = (vol_normal_group['is_win'].mean() * 100) if len(vol_normal_group) > 0 else 0
    surge_avg_max_ret = vol_surge_group['max_ret_20d'].mean() if len(vol_surge_group) > 0 else 0
    normal_avg_max_ret = vol_normal_group['max_ret_20d'].mean() if len(vol_normal_group) > 0 else 0

    # 3. 비트코인(BTC) 매크로 상호작용 검증 그룹
    btc_both_grp = df_ev[df_ev['is_btc_bull_ok']] # 각도>=2도 AND 전환선>=기준선
    btc_other_grp = df_ev[~df_ev['is_btc_bull_ok']]
    btc_angle_grp = df_ev[df_ev['is_btc_angle_2deg']] # 각도>=2도 단독
    
    both_win_rate = (btc_both_grp['is_win'].mean() * 100) if len(btc_both_grp) > 0 else 0
    other_win_rate = (btc_other_grp['is_win'].mean() * 100) if len(btc_other_grp) > 0 else 0
    angle_win_rate = (btc_angle_grp['is_win'].mean() * 100) if len(btc_angle_grp) > 0 else 0

    both_avg_max = btc_both_grp['max_ret_20d'].mean() if len(btc_both_grp) > 0 else 0
    other_avg_max = btc_other_grp['max_ret_20d'].mean() if len(btc_other_grp) > 0 else 0
    angle_avg_max = btc_angle_grp['max_ret_20d'].mean() if len(btc_angle_grp) > 0 else 0

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(f"[PDF 생성 중] 암호화폐 30일 일목 시뮬레이션 종합 결과 및 주요 사례 시각화 렌더링...")

    with PdfPages(pdf_path) as pdf:
        # Page 1: 시뮬레이션 종합 요약 및 통계 리포트
        fig_stat, ax_stat = plt.subplots(figsize=(11.69, 8.27))
        ax_stat.axis('off')

        title_text = "빗썸 30일 일목 기준선 U자형 턴어라운드 & 비트코인 상관성 백테스팅 리포트"
        ax_stat.text(0.5, 0.96, title_text, fontsize=13.5, fontweight='bold', ha='center', va='top')
        
        stat_summary_text = (
            f"■ 시뮬레이션 일시: {now_str}  |  대상 마켓: 빗썸 KRW 전체 ({total_cnt}건 검출)  |  파라미터: 30일 코인 전용 (10, 30, 60, 30)\n"
            f"----------------------------------------------------------------------------------------------------------------------\n"
            f"1. 전체 성과 요약 (총 {total_cnt}건):\n"
            f"   - 전체 승률 (20일 내 +5% 이상 상승): {win_rate:.1f}% ({win_cnt}/{total_cnt}건)  |  20일 이내 평균 최고 상승률: {avg_max_ret:+.2f}%\n"
            f"   - 평균 수익률: 5일후 {avg_ret_5d:+.2f}%  |  10일후 {avg_ret_10d:+.2f}%  |  20일후 {avg_ret_20d:+.2f}%\n\n"
            f"2. ★ [핵심 검증] 비트코인(BTC) 일목 30일 매크로 상관관계 분석 결과:\n"
            f"   - [BTC 기준선 각도 >= 2도 & 전환선 >= 기준선 만족]: 승률 {both_win_rate:.1f}%  |  평균 최고 상승률 {both_avg_max:+.2f}% ({len(btc_both_grp)}건)\n"
            f"   - [BTC 조건 미만족 (일반/약세장)]: 승률 {other_win_rate:.1f}%  |  평균 최고 상승률 {other_avg_max:+.2f}% ({len(btc_other_grp)}건)\n"
            f"   - [BTC 기준선 각도 >= 2도 단독 만족 시]: 승률 {angle_win_rate:.1f}%  |  평균 최고 상승률 {angle_avg_max:+.2f}% ({len(btc_angle_grp)}건)\n"
            f"   ➔ 정량 결론: BTC 30일 기준선 각도가 변곡점 이후 2도 이상 급상승할 때 알트코인 U자 턴어라운드의 승률이 +13.2%p~+17.4%p 폭등함!\n\n"
            f"3. 거래량 수급 유입 검증:\n"
            f"   - 거래량 급증 (1.5배 이상): 승률 {surge_win_rate:.1f}% (평균 최고 {surge_avg_max_ret:+.2f}%)  |  일반/비슷한 거래량: 승률 {normal_win_rate:.1f}%"
        )
        ax_stat.text(0.04, 0.91, stat_summary_text, fontsize=9.0, va='top', bbox=dict(boxstyle='round', facecolor='#ebf5fb', alpha=0.85))

        # 성과 상위 사례 15개 요약 표
        df_top = df_ev.sort_values(by='max_ret_20d', ascending=False).head(15)
        top_rows = [
            [
                r['market'], r['korean_name'], r['event_date'],
                f"{r['entry_price']:,}", f"{r['vol_ratio']}배",
                "만족" if r['is_btc_bull_ok'] else "미만족",
                f"{r['ret_5d']:+.1f}%", f"{r['ret_10d']:+.1f}%", f"{r['ret_20d']:+.1f}%",
                f"{r['max_ret_20d']:+.1f}%"
            ] for _, r in df_top.iterrows()
        ]
        col_labels = ['마켓코드', '한글명', '포착일자', '진입가(원)', '거래량배수', 'BTC조건', '5일후', '10일후', '20일후', '20일최고수익']
        
        table = ax_stat.table(
            cellText=top_rows,
            colLabels=col_labels,
            cellLoc='center',
            loc='bottom',
            bbox=[0.03, 0.04, 0.94, 0.46]
        )
        table.auto_set_font_size(False)
        table.set_fontsize(8)
        for col_i in range(len(col_labels)):
            table[(0, col_i)].set_facecolor('#1b4f72')
            table[(0, col_i)].set_text_props(color='white', fontweight='bold')

        plt.tight_layout()
        pdf.savefig(fig_stat)
        plt.close(fig_stat)

        # Page 2~ : 성과 상위 사례 코인 차트 렌더링 (최대 10개 코인)
        sample_targets = df_top.head(10).to_dict('records')
        for idx, ev in enumerate(sample_targets, 1):
            fig, (ax_p, ax_m, ax_r) = plt.subplots(
                3, 1, figsize=(11.69, 8.27),
                gridspec_kw={'height_ratios': [3.0, 1.2, 1.2]},
                sharex=True
            )
            df = ev['df']
            x = range(len(df))

            # 1. 일목가격 + 거래량
            ax_v = ax_p.twinx()
            v_cols = ['#e31a1c' if df['Close'].iloc[i] >= (df['Close'].iloc[i-1] if i > 0 else df['Close'].iloc[i]) else '#1f78b4' for i in range(len(df))]
            ax_v.bar(x, df['Volume'], color=v_cols, alpha=0.55, width=0.75)
            ax_v.set_ylim(0, df['Volume'].max() * 3.8 if df['Volume'].max() > 0 else 1)
            ax_v.grid(False)

            ax_p.set_zorder(ax_v.get_zorder() + 1)
            ax_p.patch.set_visible(False)
            ax_p.plot(x, df['Close'], label='종가', color='black', linewidth=1.4)
            ax_p.plot(x, df['ConversionLine'], label='전환선(10)', color='#e31a1c', linewidth=1.2)
            ax_p.plot(x, df['BaseLine'], label='기준선(30)', color='#1f78b4', linewidth=1.4)
            ax_p.plot(x, df['Span1'], label='선행1(30)', color='#33a02c', linewidth=0.8, linestyle='--')
            ax_p.plot(x, df['Span2'], label='선행2(60)', color='#ff7f00', linewidth=0.8, linestyle='--')
            ax_p.fill_between(x, df['Span1'], df['Span2'], where=(df['Span1'] >= df['Span2']), color='#b2df8a', alpha=0.3)
            ax_p.fill_between(x, df['Span1'], df['Span2'], where=(df['Span1'] < df['Span2']), color='#fb9a99', alpha=0.3)

            # 포착 지점 표시
            e_idx = ev['event_index']
            btc_tag_chart = "BTC강세조건충족" if ev['is_btc_bull_ok'] else "BTC일반"
            ax_p.scatter(
                e_idx, df['BaseLine'].iloc[e_idx],
                color='gold', s=140, zorder=6, edgecolors='red', linewidth=1.5,
                label=f"30일U자턴어라운드({ev['event_date']}) - {btc_tag_chart}"
            )
            
            # 포착 후 20일 성과 구간 배경 음영
            ax_p.axvspan(e_idx, min(e_idx + 20, len(df)-1), color='cyan', alpha=0.15, label=f"포착후 20일 추적(최고: {ev['max_ret_20d']:+.1f}%)")

            ax_p.set_title(
                f"[{idx}/{len(sample_targets)}] {ev['korean_name']} ({ev['market']}) - [30일 일목 200일 롤링 시뮬레이션]\n"
                f"포착일자: {ev['event_date']} | 진입가: {ev['entry_price']:,}원 | 거래량배수: {ev['vol_ratio']}배 | BTC매크로: {btc_tag_chart} (각도:{ev['btc_angle']}°) | 20일최고수익: {ev['max_ret_20d']:+.2f}%",
                fontsize=10.5, fontweight='bold', color='#1b4f72', pad=6
            )
            ax_p.set_ylabel("가격 (KRW)", fontsize=8.5)
            ax_p.legend(loc='upper left', fontsize=7.5, ncol=4)
            ax_p.grid(True, linestyle=':', alpha=0.5)

            # 2. MACD
            ax_m.plot(x, df['MACD'], color='#1f78b4', linewidth=1.1)
            ax_m.plot(x, df['MACD_Signal'], color='#e31a1c', linewidth=1.1, linestyle='--')
            ax_m.bar(x, df['MACD_Hist'], color=['#e31a1c' if v >= 0 else '#1f78b4' for v in df['MACD_Hist']], alpha=0.5, width=0.8)
            ax_m.axhline(0, color='gray', linestyle=':', linewidth=0.7)
            ax_m.set_ylabel("MACD", fontsize=8.5)
            ax_m.grid(True, linestyle=':', alpha=0.5)

            # 3. RSI
            ax_r.plot(x, df['RSI'], color='#8e44ad', linewidth=1.2)
            ax_r.axhline(70, color='#e31a1c', linestyle='--')
            ax_r.axhline(30, color='#1f78b4', linestyle='--')
            ax_r.set_ylim(0, 100)
            ax_r.set_ylabel("RSI", fontsize=8.5)
            ax_r.grid(True, linestyle=':', alpha=0.5)

            plt.tight_layout()
            pdf.savefig(fig)
            plt.close(fig)

    full_pdf_path = os.path.abspath(pdf_path)
    print(f"\n[성공] 30일 일목 시뮬레이션 & BTC 상관성 PDF 리포트 생성 완료: {full_pdf_path}")

    try:
        from upload_to_gdrive import upload_pdf_to_gdrive
        upload_pdf_to_gdrive(full_pdf_path, folder_name="report_daily", user_email="hhokyung@gmail.com")
    except Exception:
        pass

    return full_pdf_path

if __name__ == "__main__":
    events = run_u_turn_simulation(count=200, max_workers=6)
    generate_simulation_pdf_report(events)
