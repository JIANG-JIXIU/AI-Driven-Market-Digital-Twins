"""
Tesla 投资者关系文档爬取脚本
爬取范围：2022-2026年的季度报告、年报、新闻稿、Update Deck等
数据来源：
1. SEC EDGAR (10-K, 10-Q 等SEC申报文件)
2. Tesla IR 资产服务器 (Update Deck PDF)
3. Tesla IR 官网 (新闻稿等)
"""

import os
import sys
import re
import json
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime

# 修复Windows控制台编码问题
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ============ 配置 ============
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "tesla_ir_docs")
LOG_FILE = os.path.join(OUTPUT_DIR, "download_log.json")

# Tesla CIK号码 (SEC EDGAR使用)
TESLA_CIK = "0001318605"

# 年份范围
YEARS = [2022, 2023, 2024, 2025, 2026]
QUARTERS = ["Q1", "Q2", "Q3", "Q4"]

# 请求头 - 模拟浏览器访问
HEADERS_BROWSER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
}

# SEC EDGAR 要求提供身份信息
HEADERS_SEC = {
    "User-Agent": "Research Agent research@example.com",
    "Accept": "application/json",
}


def ensure_dir(path):
    """确保目录存在"""
    os.makedirs(path, exist_ok=True)


def safe_filename(name):
    """生成安全的文件名"""
    return re.sub(r'[<>:"/\\|?*]', '_', name)


def download_file(url, filepath, headers=None):
    """下载文件，带重试机制"""
    if os.path.exists(filepath):
        print(f"  [跳过] 已存在: {os.path.basename(filepath)}")
        return True

    if headers is None:
        headers = HEADERS_BROWSER

    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=60, stream=True)
            if resp.status_code == 200:
                with open(filepath, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                size_mb = os.path.getsize(filepath) / (1024 * 1024)
                print(f"  [成功] {os.path.basename(filepath)} ({size_mb:.2f} MB)")
                return True
            elif resp.status_code == 403:
                print(f"  [拒绝] 403 Forbidden: {url}")
                return False
            elif resp.status_code == 404:
                print(f"  [不存在] 404: {url}")
                return False
            else:
                print(f"  [失败] HTTP {resp.status_code}: {url} (尝试 {attempt+1}/3)")
        except requests.exceptions.RequestException as e:
            print(f"  [错误] {e} (尝试 {attempt+1}/3)")
        time.sleep(2)

    return False


def download_update_decks():
    """
    下载季度更新演示文稿 (Quarterly Update Deck)
    Tesla使用两个CDN：
    - 旧版(2022-2025 Q2): https://digitalassets.tesla.com/tesla-contents/image/upload/IR/TSLA-{Q}-{YEAR}-Update.pdf
    - 新版(2025 Q3+): https://assets-ir.tesla.com/tesla-contents/IR/TSLA-{Q}-{YEAR}-Update.pdf
    """
    print("\n" + "="*60)
    print("[下载] Quarterly Update Deck（季度更新演示文稿）")
    print("="*60)

    subdir = os.path.join(OUTPUT_DIR, "01_Quarterly_Update_Deck")
    ensure_dir(subdir)

    # 需要Referer头才能通过Tesla CDN的验证
    tesla_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "application/pdf,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://ir.tesla.com/",
        "Origin": "https://ir.tesla.com",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-site",
    }

    results = []
    for year in YEARS:
        for q in QUARTERS:
            filename = f"Tesla_{year}_{q}_Update_Deck.pdf"
            filepath = os.path.join(subdir, filename)

            if os.path.exists(filepath):
                # 验证是否为有效PDF
                with open(filepath, 'rb') as f:
                    if f.read(5) == b'%PDF-':
                        print(f"\n[跳过] {filename} 已存在且有效")
                        results.append({"type": "Update Deck", "year": year, "quarter": q, "filename": filename, "success": True})
                        continue
                    else:
                        os.remove(filepath)

            # 尝试多个URL源
            urls_to_try = [
                f"https://digitalassets.tesla.com/tesla-contents/image/upload/IR/TSLA-{q}-{year}-Update.pdf",
                f"https://assets-ir.tesla.com/tesla-contents/IR/TSLA-{q}-{year}-Update.pdf",
            ]

            print(f"\n尝试下载: {year} {q} Update Deck")
            success = False
            for url in urls_to_try:
                try:
                    resp = requests.get(url, headers=tesla_headers, timeout=60)
                    if resp.status_code == 200 and resp.content[:5] == b'%PDF-':
                        with open(filepath, 'wb') as f:
                            f.write(resp.content)
                        size_mb = len(resp.content) / (1024 * 1024)
                        print(f"  [成功] {filename} ({size_mb:.2f} MB)")
                        success = True
                        break
                except Exception as e:
                    continue

            if not success:
                print(f"  [未找到] {filename}")

            results.append({
                "type": "Update Deck",
                "year": year,
                "quarter": q,
                "filename": filename,
                "success": success
            })
            time.sleep(1.5)

    return results


