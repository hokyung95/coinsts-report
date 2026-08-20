"""
========================================================================================
 [모듈 명]: U_Style_Code/last_u_turn_report.py
 [구현 목적]:
   - simulate_kijun_u_turn 모듈의 30일 일목균형표 기준선(30일) U자형 턴어라운드 로직 기반
   - 지난 3일부터 오늘까지(0일전, 1일전, 2일전, 3일전) 최근 발생한 U자형 턴어라운드 코인 포착
   - 거래량 급증 사례뿐만 아니라 비슷한 거래량(일반 거래량) 사례까지 포함하여 전수 분석
   - 일목균형표(전환선 10, 기준선 30, 선행스팬 30/60), 거래량배수, MACD, RSI 3단 차트 PDF 리포트 생성
   - Google Drive 자동 업로드 연동 (upload_to_gdrive)

 [실행 방법]:
   - python U_Style_Code/last_u_turn_report.py
   - python last_u_turn_report.py
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

# Matplotlib 한글 폰트 설정
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

def get_krw_markets():
    """빗썸 원화(KRW) 마켓 목록 조회"""
    url = "https://api.bithumb.com/v1/market/all"
    headers = {"accept": "application/json"}
    res = requests.get(url, headers=headers).json()
    krw_markets = [
        {
            'market': m['market'],
            'korean_name': m.get('korean_name', m['market']),
            'english_name': m.get('english_name', m['market'])
        }
        for m in res if m['market'].startswith('KRW-')
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
    
    # 30일 코인 전용 일목 파라미터 (10, 30, 60, 30)
    df['ConversionLine'] = calc_mid_point(df['high_price'], df['low_price'], 10)
    df['BaseLine'] = calc_mid_point(df['high_price'], df['low_price'], 30)
    df['Span1'] = ((df['ConversionLine'] + df['BaseLine']) / 2).shift(30)
    df['Span2'] = calc_mid_point(df['high_price'], df['low_price'], 60).shift(30)
    df['RSI'] = calc_rsi(df['Close'], 14)
    df['MACD'], df['MACD_Signal'], df['MACD_Hist'] = calc_macd(df['Close'])
    return df

def check_kijun_u_turn_recent_days(df, max_lookback_days=3, flat_tolerance_pct=0.012):
    """
    최근 3일전 ~ 오늘 현재 (offset 0, 1, 2, 3) 30일 기준선 U자형 턴어라운드 탐색
    - 비슷한 거래량(일반 거래량) 및 거래량 급증 사례 모두 포함
    """
    n = len(df)
    if n < 60:
        return False, None
        
    kijun = df['BaseLine']
    close = df['Close']
    volume = df['Volume']
    vol_ma20 = df['Vol_MA20']
    
    # offset 0 (오늘), 1 (1일전), 2 (2일전), 3 (3일전)
    for offset in range(max_lookback_days + 1):
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

        # 1단계: 하락 구간 (30봉전 대비 15봉전 하향)
        cond1_down = (mid15_k < past30_k)
        
        # 2단계: 최근 수평(Flat) 바닥 (idx-15 ~ idx-2 변동폭 <= 1.2%)
        flat_window = kijun.iloc[idx-15 : idx-2]
        if len(flat_window) < 5:
            continue
        flat_diff = (flat_window.max() - flat_window.min()) / flat_window.min() if flat_window.min() > 0 else 1.0
        cond2_flat = (flat_diff <= flat_tolerance_pct)
        
        # 3단계: 최근 1~2봉 이내 30일 기준선 우상향 전환 (Kijun[idx] > Kijun[idx-1] or Kijun[idx-1] > Kijun[idx-2])
        cond3_turn = (curr_k > prev1_k) or (prev1_k > prev2_k)
        
        # 4단계: 주가 안착 (현재가 또는 포착일 종가가 기준선 이상)
        curr_price = close.iloc[-1]
        event_price = close.iloc[idx]
        cond4_price = (curr_price >= curr_k or event_price >= curr_k)
        
        if cond1_down and cond2_flat and cond3_turn and cond4_price:
            event_date = str(df['candle_date_time_kst'].iloc[idx])[:10] if 'candle_date_time_kst' in df.columns else f"{offset}일 전"
            if offset == 0:
                day_desc = "오늘(0일전)"
            else:
                day_desc = f"{offset}일전({event_date})"
                
            cur_vol = volume.iloc[idx]
            avg_vol = vol_ma20.iloc[idx] if not pd.isna(vol_ma20.iloc[idx]) and vol_ma20.iloc[idx] > 0 else 1.0
            vol_ratio = cur_vol / avg_vol
            
            # 거래량 구분: 1.5배 이상 '급증', 그 외 '비슷한 거래량'
            vol_status = "거래량 급증" if vol_ratio >= 1.5 else "비슷한 거래량"
            
            # 이후 N일 성과 (현재 시점까지의 성과/최고 상승률 추적)
            future_window = close.iloc[idx+1:]
            max_ret_after_event = ((future_window.max() - event_price) / event_price * 100) if len(future_window) > 0 else 0.0
            curr_ret = ((curr_price - event_price) / event_price * 100)
            
            return True, {
                'offset': offset,
                'event_date': event_date,
                'day_desc': day_desc,
                'idx': idx,
                'price': curr_price,
                'event_price': event_price,
                'kijun': round(curr_k, 2),
                'vol_ratio': round(vol_ratio, 2),
                'vol_status': vol_status,
                'is_vol_surge': vol_ratio >= 1.5,
                'rsi': round(df['RSI'].iloc[-1], 1),
                'macd': round(df['MACD'].iloc[-1], 2),
                'curr_ret': round(curr_ret, 2),
                'max_ret_after': round(max_ret_after_event, 2),
                'df': df
            }
    return False, None

def fetch_and_analyze(m, max_lookback_days=3):
    """단일 코인 일봉 데이터 조회 및 U자형 턴어라운드 분석"""
    url = f"https://api.bithumb.com/v1/candles/days?market={m['market']}&count=200"
    headers = {"accept": "application/json"}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            df = process_daily_candle_df(res.json())
            ok, info = check_kijun_u_turn_recent_days(df, max_lookback_days=max_lookback_days)
            if ok:
                info['market'] = m['market']
                info['korean_name'] = m['korean_name']
                info['english_name'] = m['english_name']
                return info
    except Exception:
        pass
    return None

def scan_u_turn_recent(max_lookback_days=3, max_workers=6):
    """빗썸 KRW 전체 종목 대상 최근 (지난3일~오늘) U자형 턴어라운드 스캔"""
    markets = get_krw_markets()
    print("=" * 100)
    print(f" [지난 3일부터 오늘까지 30일 기준선 U자형 턴어라운드 포착 스캔 (비슷한 거래량 포함)]")
    print(f" - 대상: 빗썸 원화(KRW) 마켓 전체 {len(markets)}개 종목")
    print(f" - 탐색 범위: 지난 3일전 ~ 오늘 현재 (Offset 0 ~ 3)")
    print(f" - 조건: 30일 기준선 U자 턴어라운드 + 주가 안착 (거래량 급증 및 비슷한 거래량 모두 포함)")
    print("=" * 100)
    
    matched = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_and_analyze, m, max_lookback_days): m for m in markets}
        for f in as_completed(futures):
            res = f.result()
            if res:
                matched.append(res)
                print(f" [포착] [{res['day_desc']}] {res['korean_name']}({res['market']}) | 현재가: {res['price']:,}원 | 거래량: {res['vol_ratio']}배 ({res['vol_status']}) | 현재수익: {res['curr_ret']:+.2f}%")
                
    # 정렬: offset 오름차순 (오늘 -> 1일전 -> 2일전 -> 3일전), 거래량배수 내림차순
    matched.sort(key=lambda x: (x['offset'], -x['vol_ratio'], x['korean_name']))
    print(f"\n[스캔 완료] 지난 3일부터 오늘까지 총 {len(matched)}개 종목 30일 U자형 턴어라운드 포착!\n")
    return matched

def generate_last_u_turn_pdf(matched, pdf_path=None):
    """포착된 U자형 턴어라운드 종목 PDF 리포트 생성"""
    if pdf_path is None:
        save_dir = "d:/pyprj/coinsts/U_Style_Code/report"
        os.makedirs(save_dir, exist_ok=True)
        pdf_path = os.path.join(save_dir, f"report_last_u_turn_3d_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf")
    else:
        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)

    if not matched:
        print("[안내] 최근 3일간 U자형 턴어라운드 조건 만족 종목이 없습니다. 빈 PDF 생성을 건너뜁니다.")
        return None

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_cnt = len(matched)
    
    surge_cnt = sum(1 for m in matched if m['is_vol_surge'])
    normal_cnt = total_cnt - surge_cnt

    print(f"[PDF 생성 중] 지난 3일~오늘 U자형 턴어라운드 리포트 생성 (총 {total_cnt}개 종목)...")

    with PdfPages(pdf_path) as pdf:
        # Page 1: 종합 요약 및 포착 종목 목록 표
        fig_stat, ax_stat = plt.subplots(figsize=(11.69, 8.27))
        ax_stat.axis('off')

        title_text = "지난 3일부터 오늘까지 30일 기준선 U자형 턴어라운드 포착 리포트 (비슷한 거래량 포함)"
        ax_stat.text(0.5, 0.96, title_text, fontsize=13.5, fontweight='bold', ha='center', va='top')
        
        stat_summary_text = (
            f"■ 생성 일시: {now_str}  |  대상: 빗썸 KRW 전체 마켓  |  탐색 범위: 지난 3일전 ~ 오늘 현재\n"
            f"----------------------------------------------------------------------------------------------------------------------\n"
            f"1. 지난 3일간 총 포착 건수: {total_cnt}건\n"
            f"   - 거래량 급증 (평균 1.5배 이상): {surge_cnt}건\n"
            f"   - 비슷한 거래량 (평균 수준/일반): {normal_cnt}건 (모두 포함 분석)\n\n"
            f"2. 주요 특징:\n"
            f"   - 30일 일목균형표 기준선(30일)이 하락 후 수평 횡보를 거쳐 최근 우상향 전환된 중기 추세 턴어라운드 종목입니다.\n"
            f"   - 거래량 급증 종목과 비슷한 거래량을 유지하며 차분히 안착하는 종목을 모두 포함하여 폭넓은 기회를 제공합니다."
        )
        ax_stat.text(0.04, 0.90, stat_summary_text, fontsize=9.5, va='top', bbox=dict(boxstyle='round', facecolor='#ebf5fb', alpha=0.85))

        # 표 구성
        top_rows = [
            [
                r['market'],
                r['korean_name'],
                r['day_desc'],
                f"{r['event_price']:,}",
                f"{r['price']:,}",
                f"{r['vol_ratio']}배",
                r['vol_status'],
                f"{r['kijun']:,}",
                f"{r['curr_ret']:+.1f}%",
                f"{r['max_ret_after']:+.1f}%",
                f"{r['rsi']:.1f}"
            ] for r in matched
        ]
        col_labels = ['마켓코드', '한글명', '포착시점', '포착가(원)', '현재가(원)', '거래량배수', '거래량구분', '기준선(30일)', '현재수익률', '포착후최고', 'RSI']
        
        table = ax_stat.table(
            cellText=top_rows,
            colLabels=col_labels,
            cellLoc='center',
            loc='bottom',
            bbox=[0.02, 0.05, 0.96, min(0.55, 0.045 * (len(top_rows) + 1.5))]
        )
        table.auto_set_font_size(False)
        table.set_fontsize(8)
        for col_i in range(len(col_labels)):
            table[(0, col_i)].set_facecolor('#1b4f72')
            table[(0, col_i)].set_text_props(color='white', fontweight='bold')
            
        # 행별 배경색 지정 (거래량 급증 vs 비슷한 거래량)
        for row_i, r in enumerate(matched, start=1):
            if r['is_vol_surge']:
                for col_i in range(len(col_labels)):
                    table[(row_i, col_i)].set_facecolor('#fef9e7')

        plt.tight_layout()
        pdf.savefig(fig_stat)
        plt.close(fig_stat)

        # Page 2~ : 개별 코인 3단 차트 렌더링
        for idx, item in enumerate(matched, 1):
            fig, (ax_p, ax_m, ax_r) = plt.subplots(
                3, 1, figsize=(11.69, 8.27),
                gridspec_kw={'height_ratios': [3.0, 1.2, 1.2]},
                sharex=True
            )
            df = item['df']
            x = range(len(df))

            # 1. 가격 + 거래량
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
            e_idx = item['idx']
            ax_p.scatter(
                e_idx, df['BaseLine'].iloc[e_idx],
                color='gold', s=150, zorder=6, edgecolors='red', linewidth=1.8,
                label=f"30일U자턴어라운드[{item['day_desc']}]"
            )
            
            # 포착 지점 이후 영역 강조
            if e_idx < len(df) - 1:
                ax_p.axvspan(e_idx, len(df)-1, color='yellow', alpha=0.15, label=f"포착후 추적 (수익률: {item['curr_ret']:+.1f}%)")

            ax_p.set_title(
                f"[{idx}/{total_cnt}] {item['korean_name']} ({item['market']}) - 30일 일목 기준선 U자형 턴어라운드\n"
                f"포착시점: {item['day_desc']} | 포착가: {item['event_price']:,}원 | 현재가: {item['price']:,}원 ({item['curr_ret']:+.2f}%) | "
                f"거래량배수: {item['vol_ratio']}배 ({item['vol_status']})",
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
    print(f"\n[성공] 지난 3일~오늘 U자형 턴어라운드 PDF 리포트 생성 완료: {full_pdf_path}")

    # Google Drive 업로드 연동
    try:
        # sys.path에 Root 폴더 추가
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if root_dir not in sys.path:
            sys.path.insert(0, root_dir)
        from upload_to_gdrive import upload_pdf_to_gdrive
        upload_pdf_to_gdrive(full_pdf_path, folder_name="report_daily", user_email="hhokyung@gmail.com")
    except Exception as e:
        print(f"[안내] 구글 드라이브 업로드 패스/실패: {e}")

    return full_pdf_path

if __name__ == "__main__":
    matched_events = scan_u_turn_recent(max_lookback_days=3, max_workers=6)
    generate_last_u_turn_pdf(matched_events)
