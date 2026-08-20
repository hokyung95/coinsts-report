"""
========================================================================================
 [모듈 명]: onehour_report/onehour_report_pdf.py
 [구현 목적]:
   - 일봉 기준 일목균형표 전환선(9)이 기준선(30) 위에 위치하고,
     60분봉(1시간봉) 시계열 데이터 기준 일목균형표 전환선(9)이 기준선(30) 위에 위치한 코인을 포착
   - 60분봉 일목균형표(진한 거래량 포함), MACD, RSI 3단 시각화와
     일봉 일목균형표(진한 거래량 포함), MACD, RSI 3단 시각화를 같은 페이지에 나란히 PDF 리포트 생성
   - **저장 위치**: onehour_report/report/report_onehour_YYYYMMDDHHMMSS.pdf
========================================================================================
"""

import os
import sys

# 상위 디렉터리 모듈 임포트 가능하도록 sys.path 추가
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from onehour_report_pdf import generate_onehour_pdf_report, fetch_and_analyze_single_coin, get_krw_markets

if __name__ == "__main__":
    generate_onehour_pdf_report()