def download_sec_filings():
    """
    从 SEC EDGAR 下载 10-K（年报）和 10-Q（季报）
    使用 EDGAR Full-Text Search API
    """
    print("\n" + "="*60)
    print("📋 下载 SEC 申报文件 (10-K 年报 / 10-Q 季报)")
    print("="*60)

    subdir_10k = os.path.join(OUTPUT_DIR, "02_SEC_10K_Annual_Report")
    subdir_10q = os.path.join(OUTPUT_DIR, "03_SEC_10Q_Quarterly_Report")
    subdir_8k = os.path.join(OUTPUT_DIR, "04_SEC_8K_Current_Report")
    ensure_dir(subdir_10k)
    ensure_dir(subdir_10q)
    ensure_dir(subdir_8k)

    results = []

    # 使用 EDGAR API 获取 Tesla 的申报列表
    # 先获取公司的申报索引
    submissions_url = f"https://data.sec.gov/submissions/CIK{TESLA_CIK}.json"
    print(f"\n获取 Tesla SEC 申报索引...")

    try:
        resp = requests.get(submissions_url, headers=HEADERS_SEC, timeout=30)
        if resp.status_code != 200:
            print(f"  [错误] 无法获取SEC数据: HTTP {resp.status_code}")
            return results

        data = resp.json()
        recent = data.get("filings", {}).get("recent", {})

        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accession_numbers = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])

        print(f"  找到 {len(forms)} 个申报记录，筛选2022-2026年...")

        for i, (form, date, accession, doc) in enumerate(
            zip(forms, dates, accession_numbers, primary_docs)
        ):
            filing_year = int(date[:4])
            if filing_year < 2022 or filing_year > 2026:
                continue

            # 只下载 10-K, 10-Q, 8-K
            if form not in ["10-K", "10-Q", "8-K"]:
                continue

            # 构造下载URL
            accession_no_dash = accession.replace("-", "")
            file_url = f"https://www.sec.gov/Archives/edgar/data/{TESLA_CIK}/{accession_no_dash}/{doc}"

            # 确定保存目录和文件名
            if form == "10-K":
                subdir = subdir_10k
                filename = f"Tesla_{filing_year}_10K_Annual_Report_{date}.pdf"
            elif form == "10-Q":
                subdir = subdir_10q
                filename = f"Tesla_{filing_year}_10Q_Quarterly_{date}.pdf"
            else:  # 8-K
                subdir = subdir_8k
                filename = f"Tesla_{filing_year}_8K_{date}.pdf"

            # 如果文件扩展名不是pdf，保留原始扩展名
            if doc.endswith(".htm") or doc.endswith(".html"):
                filename = filename.replace(".pdf", ".html")

            filepath = os.path.join(subdir, safe_filename(filename))

            print(f"\n下载 {form} ({date}): {doc}")
            success = download_file(file_url, filepath, headers=HEADERS_SEC)
            results.append({
                "type": f"SEC {form}",
                "year": filing_year,
                "date": date,
                "url": file_url,
                "filename": filename,
                "success": success
            })
            time.sleep(0.5)  # SEC EDGAR 限流

    except Exception as e:
        print(f"  [错误] SEC EDGAR 请求失败: {e}")

    return results


