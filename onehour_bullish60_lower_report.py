"""
========================================================================================
 [모듈 명]: onehour_bullish60_lower_report.py (루트 래퍼)
 [구현 목적]: onehour_report/onehour_bullish60_lower_report.py 모듈 실행
========================================================================================
"""

import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
target_dir = os.path.join(script_dir, "onehour_report")
if target_dir not in sys.path:
    sys.path.insert(0, target_dir)

from onehour_bullish60_lower_report import generate_onehour_bullish60_lower_pdf_report

if __name__ == "__main__":
    generate_onehour_bullish60_lower_pdf_report()
