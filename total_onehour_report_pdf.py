"""
========================================================================================
 [모듈 명]: total_onehour_report_pdf.py (루트 래퍼)
 [구현 목적]: total_onehour_report/total_onehour_report_pdf.py 모듈 실행
========================================================================================
"""

import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
target_dir = os.path.join(script_dir, "total_onehour_report")
if target_dir not in sys.path:
    sys.path.insert(0, target_dir)

from total_onehour_report_pdf import generate_total_onehour_pdf_report

if __name__ == "__main__":
    generate_total_onehour_pdf_report()