def download_press_releases():
    """
    下载财报新闻稿 (Press Release)
    尝试从Tesla IR获取，如果失败则从SEC 8-K中提取
    """
    print("\n" + "="*60)
    print("📰 下载 Press Release（新闻稿/财报公告）")
    print("="*60)

    subdir = os.path.join(OUTPUT_DIR, "05_Press_Release")
    ensure_dir(subdir)

    results = []

    # Tesla 新闻稿通常通过8-K提交到SEC，也可以直接尝试IR页面
    # 尝试从 Tesla IR 直接获取
    # 已知URL格式
    press_release_urls = []

    for year in YEARS:
        for q in QUARTERS:
            # Tesla 通常在财报日发布新闻稿，尝试多种URL格式
            urls_to_try = [
                f"https://ir.tesla.com/press-release/tesla-vehicle-production-deliveries-and-deployments-{q.lower()}-{year}",
                f"https://ir.tesla.com/press-release/tesla-{q.lower()}-{year}-financial-results",
            ]
            press_release_urls.append((year, q, urls_to_try))

    # 尝试用 SEC EDGAR EFTS 搜索新闻稿类型的8-K
    print("\n从 SEC EDGAR 搜索 Tesla 财报相关8-K新闻稿...")
    search_url = "https://efts.sec.gov/LATEST/search-index?q=%22financial+results%22&dateRange=custom&startdt=2022-01-01&enddt=2026-12-31&forms=8-K&entities=Tesla"

    # 使用更可靠的方式 - 从已下载的SEC数据中提取
    # 新闻稿通常作为8-K的附件(Exhibit 99.1)
    submissions_url = f"https://data.sec.gov/submissions/CIK{TESLA_CIK}.json"

    try:
        resp = requests.get(submissions_url, headers=HEADERS_SEC, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            recent = data.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])
            accession_numbers = recent.get("accessionNumber", [])

            # 找到8-K filing，然后获取其exhibit 99.1
            for i, (form, date, accession) in enumerate(zip(forms, dates, accession_numbers)):
                filing_year = int(date[:4])
                if filing_year < 2022 or filing_year > 2026:
                    continue
                if form != "8-K":
                    continue

                # 获取该8-K的详细文件列表
                accession_no_dash = accession.replace("-", "")
                index_url = f"https://www.sec.gov/Archives/edgar/data/{TESLA_CIK}/{accession_no_dash}/index.json"

                try:
                    idx_resp = requests.get(index_url, headers=HEADERS_SEC, timeout=15)
                    if idx_resp.status_code == 200:
                        idx_data = idx_resp.json()
                        directory = idx_data.get("directory", {})
                        items = directory.get("item", [])

                        for item in items:
                            name = item.get("name", "")
                            # 查找 exhibit 99.1 (通常是新闻稿)
                            if "ex99" in name.lower() or "exhibit99" in name.lower() or "press" in name.lower():
                                file_url = f"https://www.sec.gov/Archives/edgar/data/{TESLA_CIK}/{accession_no_dash}/{name}"
                                ext = os.path.splitext(name)[1] or ".html"
                                filename = f"Tesla_{date}_Press_Release_8K{ext}"
                                filepath = os.path.join(subdir, safe_filename(filename))

                                print(f"\n下载新闻稿附件 ({date}): {name}")
                                success = download_file(file_url, filepath, headers=HEADERS_SEC)
                                results.append({
                                    "type": "Press Release (8-K Exhibit)",
                                    "year": filing_year,
                                    "date": date,
                                    "url": file_url,
                                    "filename": filename,
                                    "success": success
                                })
                                time.sleep(0.3)
                                break  # 每个8-K只取第一个press release

                except Exception as e:
                    continue

                time.sleep(0.3)

    except Exception as e:
        print(f"  [错误] 获取新闻稿失败: {e}")

    return results


def download_earnings_transcripts():
    """
    下载/记录财报电话会议信息
    注意：音频文件通常需要特殊认证，这里记录链接信息
    """
    print("\n" + "="*60)
    print("🎙️ 财报电话会议 (Earnings Call) 信息")
    print("="*60)

    subdir = os.path.join(OUTPUT_DIR, "06_Earnings_Call_Info")
    ensure_dir(subdir)

    # 生成一个信息文件，记录电话会议的常规获取方式
    info = {
        "说明": "Tesla财报电话会议(Earnings Call)音频通常通过实时网络研讨会提供",
        "获取方式": [
            "1. Tesla IR官网会在财报发布后提供Webcast回放链接",
            "2. 第三方平台如Seeking Alpha、The Motley Fool等通常提供文字转录(Transcript)",
            "3. YouTube上通常有Tesla官方或第三方录制的完整电话会议视频",
        ],
        "已知季度": []
    }

    for year in YEARS:
        for q in QUARTERS:
            info["已知季度"].append({
                "quarter": f"{year} {q}",
                "webcast_search": f"Tesla {q} {year} earnings call webcast",
                "transcript_search": f"Tesla {q} {year} earnings call transcript",
            })

    info_path = os.path.join(subdir, "earnings_call_info.json")
    with open(info_path, 'w', encoding='utf-8') as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    print(f"  已保存电话会议获取指南: {info_path}")

    return [{"type": "Earnings Call Info", "filename": "earnings_call_info.json", "success": True}]


