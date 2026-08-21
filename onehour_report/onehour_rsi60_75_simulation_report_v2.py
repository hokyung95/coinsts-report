"""
========================================================================================
 [모듈 명]: onehour_report/onehour_rsi60_75_simulation_report_v2.py
 [구현 목적]:
   - 빗썸 거래 전체 원화(KRW) 마켓 코인을 대상으로 최근 200개 60분봉(1시간봉) 수집
   - N번째 봉 기준 최근 20개봉(N-19 ~ N)의 RSI(14) 값이 60 이상 75 이하(60 <= RSI <= 75) 조건 만족 비율이 80% 이상(16개봉 이상)일 때 매수
   - [v2 매도 조건]: 거래가격(종가 Close)이 일목균형표 전환선(9)을 하향 이탈(체결가 < 전환선)할 때 매도
   - [보완 매도 조건]: 스탑로스(-3.0%) 이하 손실 발생 시 손절 매도
   - 시뮬레이션 매도 후 거래별 수익률, 승률, 손익비(Profit Factor), 평균 수익률 등 수익률 분석 및 3단 차트 포함 PDF 리포트 생성
   - **저장 위치**: onehour_report/report/onehour_rsi60_75_simulation_report_v2_YYYYMMDDHHMMSS.pdf
========================================================================================
"""

import requests
import numpy as np
import pandas as pd
import time
import os
import sys
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Matplotlib 한글 폰트 설정 (Windows 맑은 고딕)
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

