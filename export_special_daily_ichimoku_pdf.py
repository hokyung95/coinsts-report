"""
========================================================================================
 [모듈 명]: export_special_daily_ichimoku_pdf.py
 [구현 목적]:
   - 특정 코인명(한글명, 영문 심볼, 마켓코드)을 사용자로부터 입력받아 빗썸 일봉(Daily) 시계열 데이터를 수집하고,
     일목균형표(거래량 포함), MACD, RSI 보조지표 차트를 3단으로 구성한 결합 시각화 리포트를 PDF 문서로 자동 생성합니다.

 [주요 기능 및 사양]:
   1. 유연한 검색 매칭: '비트코인', 'BTC', 'KRW-BTC', '리플', 'XRP', '오브스' 등 다양한 표현 방식 자동 검색 지원
   2. 다중 코인 일괄 리포트 생성: CLI 명령어 파라미터나 파이썬 리스트로 여러 코인을 지정 시 1페이지당 1코인씩 통합 PDF 출력
   3. 3단 서브플롯 구성:
      - 1행: 일봉 일목균형표 차트 + **진한 이중 Y축 거래량(Volume) 바 차트** (종가, 전환선, 기준선, 선행스팬1/2, 양운/음운 구름대)
      - 2행: 일봉 MACD 차트 (MACD Line, Signal Line, Oscillator Histogram)
      - 3행: 일봉 RSI 차트 (RSI(14) 지수선, 과매수 70 / 과매도 30 레벨선)

 [사용 및 실행 방법]:
   - 단일 코인 검색: python export_special_daily_ichimoku_pdf.py "오브스"
   - 여러 코인 검색: python export_special_daily_ichimoku_pdf.py "비트코인" "리플" "솔라나" "ETH"
   - 파이썬 코드 호출: from export_special_daily_ichimoku_pdf import generate_special_coin_pdf; generate_special_coin_pdf(["BTC", "XRP"])
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

# Matplotlib 한글 폰트 설정 (Windows 맑은 고딕)
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

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
            'english_name': m.get('english_name', m['market']),
            'symbol': m['market'].replace('KRW-', '')
        }
        for m in markets if m['market'].startswith('KRW-')
    ]
    return krw_markets

def find_market_by_query(query, markets):
    """
    입력 쿼리(한글명, 영문명, 마켓코드, 심볼)로 마켓 찾기
    예: '비트코인', 'BTC', 'KRW-BTC', '리플', 'XRP'
    """
    q = query.strip().upper()
    
    # 1. 완벽 일치 검색
    for m in markets:
        if m['market'].upper() == q or m['symbol'].upper() == q or m['korean_name'].upper() == q or m['english_name'].upper() == q:
            return m
            
    # 2. 부분 일치 검색
    for m in markets:
        if q in m['korean_name'].upper() or q in m['english_name'].upper() or q in m['market'].upper():
            return m
            
    return None

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

def calc_macd(series, short=12, long=26, signal=9):
    """MACD, Signal, Histogram 계산"""
    ema_short = series.ewm(span=short, adjust=False).mean()
    ema_long = series.ewm(span=long, adjust=False).mean()
    macd = ema_short - ema_long
    macd_signal = macd.ewm(span=signal, adjust=False).mean()
    macd_hist = macd - macd_signal
    return macd, macd_signal, macd_hist

def fetch_daily_candle_df(market_code, count=200):
    """일봉 JSON 데이터 수집 및 일목/MACD/RSI/거래량 지표 산출"""
    url = f"https://api.bithumb.com/v1/candles/days?market={market_code}&count={count}"
    headers = {"accept": "application/json"}
    
    res = requests.get(url, headers=headers, timeout=5)
    if res.status_code != 200:
        return None
    data = res.json()
    if not isinstance(data, list) or len(data) < 30:
        return None
        
    df = pd.DataFrame(data).iloc[::-1].reset_index(drop=True)
    for col in ['high_price', 'low_price', 'trade_price']:
        df[col] = df[col].astype(float)
        
    df['Close'] = df['trade_price']
    if 'candle_acc_trade_volume' in df.columns:
        df['Volume'] = df['candle_acc_trade_volume'].astype(float)
    else:
        df['Volume'] = 0.0

    df['ConversionLine'] = calc_mid_point(df['high_price'], df['low_price'], 9)
    df['BaseLine'] = calc_mid_point(df['high_price'], df['low_price'], 26)
    df['Span1'] = ((df['ConversionLine'] + df['BaseLine']) / 2).shift(26)
    df['Span2'] = calc_mid_point(df['high_price'], df['low_price'], 52).shift(26)
    df['RSI'] = calc_rsi(df['Close'], 14)
    df['MACD'], df['MACD_Signal'], df['MACD_Hist'] = calc_macd(df['Close'])
    return df

def generate_special_coin_pdf(coin_queries, pdf_path=None, count=200, upload_gdrive=True):
    """
    특정 코인명(단일 또는 리스트)을 입력받아 일봉 기준 일목균형표(진한 거래량 포함), MACD, RSI 차트를 통합 PDF 생성
    """
    if isinstance(coin_queries, str):
        coin_queries = [coin_queries]
        
    all_markets = get_krw_markets()
    matched_targets = []
    
    for q in coin_queries:
        m = find_market_by_query(q, all_markets)
        if m:
            matched_targets.append(m)
        else:
            print(f"⚠️ 검색된 코인이 없습니다: '{q}'")
            
    if not matched_targets:
        print("❌ 분석할 대상을 찾지 못해 PDF 생성을 중단합니다.")
        return None

    if pdf_path is None:
        save_dir = "d:/pyprj/coinsts/report_daily"
        os.makedirs(save_dir, exist_ok=True)
        first_symbol = matched_targets[0]['symbol']
        suffix = f"_{len(matched_targets)}coins" if len(matched_targets) > 1 else f"_{first_symbol}"
        filename = f"report_special{suffix}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        pdf_path = os.path.join(save_dir, filename)
    else:
        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)

    print(f"\n[1/2] 총 {len(matched_targets)}개 대상 코인 일봉 데이터 수집 및 분석 시작...")

    analyzed_coins = []
    for m in matched_targets:
        df = fetch_daily_candle_df(m['market'], count=count)
        if df is not None:
            last = df.iloc[-1]
            tenkan, kijun, price = last['ConversionLine'], last['BaseLine'], last['Close']
            
            past_kijun = df['BaseLine'].iloc[-10:]
            _, kijun_angle = get_slope_and_angle(past_kijun.dropna())
            
            past_tenkan = df['ConversionLine'].iloc[-10:]
            _, tenkan_angle = get_slope_and_angle(past_tenkan.dropna())
            
            analyzed_coins.append({
                'market_info': m,
                'df': df,
                'last': last,
                'price': price,
                'tenkan': tenkan,
                'kijun': kijun,
                'tenkan_angle': round(tenkan_angle, 2),
                'kijun_angle': round(kijun_angle, 2),
                'rsi': round(last['RSI'], 1) if not pd.isna(last['RSI']) else 0.0,
                'macd': round(last['MACD'], 2) if not pd.isna(last['MACD']) else 0.0,
                'macd_signal': round(last['MACD_Signal'], 2) if not pd.isna(last['MACD_Signal']) else 0.0,
            })
            print(f"  - {m['korean_name']}({m['symbol']}): 현재가 {price:,}원 | RSI {last['RSI']:.1f} | MACD {last['MACD']:.2f}")

    if not analyzed_coins:
        print("데이터를 수집하지 못해 PDF 생성을 취소합니다.")
        return None

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(f"\n[2/2] 차트(일목균형표+진한거래량 + MACD + RSI) 시각화 및 PDF 렌더링 중...")

    with PdfPages(pdf_path) as pdf:
        for idx, item in enumerate(analyzed_coins, 1):
            m = item['market_info']
            df = item['df']
            price = item['price']
            
            # 3행 서브플롯 구성: 일목균형표(가격+거래량), MACD, RSI
            fig, (ax_price, ax_macd, ax_rsi) = plt.subplots(
                3, 1, figsize=(11.69, 8.27),
                gridspec_kw={'height_ratios': [3.0, 1.2, 1.2]},
                sharex=True
            )
            
            x_range = range(len(df))
            
            # ---------------------------------------------------------
            # 1. 일봉 일목균형표 차트 + 진한 이중 Y축 거래량(Volume) 바 차트
            # ---------------------------------------------------------
            # (1-A) 진한 거래량(Volume) 이중 Y축 렌더링 (alpha=0.55로 시인성 향상)
            ax_vol = ax_price.twinx()
            vol_colors = ['#e31a1c' if df['Close'].iloc[i] >= (df['Close'].iloc[i-1] if i > 0 else df['Close'].iloc[i]) else '#1f78b4' for i in range(len(df))]
            ax_vol.bar(x_range, df['Volume'], color=vol_colors, alpha=0.55, width=0.75, label='거래량') # 진한 색상 표기
            max_vol = df['Volume'].max() if df['Volume'].max() > 0 else 1.0
            ax_vol.set_ylim(0, max_vol * 3.8) # 거래량이 차트 하단 1/4 영역 이하에 오도록 조율
            ax_vol.set_ylabel("거래량", fontsize=7.5, color='#555555')
            ax_vol.tick_params(axis='y', labelcolor='#555555', labelsize=7)
            ax_vol.grid(False)

            # (1-B) 일목균형표 메인 주 가격 차트 렌더링
            ax_price.set_zorder(ax_vol.get_zorder() + 1)
            ax_price.patch.set_visible(False)
            
            ax_price.plot(x_range, df['Close'], label='일봉 종가', color='black', linewidth=1.4)
            ax_price.plot(x_range, df['ConversionLine'], label='전환선(9)', color='#e31a1c', linewidth=1.2)
            ax_price.plot(x_range, df['BaseLine'], label='기준선(26)', color='#1f78b4', linewidth=1.2)
            ax_price.plot(x_range, df['Span1'], label='선행스팬1', color='#33a02c', linewidth=0.8, linestyle='--')
            ax_price.plot(x_range, df['Span2'], label='선행스팬2', color='#ff7f00', linewidth=0.8, linestyle='--')
            
            ax_price.fill_between(
                x_range, df['Span1'], df['Span2'],
                where=(df['Span1'] >= df['Span2']),
                color='#b2df8a', alpha=0.35, label='양운'
            )
            ax_price.fill_between(
                x_range, df['Span1'], df['Span2'],
                where=(df['Span1'] < df['Span2']),
                color='#fb9a99', alpha=0.35, label='음운'
            )
            
            title_str = (
                f"[{idx}/{len(analyzed_coins)}] {m['korean_name']} ({m['english_name']} / {m['market']})  -  [일봉 일목균형표 + 거래량 차트]\n"
                f"현재종가: {price:,}원 | 전환선: {item['tenkan']:,}원 | 기준선: {item['kijun']:,}원 (각도: {item['kijun_angle']:+.2f}°) | RSI: {item['rsi']} | 생성시간: {now_str}"
            )
            ax_price.set_title(title_str, fontsize=10.5, fontweight='bold', color='#1b4f72', pad=8)
            ax_price.set_ylabel("가격 (KRW)", fontsize=8.5)
            ax_price.legend(loc='upper left', fontsize=7.5, framealpha=0.85, ncol=4)
            ax_price.grid(True, linestyle=':', alpha=0.5)

            # ---------------------------------------------------------
            # 2. 일봉 MACD 차트
            # ---------------------------------------------------------
            ax_macd.plot(x_range, df['MACD'], label='MACD(12,26)', color='#1f78b4', linewidth=1.1)
            ax_macd.plot(x_range, df['MACD_Signal'], label='Signal(9)', color='#e31a1c', linewidth=1.1, linestyle='--')
            
            colors_hist = ['#e31a1c' if val >= 0 else '#1f78b4' for val in df['MACD_Hist']]
            ax_macd.bar(x_range, df['MACD_Hist'], color=colors_hist, alpha=0.5, width=0.8, label='Oscillator')
            ax_macd.axhline(0, color='gray', linestyle=':', linewidth=0.7)
            
            ax_macd.set_ylabel("MACD", fontsize=8.5)
            ax_macd.legend(loc='upper left', fontsize=7.5, framealpha=0.85, ncol=3)
            ax_macd.grid(True, linestyle=':', alpha=0.5)

            # ---------------------------------------------------------
            # 3. 일봉 RSI 차트
            # ---------------------------------------------------------
            ax_rsi.plot(x_range, df['RSI'], label='RSI(14)', color='#8e44ad', linewidth=1.2)
            ax_rsi.axhline(70, color='#e31a1c', linestyle='--', linewidth=0.8, label='과매수(70)')
            ax_rsi.axhline(50, color='gray', linestyle=':', linewidth=0.7)
            ax_rsi.axhline(30, color='#1f78b4', linestyle='--', linewidth=0.8, label='과매도(30)')
            
            ax_rsi.set_ylim(0, 100)
            ax_rsi.set_ylabel("RSI", fontsize=8.5)
            ax_rsi.set_xlabel("일자 (최신 일봉 시계열)", fontsize=8.5)
            ax_rsi.legend(loc='upper left', fontsize=7.5, framealpha=0.85, ncol=3)
            ax_rsi.grid(True, linestyle=':', alpha=0.5)

            plt.tight_layout()
            pdf.savefig(fig)
            plt.close(fig)

    full_pdf_path = os.path.abspath(pdf_path)
    print(f"\n[성공] 특정 코인(일목+거래량+MACD+RSI) PDF 리포트 생성 완료!\n -> 저장 위치: '{full_pdf_path}'")

    if upload_gdrive:
        try:
            from upload_to_gdrive import upload_pdf_to_gdrive
            upload_pdf_to_gdrive(full_pdf_path, folder_name="report_daily", user_email="hhokyung@gmail.com")
        except Exception as e:
            print(f"구글 드라이브 업로드 안내: {e}")

    return full_pdf_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="특정 코인 일봉 기준 일목균형표(거래량 포함) + MACD + RSI PDF 보고서 생성기")
    parser.add_argument("coins", type=str, nargs="*", default=["오브스", "비트코인", "SOL"], help="분석할 코인명/심볼 (예: 오브스 비트코인 리플 SOL)")
    parser.add_argument("--count", type=int, default=200, help="조회할 일봉 봉 수 (기본값: 200)")
    
    args = parser.parse_args()
    
    print("=" * 90)
    print(f" [특정 코인 일봉 통합 지표 및 거래량 분석 리포터]")
    print(f" 대상 코인: {args.coins}")
    print("=" * 90)
    
    generate_special_coin_pdf(args.coins, count=args.count)
