"""
NVIDIA Investor Relations - Full Document Scraper
Downloads all available IR documents (2022-2026):
- Quarterly Presentations
- CFO Commentary
- Quarterly Revenue Trends
- Earnings Call Transcripts
- 10-K Annual Reports (from SEC EDGAR)
- 10-Q Quarterly Reports (from SEC EDGAR)
- Historical Non-GAAP Measures

NVIDIA fiscal year ends in late January:
  FY23: Feb 2022 - Jan 2023 (Calendar 2022)
  FY24: Feb 2023 - Jan 2024 (Calendar 2023)
  FY25: Feb 2024 - Jan 2025 (Calendar 2024)
  FY26: Feb 2025 - Jan 2026 (Calendar 2025)
  FY27: Feb 2026 - Jan 2027 (Calendar 2026)
"""

import os
import sys
import time
import json
import requests
from pathlib import Path

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = BASE_DIR
LOG_FILE = BASE_DIR / "download_log.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
}

HEADERS_SEC = {
    "User-Agent": "Research Agent research@example.com",
    "Accept": "application/json",
}

Q4CDN = "https://s201.q4cdn.com/141608511/files"
NVDA_CIK = "0001045810"

# Fiscal quarters: (FY, FQ) covering calendar 2022-2026
FY_QUARTERS = [
    (23, 1), (23, 2), (23, 3), (23, 4),
    (24, 1), (24, 2), (24, 3), (24, 4),
    (25, 1), (25, 2), (25, 3), (25, 4),
    (26, 1), (26, 2), (26, 3), (26, 4),
    (27, 1), (27, 2),
]


def download_file(url, filepath, headers=None):
    """Download a file with retry logic."""
    if os.path.exists(filepath):
        with open(filepath, 'rb') as f:
            if f.read(5) == b'%PDF-':
                return True
        os.remove(filepath)

    if headers is None:
        headers = HEADERS

    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=60, stream=True)
            if resp.status_code == 200:
                content = resp.content
                if content[:5] == b'%PDF-' or content[:4] == b'PK\x03\x04' or len(content) > 10000:
                    with open(filepath, 'wb') as f:
                        f.write(content)
                    return True
            elif resp.status_code in [403, 404]:
                return False
        except Exception:
            pass
        time.sleep(2)
    return False


def try_urls(urls, filepath):
    """Try multiple URLs, return first successful one."""
    for url in urls:
        if download_file(url, filepath):
            size_mb = os.path.getsize(filepath) / (1024*1024)
            return True, size_mb
    return False, 0


def download_presentations():
    """Download quarterly investor presentations."""
    subdir = OUTPUT_DIR / "01_Quarterly_Presentation"
    subdir.mkdir(parents=True, exist_ok=True)
    results = []

    print("\n[1/6] Downloading Quarterly Presentations...")

    for fy, fq in FY_QUARTERS:
        filename = f"NVDA_FY{fy}_Q{fq}_Presentation.pdf"
        filepath = subdir / filename

        urls = [
            f"{Q4CDN}/doc_financials/20{fy}/q{fq}/NVDA-F{fq}Q{fy}-Quarterly-Presentation-FINAL.pdf",
            f"{Q4CDN}/doc_financials/20{fy}/q{fq}/NVDA-F{fq}Q{fy}-Quarterly-Presentation.pdf",
            f"{Q4CDN}/doc_financials/20{fy}/q{fq}/NVDA-F{fq}Q{fy}-Investor-Presentation-FINAL.pdf",
            f"{Q4CDN}/doc_financials/20{fy}/q{fq}/NVDA-F{fq}Q{fy}-Investor-Presentation_FINAL.pdf",
            f"{Q4CDN}/doc_financials/20{fy}/q{fq}/nvda-f{fq}q{fy}-investor-presentation-final.pdf",
            f"{Q4CDN}/doc_financials/20{fy}/q{fq}/nvda-f{fq}q{fy}-quarterly-presentation-final.pdf",
            f"{Q4CDN}/doc_presentations/20{fy-1 if fq <= 2 else fy}/NVDA-F{fq}Q{fy}-Investor-Presentation-FINAL.pdf",
            f"{Q4CDN}/doc_presentations/20{fy-1 if fq <= 2 else fy}/NVDA-F{fq}Q{fy}-Investor-Presentation-FINAL-(1).pdf",
        ]

        success, size = try_urls(urls, filepath)
        status = f"OK ({size:.1f}MB)" if success else "FAIL"
        print(f"  FY{fy} Q{fq}: {status}")
        results.append({"file": filename, "success": success})
        time.sleep(1)

    return results