def get_krw_markets():
    """빗썸에서 거래되는 모든 원화(KRW) 마켓 목록 및 한글명/영문명 조회"""
    url = "https://api.bithumb.com/v1/market/all"
    headers = {"accept": "application/json"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
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
    except Exception as e:
        print(f"마켓 목록 조회 중 오류 발생: {e}")
        return []

def calc_mid_point(high, low, window):
    """지정된 기간 동안의 (최고가 + 최저가) / 2 계산"""
    return (high.rolling(window=window).max() + low.rolling(window=window).min()) / 2

def calc_rsi(series, period=14):
    """RSI 지수 계산"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calc_macd(series, short=12, long=26, signal=9):
    """MACD, Signal, Histogram 계산"""
    ema_short = series.ewm(span=short, adjust=False).mean()
    ema_long = series.ewm(span=long, adjust=False).mean()
    macd = ema_short - ema_long
    macd_signal = macd.ewm(span=signal, adjust=False).mean()
    macd_hist = macd - macd_signal
    return macd, macd_signal, macd_hist

def process_candle_df(data):
    """캔들 JSON 데이터를 DataFrame으로 변환 및 일목(전환9, 기준26)/MACD/RSI 계산"""
    df = pd.DataFrame(data).iloc[::-1].reset_index(drop=True)
    for col in ['high_price', 'low_price', 'trade_price']:
        df[col] = df[col].astype(float)
        
    df['Close'] = df['trade_price']
    df['Volume'] = df['candle_acc_trade_volume'].astype(float) if 'candle_acc_trade_volume' in df.columns else 0.0
    
    # 일목균형표 계산 (전환선 9, 기준선 26, 선행스팬1 26, 선행스팬2 52)
    df['ConversionLine'] = calc_mid_point(df['high_price'], df['low_price'], 9)
    df['BaseLine'] = calc_mid_point(df['high_price'], df['low_price'], 26)
    df['Span1'] = ((df['ConversionLine'] + df['BaseLine']) / 2).shift(26)
    df['Span2'] = calc_mid_point(df['high_price'], df['low_price'], 52).shift(26)
    
    # RSI 및 MACD
    df['RSI'] = calc_rsi(df['Close'], 14)
    df['MACD'], df['MACD_Signal'], df['MACD_Hist'] = calc_macd(df['Close'])
    return df

def simulate_single_coin_strategy_v2(m, count=200, stop_loss_pct=-3.0):
    """
    단일 코인의 200개 60분봉 데이터를 수집하고 시뮬레이션 매수/매도 수행 (v2)
    
    [시뮬레이션 규칙 v2]:
    1. 매수 (Buy):
       - N번째 봉 기준 최근 20개봉 (N-19 ~ N) 중 60 <= RSI <= 75 범위 봉 수 >= 16개 (80% 이상)
       - 미보유 상태에서 매수 조건 충족 시 N번째 봉 종가로 매수
    2. 매도 (Sell v2):
       - [스탑로스 매도]: 진입가 대비 저가(low_price) 손실률이 stop_loss_pct (예: -3.0%) 이하 손실 발생 시 매도
       - [체결가 < 전환선 매도]: 보유 상태에서 거래가격(종가 Close)이 전환선(9)을 하향 이탈(Close < ConversionLine)할 때 매도
       - [마지막봉 청산]: 200번째 마지막 봉까지 보유 중이면 마지막 봉 종가로 청산
    """
    market_code = m['market']
    korean_name = m['korean_name']
    english_name = m['english_name']
    
    headers = {"accept": "application/json"}
    url_1h = f"https://api.bithumb.com/v1/candles/minutes/60?market={market_code}&count={count}"
    
    try:
        res_1h = requests.get(url_1h, headers=headers, timeout=5)
        if res_1h.status_code == 200:
            data_1h = res_1h.json()
            if isinstance(data_1h, list) and len(data_1h) >= 50:
                df_1h = process_candle_df(data_1h)
                
                trades = []
                position = None
                
                # N번째 봉 기반 시뮬레이션 (최소 20개 봉의 RSI가 확보된 20번째 인덱스부터 시작)
                for idx in range(20, len(df_1h)):
                    row = df_1h.iloc[idx]
                    
                    # 1) 매수 조건 검사 (미보유 상태)
                    if position is None:
                        window_rsi = df_1h['RSI'].iloc[idx-19 : idx+1]
                        valid_cnt = int(((window_rsi >= 60.0) & (window_rsi <= 75.0)).sum())
                        
                        if valid_cnt >= 16:  # 80% 이상 만족
                            buy_price = row['Close']
                            buy_time = row['candle_date_time_kst'] if 'candle_date_time_kst' in row else str(idx)
                            position = {
                                'buy_idx': idx,
                                'buy_price': buy_price,
                                'buy_time': buy_time,
                                'rsi_ratio': round((valid_cnt / 20.0) * 100.0, 1),
                                'rsi_cnt': valid_cnt
                            }
                    
                    # 2) 매도 조건 검사 (보유 상태 v2: 체결가 < 전환선 또는 스탑로스)
                    else:
                        conv = row['ConversionLine']
                        c_price = row['Close']
                        
                        target_sl_price = position['buy_price'] * (1.0 + stop_loss_pct / 100.0)
                        
                        is_stop_loss = (row['low_price'] <= target_sl_price) or (((c_price - position['buy_price']) / position['buy_price'] * 100.0) <= stop_loss_pct)
                        # v2 신규 매도 조건: 거래가격(종가)이 일목 전환선(9)을 하향 돌파/이탈 (Close < ConversionLine)
                        is_price_cross_below_tenkan = not pd.isna(conv) and (c_price < conv)
                        is_last_candle = (idx == len(df_1h) - 1)
                        
                        if is_stop_loss or is_price_cross_below_tenkan or is_last_candle:
                            if is_stop_loss:
                                sell_price = min(c_price, target_sl_price)
                                sell_reason = f'스탑로스 ({stop_loss_pct:+.1f}%)'
                            elif is_price_cross_below_tenkan:
                                sell_price = c_price
                                sell_reason = '체결가 < 전환선 데드크로스'
                            else:
                                sell_price = c_price
                                sell_reason = '마지막봉 청산'
                                
                            sell_time = row['candle_date_time_kst'] if 'candle_date_time_kst' in row else str(idx)
                            ret_pct = ((sell_price - position['buy_price']) / position['buy_price']) * 100.0
                            holding_bars = idx - position['buy_idx']
                            
                            trades.append({
                                'market': market_code,
                                'korean_name': korean_name,
                                'english_name': english_name,
                                'buy_idx': position['buy_idx'],
                                'buy_price': position['buy_price'],
                                'buy_time': position['buy_time'],
                                'buy_rsi_ratio': position['rsi_ratio'],
                                'sell_idx': idx,
                                'sell_price': sell_price,
                                'sell_time': sell_time,
                                'sell_reason': sell_reason,
                                'return_pct': round(ret_pct, 2),
                                'holding_bars': holding_bars
                            })
                            position = None  # 포지션 종료
                
                if trades:
                    total_ret = sum(t['return_pct'] for t in trades)
                    win_trades = [t for t in trades if t['return_pct'] > 0]
                    win_rate = (len(win_trades) / len(trades)) * 100.0
                    
                    return {
                        'market': market_code,
                        'korean_name': korean_name,
                        'english_name': english_name,
                        'trades': trades,
                        'total_trades': len(trades),
                        'win_trades': len(win_trades),
                        'loss_trades': len(trades) - len(win_trades),
                        'win_rate': round(win_rate, 1),
                        'avg_return': round(total_ret / len(trades), 2),
                        'df_1h': df_1h
                    }
    except Exception as e:
        pass
    return None

def plot_simulation_chart(ax_p, ax_m, ax_r, df, trades, title_prefix):
    """
    시뮬레이션 거래 매수/매도 시점이 표시된 3단 차트 그리기 (v2)
    """
    x = range(len(df))
    
    # ---------------------------------------------------------
    # 1단: 가격 + 일목(전환9, 기준26) + 거래량 + 매수/매도 마커
    # ---------------------------------------------------------
    ax_v = ax_p.twinx()
    v_colors = ['#c0392b' if df['Close'].iloc[i] >= (df['Close'].iloc[i-1] if i > 0 else df['Close'].iloc[i]) else '#2980b9' for i in range(len(df))]
    ax_v.bar(x, df['Volume'], color=v_colors, alpha=0.6, width=0.75)
    ax_v.set_ylim(0, df['Volume'].max() * 4.0 if df['Volume'].max() > 0 else 1)
    ax_v.set_ylabel("거래량", fontsize=7.5, color='gray')
    ax_v.tick_params(axis='y', labelsize=6.5, labelcolor='gray')
    ax_v.grid(False)
    
    ax_p.set_zorder(ax_v.get_zorder() + 1)
    ax_p.patch.set_visible(False)
    
    ax_p.plot(x, df['Close'], label='종가', color='black', linewidth=1.2)
    ax_p.plot(x, df['ConversionLine'], label='전환선(9)', color='#e31a1c', linewidth=1.2)
    ax_p.plot(x, df['BaseLine'], label='기준선(26)', color='#1f78b4', linewidth=1.3)
    ax_p.plot(x, df['Span1'], label='선행1(26)', color='#33a02c', linewidth=0.8, linestyle='--')
    ax_p.plot(x, df['Span2'], label='선행2(52)', color='#ff7f00', linewidth=0.8, linestyle='--')
    
    # 매수 / 매도 시점 표시
    for t in trades:
        b_idx = t['buy_idx']
        s_idx = t['sell_idx']
        b_p = t['buy_price']
        s_p = t['sell_price']
        ret = t['return_pct']
        
        # 매수 마커 (녹색 삼각)
        ax_p.scatter(b_idx, b_p, color='#27ae60', s=70, marker='^', zorder=10, label='매수' if t == trades[0] else "")
        ax_p.annotate(f"매수\n{b_p:,.0f}", (b_idx, b_p), textcoords="offset points", xytext=(0, 10),
                    ha='center', fontsize=6.5, fontweight='bold', color='#1e8449',
                    bbox=dict(boxstyle='round,pad=0.2', facecolor='#e8f8f5', edgecolor='#27ae60', alpha=0.85))
        
        # 매도 마커 (붉은 역삼각)
        m_color = '#c0392b' if ret < 0 else '#8e44ad'
        ax_p.scatter(s_idx, s_p, color=m_color, s=70, marker='v', zorder=10, label='매도' if t == trades[0] else "")
        ret_sign = f"+{ret}%" if ret > 0 else f"{ret}%"
        ax_p.annotate(f"매도({ret_sign})\n{s_p:,.0f}", (s_idx, s_p), textcoords="offset points", xytext=(0, -20),
                    ha='center', fontsize=6.5, fontweight='bold', color=m_color,
                    bbox=dict(boxstyle='round,pad=0.2', facecolor='#fadbd8' if ret < 0 else '#ebdef0', edgecolor=m_color, alpha=0.85))
        
        # 매수-매도 연결선
        ax_p.plot([b_idx, s_idx], [b_p, s_p], color='#27ae60' if ret >= 0 else '#e74c3c', linestyle='--', linewidth=1.5, alpha=0.7)

    ax_p.set_title(f"{title_prefix} - [60분봉 v2 매수/매도 이력 차트 (체결가 < 전환선 매도)]", fontsize=10, fontweight='bold', color='#1b4f72', pad=4)
    ax_p.set_ylabel("가격 (KRW)", fontsize=8)
    ax_p.tick_params(axis='y', labelsize=7.5)
    ax_p.legend(loc='upper left', fontsize=7, framealpha=0.85, ncol=4)
    ax_p.grid(True, linestyle=':', alpha=0.5)
    
    # ---------------------------------------------------------
    # 2단: MACD (12, 26, 9)
    # ---------------------------------------------------------
    ax_m.plot(x, df['MACD'], label='MACD(12,26)', color='#1f78b4', linewidth=1.0)
    ax_m.plot(x, df['MACD_Signal'], label='Signal(9)', color='#e31a1c', linewidth=1.0, linestyle='--')
    hist_colors = ['#e31a1c' if v >= 0 else '#1f78b4' for v in df['MACD_Hist']]
    ax_m.bar(x, df['MACD_Hist'], color=hist_colors, alpha=0.55, width=0.75, label='Oscillator')
    ax_m.axhline(0, color='gray', linestyle=':', linewidth=0.7)
    ax_m.set_ylabel("MACD", fontsize=8)
    ax_m.tick_params(axis='y', labelsize=7.5)
    ax_m.legend(loc='upper left', fontsize=6.5, framealpha=0.85, ncol=3)
    ax_m.grid(True, linestyle=':', alpha=0.5)
    
    # ---------------------------------------------------------
    # 3단: RSI (14) (60~75 하이라이트)
    # ---------------------------------------------------------
    ax_r.plot(x, df['RSI'], label='RSI(14)', color='#8e44ad', linewidth=1.2)
    ax_r.axhspan(60, 75, color='#f39c12', alpha=0.25, label='60~75 목표구간')
    ax_r.axhline(75, color='#e31a1c', linestyle='--', linewidth=0.8, label='75선')
    ax_r.axhline(60, color='#27ae60', linestyle=':', linewidth=0.8, label='60선')
    ax_r.axhline(30, color='#1f78b4', linestyle='--', linewidth=0.8, label='30선')
    ax_r.set_ylim(0, 100)
    ax_r.set_ylabel("RSI", fontsize=8)
    ax_r.tick_params(axis='x', labelsize=7.5)
    ax_r.tick_params(axis='y', labelsize=7.5)
    ax_r.legend(loc='upper left', fontsize=6.5, framealpha=0.85, ncol=4)
    ax_r.grid(True, linestyle=':', alpha=0.5)

def generate_onehour_rsi60_75_simulation_pdf_report_v2(pdf_path=None, max_workers=8, stop_loss_pct=-3.0):
    """
    RSI 60~75 (80%+) 매수 & 체결가 < 전환선 / 스탑로스 매도 시뮬레이션 수행 및 PDF 성과 리포트 생성 (v2)
    - PDF 저장 위치: onehour_report/report/onehour_rsi60_75_simulation_report_v2_YYYYMMDDHHMMSS.pdf
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    if pdf_path is None:
        save_dir = os.path.join(base_dir, "report")
        os.makedirs(save_dir, exist_ok=True)
        filename = f"onehour_rsi60_75_simulation_report_v2_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        pdf_path = os.path.join(save_dir, filename)
    else:
        os.makedirs(os.path.dirname(os.path.abspath(pdf_path)), exist_ok=True)

    markets = get_krw_markets()
    if not markets:
        print("조회된 KRW 마켓이 없습니다.")
        return None

    print(f"[1/3] 빗썸 {len(markets)}개 원화 코인 백테스팅/시뮬레이션 진행 중 (v2 - 매도: 체결가 < 전환선9, 스탑로스: {stop_loss_pct:+.1f}%)...")
    print(f" -> 조건: 20개 1시간봉 중 60<=RSI<=75 비율 80%+ 매수 & 체결가<전환선9 / 스탑로스({stop_loss_pct:+.1f}%) 매도")
    
    coin_results = []
    all_trades = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(simulate_single_coin_strategy_v2, m, 200, stop_loss_pct): m for m in markets}
        for future in as_completed(futures):
            res = future.result()
            if res and res['trades']:
                coin_results.append(res)
                all_trades.extend(res['trades'])
                print(f" ★ [{res['korean_name']}({res['market']})] 총 {res['total_trades']}회 거래 | 승률: {res['win_rate']}% | 평균수익률: {res['avg_return']}%")

    # 포착 거래 내역 정렬
    all_trades.sort(key=lambda x: x['return_pct'], reverse=True)
    coin_results.sort(key=lambda x: (x['avg_return'], x['win_rate']), reverse=True)

    print(f"\n[2/3] v2 시뮬레이션 성과 분석 및 PDF 리포트 생성 중... (저장경로: {pdf_path})")

    # 전체 통계 계산
    total_trades_count = len(all_trades)
    if total_trades_count == 0:
        print("시뮬레이션 결과 조건에 부합하는 매수/매도 거래가 발생하지 않았습니다.")
        return None

    winning_trades = [t for t in all_trades if t['return_pct'] > 0]
    losing_trades = [t for t in all_trades if t['return_pct'] <= 0]
    
    overall_win_rate = (len(winning_trades) / total_trades_count) * 100.0
    overall_avg_return = sum(t['return_pct'] for t in all_trades) / total_trades_count
    
    total_gain_sum = sum(t['return_pct'] for t in winning_trades)
    total_loss_sum = abs(sum(t['return_pct'] for t in losing_trades))
    profit_factor = (total_gain_sum / total_loss_sum) if total_loss_sum > 0 else (total_gain_sum if total_gain_sum > 0 else 1.0)
    
    max_gain = max(t['return_pct'] for t in all_trades)
    max_loss = min(t['return_pct'] for t in all_trades)
    avg_holding_bars = sum(t['holding_bars'] for t in all_trades) / total_trades_count
    
    # 터미널 콘솔 성과 요약 출력
    print("=" * 80)
    print("                [ v2 시뮬레이션 전략 성과 종합 결과 ]")
    print("=" * 80)
    print(f" - 총 분석 대상 코인 수   : {len(markets)}개")
    print(f" - 거래 발생 코인 수     : {len(coin_results)}개")
    print(f" - 총 실행 거래 횟수     : {total_trades_count}회 (수익 {len(winning_trades)}회 / 손실 {len(losing_trades)}회)")
    print(f" - 전체 승률 (Win Rate)  : {overall_win_rate:.1f}%")
    print(f" - 거래당 평균 수익률    : {overall_avg_return:+.2f}%")
    print(f" - 손익비 (Profit Factor): {profit_factor:.2f}")
    print(f" - 최고 수익 거래       : {max_gain:+.2f}%")
    print(f" - 최대 손실 거래       : {max_loss:+.2f}%")
    print(f" - 평균 포지션 보유 기간 : 약 {avg_holding_bars:.1f}시간 ({avg_holding_bars:.1f}개 봉)")
    print("=" * 80)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with PdfPages(pdf_path) as pdf:
        # -------------------------------------------------------------
        # 1. 성과 종합 요약 (Executive Summary) 페이지
        # -------------------------------------------------------------
        fig_sum, ax_sum = plt.subplots(figsize=(14, 8.5))
        ax_sum.axis('off')
        
        ax_sum.text(0.5, 0.96, f"빗썸 1시간봉 RSI 60~75 (80%+) & 체결가<전환선9 / 스탑로스({stop_loss_pct:+.1f}%) 시뮬레이션 리포트 (v2)",
                    fontsize=14, fontweight='bold', ha='center', va='top', color='#1a5276')
        ax_sum.text(0.5, 0.92, f"분석 일시: {now_str} | 수집 대상: 빗썸 원화 마켓 코인 최근 200개 1시간봉",
                    fontsize=10, color='gray', ha='center', va='top')

        # 요약 메트릭 박스 렌더링
        metrics_text = (
            f" [v2 전략 종합 성과 메트릭 Summary]\n"
            f" ---------------------------------------------------------\n"
            f" - 신규 매도 조건    : 체결가 < 일목 전환선(9) 데드크로스 이탈\n"
            f" - 스탑로스 설정      : {stop_loss_pct:+.1f}%\n"
            f" - 분석 코인 수      : {len(markets)}개 (거래 발생: {len(coin_results)}개 코인)\n"
            f" - 총 거래 횟수      : {total_trades_count}회\n"
            f" - 성공/실패 거래    : 수익 {len(winning_trades)}회 / 손실 {len(losing_trades)}회\n"
            f" - 전체 승률         : {overall_win_rate:.1f}%\n"
            f" - 거래당 평균 수익률: {overall_avg_return:+.2f}%\n"
            f" - 손익비 (Profit Factor): {profit_factor:.2f}\n"
            f" - 최대 수익 거래    : {max_gain:+.2f}%\n"
            f" - 최대 손실 거래    : {max_loss:+.2f}%\n"
            f" - 평균 보유 시간    : {avg_holding_bars:.1f}시간 ({avg_holding_bars:.1f}개 60분봉)"
        )
        ax_sum.text(0.05, 0.86, metrics_text, fontsize=10, fontfamily='Malgun Gothic', va='top',
                    bbox=dict(boxstyle='round,pad=0.8', facecolor='#eaf2f8', edgecolor='#2980b9', alpha=0.9))

        # 상위/하위 성과 코인 요약 표
        summary_rows = [
            [
                c['market'],
                c['korean_name'],
                f"{c['total_trades']}회",
                f"{c['win_rate']}%",
                f"{c['avg_return']:+.2f}%",
                f"{max([t['return_pct'] for t in c['trades']]):+.2f}%",
                f"{min([t['return_pct'] for t in c['trades']]):+.2f}%"
            ] for c in coin_results[:15]  # 상위 15개 코인
        ]
        col_labels = ['마켓코드', '한글명', '총 거래횟수', '승률(%)', '평균 수익률(%)', '최대 수익(%)', '최대 손실(%)']
        
        table = ax_sum.table(
            cellText=summary_rows,
            colLabels=col_labels,
            cellLoc='center',
            loc='center',
            bbox=[0.05, 0.05, 0.90, 0.45]
        )
        table.auto_set_font_size(False)
        table.set_fontsize(8.5)
        
        for col_i in range(len(col_labels)):
            cell = table[(0, col_i)]
            cell.set_facecolor('#1a5276')
            cell.set_text_props(color='white', fontweight='bold')
            
        plt.tight_layout()
        pdf.savefig(fig_sum)
        plt.close(fig_sum)

        # -------------------------------------------------------------
        # 2. 전체 매수/매도 거래 세부 내역 표 페이지 (상위 44개 거래)
        # -------------------------------------------------------------
        chunk_size = 22
        trade_rows_all = [
            [
                t['market'],
                t['korean_name'],
                f"{t['buy_price']:,}",
                f"{t['sell_price']:,}",
                f"{t['return_pct']:+.2f}%",
                f"{t['holding_bars']}시간",
                t['buy_time'].split('T')[-1][:5] if 'T' in str(t['buy_time']) else str(t['buy_idx'])+'봉',
                t['sell_time'].split('T')[-1][:5] if 'T' in str(t['sell_time']) else str(t['sell_idx'])+'봉',
                t['sell_reason']
            ] for t in all_trades[:44]
        ]
        col_labels_t = ['마켓코드', '한글명', '매수가(원)', '매도가(원)', '수익률(%)', '보유시간', '매수시점', '매도시점', '청산 사유']

        for page_idx in range(0, len(trade_rows_all), chunk_size):
            chunk = trade_rows_all[page_idx : page_idx + chunk_size]
            fig_t, ax_t = plt.subplots(figsize=(14, 8.5))
            ax_t.axis('off')

            ax_t.text(0.5, 0.96, "v2 시뮬레이션 개별 거래 상세 내역 표 (상위 거래)", fontsize=15, fontweight='bold', ha='center', va='top', color='#1a5276')
            ax_t.text(0.5, 0.92, f"전체 {total_trades_count}개 거래 중 수익률 상위 거래 내역 (p.{page_idx//chunk_size + 1})",
                      fontsize=10, color='gray', ha='center', va='top')

            t_table = ax_t.table(
                cellText=chunk,
                colLabels=col_labels_t,
                cellLoc='center',
                loc='center',
                bbox=[0.02, 0.05, 0.96, 0.82]
            )
            t_table.auto_set_font_size(False)
            t_table.set_fontsize(8.0)
            
            for col_i in range(len(col_labels_t)):
                cell = t_table[(0, col_i)]
                cell.set_facecolor('#2471a3')
                cell.set_text_props(color='white', fontweight='bold')
                
            plt.tight_layout()
            pdf.savefig(fig_t)
            plt.close(fig_t)

        # -------------------------------------------------------------
        # 3. 거래 발생 코인별 시뮬레이션 매수/매도 차트 페이지 (상위 15개 코인)
        # -------------------------------------------------------------
        for idx, item in enumerate(coin_results[:15], 1):
            fig, axes = plt.subplots(
                3, 1, figsize=(14, 8.5),
                gridspec_kw={'height_ratios': [3.0, 1.2, 1.2], 'hspace': 0.25}
            )
            
            k_name = item['korean_name']
            m_code = item['market']
            
            title_page = f"[{idx}/{len(coin_results[:15])}] {k_name} ({m_code}) v2 시뮬레이션 차트  |  총 {item['total_trades']}회 거래 (승률: {item['win_rate']}%)  |  평균 수익률: {item['avg_return']:+.2f}%"
            fig.suptitle(title_page, fontsize=12, fontweight='bold', color='#0e6251', y=0.98)
            
            plot_simulation_chart(
                ax_p=axes[0],
                ax_m=axes[1],
                ax_r=axes[2],
                df=item['df_1h'],
                trades=item['trades'],
                title_prefix=k_name
            )
            
            plt.subplots_adjust(top=0.93, bottom=0.06, left=0.06, right=0.95)
            pdf.savefig(fig)
            plt.close(fig)

    full_pdf_path = os.path.abspath(pdf_path)
    print(f"\n[3/3] 성공! v2 시뮬레이션 성과 분석 및 PDF 리포트 생성 완료!")
    print(f" -> PDF 저장 위치: '{full_pdf_path}'")
    return full_pdf_path

if __name__ == "__main__":
    generate_onehour_rsi60_75_simulation_pdf_report_v2()
