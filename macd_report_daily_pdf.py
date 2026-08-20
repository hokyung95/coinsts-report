"""
========================================================================================
 [모듈 명]: macd_report_daily_pdf.py (루트 래퍼)
 [구현 목적]: macd_report_daily/macd_report_daily_pdf.py 모듈 실행
========================================================================================
"""

import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
target_dir = os.path.join(script_dir, "macd_report_daily")
if target_dir not in sys.path:
    sys.path.insert(0, target_dir)

from macd_report_daily_pdf import generate_macd_daily_pdf_report

if __name__ == "__main__":
    generate_macd_daily_pdf_report()