def download_proxy_statements():
    """
    下载代理声明书 (Proxy Statement / DEF 14A)
    """
    print("\n" + "="*60)
    print("📜 下载 Proxy Statement（代理声明书/股东大会材料）")
    print("="*60)

    subdir = os.path.join(OUTPUT_DIR, "07_Proxy_Statement")
    ensure_dir(subdir)

    results = []

    submissions_url = f"https://data.sec.gov/submissions/CIK{TESLA_CIK}.json"

    try:
        resp = requests.get(submissions_url, headers=HEADERS_SEC, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            recent = data.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])
            accession_numbers = recent.get("accessionNumber", [])
            primary_docs = recent.get("primaryDocument", [])

            for form, date, accession, doc in zip(forms, dates, accession_numbers, primary_docs):
                filing_year = int(date[:4])
                if filing_year < 2022 or filing_year > 2026:
                    continue
                if form not in ["DEF 14A", "PRE 14A", "DEFA14A"]:
                    continue

                accession_no_dash = accession.replace("-", "")
                file_url = f"https://www.sec.gov/Archives/edgar/data/{TESLA_CIK}/{accession_no_dash}/{doc}"

                ext = os.path.splitext(doc)[1] or ".html"
                filename = f"Tesla_{filing_year}_Proxy_Statement_{form}_{date}{ext}"
                filepath = os.path.join(subdir, safe_filename(filename))

                print(f"\n下载 {form} ({date})")
                success = download_file(file_url, filepath, headers=HEADERS_SEC)
                results.append({
                    "type": f"Proxy Statement ({form})",
                    "year": filing_year,
                    "date": date,
                    "url": file_url,
                    "filename": filename,
                    "success": success
                })
                time.sleep(0.5)

    except Exception as e:
        print(f"  [错误] {e}")

    return results


