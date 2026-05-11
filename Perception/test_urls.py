import requests

urls_to_test = [
    ("NVDA FY25Q2", "https://s201.q4cdn.com/141608511/files/doc_financials/2025/q2/NVDA-F2Q25-Quarterly-Presentation-FINAL.pdf"),
    ("NVDA FY24Q4", "https://s201.q4cdn.com/141608511/files/doc_financials/2024/q4/NVDA-F4Q24-Quarterly-Presentation-FINAL.pdf"),
    ("META 2024Q2", "https://s21.q4cdn.com/399680738/files/doc_financials/2024/q2/Earnings-Presentation-Q2-2024.pdf"),
    ("META 2024Q4", "https://s21.q4cdn.com/399680738/files/doc_financials/2024/q4/Earnings-Presentation-Q4-2024.pdf"),
]

headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

for name, url in urls_to_test:
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        is_pdf = resp.content[:5] == b'%PDF-'
        print(f"{name}: status={resp.status_code}, is_pdf={is_pdf}, size={len(resp.content)}")
    except Exception as e:
        print(f"{name}: ERROR {e}")
