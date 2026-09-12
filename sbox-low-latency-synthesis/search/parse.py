# optimizer/parse.py
import re

def get_delay(log_text):
    match = re.search(r"delay\s*=\s*([\d.]+)", log_text, re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None

def get_cell_count(log_text):
    match = re.search(r"Number of cells:\s+(\d+)", log_text)
    if match:
        return int(match.group(1))
    return None