def download_additional_sec_filings():
    """
    下载额外的SEC申报文件页（如果第一页不够，获取更多历史数据）
    """
    print("\n" + "="*60)
    print("📂 检查是否有更多历史SEC申报文件...")
    print("="*60)

    results = []
    subdir_10k = os.path.join(OUTPUT_DIR, "02_SEC_10K_Annual_Report")
    subdir_10q = os.path.join(OUTPUT_DIR, "03_SEC_10Q_Quarterly_Report")

    # SEC EDGAR 的 submissions JSON 可能有多页
    # 检查 files 字段中的额外文件
    submissions_url = f"https://data.sec.gov/submissions/CIK{TESLA_CIK}.json"

    try:
        resp = requests.get(submissions_url, headers=HEADERS_SEC, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            filing_files = data.get("filings", {}).get("files", [])

            for file_info in filing_files:
                file_name = file_info.get("name", "")
                if not file_name:
                    continue

                extra_url = f"https://data.sec.gov/submissions/{file_name}"
                print(f"\n获取额外申报列表: {file_name}")

                try:
                    extra_resp = requests.get(extra_url, headers=HEADERS_SEC, timeout=30)
                    if extra_resp.status_code == 200:
                        extra_data = extra_resp.json()
                        forms = extra_data.get("form", [])
                        dates = extra_data.get("filingDate", [])
                        accession_numbers = extra_data.get("accessionNumber", [])
                        primary_docs = extra_data.get("primaryDocument", [])

                        for form, date, accession, doc in zip(forms, dates, accession_numbers, primary_docs):
                            filing_year = int(date[:4])
                            if filing_year < 2022 or filing_year > 2026:
                                continue
                            if form not in ["10-K", "10-Q"]:
                                continue

                            accession_no_dash = accession.replace("-", "")
                            file_url = f"https://www.sec.gov/Archives/edgar/data/{TESLA_CIK}/{accession_no_dash}/{doc}"

                            if form == "10-K":
                                subdir = subdir_10k
                                filename = f"Tesla_{filing_year}_10K_Annual_Report_{date}.pdf"
                            else:
                                subdir = subdir_10q
                                filename = f"Tesla_{filing_year}_10Q_Quarterly_{date}.pdf"

                            if doc.endswith(".htm") or doc.endswith(".html"):
                                filename = filename.replace(".pdf", ".html")

                            filepath = os.path.join(subdir, safe_filename(filename))

                            if os.path.exists(filepath):
                                continue

                            print(f"  下载 {form} ({date})")
                            success = download_file(file_url, filepath, headers=HEADERS_SEC)
                            results.append({
                                "type": f"SEC {form}",
                                "year": filing_year,
                                "date": date,
                                "filename": filename,
                                "success": success
                            })
                            time.sleep(0.5)

                except Exception as e:
                    print(f"  [错误] {e}")
                    continue

    except Exception as e:
        print(f"  [错误] {e}")

    return results


def generate_summary(all_results):
    """生成下载汇总报告"""
    print("\n" + "="*60)
    print("📊 下载汇总报告")
    print("="*60)

    success_count = sum(1 for r in all_results if r.get("success"))
    fail_count = sum(1 for r in all_results if not r.get("success"))

    print(f"\n总计尝试: {len(all_results)} 个文件")
    print(f"成功下载: {success_count} 个")
    print(f"下载失败: {fail_count} 个")

    # 按类型统计
    type_stats = {}
    for r in all_results:
        t = r.get("type", "Unknown")
        if t not in type_stats:
            type_stats[t] = {"success": 0, "fail": 0}
        if r.get("success"):
            type_stats[t]["success"] += 1
        else:
            type_stats[t]["fail"] += 1

    print("\n按类型统计:")
    for t, stats in type_stats.items():
        print(f"  {t}: 成功 {stats['success']}, 失败 {stats['fail']}")

    # 保存完整日志
    log_data = {
        "download_time": datetime.now().isoformat(),
        "summary": {
            "total_attempted": len(all_results),
            "total_success": success_count,
            "total_failed": fail_count,
            "by_type": type_stats
        },
        "details": all_results
    }

    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)
    print(f"\n详细日志已保存: {LOG_FILE}")

    # 生成目录说明文件
    readme_content = """Tesla 投资者关系文档目录说明
========================================

目录结构：
├── 01_Quarterly_Update_Deck/    - 季度更新演示文稿 (最核心的季度数据概览)
├── 02_SEC_10K_Annual_Report/    - 年度报告 10-K (最全面的年度财务信息)
├── 03_SEC_10Q_Quarterly_Report/ - 季度报告 10-Q (详细季度财务报表)
├── 04_SEC_8K_Current_Report/    - 当期报告 8-K (重大事件公告)
├── 05_Press_Release/            - 新闻稿 (财报公告、交付数据等)
├── 06_Earnings_Call_Info/       - 财报电话会议信息 (获取指南)
├── 07_Proxy_Statement/          - 代理声明书 (股东大会材料、高管薪酬)
└── download_log.json            - 下载日志

文件命名规则：
Tesla_{年份}_{季度/日期}_{文档类型}.{扩展名}

数据用途（智能投顾）：
- Update Deck: 快速提取关键业绩指标(KPI)、图表数据
- 10-K/10-Q: 深度财务分析、风险因素识别
- Press Release: 实时业绩快报、交付量数据
- 8-K: 重大事件追踪（高管变动、收购等）
- Earnings Call: 管理层态度分析、未来展望提取
- Proxy Statement: 公司治理分析、高管薪酬评估
"""

    readme_path = os.path.join(OUTPUT_DIR, "目录说明.txt")
    with open(readme_path, 'w', encoding='utf-8') as f:
        f.write(readme_content)
    print(f"目录说明已保存: {readme_path}")


def main():
    """主函数"""
    print("="*60)
    print("  Tesla 投资者关系文档爬取工具")
    print("  时间范围: 2022-2026")
    print("  输出目录: " + OUTPUT_DIR)
    print("="*60)

    ensure_dir(OUTPUT_DIR)
    all_results = []

    # 1. 下载 Quarterly Update Deck
    results = download_update_decks()
    all_results.extend(results)

    # 2. 下载 SEC 申报文件 (10-K, 10-Q, 8-K)
    results = download_sec_filings()
    all_results.extend(results)

    # 3. 下载额外历史SEC文件
    results = download_additional_sec_filings()
    all_results.extend(results)

    # 4. 下载新闻稿
    results = download_press_releases()
    all_results.extend(results)

    # 5. 财报电话会议信息
    results = download_earnings_transcripts()
    all_results.extend(results)

    # 6. 下载代理声明书
    results = download_proxy_statements()
    all_results.extend(results)

    # 7. 生成汇总报告
    generate_summary(all_results)

    print("\n\n✅ 爬取完成！请检查输出目录: " + OUTPUT_DIR)


if __name__ == "__main__":
    main()