def download_cfo_commentary():
    """Download CFO Commentary PDFs."""
    subdir = OUTPUT_DIR / "02_CFO_Commentary"
    subdir.mkdir(parents=True, exist_ok=True)
    results = []

    print("\n[2/6] Downloading CFO Commentary...")

    for fy, fq in FY_QUARTERS:
        filename = f"NVDA_FY{fy}_Q{fq}_CFO_Commentary.pdf"
        filepath = subdir / filename

        urls = [
            f"{Q4CDN}/doc_financials/20{fy}/Q{fq}{fy}/Q{fq}FY{fy}-CFO-Commentary.pdf",
            f"{Q4CDN}/doc_financials/20{fy}/Q{fq}FY{fy}/Q{fq}FY{fy}-CFO-Commentary.pdf",
            f"{Q4CDN}/doc_financials/20{fy}/Q{fq}FY{fy}-CFO-Commentary.pdf",
            f"{Q4CDN}/doc_financials/20{fy}/q{fq}/Q{fq}FY{fy}-CFO-Commentary.pdf",
            f"{Q4CDN}/doc_financials/20{fy}/Q{fq}{fy}/q{fq}fy{fy}-cfo-commentary.pdf",
            f"{Q4CDN}/doc_financials/20{fy}/Q{fq}23/Q{fq}FY{fy}-CFO-Commentary.pdf",
            f"{Q4CDN}/doc_financials/20{fy}/Q123/Q{fq}FY{fy}-CFO-Commentary.pdf",
        ]

        success, size = try_urls(urls, filepath)
        status = f"OK ({size:.1f}MB)" if success else "FAIL"
        print(f"  FY{fy} Q{fq}: {status}")
        results.append({"file": filename, "success": success})
        time.sleep(1)

    return results


def download_revenue_trends():
    """Download Quarterly Revenue Trend PDFs."""
    subdir = OUTPUT_DIR / "03_Revenue_Trend"
    subdir.mkdir(parents=True, exist_ok=True)
    results = []

    print("\n[3/6] Downloading Revenue Trends...")

    for fy, fq in FY_QUARTERS:
        filename = f"NVDA_FY{fy}_Q{fq}_Revenue_Trend.pdf"
        filepath = subdir / filename

        urls = [
            f"{Q4CDN}/doc_financials/20{fy}/q{fq}/NVIDIA-Quarterly-Revenue-Trend.pdf",
            f"{Q4CDN}/doc_financials/20{fy}/Q{fq}{fy}/NVIDIA-Quarterly-Revenue-Trend.pdf",
            f"{Q4CDN}/doc_financials/20{fy}/Q{fq}FY{fy}/NVIDIA-Quarterly-Revenue-Trend.pdf",
            f"{Q4CDN}/doc_financials/20{fy}/q{fq}/nvidia-quarterly-revenue-trend.pdf",
        ]

        success, size = try_urls(urls, filepath)
        status = f"OK ({size:.1f}MB)" if success else "FAIL"
        print(f"  FY{fy} Q{fq}: {status}")
        results.append({"file": filename, "success": success})
        time.sleep(1)

    return results


def download_transcripts():
    """Download Earnings Call Transcripts."""
    subdir = OUTPUT_DIR / "04_Earnings_Transcript"
    subdir.mkdir(parents=True, exist_ok=True)
    results = []

    print("\n[4/6] Downloading Earnings Transcripts...")

    for fy, fq in FY_QUARTERS:
        filename = f"NVDA_FY{fy}_Q{fq}_Transcript.pdf"
        filepath = subdir / filename

        urls = [
            f"{Q4CDN}/doc_financials/20{fy}/q{fq}/NVDA-F{fq}Q{fy}-Earnings-Call-Transcript.pdf",
            f"{Q4CDN}/doc_financials/20{fy}/Q{fq}{fy}/NVDA-F{fq}Q{fy}-Earnings-Call-Transcript.pdf",
            f"{Q4CDN}/doc_financials/20{fy}/q{fq}/Rev-1-NVDA-F{fq}Q{fy}-Earnings-Call-Transcript.pdf",
        ]

        success, size = try_urls(urls, filepath)
        status = f"OK ({size:.1f}MB)" if success else "FAIL"
        print(f"  FY{fy} Q{fq}: {status}")
        results.append({"file": filename, "success": success})
        time.sleep(1)

    return results


