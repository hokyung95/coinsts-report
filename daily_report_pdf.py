"""
========================================================================================
 [모듈 명]: daily_report_pdf.py (루트 래퍼)
 [구현 목적]: daily_report/daily_report_pdf.py 모듈 실행
========================================================================================
"""

import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
daily_report_dir = os.path.join(script_dir, "daily_report")
if daily_report_dir not in sys.path:
    sys.path.insert(0, daily_report_dir)

from daily_report_pdf import generate_daily_divergence_pdf

if __name__ == "__main__":
    generate_daily_divergence_pdf()
