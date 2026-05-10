"""
Meta Platforms Investor Relations - Full Document Scraper
Downloads all available IR documents (2022-2026):
- Quarterly Earnings Presentations
- Earnings Call Transcripts
- Prepared Remarks
- Earnings Press Releases
- 10-K Annual Reports (from SEC EDGAR)
- 10-Q Quarterly Reports (from SEC EDGAR)

Meta uses calendar year quarters (Q1=Jan-Mar, Q2=Apr-Jun, Q3=Jul-Sep, Q4=Oct-Dec)
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

Q4CDN = "https://s21.q4cdn.com/399680738/files"
META_CIK = "0001326801"

# Calendar year quarters to scrape
YEARS = [2022, 2023, 2024, 2025, 2026]
QUARTERS = [1, 2, 3, 4]


def download_file(url, filepath, headers=None):
    """Download a file with retry logic."""
    if os.path.exists(filepath):
        with open(filepath, 'rb') as f:
            header = f.read(5)
            if header == b'%PDF-' or header[:4] == b'PK\x03\x04':
                return True
        os.remove(filepath)

    if headers is None:
        headers = HEADERS

    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=60)
            if resp.status_code == 200:
                content = resp.content
                if content[:5] == b'%PDF-' or len(content) > 10000:
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
    """Download quarterly earnings presentations."""
    subdir = OUTPUT_DIR / "01_Earnings_Presentation"
    subdir.mkdir(parents=True, exist_ok=True)
    results = []

    print("\n[1/5] Downloading Earnings Presentations...")

    for year in YEARS:
        for q in QUARTERS:
            filename = f"META_{year}_Q{q}_Earnings_Presentation.pdf"
            filepath = subdir / filename

            urls = [
                f"{Q4CDN}/doc_financials/{year}/q{q}/Earnings-Presentation-Q{q}-{year}.pdf",
                f"{Q4CDN}/doc_financials/{year}/q{q}/Earnings-Presentation-Q{q}-{year}-FINAL.pdf",
                f"{Q4CDN}/doc_financials/{year}/q{q}/Earnings-Presentation-Q{q}-{year}-Final.pdf",
                f"{Q4CDN}/doc_financials/{year}/q{q}/Q{q}-{year}_Earnings-Presentation.pdf",
                f"{Q4CDN}/doc_earnings/{year}/q{q}/presentation/Earnings-Presentation-Q{q}-{year}.pdf",
                f"{Q4CDN}/doc_earnings/{year}/q{q}/Earnings-Presentation-Q{q}-{year}.pdf",
                f"{Q4CDN}/doc_financials/{year}/q{q}/Meta-Earnings-Presentation-Q{q}-{year}.pdf",
            ]

            success, size = try_urls(urls, filepath)
            status = f"OK ({size:.1f}MB)" if success else "FAIL"
            print(f"  {year} Q{q}: {status}")
            results.append({"file": filename, "success": success})
            time.sleep(1)

    return results


def download_transcripts():
    """Download earnings call transcripts."""
    subdir = OUTPUT_DIR / "02_Earnings_Transcript"
    subdir.mkdir(parents=True, exist_ok=True)
    results = []

    print("\n[2/5] Downloading Earnings Call Transcripts...")

    for year in YEARS:
        for q in QUARTERS:
            filename = f"META_{year}_Q{q}_Transcript.pdf"
            filepath = subdir / filename

            urls = [
                f"{Q4CDN}/doc_financials/{year}/q{q}/META-Q{q}-{year}-Earnings-Call-Transcript.pdf",
                f"{Q4CDN}/doc_financials/{year}/q{q}/Transcripts/META-Q{q}-{year}-Earnings-Call-Transcript.pdf",
                f"{Q4CDN}/doc_financials/{year}/q{q}/Transcripts/META-Q{q}-{year}-Earnings-Call-Transcript-1.pdf",
                f"{Q4CDN}/doc_financials/{year}/q{q}/Meta-Q{q}-{year}-Earnings-Call-Transcript.pdf",
                f"{Q4CDN}/doc_earnings/{year}/q{q}/transcript/META-Q{q}-{year}-Earnings-Call-Transcript.pdf",
                f"{Q4CDN}/doc_earnings/{year}/q{q}/generic/META-Q{q}-{year}-Earnings-Call-Transcript.pdf",
            ]

            success, size = try_urls(urls, filepath)
            status = f"OK ({size:.1f}MB)" if success else "FAIL"
            print(f"  {year} Q{q}: {status}")
            results.append({"file": filename, "success": success})
            time.sleep(1)

    return results


def download_prepared_remarks():
    """Download prepared remarks."""
    subdir = OUTPUT_DIR / "03_Prepared_Remarks"
    subdir.mkdir(parents=True, exist_ok=True)
    results = []

    print("\n[3/5] Downloading Prepared Remarks...")

    for year in YEARS:
        for q in QUARTERS:
            filename = f"META_{year}_Q{q}_Prepared_Remarks.pdf"
            filepath = subdir / filename

            urls = [
                f"{Q4CDN}/doc_financials/{year}/q{q}/META-Q{q}-{year}-Prepared-Remarks.pdf",
                f"{Q4CDN}/doc_downloads/{year}/META-Q{q}-{year}-Prepared-Remarks.pdf",
                f"{Q4CDN}/doc_earnings/{year}/q{q}/generic/META-Q{q}-{year}-Prepared-Remarks.pdf",
                f"{Q4CDN}/doc_financials/{year}/q{q}/Meta-Q{q}-{year}-Prepared-Remarks.pdf",
            ]

            success, size = try_urls(urls, filepath)
            status = f"OK ({size:.1f}MB)" if success else "FAIL"
            print(f"  {year} Q{q}: {status}")
            results.append({"file": filename, "success": success})
            time.sleep(1)

    return results


def download_press_releases():
    """Download earnings press releases."""
    subdir = OUTPUT_DIR / "04_Press_Release"
    subdir.mkdir(parents=True, exist_ok=True)
    results = []

    print("\n[4/5] Downloading Earnings Press Releases...")

    quarter_names = {1: "First", 2: "Second", 3: "Third", 4: "Fourth"}

    for year in YEARS:
        for q in QUARTERS:
            filename = f"META_{year}_Q{q}_Press_Release.pdf"
            filepath = subdir / filename
            qname = quarter_names[q]

            urls = [
                f"{Q4CDN}/doc_news/Meta-Reports-{qname}-Quarter-{year}-Results-{year}.pdf",
                f"{Q4CDN}/doc_news/Meta-Reports-{qname}-Quarter-and-Full-Year-{year}-Results-{year+1}.pdf",
                f"{Q4CDN}/doc_financials/{year}/q{q}/META-Q{q}-{year}-Earnings-Release.pdf",
                f"{Q4CDN}/doc_financials/{year}/q{q}/Meta-03-31-{year}-Exhibit-99-1_FINAL.pdf" if q == 1 else "",
                f"{Q4CDN}/doc_financials/{year}/q{q}/Meta-{year}-Q{q}-Earnings-Release.pdf",
            ]
            urls = [u for u in urls if u]

            success, size = try_urls(urls, filepath)
            status = f"OK ({size:.1f}MB)" if success else "FAIL"
            print(f"  {year} Q{q}: {status}")
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

    print("\n[5/5] Downloading SEC Filings (10-K, 10-Q)...")

    try:
        url = f"https://data.sec.gov/submissions/CIK{META_CIK}.json"
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
            doc_url = f"https://www.sec.gov/Archives/edgar/data/{int(META_CIK)}/{accession}/{doc}"

            if form == "10-K":
                filename = f"META_{filing_date}_10K.htm"
                filepath = subdir_10k / filename
            else:
                filename = f"META_{filing_date}_10Q.htm"
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


def main():
    print("=" * 60)
    print("Meta Platforms Full IR Document Scraper (2022-2026)")
    print("=" * 60)

    all_results = {}
    all_results["presentations"] = download_presentations()
    all_results["transcripts"] = download_transcripts()
    all_results["prepared_remarks"] = download_prepared_remarks()
    all_results["press_releases"] = download_press_releases()
    all_results["sec_filings"] = download_sec_filings()

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
        json.dump({"company": "Meta Platforms", "ticker": "META", "results": all_results,
                   "total_success": total_success, "total_failed": total_fail}, f, indent=2)

    print(f"\nLog saved: {LOG_FILE}")


if __name__ == "__main__":
    main()
