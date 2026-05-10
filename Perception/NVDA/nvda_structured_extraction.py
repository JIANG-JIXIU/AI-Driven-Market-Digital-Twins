"""
NVIDIA Structured Data Extraction
===================================
从MineRU解析的markdown + Chart CSV中提取结构化财务/运营数据
参照Tesla pipeline架构，针对NVIDIA业务特征设计

输出Schema:
- metadata: 文档元信息（公司、财年、季度、报告类型）
- highlights: 关键要点 + 提及的指标
- financial: 收入分解、利润率、现金流、资产负债
- segments: 业务分部详情（Data Center/Gaming/ProViz/Automotive）
- guidance: 下季度展望
- qualitative: 定性信息（技术公告、风险）
- chart_data: 图表分类与提取数据
"""

import os
import sys
import json
import re
import csv
import io
import logging
import argparse
from pathlib import Path
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("nvda_extraction.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============ Path Config ============
PROJECT_ROOT = Path(os.path.expanduser("~/AI-Driven-Market-Digital-Twins"))
PERCEPTION_DIR = PROJECT_ROOT / "Perception" / "NVDA"
OUTPUT_DIR = PERCEPTION_DIR / "parsed_output"
MINERU_OUTPUT_DIR = OUTPUT_DIR / "mineru_results"
CHART_OUTPUT_DIR = OUTPUT_DIR / "chart_extractions"
STRUCTURED_OUTPUT_DIR = OUTPUT_DIR / "structured_data"

# ============ NVIDIA-specific Constants ============

# NVIDIA fiscal year mapping: FY ends in January
# FY25 Q3 = Aug-Oct 2024, reported Nov 2024
NVDA_FY_QUARTER_TO_CALENDAR = {
    "Q1": {"month_end": "04-30", "calendar_offset": -1},  # Feb-Apr, same calendar year as FY-1
    "Q2": {"month_end": "07-31", "calendar_offset": -1},  # May-Jul
    "Q3": {"month_end": "10-31", "calendar_offset": -1},  # Aug-Oct
    "Q4": {"month_end": "01-31", "calendar_offset": 0},   # Nov-Jan, straddles years
}

# Chart classification keywords for NVIDIA
CHART_CATEGORY_KEYWORDS = {
    "revenue": ["revenue", "total revenue", "revenue ($", "revenue growth"],
    "data_center": ["data center", "datacenter", "compute revenue", "networking revenue"],
    "gaming": ["gaming", "geforce"],
    "professional_visualization": ["professional visualization", "proviz", "quadro", "rtx workstation"],
    "automotive": ["automotive", "drive", "orin"],
    "gross_margin": ["gross margin", "gross profit"],
    "operating_income": ["operating income", "operating expense", "opex"],
    "net_income": ["net income", "net profit", "earnings"],
    "eps": ["earnings per share", "eps", "diluted eps"],
    "cash_flow": ["cash flow", "free cash flow", "fcf", "operating cash flow", "capex", "capital expenditure"],
    "balance_sheet": ["cash and equivalents", "balance sheet", "inventory", "total assets"],
    "shareholder_returns": ["repurchase", "buyback", "dividend", "shareholder return"],
    "income_statement": ["statement of income", "condensed consolidated", "cost of revenue"],
    "reconciliation": ["gaap", "non-gaap", "reconciliation", "stock-based compensation"],
}

# Section classification for NVIDIA presentations
SECTION_KEYWORDS = {
    "highlights": ["highlight", "earnings summary", "q1 fy", "q2 fy", "q3 fy", "q4 fy"],
    "financial_summary": ["financial summary", "financial highlight"],
    "data_center": ["data center", "datacenter"],
    "gaming": ["gaming"],
    "professional_visualization": ["professional visualization"],
    "automotive": ["automotive"],
    "cash_flow": ["sources & uses of cash", "cash flow", "balance sheet and cash flow"],
    "outlook": ["outlook", "guidance", "fourth quarter", "first quarter", "second quarter", "third quarter"],
    "revenue": ["revenue"],
    "gross_margin": ["gross margin"],
    "expenses": ["expense"],
    "other_income": ["other income", "income tax"],
    "key_announcements": ["key announcement", "this quarter"],
    "reconciliation": ["reconciliation", "non-gaap"],
    "legal": ["forward-looking", "non-gaap measures", "non-gaap financial information"],
}


# ============ Utility Functions ============

def clean_numeric(value_str: str):
    """清理数值字符串，返回 (float_value, unit)"""
    if not value_str or not isinstance(value_str, str):
        return None, ""
    s = value_str.strip()
    if not s:
        return None, ""
    
    unit = ""
    s_lower = s.lower()
    if s_lower.endswith('billion') or (s_lower.endswith('b') and not s_lower.endswith('feb')):
        unit = "B"
    elif s_lower.endswith('million') or s_lower.endswith('m'):
        unit = "M"
    elif s_lower.endswith('thousand') or s_lower.endswith('k'):
        unit = "K"
    elif s_lower.endswith('%'):
        unit = "%"
    
    s = s.lstrip('>').lstrip('<').lstrip('~').lstrip('≈')
    s = s.replace('$', '').replace(',', '').replace(' ', '')
    s = s.rstrip('BbMmKk%')
    s = s.replace('billion', '').replace('million', '').replace('thousand', '')
    
    if s.startswith('(') and s.endswith(')'):
        s = '-' + s[1:-1]
    
    match = re.search(r'-?[\d.]+', s)
    if match:
        s = match.group(0)
    
    try:
        return float(s), unit
    except (ValueError, TypeError):
        return None, ""


def parse_fiscal_year_quarter(pdf_name: str) -> dict:
    """从NVIDIA文件名解析财年和季度
    Examples: NVDA_FY25_Q3_Presentation, NVDA_FY24_Q2_CFO_Commentary
    """
    match = re.search(r'FY(\d{2})_Q(\d)', pdf_name)
    if match:
        fy = int("20" + match.group(1))
        quarter = f"Q{match.group(2)}"
        q_num = int(match.group(2))
        
        # Convert to calendar date
        # FY25 Q3 (Aug-Oct 2024): calendar year = FY - 1 = 2024
        if q_num <= 3:
            cal_year = fy - 1
        else:  # Q4 spans to January of FY year
            cal_year = fy - 1  # Nov-Dec of previous year, Jan of FY year
        
        quarter_end_map = {"Q1": f"{cal_year}-04-30", "Q2": f"{cal_year}-07-31",
                           "Q3": f"{cal_year}-10-31", "Q4": f"{fy}-01-31"}
        
        return {
            "fiscal_year": fy,
            "quarter": quarter,
            "period_end": quarter_end_map.get(quarter, ""),
            "calendar_year": cal_year
        }
    return {"fiscal_year": None, "quarter": None, "period_end": "", "calendar_year": None}


def detect_report_type(pdf_name: str) -> str:
    """检测报告类型"""
    name_lower = pdf_name.lower()
    if "presentation" in name_lower:
        return "Investor Presentation"
    elif "cfo" in name_lower or "commentary" in name_lower:
        return "CFO Commentary"
    elif "transcript" in name_lower:
        return "Earnings Transcript"
    elif "revenue" in name_lower:
        return "Revenue Trend"
    elif "non_gaap" in name_lower or "non-gaap" in name_lower:
        return "Non-GAAP Historical"
    return "Other"


# ============ Section Parsing ============

def parse_sections(md_content: str) -> dict:
    """将MD内容按章节分段"""
    sections = {}
    lines = md_content.split('\n')
    
    current_section = "highlights"
    current_lines = []
    
    for line in lines:
        header_match = re.match(r'^#{1,3}\s+(.+)', line)
        if header_match:
            if current_lines:
                text = '\n'.join(current_lines).strip()
                if text:
                    if current_section in sections:
                        sections[current_section] += '\n\n' + text
                    else:
                        sections[current_section] = text
            
            header_text = header_match.group(1).lower().strip()
            new_section = "_unclassified"
            
            for section_key, keywords in SECTION_KEYWORDS.items():
                if any(kw in header_text for kw in keywords):
                    new_section = section_key
                    break
            
            current_section = new_section
            current_lines = []
        else:
            current_lines.append(line)
    
    if current_lines:
        text = '\n'.join(current_lines).strip()
        if text:
            if current_section in sections:
                sections[current_section] += '\n\n' + text
            else:
                sections[current_section] = text
    
    return sections


def extract_tables_from_markdown(md_content: str) -> list:
    """从Markdown中提取所有表格"""
    tables = []
    table_pattern = r'(\|[^\n]+\|\n\|[-:\s|]+\|\n(?:\|[^\n]+\|\n?)+)'
    matches = re.findall(table_pattern, md_content)

    for i, table_str in enumerate(matches):
        rows = [row.strip() for row in table_str.strip().split('\n') if row.strip()]
        if len(rows) >= 3:
            headers = [cell.strip() for cell in rows[0].split('|')[1:-1]]
            data_rows = []
            for row in rows[2:]:
                cells = [cell.strip() for cell in row.split('|')[1:-1]]
                data_rows.append(cells)
            tables.append({"table_index": i, "headers": headers, "data": data_rows})

    return tables


# ============ Chart Data Processing ============

def parse_csv_data(csv_raw: str) -> dict:
    """解析CSV字符串"""
    result = {"headers": [], "rows": [], "parse_errors": []}
    if not csv_raw or not csv_raw.strip():
        return result
    
    content = csv_raw.strip()
    if content.startswith('```'):
        lines = content.split('\n')
        if lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        content = '\n'.join(lines)
    
    if not content.strip():
        return result
    
    try:
        reader = csv.reader(io.StringIO(content))
        all_rows = list(reader)
        if not all_rows:
            return result
        result["headers"] = [h.strip() for h in all_rows[0]]
        for row in all_rows[1:]:
            if row and any(cell.strip() for cell in row):
                result["rows"].append([cell.strip() for cell in row])
    except Exception as e:
        result["parse_errors"].append(str(e))
    
    return result


def categorize_chart(chart_info: dict) -> list:
    """对图表分类"""
    scores = {cat: 0 for cat in CHART_CATEGORY_KEYWORDS}
    
    csv_data = chart_info.get("csv_data", "")
    if csv_data:
        header_line = ""
        for line in csv_data.strip().split('\n'):
            stripped = line.strip().lower()
            if stripped.startswith('```') or not stripped:
                continue
            header_line = stripped
            break
        if header_line:
            for cat, keywords in CHART_CATEGORY_KEYWORDS.items():
                for kw in keywords:
                    if kw in header_line:
                        scores[cat] += 3
    
    description = chart_info.get("description", "").lower()
    for cat, keywords in CHART_CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in description:
                scores[cat] += 2
    
    threshold = 4
    categories = [cat for cat, score in scores.items() if score >= threshold]
    if not categories:
        categories = [cat for cat, score in scores.items() if score >= 2]
    if not categories:
        return ["uncategorized"]
    return categories


def load_chart_data_for_pdf(pdf_name: str, chart_results_in_memory: list = None) -> list:
    """加载PDF对应的图表数据"""
    if chart_results_in_memory:
        return [c for c in chart_results_in_memory if c.get("pdf_source") == pdf_name]
    
    charts_json = CHART_OUTPUT_DIR / pdf_name / f"{pdf_name}_charts.json"
    if charts_json.exists():
        try:
            with open(charts_json, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []


def extract_metrics_from_csv(parsed_csv: dict) -> dict:
    """从CSV中提取结构化指标"""
    metrics = {"time_series": [], "latest_values": {}, "raw_data": {
        "headers": parsed_csv["headers"], "rows": parsed_csv["rows"][:20]
    }}
    
    headers = parsed_csv["headers"]
    rows = parsed_csv["rows"]
    if not headers or not rows:
        return metrics
    
    time_pattern = re.compile(r'(Q[1-4]|FY\d{2}|20\d{2}|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', re.IGNORECASE)
    
    first_col_is_time = False
    if rows:
        time_matches = sum(1 for row in rows if row and time_pattern.search(row[0]))
        if time_matches >= len(rows) * 0.5:
            first_col_is_time = True
    
    if first_col_is_time:
        summary_keywords = ["yoy", "y/y", "change", "growth", "vs", "qoq"]
        for row in rows:
            if not row or len(row) < 2:
                continue
            period = row[0].strip()
            if any(kw in period.lower() for kw in summary_keywords):
                continue
            entry = {"period": period}
            for i, header in enumerate(headers[1:], 1):
                if i < len(row):
                    value, unit = clean_numeric(row[i])
                    if value is not None:
                        entry[header] = {"value": value, "unit": unit}
            if len(entry) > 1:
                metrics["time_series"].append(entry)
        if metrics["time_series"]:
            metrics["latest_values"] = metrics["time_series"][-1]
    else:
        for row in rows:
            if not row or len(row) < 2:
                continue
            line_item = row[0].strip()
            if not line_item:
                continue
            values = {}
            for i, header in enumerate(headers[1:], 1):
                if i < len(row):
                    value, unit = clean_numeric(row[i])
                    if value is not None:
                        values[header] = {"value": value, "unit": unit}
            if values:
                metrics["latest_values"][line_item] = values
    
    return metrics


# ============ Highlights Extraction ============

def extract_highlights(md_content: str, sections: dict) -> dict:
    """提取关键要点和指标"""
    highlights = {"bullet_points": [], "key_metrics_mentioned": []}
    
    nvidia_terms = [
        'revenue', 'data center', 'gaming', 'professional visualization', 'automotive',
        'gross margin', 'operating income', 'net income', 'eps', 'earnings per share',
        'cash flow', 'free cash flow', 'capex', 'share repurchase', 'dividend',
        'blackwell', 'hopper', 'h100', 'h200', 'a100', 'gpu', 'inference',
        'record', 'growth', 'up', 'down', 'billion', 'million', 'inventory',
        'dso', 'networking', 'spectrum-x', 'infiniband', 'nvlink',
        'dgx', 'hgx', 'drive', 'orin', 'omniverse', 'cuda'
    ]
    
    lines = md_content.split('\n')
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('!['):
            continue
        
        line_lower = stripped.lower()
        if any(term in line_lower for term in nvidia_terms) and re.search(r'\d', stripped):
            highlights["bullet_points"].append(stripped)
            
            # Extract specific metrics
            metric_patterns = [
                (r'total revenue[^.]*?[\$]?\s*([\d,]+\.?\d*)\s*(B|billion|M|million)', 'total_revenue'),
                (r'data center[^.]*?[\$]?\s*([\d,]+\.?\d*)\s*(B|billion|M|million)', 'data_center_revenue'),
                (r'gaming[^.]*?[\$]?\s*([\d,]+\.?\d*)\s*(B|billion|M|million)', 'gaming_revenue'),
                (r'([\d,]+\.?\d*)\s*%.*(?:gross margin|margin)', 'gross_margin'),
                (r'up\s+([\d,]+\.?\d*)\s*%\s*(?:Y/Y|year)', 'yoy_growth'),
                (r'free cash flow[^.]*?[\$]?\s*([\d,]+\.?\d*)\s*(B|billion|M|million)', 'free_cash_flow'),
                (r'[\$]?\s*([\d,]+\.?\d*)\s*(B|billion).*(?:share repurchase|buyback)', 'share_repurchases'),
                (r'[\$]?\s*([\d,]+\.?\d*)\s*(?:per share|EPS)', 'eps'),
                (r'cash.*?[\$]?\s*([\d,]+\.?\d*)\s*(B|billion)', 'cash_position'),
            ]
            
            for pattern, metric_name in metric_patterns:
                match = re.search(pattern, stripped, re.IGNORECASE)
                if match:
                    value, unit = clean_numeric(match.group(1))
                    if value is not None:
                        highlights["key_metrics_mentioned"].append({
                            "metric_name": metric_name,
                            "value": value,
                            "unit": match.group(2) if len(match.groups()) > 1 else "",
                            "context": stripped[:200]
                        })
    
    return highlights


# ============ Financial Data Extraction ============

def extract_financial_from_text(sections: dict, md_content: str) -> dict:
    """从文本中提取财务数据"""
    financial = {
        "revenue": {
            "total": None,
            "data_center": None,
            "gaming": None,
            "professional_visualization": None,
            "automotive": None,
            "yoy_growth_pct": None,
            "sequential_growth_pct": None,
        },
        "profitability": {
            "gross_margin_gaap_pct": None,
            "gross_margin_non_gaap_pct": None,
            "operating_income_gaap": None,
            "operating_income_non_gaap": None,
            "operating_margin_pct": None,
            "net_income_gaap": None,
            "net_income_non_gaap": None,
        },
        "per_share": {
            "eps_gaap_diluted": None,
            "eps_non_gaap_diluted": None,
        },
        "cash_flow": {
            "operating_cash_flow": None,
            "free_cash_flow": None,
            "capital_expenditure": None,
            "share_repurchases": None,
            "dividends": None,
        },
        "balance_sheet": {
            "cash_and_marketable_securities": None,
            "inventory": None,
            "accounts_receivable": None,
            "total_debt": None,
            "net_cash": None,
            "dso_days": None,
            "dsi_days": None,
        },
    }
    
    # Combine relevant text
    all_text = md_content
    
    # --- Revenue extraction ---
    # "Revenue was a record $35.1 billion, up 94% from a year ago and up 17% sequentially"
    rev_match = re.search(r'(?:total )?revenue was[^.]*?[\$]\s*([\d,.]+)\s*(billion|B)', all_text, re.IGNORECASE)
    if rev_match:
        val, _ = clean_numeric(rev_match.group(1))
        if val:
            financial["revenue"]["total"] = {"value": val * 1000 if val < 100 else val, "unit": "$M"}
    
    # "Total revenue up 94% Y/Y to $35.1B"
    rev_match2 = re.search(r'total revenue\s+(?:up|down)\s+([\d.]+)%\s*(?:Y/Y|year)', all_text, re.IGNORECASE)
    if rev_match2:
        financial["revenue"]["yoy_growth_pct"] = float(rev_match2.group(1))
    
    rev_match3 = re.search(r'up\s+([\d.]+)%\s*sequential', all_text, re.IGNORECASE)
    if rev_match3:
        financial["revenue"]["sequential_growth_pct"] = float(rev_match3.group(1))
    
    # Segment revenues
    # "Data Center revenue was a record, up 112% from a year ago" or "Data Center up 171% Y/Y to $10.32B"
    dc_match = re.search(r'data center[^.]*?[\$]\s*([\d,.]+)\s*(B|billion|M|million)', all_text, re.IGNORECASE)
    if dc_match:
        val, _ = clean_numeric(dc_match.group(1))
        if val:
            unit = dc_match.group(2).upper()
            if unit.startswith('B'):
                financial["revenue"]["data_center"] = {"value": val * 1000, "unit": "$M"}
            else:
                financial["revenue"]["data_center"] = {"value": val, "unit": "$M"}
    
    gaming_match = re.search(r'gaming[^.]*?[\$]\s*([\d,.]+)\s*(B|billion|M|million)', all_text, re.IGNORECASE)
    if gaming_match:
        val, _ = clean_numeric(gaming_match.group(1))
        if val:
            unit = gaming_match.group(2).upper()
            if unit.startswith('B'):
                financial["revenue"]["gaming"] = {"value": val * 1000, "unit": "$M"}
            else:
                financial["revenue"]["gaming"] = {"value": val, "unit": "$M"}
    
    proviz_match = re.search(r'professional visualization[^.]*?[\$]\s*([\d,.]+)\s*(B|billion|M|million)', all_text, re.IGNORECASE)
    if proviz_match:
        val, _ = clean_numeric(proviz_match.group(1))
        if val:
            unit = proviz_match.group(2).upper()
            if unit.startswith('B'):
                financial["revenue"]["professional_visualization"] = {"value": val * 1000, "unit": "$M"}
            else:
                financial["revenue"]["professional_visualization"] = {"value": val, "unit": "$M"}
    
    auto_match = re.search(r'automotive[^.]*?[\$]\s*([\d,.]+)\s*(B|billion|M|million)', all_text, re.IGNORECASE)
    if auto_match:
        val, _ = clean_numeric(auto_match.group(1))
        if val:
            unit = auto_match.group(2).upper()
            if unit.startswith('B'):
                financial["revenue"]["automotive"] = {"value": val * 1000, "unit": "$M"}
            else:
                financial["revenue"]["automotive"] = {"value": val, "unit": "$M"}
    
    # --- Gross Margin ---
    gm_gaap = re.search(r'GAAP\s+(?:and\s+non-GAAP\s+)?gross margin[s]?\s+(?:were|was|of)\s+(?:approximately\s+)?([\d.]+)%\s+and\s+([\d.]+)%', all_text, re.IGNORECASE)
    if gm_gaap:
        financial["profitability"]["gross_margin_gaap_pct"] = float(gm_gaap.group(1))
        financial["profitability"]["gross_margin_non_gaap_pct"] = float(gm_gaap.group(2))
    else:
        gm_single = re.search(r'(?:non-GAAP\s+)?gross margin[s]?\s+(?:were|was|of)\s+(?:approximately\s+)?([\d.]+)%', all_text, re.IGNORECASE)
        if gm_single:
            financial["profitability"]["gross_margin_non_gaap_pct"] = float(gm_single.group(1))
    
    # --- EPS ---
    eps_gaap = re.search(r'GAAP\s+(?:diluted\s+)?(?:earnings|EPS)[^.]*?[\$]\s*(\d+\.\d+)', all_text, re.IGNORECASE)
    if eps_gaap:
        try:
            financial["per_share"]["eps_gaap_diluted"] = float(eps_gaap.group(1))
        except ValueError:
            pass
    
    eps_nongaap = re.search(r'non-GAAP\s+(?:diluted\s+)?(?:earnings|EPS)[^.]*?[\$]\s*(\d+\.\d+)', all_text, re.IGNORECASE)
    if eps_nongaap:
        try:
            financial["per_share"]["eps_non_gaap_diluted"] = float(eps_nongaap.group(1))
        except ValueError:
            pass
    
    # --- Cash Flow ---
    ocf_match = re.search(r'cash flow from operating activities was\s*[\$]?\s*([\d,.]+)\s*(billion|B|million|M)', all_text, re.IGNORECASE)
    if ocf_match:
        val, _ = clean_numeric(ocf_match.group(1))
        if val:
            unit = ocf_match.group(2).upper()
            if unit.startswith('B'):
                financial["cash_flow"]["operating_cash_flow"] = {"value": val * 1000, "unit": "$M"}
            else:
                financial["cash_flow"]["operating_cash_flow"] = {"value": val, "unit": "$M"}
    
    fcf_match = re.search(r'free cash flow[^.]*?[\$]?\s*([\d,.]+)\s*(billion|B|million|M)', all_text, re.IGNORECASE)
    if fcf_match:
        val, _ = clean_numeric(fcf_match.group(1))
        if val:
            unit = fcf_match.group(2).upper()
            if unit.startswith('B'):
                financial["cash_flow"]["free_cash_flow"] = {"value": val * 1000, "unit": "$M"}
            else:
                financial["cash_flow"]["free_cash_flow"] = {"value": val, "unit": "$M"}
    
    capex_match = re.search(r'(?:capex|capital expenditures?)[^.]*?[\$]?\s*([\d,.]+)\s*(billion|B|million|M)', all_text, re.IGNORECASE)
    if capex_match:
        val, _ = clean_numeric(capex_match.group(1))
        if val:
            unit = capex_match.group(2).upper()
            if unit.startswith('B'):
                financial["cash_flow"]["capital_expenditure"] = {"value": val * 1000, "unit": "$M"}
            else:
                financial["cash_flow"]["capital_expenditure"] = {"value": val, "unit": "$M"}
    
    repurchase_match = re.search(r'[\$]\s*([\d,.]+)\s*(billion|B|million|M)\s*(?:in\s+)?share repurchase', all_text, re.IGNORECASE)
    if repurchase_match:
        val, _ = clean_numeric(repurchase_match.group(1))
        if val:
            unit = repurchase_match.group(2).upper()
            if unit.startswith('B'):
                financial["cash_flow"]["share_repurchases"] = {"value": val * 1000, "unit": "$M"}
            else:
                financial["cash_flow"]["share_repurchases"] = {"value": val, "unit": "$M"}
    
    dividend_match = re.search(r'[\$]\s*([\d,.]+)\s*(billion|B|million|M)\s*(?:in\s+)?(?:cash\s+)?dividend', all_text, re.IGNORECASE)
    if dividend_match:
        val, _ = clean_numeric(dividend_match.group(1))
        if val:
            unit = dividend_match.group(2).upper()
            if unit.startswith('B'):
                financial["cash_flow"]["dividends"] = {"value": val * 1000, "unit": "$M"}
            else:
                financial["cash_flow"]["dividends"] = {"value": val, "unit": "$M"}
    
    # --- Balance Sheet ---
    cash_match = re.search(r'(?:cash.*?(?:equivalents?|securities|investments))\s+(?:were|was|of)\s*[\$]?\s*([\d,.]+)\s*(billion|B)', all_text, re.IGNORECASE)
    if cash_match:
        val, _ = clean_numeric(cash_match.group(1))
        if val:
            financial["balance_sheet"]["cash_and_marketable_securities"] = {"value": val * 1000, "unit": "$M"}
    
    inv_match = re.search(r'inventory was\s*[\$]?\s*([\d,.]+)\s*(billion|B|million|M)', all_text, re.IGNORECASE)
    if inv_match:
        val, _ = clean_numeric(inv_match.group(1))
        if val:
            unit = inv_match.group(2).upper()
            if unit.startswith('B'):
                financial["balance_sheet"]["inventory"] = {"value": val * 1000, "unit": "$M"}
            else:
                financial["balance_sheet"]["inventory"] = {"value": val, "unit": "$M"}
    
    ar_match = re.search(r'accounts receivable was\s*[\$]?\s*([\d,.]+)\s*(billion|B|million|M)', all_text, re.IGNORECASE)
    if ar_match:
        val, _ = clean_numeric(ar_match.group(1))
        if val:
            unit = ar_match.group(2).upper()
            if unit.startswith('B'):
                financial["balance_sheet"]["accounts_receivable"] = {"value": val * 1000, "unit": "$M"}
            else:
                financial["balance_sheet"]["accounts_receivable"] = {"value": val, "unit": "$M"}
    
    debt_match = re.search(r'[\$]\s*([\d,.]+)\s*(billion|B)\s*in\s*debt', all_text, re.IGNORECASE)
    if debt_match:
        val, _ = clean_numeric(debt_match.group(1))
        if val:
            financial["balance_sheet"]["total_debt"] = {"value": val * 1000, "unit": "$M"}
    
    net_cash_match = re.search(r'[\$]\s*([\d,.]+)\s*(billion|B)\s*in\s*net\s*cash', all_text, re.IGNORECASE)
    if net_cash_match:
        val, _ = clean_numeric(net_cash_match.group(1))
        if val:
            financial["balance_sheet"]["net_cash"] = {"value": val * 1000, "unit": "$M"}
    
    dso_match = re.search(r'(\d+)\s*days?\s*sales?\s*outstanding', all_text, re.IGNORECASE)
    if dso_match:
        financial["balance_sheet"]["dso_days"] = int(dso_match.group(1))
    
    dsi_match = re.search(r'(\d+)\s*days?\s*(?:sales?\s*of\s*)?inventor', all_text, re.IGNORECASE)
    if dsi_match:
        financial["balance_sheet"]["dsi_days"] = int(dsi_match.group(1))
    
    return financial


# ============ Segments Extraction ============

def extract_segments(sections: dict, md_content: str) -> dict:
    """提取业务分部详情"""
    segments = {
        "data_center": {
            "revenue": None,
            "yoy_growth_pct": None,
            "sequential_growth_pct": None,
            "compute_revenue": None,
            "networking_revenue": None,
            "key_drivers": [],
            "customer_mix": {},
        },
        "gaming": {
            "revenue": None,
            "yoy_growth_pct": None,
            "sequential_growth_pct": None,
            "key_drivers": [],
        },
        "professional_visualization": {
            "revenue": None,
            "yoy_growth_pct": None,
            "sequential_growth_pct": None,
            "key_drivers": [],
        },
        "automotive": {
            "revenue": None,
            "yoy_growth_pct": None,
            "sequential_growth_pct": None,
            "key_drivers": [],
        },
    }
    
    # Data Center
    dc_text = sections.get("data_center", "") + "\n" + md_content
    
    # "Data Center revenue was a record, up 112% from a year ago and up 17% sequentially"
    dc_yoy = re.search(r'data center[^.]*?up\s+([\d.]+)%\s*(?:from a year ago|Y/Y|year)', dc_text, re.IGNORECASE)
    if dc_yoy:
        segments["data_center"]["yoy_growth_pct"] = float(dc_yoy.group(1))
    
    dc_seq = re.search(r'data center[^.]*?up\s+([\d.]+)%\s*sequential', dc_text, re.IGNORECASE)
    if dc_seq:
        segments["data_center"]["sequential_growth_pct"] = float(dc_seq.group(1))
    
    # Compute vs Networking breakdown
    compute_match = re.search(r'(?:data center\s+)?compute\s+revenue\s+(?:was\s+)?[\$]?\s*([\d,.]+)\s*(billion|B|million|M)', dc_text, re.IGNORECASE)
    if compute_match:
        val, _ = clean_numeric(compute_match.group(1))
        if val:
            unit = compute_match.group(2).upper()
            if unit.startswith('B'):
                segments["data_center"]["compute_revenue"] = {"value": val * 1000, "unit": "$M"}
            else:
                segments["data_center"]["compute_revenue"] = {"value": val, "unit": "$M"}
    
    net_match = re.search(r'networking\s+revenue\s+(?:was\s+)?[\$]?\s*([\d,.]+)\s*(billion|B|million|M)', dc_text, re.IGNORECASE)
    if net_match:
        val, _ = clean_numeric(net_match.group(1))
        if val:
            unit = net_match.group(2).upper()
            if unit.startswith('B'):
                segments["data_center"]["networking_revenue"] = {"value": val * 1000, "unit": "$M"}
            else:
                segments["data_center"]["networking_revenue"] = {"value": val, "unit": "$M"}
    
    # CSP mix
    csp_match = re.search(r'cloud service providers?\s+(?:represented\s+)?(?:approximately\s+)?([\d]+)%', dc_text, re.IGNORECASE)
    if csp_match:
        segments["data_center"]["customer_mix"]["csp_pct"] = int(csp_match.group(1))
    
    # Key drivers from Data Center section
    dc_section = sections.get("data_center", "")
    if dc_section:
        for line in dc_section.split('\n'):
            stripped = line.strip().lstrip('·').lstrip('•').lstrip('-').strip()
            if stripped and not stripped.startswith('![') and len(stripped) > 20:
                segments["data_center"]["key_drivers"].append(stripped)
    
    # Gaming
    gaming_yoy = re.search(r'gaming[^.]*?up\s+([\d.]+)%\s*(?:from a year ago|Y/Y|year)', md_content, re.IGNORECASE)
    if gaming_yoy:
        segments["gaming"]["yoy_growth_pct"] = float(gaming_yoy.group(1))
    
    gaming_seq = re.search(r'gaming[^.]*?up\s+([\d.]+)%\s*sequential', md_content, re.IGNORECASE)
    if gaming_seq:
        segments["gaming"]["sequential_growth_pct"] = float(gaming_seq.group(1))
    
    gaming_section = sections.get("gaming", "")
    if gaming_section:
        for line in gaming_section.split('\n'):
            stripped = line.strip().lstrip('·').lstrip('•').lstrip('-').strip()
            if stripped and not stripped.startswith('![') and len(stripped) > 20:
                segments["gaming"]["key_drivers"].append(stripped)
    
    # Professional Visualization
    pv_yoy = re.search(r'professional visualization[^.]*?up\s+([\d.]+)%\s*(?:from a year ago|Y/Y|year)', md_content, re.IGNORECASE)
    if pv_yoy:
        segments["professional_visualization"]["yoy_growth_pct"] = float(pv_yoy.group(1))
    
    pv_section = sections.get("professional_visualization", "")
    if pv_section:
        for line in pv_section.split('\n'):
            stripped = line.strip().lstrip('·').lstrip('•').lstrip('-').strip()
            if stripped and not stripped.startswith('![') and len(stripped) > 20:
                segments["professional_visualization"]["key_drivers"].append(stripped)
    
    # Automotive
    auto_yoy = re.search(r'automotive[^.]*?up\s+([\d.]+)%\s*(?:from a year ago|Y/Y|year)', md_content, re.IGNORECASE)
    if auto_yoy:
        segments["automotive"]["yoy_growth_pct"] = float(auto_yoy.group(1))
    
    auto_section = sections.get("automotive", "")
    if auto_section:
        for line in auto_section.split('\n'):
            stripped = line.strip().lstrip('·').lstrip('•').lstrip('-').strip()
            if stripped and not stripped.startswith('![') and len(stripped) > 20:
                segments["automotive"]["key_drivers"].append(stripped)
    
    return segments


# ============ Guidance Extraction ============

def extract_guidance(sections: dict, md_content: str) -> dict:
    """提取下季度展望"""
    guidance = {
        "next_quarter_revenue": None,
        "next_quarter_revenue_range_pct": None,
        "gross_margin_gaap_pct": None,
        "gross_margin_non_gaap_pct": None,
        "opex_gaap": None,
        "opex_non_gaap": None,
        "tax_rate_pct": None,
        "raw_text": "",
    }
    
    outlook_text = sections.get("outlook", "")
    if not outlook_text:
        # Try to find outlook in full text
        outlook_match = re.search(r'(?:outlook|guidance)[^#]*', md_content, re.IGNORECASE)
        if outlook_match:
            outlook_text = outlook_match.group(0)[:2000]
    
    if outlook_text:
        guidance["raw_text"] = outlook_text[:1000]
        
        # "Revenue is expected to be $37.5 billion, plus or minus 2%"
        rev_outlook = re.search(r'revenue\s+(?:is\s+)?expected\s+(?:to\s+be\s+)?[\$]?\s*([\d,.]+)\s*(billion|B)', outlook_text, re.IGNORECASE)
        if rev_outlook:
            val, _ = clean_numeric(rev_outlook.group(1))
            if val:
                guidance["next_quarter_revenue"] = {"value": val * 1000, "unit": "$M"}
        
        range_match = re.search(r'plus or minus\s+([\d.]+)%', outlook_text, re.IGNORECASE)
        if range_match:
            guidance["next_quarter_revenue_range_pct"] = float(range_match.group(1))
        
        # Gross margins
        gm_outlook = re.search(r'gross margins?\s+(?:are\s+)?expected\s+(?:to\s+be\s+)?([\d.]+)%\s+and\s+([\d.]+)%', outlook_text, re.IGNORECASE)
        if gm_outlook:
            guidance["gross_margin_gaap_pct"] = float(gm_outlook.group(1))
            guidance["gross_margin_non_gaap_pct"] = float(gm_outlook.group(2))
        
        # Operating expenses
        opex_outlook = re.search(r'operating expenses\s+(?:are\s+)?expected.*?[\$]\s*([\d,.]+)\s*(billion|B).*?[\$]\s*([\d,.]+)\s*(billion|B)', outlook_text, re.IGNORECASE)
        if opex_outlook:
            val1, _ = clean_numeric(opex_outlook.group(1))
            val2, _ = clean_numeric(opex_outlook.group(3))
            if val1:
                guidance["opex_gaap"] = {"value": val1 * 1000, "unit": "$M"}
            if val2:
                guidance["opex_non_gaap"] = {"value": val2 * 1000, "unit": "$M"}
        
        # Tax rate
        tax_outlook = re.search(r'tax rate[s]?\s+(?:are\s+)?expected\s+(?:to\s+be\s+)?([\d.]+)%', outlook_text, re.IGNORECASE)
        if tax_outlook:
            guidance["tax_rate_pct"] = float(tax_outlook.group(1))
    
    return guidance


# ============ Qualitative Extraction ============

def extract_qualitative(sections: dict, md_content: str) -> dict:
    """提取定性信息"""
    qualitative = {
        "key_announcements": [],
        "technology_highlights": [],
        "risks_and_challenges": [],
        "product_launches": [],
    }
    
    # Key announcements
    ann_text = sections.get("key_announcements", "")
    if ann_text:
        for line in ann_text.split('\n'):
            stripped = line.strip()
            if stripped and not stripped.startswith('![') and len(stripped) > 30:
                qualitative["key_announcements"].append(stripped)
    
    # Technology highlights from various sections
    tech_keywords = ['blackwell', 'hopper', 'grace', 'h100', 'h200', 'b100', 'b200', 'gb200',
                     'spectrum-x', 'nvlink', 'dgx', 'hgx', 'cuda', 'tensorrt',
                     'omniverse', 'drive', 'isaac', 'nemo', 'riva']
    
    for line in md_content.split('\n'):
        stripped = line.strip()
        if stripped and not stripped.startswith('!['):
            if any(kw in stripped.lower() for kw in tech_keywords) and len(stripped) > 30:
                if stripped not in qualitative["technology_highlights"]:
                    qualitative["technology_highlights"].append(stripped)
    
    # Risks
    risk_keywords = ['decline', 'decreased', 'constraint', 'supply', 'challenge', 'risk',
                     'headwind', 'lower', 'uncertainty', 'tariff', 'restriction', 'export control']
    
    for line in md_content.split('\n'):
        stripped = line.strip()
        if stripped and not stripped.startswith('!['):
            if any(kw in stripped.lower() for kw in risk_keywords) and re.search(r'\d', stripped):
                qualitative["risks_and_challenges"].append(stripped)
    
    # Product launches
    launch_keywords = ['launched', 'launch', 'introduced', 'released', 'announced', 'unveiled']
    for line in md_content.split('\n'):
        stripped = line.strip()
        if stripped and not stripped.startswith('!['):
            if any(kw in stripped.lower() for kw in launch_keywords) and len(stripped) > 20:
                qualitative["product_launches"].append(stripped)
    
    # Limit to top entries
    qualitative["technology_highlights"] = qualitative["technology_highlights"][:20]
    qualitative["risks_and_challenges"] = qualitative["risks_and_challenges"][:15]
    qualitative["product_launches"] = qualitative["product_launches"][:15]
    
    return qualitative


# ============ Timeline Generation ============

def generate_timeline(all_structured: list) -> dict:
    """生成时间序列数据"""
    timeline = {
        "description": "NVIDIA Quarterly Financial & Operational Timeline",
        "period_range": {},
        "reports_included": len(all_structured),
        "metrics": {},
        "computed_analytics": {}
    }
    
    sorted_data = sorted(
        [d for d in all_structured if d.get("metadata", {}).get("fiscal_year")],
        key=lambda x: (x["metadata"]["fiscal_year"], x["metadata"]["quarter"])
    )
    
    if not sorted_data:
        return timeline
    
    first = sorted_data[0]["metadata"]
    last = sorted_data[-1]["metadata"]
    timeline["period_range"] = {
        "start": f"FY{first['fiscal_year']} {first['quarter']}",
        "end": f"FY{last['fiscal_year']} {last['quarter']}"
    }
    
    # Collect metrics
    metric_collectors = {}
    
    for data in sorted_data:
        period = f"FY{data['metadata']['fiscal_year']} {data['metadata']['quarter']}"
        
        # Financial metrics
        financial = data.get("financial", {})
        for section_name, section_data in financial.items():
            if isinstance(section_data, dict):
                for key, val in section_data.items():
                    if isinstance(val, dict) and "value" in val:
                        metric_name = f"financial.{section_name}.{key}"
                        if metric_name not in metric_collectors:
                            metric_collectors[metric_name] = []
                        metric_collectors[metric_name].append({
                            "period": period, "value": val["value"], "unit": val.get("unit", "")
                        })
                    elif isinstance(val, (int, float)) and val is not None:
                        metric_name = f"financial.{section_name}.{key}"
                        if metric_name not in metric_collectors:
                            metric_collectors[metric_name] = []
                        metric_collectors[metric_name].append({
                            "period": period, "value": val, "unit": "%"
                        })
        
        # Segment growth metrics
        segments = data.get("segments", {})
        for seg_name, seg_data in segments.items():
            if isinstance(seg_data, dict):
                for key in ["yoy_growth_pct", "sequential_growth_pct"]:
                    val = seg_data.get(key)
                    if val is not None:
                        metric_name = f"segments.{seg_name}.{key}"
                        if metric_name not in metric_collectors:
                            metric_collectors[metric_name] = []
                        metric_collectors[metric_name].append({
                            "period": period, "value": val, "unit": "%"
                        })
    
    timeline["metrics"] = metric_collectors
    
    # Compute analytics
    for metric_name, data_points in metric_collectors.items():
        if len(data_points) < 2:
            continue
        values = [dp["value"] for dp in data_points if dp["value"] is not None]
        if not values:
            continue
        
        analytics = {
            "latest_value": values[-1],
            "min_value": min(values),
            "max_value": max(values),
            "avg_value": round(sum(values) / len(values), 2),
            "data_points_count": len(values)
        }
        
        if len(values) >= 4 and values[0] > 0 and values[-1] > 0:
            years = len(values) / 4.0
            try:
                cagr = (values[-1] / values[0]) ** (1 / years) - 1
                analytics["cagr_pct"] = round(cagr * 100, 2)
            except (ValueError, ZeroDivisionError):
                pass
        
        # Trend direction
        if len(values) >= 4:
            mid = len(values) // 2
            first_avg = sum(values[:mid]) / mid
            last_avg = sum(values[mid:]) / (len(values) - mid)
        else:
            first_avg = values[0]
            last_avg = values[-1]
        
        if first_avg != 0:
            change_pct = (last_avg - first_avg) / abs(first_avg) * 100
            if change_pct > 10:
                analytics["trend_direction"] = "up"
            elif change_pct < -10:
                analytics["trend_direction"] = "down"
            else:
                analytics["trend_direction"] = "flat"
        
        timeline["computed_analytics"][metric_name] = analytics
    
    return timeline


# ============ Main Extraction Function ============

def run_structured_extraction(mineru_results: list = None, chart_results: list = None):
    """执行结构化数据提取"""
    logger.info("=" * 60)
    logger.info("NVIDIA Structured Data Extraction (Enhanced)")
    logger.info("=" * 60)
    
    STRUCTURED_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Load mineru results if not provided
    if mineru_results is None:
        summary_path = MINERU_OUTPUT_DIR / "parse_summary.json"
        if summary_path.exists():
            with open(summary_path, 'r', encoding='utf-8') as f:
                mineru_results = json.load(f)
        else:
            logger.error("No MineRU results found")
            return []
    
    all_structured = []
    
    for result in mineru_results:
        if not result.get("success"):
            continue
        
        pdf_name = result["pdf_name"]
        md_path = result.get("md_path", "")
        
        if not md_path or not os.path.exists(md_path):
            continue
        
        logger.info(f"Processing: {pdf_name}")
        
        try:
            with open(md_path, 'r', encoding='utf-8') as f:
                md_content = f.read()
            
            # 1. Parse metadata
            fy_info = parse_fiscal_year_quarter(pdf_name)
            report_type = detect_report_type(pdf_name)
            
            # 2. Parse sections
            sections = parse_sections(md_content)
            
            # 3. Load chart data
            chart_data_list = load_chart_data_for_pdf(pdf_name, chart_results)
            
            # 4. Process charts
            categorized_charts = {}
            for chart_info in chart_data_list:
                categories = categorize_chart(chart_info)
                parsed_csv = parse_csv_data(chart_info.get("csv_data", ""))
                metrics = extract_metrics_from_csv(parsed_csv)
                
                chart_entry = {
                    "image_name": chart_info.get("image_name", ""),
                    "categories": categories,
                    "description": chart_info.get("description", ""),
                    "parsed_metrics": metrics,
                }
                
                for category in categories:
                    if category not in categorized_charts:
                        categorized_charts[category] = []
                    categorized_charts[category].append(chart_entry)
            
            # 5. Extract markdown tables
            md_tables = extract_tables_from_markdown(md_content)
            
            # 6. Extract highlights
            highlights = extract_highlights(md_content, sections)
            
            # 7. Extract financial data
            financial = extract_financial_from_text(sections, md_content)
            
            # 8. Extract segments
            segments = extract_segments(sections, md_content)
            
            # 9. Extract guidance
            guidance = extract_guidance(sections, md_content)
            
            # 10. Extract qualitative
            qualitative = extract_qualitative(sections, md_content)
            
            # 11. Assemble final structure
            structured = {
                "metadata": {
                    "company": "NVIDIA",
                    "ticker": "NVDA",
                    "pdf_name": pdf_name,
                    "fiscal_year": fy_info["fiscal_year"],
                    "quarter": fy_info["quarter"],
                    "period_end": fy_info["period_end"],
                    "calendar_year": fy_info["calendar_year"],
                    "report_type": report_type,
                    "extraction_timestamp": datetime.now().isoformat(),
                    "data_completeness": {
                        "text_sections_found": len(sections),
                        "charts_processed": len(chart_data_list),
                        "md_tables_found": len(md_tables),
                        "highlights_extracted": len(highlights["bullet_points"]),
                        "metrics_extracted": len(highlights["key_metrics_mentioned"]),
                    }
                },
                "highlights": highlights,
                "financial": financial,
                "segments": segments,
                "guidance": guidance,
                "qualitative": qualitative,
                "chart_data": {
                    "total_charts_processed": len(chart_data_list),
                    "categorized_charts": {k: len(v) for k, v in categorized_charts.items()},
                    "chart_details": categorized_charts,
                },
                "tables_extracted": md_tables[:10],  # Limit to first 10
                "data_sources": {
                    "sections_found": list(sections.keys()),
                    "chart_categories": list(categorized_charts.keys()),
                }
            }
            
            all_structured.append(structured)
            
            # Save individual file
            output_path = STRUCTURED_OUTPUT_DIR / f"{pdf_name}_structured.json"
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(structured, f, ensure_ascii=False, indent=2)
            
            logger.info(f"  Done: {len(chart_data_list)} charts, {len(md_tables)} tables, "
                       f"{len(highlights['bullet_points'])} highlights")
        
        except Exception as e:
            logger.error(f"  Failed [{pdf_name}]: {e}")
            import traceback
            traceback.print_exc()
    
    # Save summary
    summary_path = STRUCTURED_OUTPUT_DIR / "all_structured_data.json"
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(all_structured, f, ensure_ascii=False, indent=2)
    
    # Generate timeline
    timeline = generate_timeline(all_structured)
    timeline_path = STRUCTURED_OUTPUT_DIR / "financial_timeline.json"
    with open(timeline_path, 'w', encoding='utf-8') as f:
        json.dump(timeline, f, ensure_ascii=False, indent=2)
    
    logger.info(f"\nStructured extraction complete: {len(all_structured)} documents")
    logger.info(f"Output: {STRUCTURED_OUTPUT_DIR}")
    
    return all_structured


# ============ Entry Point ============

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NVIDIA Structured Data Extraction")
    parser.add_argument("--input-dir", type=str, default=None,
                       help="Override MineRU results directory")
    args = parser.parse_args()
    
    if args.input_dir:
        MINERU_OUTPUT_DIR = Path(args.input_dir)
    
    run_structured_extraction()