def download_sec_filings():
    """Download 10-K and 10-Q from SEC EDGAR."""
    subdir_10k = OUTPUT_DIR / "05_SEC_10K"
    subdir_10q = OUTPUT_DIR / "06_SEC_10Q"
    subdir_10k.mkdir(parents=True, exist_ok=True)
    subdir_10q.mkdir(parents=True, exist_ok=True)
    results = []

    print("\n[5/6] Downloading SEC Filings (10-K, 10-Q)...")

    try:
        url = f"https://data.sec.gov/submissions/CIK{NVDA_CIK}.json"
        resp = requests.get(url, headers=HEADERS_SEC, timeout=30)
        if resp.status_code != 200:
            print(f"  ERROR: Cannot fetch SEC data (HTTP {resp.status_code})")
            return results

        data = resp.json()
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accessions = recent.get("accessionNumber", [])
        dates = recent.get("filingDate", [])
        primary_docs = recent.get("primaryDocument", [])

        for i, form in enumerate(forms):
            if form not in ["10-K", "10-Q"]:
                continue

            filing_date = dates[i]
            year = int(filing_date[:4])
            if year < 2022:
                continue

            accession = accessions[i].replace("-", "")
            doc = primary_docs[i]
            doc_url = f"https://www.sec.gov/Archives/edgar/data/{int(NVDA_CIK)}/{accession}/{doc}"

            if form == "10-K":
                filename = f"NVDA_{filing_date}_10K.htm"
                filepath = subdir_10k / filename
            else:
                filename = f"NVDA_{filing_date}_10Q.htm"
                filepath = subdir_10q / filename

            if filepath.exists():
                print(f"  [SKIP] {filename}")
                results.append({"file": filename, "success": True})
                continue

            try:
                r = requests.get(doc_url, headers=HEADERS_SEC, timeout=60)
                if r.status_code == 200:
                    with open(filepath, 'wb') as f:
                        f.write(r.content)
                    size_mb = len(r.content) / (1024*1024)
                    print(f"  [OK] {filename} ({size_mb:.1f}MB)")
                    results.append({"file": filename, "success": True})
                else:
                    print(f"  [FAIL] {filename} (HTTP {r.status_code})")
                    results.append({"file": filename, "success": False})
            except Exception as e:
                print(f"  [ERROR] {filename}: {e}")
                results.append({"file": filename, "success": False})

            time.sleep(1)

    except Exception as e:
        print(f"  ERROR: {e}")

    return results


def download_non_gaap():
    """Download Historical Non-GAAP measures."""
    subdir = OUTPUT_DIR / "07_Non_GAAP_Historical"
    subdir.mkdir(parents=True, exist_ok=True)
    results = []

    print("\n[6/6] Downloading Historical Non-GAAP Measures...")

    for fy, fq in FY_QUARTERS:
        filename = f"NVDA_FY{fy}_Q{fq}_Non_GAAP.pdf"
        filepath = subdir / filename

        urls = [
            f"{Q4CDN}/doc_financials/20{fy}/q{fq}/NVDA-Historical-Non-GAAP-Financial-Measures-Including-SBC-Expense.pdf",
            f"{Q4CDN}/doc_financials/20{fy}/Q{fq}{fy}/NVDA-Historical-Non-GAAP-Financial-Measures-Including-SBC-Expense.pdf",
        ]

        success, size = try_urls(urls, filepath)
        status = f"OK ({size:.1f}MB)" if success else "FAIL"
        print(f"  FY{fy} Q{fq}: {status}")
        results.append({"file": filename, "success": success})
        time.sleep(1)

    return results


def main():
    print("=" * 60)
    print("NVIDIA Full IR Document Scraper (2022-2026)")
    print("=" * 60)

    all_results = {}
    all_results["presentations"] = download_presentations()
    all_results["cfo_commentary"] = download_cfo_commentary()
    all_results["revenue_trends"] = download_revenue_trends()
    all_results["transcripts"] = download_transcripts()
    all_results["sec_filings"] = download_sec_filings()
    all_results["non_gaap"] = download_non_gaap()

    # Summary
    print("\n" + "=" * 60)
    print("DOWNLOAD SUMMARY")
    print("=" * 60)
    total_success = 0
    total_fail = 0
    for category, items in all_results.items():
        success = sum(1 for x in items if x["success"])
        fail = len(items) - success
        total_success += success
        total_fail += fail
        print(f"  {category}: {success}/{len(items)} downloaded")

    print(f"\n  TOTAL: {total_success} success, {total_fail} failed")

    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump({"company": "NVIDIA", "ticker": "NVDA", "results": all_results,
                   "total_success": total_success, "total_failed": total_fail}, f, indent=2)

    print(f"\nLog saved: {LOG_FILE}")


if __name__ == "__main__":
    main()
