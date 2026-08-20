"""
========================================================================================
 [모듈 명]: onehour_report/report_onhour_pdf.py
========================================================================================
"""

import os
import sys

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from onehour_report_pdf import generate_onehour_pdf_report

if __name__ == "__main__":
    generate_onehour_pdf_report()
