"""
META Structured Data Extraction
================================
从MineRU解析的markdown + Chart CSV中提取结构化财务/运营数据
参照Tesla pipeline架构，针对Meta Platforms业务特征设计

输出Schema:
- metadata: 文档元信息（公司、年份、季度、报告类型）
- highlights: 关键要点 + 提及的指标
- financial: 收入（广告/其他/地理分布）、利润率、现金流、资产负债
- segments: 业务分部（Family of Apps / Reality Labs）
- operational: 用户指标（DAP/ARPP）、广告指标（impressions/price）、员工数
- guidance: 下季度/全年展望
- qualitative: CEO/CFO要点、AI进展、产品更新、风险
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
        logging.FileHandler("meta_extraction.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============ Path Config ============
PROJECT_ROOT = Path(os.path.expanduser("~/AI-Driven-Market-Digital-Twins"))
PERCEPTION_DIR = PROJECT_ROOT / "Perception" / "META"
OUTPUT_DIR = PERCEPTION_DIR / "parsed_output"
MINERU_OUTPUT_DIR = OUTPUT_DIR / "mineru_results"
CHART_OUTPUT_DIR = OUTPUT_DIR / "chart_extractions"
STRUCTURED_OUTPUT_DIR = OUTPUT_DIR / "structured_data"

# ============ META-specific Constants ============

# Chart classification keywords for Meta
CHART_CATEGORY_KEYWORDS = {
    "revenue": ["revenue", "total revenue", "advertising revenue"],
    "revenue_geography": ["user geography", "by geography", "us & canada", "europe", "asia-pacific", "rest of world"],
    "segment_results": ["segment result", "family of apps", "reality labs"],
    "expenses": ["expense", "cost of revenue", "costs and expenses", "as a percentage of revenue"],
    "net_income": ["net income", "net profit"],
    "eps": ["earnings per share", "eps", "diluted earnings"],
    "cash_flow": ["free cash flow", "cash flow", "fcf"],
    "capex": ["capital expenditure", "capex"],
    "user_metrics": ["daily active people", "dap", "monthly active", "mau", "family metrics"],
    "arpp": ["average revenue per person", "arpp", "arpu"],
    "ad_metrics": ["ad impression", "price per ad", "ad delivery"],
    "tax_rate": ["effective tax rate", "tax rate"],
    "income_statement": ["condensed consolidated", "statement of income", "statements of income"],
    "balance_sheet": ["balance sheet", "total assets", "current assets"],
    "reconciliation": ["reconciliation", "non-gaap", "free cash flow reconciliation"],
}

# Section classification
SECTION_KEYWORDS = {
    "highlights": ["highlight", "financial highlight", "third quarter", "second quarter", "first quarter", "fourth quarter"],
    "operational": ["operational", "other financial highlight"],
    "revenue_detail": ["advertising revenue", "revenue by"],
    "segment_results": ["segment result"],
    "expenses": ["expense", "costs"],
    "user_metrics": ["daily active", "family metrics", "dap"],
    "ad_metrics": ["ad impression", "price per ad"],
    "guidance": ["outlook", "guidance", "we expect", "fourth quarter 2024", "first quarter 2025"],
    "ceo_remarks": ["mark zuckerberg", "ceo"],
    "cfo_remarks": ["susan li", "cfo", "dave wehner"],
    "about": ["about meta", "forward-looking", "disclosure"],
    "reconciliation": ["reconciliation", "non-gaap"],
    "appendix": ["appendix", "limitation"],
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


def parse_year_quarter(pdf_name: str) -> dict:
    """从META文件名解析年份和季度
    Examples: META_2024_Q3_Earnings_Presentation, META_2024_Q3_Transcript
    """
    match = re.search(r'(\d{4})_Q(\d)', pdf_name)
    if match:
        year = int(match.group(1))
        quarter = f"Q{match.group(2)}"
        q_num = int(match.group(2))
        
        quarter_end_map = {"Q1": f"{year}-03-31", "Q2": f"{year}-06-30",
                           "Q3": f"{year}-09-30", "Q4": f"{year}-12-31"}
        
        return {
            "year": year,
            "quarter": quarter,
            "period_end": quarter_end_map.get(quarter, ""),
        }
    return {"year": None, "quarter": None, "period_end": ""}


def detect_report_type(pdf_name: str) -> str:
    """检测报告类型"""
    name_lower = pdf_name.lower()
    if "presentation" in name_lower:
        return "Earnings Presentation"
    elif "transcript" in name_lower:
        return "Earnings Transcript"
    elif "prepared_remarks" in name_lower or "prepared remarks" in name_lower:
        return "Prepared Remarks"
    elif "press_release" in name_lower or "press release" in name_lower:
        return "Press Release"
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
    
    time_pattern = re.compile(r'(Q[1-4]|20\d{2}|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', re.IGNORECASE)
    
    first_col_is_time = False
    if rows:
        time_matches = sum(1 for row in rows if row and time_pattern.search(row[0]))
        if time_matches >= len(rows) * 0.5:
            first_col_is_time = True
    
    if first_col_is_time:
        for row in rows:
            if not row or len(row) < 2:
                continue
            period = row[0].strip()
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
    
    meta_terms = [
        'revenue', 'income', 'operating margin', 'earnings per share', 'eps',
        'free cash flow', 'capex', 'capital expenditure', 'headcount',
        'daily active', 'dap', 'monthly active', 'ad impression', 'price per ad',
        'family of apps', 'reality labs', 'billion', 'million', 'growth',
        'advertiser', 'whatsapp', 'instagram', 'facebook', 'threads',
        'llama', 'meta ai', 'ray-ban', 'quest', 'orion',
        'repurchase', 'dividend', 'debt', 'cash'
    ]
    
    lines = md_content.split('\n')
    for line in lines:
        stripped = line.strip().lstrip('·').lstrip('•').lstrip('-').strip()
        if not stripped or stripped.startswith('!['):
            continue
        
        line_lower = stripped.lower()
        if any(term in line_lower for term in meta_terms) and re.search(r'\d', stripped):
            highlights["bullet_points"].append(stripped)
            
            metric_patterns = [
                (r'total revenue was\s*[\$]?\s*([\d,.]+)\s*(billion|B|million|M)', 'total_revenue'),
                (r'(?:ad|advertising)\s+revenue[^.]*?[\$]?\s*([\d,.]+)\s*(billion|B|million|M)', 'ad_revenue'),
                (r'net income was\s*[\$]?\s*([\d,.]+)\s*(billion|B|million|M)', 'net_income'),
                (r'operating income was\s*[\$]?\s*([\d,.]+)\s*(billion|B|million|M)', 'operating_income'),
                (r'([\d.]+)%\s*operating margin', 'operating_margin'),
                (r'[\$]\s*([\d,.]+)\s*(?:per share|EPS)', 'eps'),
                (r'free cash flow was\s*[\$]?\s*([\d,.]+)\s*(billion|B|million|M)', 'free_cash_flow'),
                (r'capital expenditures?[^.]*?[\$]?\s*([\d,.]+)\s*(billion|B|million|M)', 'capex'),
                (r'DAP.*?was\s*([\d,.]+)\s*(billion|B)', 'dap'),
                (r'ad impressions[^.]*?(?:increased|grew|up)\s+(?:by\s+)?([\d.]+)%', 'ad_impressions_growth'),
                (r'average price per ad[^.]*?(?:increased|grew|up)\s+(?:by\s+)?([\d.]+)%', 'price_per_ad_growth'),
                (r'headcount was\s*([\d,]+)', 'headcount'),
                (r'increase of\s+([\d.]+)%\s*year-over-year', 'yoy_growth'),
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
    
    # Deduplicate bullet points
    seen = set()
    unique_bullets = []
    for bp in highlights["bullet_points"]:
        if bp not in seen:
            seen.add(bp)
            unique_bullets.append(bp)
    highlights["bullet_points"] = unique_bullets[:50]
    
    return highlights


# ============ Financial Data Extraction ============

def extract_financial_from_text(sections: dict, md_content: str) -> dict:
    """从文本中提取财务数据"""
    financial = {
        "revenue": {
            "total": None,
            "advertising": None,
            "other_revenue": None,
            "yoy_growth_pct": None,
            "constant_currency_growth_pct": None,
            "by_geography": {
                "us_canada": None,
                "europe": None,
                "asia_pacific": None,
                "rest_of_world": None,
            },
        },
        "profitability": {
            "total_costs_and_expenses": None,
            "cost_of_revenue": None,
            "research_and_development": None,
            "marketing_and_sales": None,
            "general_and_administrative": None,
            "income_from_operations": None,
            "operating_margin_pct": None,
            "net_income": None,
            "effective_tax_rate_pct": None,
        },
        "per_share": {
            "eps_basic": None,
            "eps_diluted": None,
        },
        "cash_flow": {
            "free_cash_flow": None,
            "capital_expenditures": None,
            "share_repurchases": None,
            "dividends": None,
        },
        "balance_sheet": {
            "cash_and_marketable_securities": None,
            "long_term_debt": None,
        },
    }
    
    all_text = md_content
    
    # --- Total Revenue ---
    rev_match = re.search(r'(?:total )?revenue was\s*[\$]?\s*([\d,.]+)\s*(billion|B)', all_text, re.IGNORECASE)
    if rev_match:
        val, _ = clean_numeric(rev_match.group(1))
        if val:
            financial["revenue"]["total"] = {"value": val * 1000, "unit": "$M"}
    
    # YoY growth
    rev_yoy = re.search(r'(?:total )?revenue[^.]*?(?:increase|up|grew)\s+(?:of\s+)?([\d.]+)%\s*(?:year|y-o-y|yoy)', all_text, re.IGNORECASE)
    if rev_yoy:
        financial["revenue"]["yoy_growth_pct"] = float(rev_yoy.group(1))
    
    # Constant currency
    cc_match = re.search(r'constant currency[^.]*?(?:increased|would have increased)\s+([\d.]+)%', all_text, re.IGNORECASE)
    if cc_match:
        financial["revenue"]["constant_currency_growth_pct"] = float(cc_match.group(1))
    
    # Advertising revenue
    ad_match = re.search(r'(?:ad|advertising)\s+revenue\s+(?:was\s+)?[\$]?\s*([\d,.]+)\s*(billion|B)', all_text, re.IGNORECASE)
    if ad_match:
        val, _ = clean_numeric(ad_match.group(1))
        if val:
            financial["revenue"]["advertising"] = {"value": val * 1000, "unit": "$M"}
    
    # Other revenue
    other_rev = re.search(r'other revenue\s+(?:was\s+)?[\$]?\s*([\d,.]+)\s*(million|M)', all_text, re.IGNORECASE)
    if other_rev:
        val, _ = clean_numeric(other_rev.group(1))
        if val:
            financial["revenue"]["other_revenue"] = {"value": val, "unit": "$M"}
    
    # --- Costs & Expenses ---
    costs_match = re.search(r'total costs and expenses were\s*[\$]?\s*([\d,.]+)\s*(billion|B)', all_text, re.IGNORECASE)
    if costs_match:
        val, _ = clean_numeric(costs_match.group(1))
        if val:
            financial["profitability"]["total_costs_and_expenses"] = {"value": val * 1000, "unit": "$M"}
    
    # Operating income
    op_inc = re.search(r'(?:operating income|income from operations)\s+(?:was\s+)?[\$]?\s*([\d,.]+)\s*(billion|B)', all_text, re.IGNORECASE)
    if op_inc:
        val, _ = clean_numeric(op_inc.group(1))
        if val:
            financial["profitability"]["income_from_operations"] = {"value": val * 1000, "unit": "$M"}
    
    # Operating margin
    op_margin = re.search(r'([\d.]+)%\s*operating margin', all_text, re.IGNORECASE)
    if op_margin:
        financial["profitability"]["operating_margin_pct"] = float(op_margin.group(1))
    else:
        op_margin2 = re.search(r'operating margin[^.]*?([\d.]+)%', all_text, re.IGNORECASE)
        if op_margin2:
            financial["profitability"]["operating_margin_pct"] = float(op_margin2.group(1))
    
    # Net income
    ni_match = re.search(r'net income was\s*[\$]?\s*([\d,.]+)\s*(billion|B)', all_text, re.IGNORECASE)
    if ni_match:
        val, _ = clean_numeric(ni_match.group(1))
        if val:
            financial["profitability"]["net_income"] = {"value": val * 1000, "unit": "$M"}
    
    # Tax rate
    tax_match = re.search(r'(?:effective\s+)?tax rate[^.]*?(?:was|of)\s*([\d.]+)%', all_text, re.IGNORECASE)
    if tax_match:
        financial["profitability"]["effective_tax_rate_pct"] = float(tax_match.group(1))
    
    # --- EPS ---
    eps_match = re.search(r'[\$]\s*([\d.]+)\s*per share', all_text, re.IGNORECASE)
    if eps_match:
        financial["per_share"]["eps_diluted"] = float(eps_match.group(1))
    
    # --- Cash Flow ---
    fcf_match = re.search(r'free cash flow was\s*[\$]?\s*([\d,.]+)\s*(billion|B)', all_text, re.IGNORECASE)
    if fcf_match:
        val, _ = clean_numeric(fcf_match.group(1))
        if val:
            financial["cash_flow"]["free_cash_flow"] = {"value": val * 1000, "unit": "$M"}
    
    capex_match = re.search(r'capital expenditures?[^.]*?were\s*[\$]?\s*([\d,.]+)\s*(billion|B)', all_text, re.IGNORECASE)
    if capex_match:
        val, _ = clean_numeric(capex_match.group(1))
        if val:
            financial["cash_flow"]["capital_expenditures"] = {"value": val * 1000, "unit": "$M"}
    
    repurchase_match = re.search(r'(?:share\s+)?repurchases?\s+(?:were|of)\s*[\$]?\s*([\d,.]+)\s*(billion|B)', all_text, re.IGNORECASE)
    if repurchase_match:
        val, _ = clean_numeric(repurchase_match.group(1))
        if val:
            financial["cash_flow"]["share_repurchases"] = {"value": val * 1000, "unit": "$M"}
    
    dividend_match = re.search(r'dividend[^.]*?(?:were|of|paid)\s*[\$]?\s*([\d,.]+)\s*(billion|B|million|M)', all_text, re.IGNORECASE)
    if dividend_match:
        val, _ = clean_numeric(dividend_match.group(1))
        if val:
            unit = dividend_match.group(2).upper()
            if unit.startswith('B'):
                financial["cash_flow"]["dividends"] = {"value": val * 1000, "unit": "$M"}
            else:
                financial["cash_flow"]["dividends"] = {"value": val, "unit": "$M"}
    
    # --- Balance Sheet ---
    cash_match = re.search(r'cash.*?(?:marketable securities|securities)\s+(?:were|was|of)\s*[\$]?\s*([\d,.]+)\s*(billion|B)', all_text, re.IGNORECASE)
    if cash_match:
        val, _ = clean_numeric(cash_match.group(1))
        if val:
            financial["balance_sheet"]["cash_and_marketable_securities"] = {"value": val * 1000, "unit": "$M"}
    
    debt_match = re.search(r'(?:long.term\s+)?debt\s+(?:was|of)\s*[\$]?\s*([\d,.]+)\s*(billion|B)', all_text, re.IGNORECASE)
    if debt_match:
        val, _ = clean_numeric(debt_match.group(1))
        if val:
            financial["balance_sheet"]["long_term_debt"] = {"value": val * 1000, "unit": "$M"}
    
    return financial


# ============ Segments Extraction ============

def extract_segments(sections: dict, md_content: str) -> dict:
    """提取业务分部"""
    segments = {
        "family_of_apps": {
            "revenue": None,
            "ad_revenue": None,
            "other_revenue": None,
            "expenses": None,
            "operating_income": None,
            "operating_margin_pct": None,
            "yoy_growth_pct": None,
        },
        "reality_labs": {
            "revenue": None,
            "expenses": None,
            "operating_loss": None,
            "yoy_growth_pct": None,
        },
    }
    
    all_text = md_content
    
    # Family of Apps
    foa_rev = re.search(r'family of apps\s+revenue\s+(?:was\s+)?[\$]?\s*([\d,.]+)\s*(billion|B)', all_text, re.IGNORECASE)
    if foa_rev:
        val, _ = clean_numeric(foa_rev.group(1))
        if val:
            segments["family_of_apps"]["revenue"] = {"value": val * 1000, "unit": "$M"}
    
    foa_ad = re.search(r'family of apps\s+ad\s+revenue\s+(?:was\s+)?[\$]?\s*([\d,.]+)\s*(billion|B)', all_text, re.IGNORECASE)
    if foa_ad:
        val, _ = clean_numeric(foa_ad.group(1))
        if val:
            segments["family_of_apps"]["ad_revenue"] = {"value": val * 1000, "unit": "$M"}
    
    foa_other = re.search(r'family.*?other revenue\s+(?:was\s+)?[\$]?\s*([\d,.]+)\s*(million|M)', all_text, re.IGNORECASE)
    if foa_other:
        val, _ = clean_numeric(foa_other.group(1))
        if val:
            segments["family_of_apps"]["other_revenue"] = {"value": val, "unit": "$M"}
    
    foa_exp = re.search(r'family of apps\s+expenses?\s+(?:were|was)\s*[\$]?\s*([\d,.]+)\s*(billion|B)', all_text, re.IGNORECASE)
    if foa_exp:
        val, _ = clean_numeric(foa_exp.group(1))
        if val:
            segments["family_of_apps"]["expenses"] = {"value": val * 1000, "unit": "$M"}
    
    foa_oi = re.search(r'family of apps\s+operating income\s+(?:was\s+)?[\$]?\s*([\d,.]+)\s*(billion|B)', all_text, re.IGNORECASE)
    if foa_oi:
        val, _ = clean_numeric(foa_oi.group(1))
        if val:
            segments["family_of_apps"]["operating_income"] = {"value": val * 1000, "unit": "$M"}
    
    foa_margin = re.search(r'family of apps[^.]*?([\d.]+)%\s*operating margin', all_text, re.IGNORECASE)
    if foa_margin:
        segments["family_of_apps"]["operating_margin_pct"] = float(foa_margin.group(1))
    
    # Reality Labs
    rl_rev = re.search(r'reality labs[^.]*?revenue\s+(?:was\s+)?[\$]?\s*([\d,.]+)\s*(billion|B|million|M)', all_text, re.IGNORECASE)
    if rl_rev:
        val, _ = clean_numeric(rl_rev.group(1))
        if val:
            unit = rl_rev.group(2).upper()
            if unit.startswith('B'):
                segments["reality_labs"]["revenue"] = {"value": val * 1000, "unit": "$M"}
            else:
                segments["reality_labs"]["revenue"] = {"value": val, "unit": "$M"}
    
    rl_exp = re.search(r'reality labs\s+expenses?\s+(?:were|was)\s*[\$]?\s*([\d,.]+)\s*(billion|B)', all_text, re.IGNORECASE)
    if rl_exp:
        val, _ = clean_numeric(rl_exp.group(1))
        if val:
            segments["reality_labs"]["expenses"] = {"value": val * 1000, "unit": "$M"}
    
    rl_loss = re.search(r'reality labs[^.]*?operating loss\s+(?:was|of)\s*[\$]?\s*([\d,.]+)\s*(billion|B)', all_text, re.IGNORECASE)
    if rl_loss:
        val, _ = clean_numeric(rl_loss.group(1))
        if val:
            segments["reality_labs"]["operating_loss"] = {"value": val * 1000, "unit": "$M"}
    
    return segments


# ============ Operational Metrics ============

def extract_operational(sections: dict, md_content: str) -> dict:
    """提取运营指标"""
    operational = {
        "users": {
            "family_dap_billions": None,
            "dap_yoy_growth_pct": None,
            "threads_monthly_actives_millions": None,
        },
        "advertising": {
            "ad_impressions_yoy_pct": None,
            "average_price_per_ad_yoy_pct": None,
            "top_vertical_driver": None,
        },
        "headcount": None,
        "headcount_yoy_growth_pct": None,
    }
    
    all_text = md_content
    
    # DAP
    dap_match = re.search(r'DAP.*?was\s*([\d,.]+)\s*billion', all_text, re.IGNORECASE)
    if not dap_match:
        dap_match = re.search(r'([\d,.]+)\s*billion\s*(?:people|DAP|daily active)', all_text, re.IGNORECASE)
    if dap_match:
        val, _ = clean_numeric(dap_match.group(1))
        if val and val < 10:  # Sanity check
            operational["users"]["family_dap_billions"] = val
    
    dap_growth = re.search(r'DAP[^.]*?(?:increase|growth|up)\s+(?:of\s+)?([\d.]+)%', all_text, re.IGNORECASE)
    if dap_growth:
        operational["users"]["dap_yoy_growth_pct"] = float(dap_growth.group(1))
    
    # Threads
    threads_match = re.search(r'threads[^.]*?([\d,.]+)\s*million\s*monthly\s*active', all_text, re.IGNORECASE)
    if threads_match:
        val, _ = clean_numeric(threads_match.group(1))
        if val:
            operational["users"]["threads_monthly_actives_millions"] = val
    
    # Ad impressions
    impressions = re.search(r'ad impressions[^.]*?(?:increased|grew|up)\s+(?:by\s+)?([\d.]+)%', all_text, re.IGNORECASE)
    if impressions:
        operational["advertising"]["ad_impressions_yoy_pct"] = float(impressions.group(1))
    
    # Price per ad
    price = re.search(r'(?:average\s+)?price per ad[^.]*?(?:increased|grew|up)\s+(?:by\s+)?([\d.]+)%', all_text, re.IGNORECASE)
    if price:
        operational["advertising"]["average_price_per_ad_yoy_pct"] = float(price.group(1))
    
    # Top vertical
    vertical = re.search(r'(?:online commerce|gaming|retail|e-commerce)\s+(?:vertical\s+)?was the largest contributor', all_text, re.IGNORECASE)
    if vertical:
        operational["advertising"]["top_vertical_driver"] = vertical.group(0).strip()
    
    # Headcount
    hc_match = re.search(r'headcount\s+(?:was\s+)?([\d,]+)', all_text, re.IGNORECASE)
    if hc_match:
        val, _ = clean_numeric(hc_match.group(1))
        if val:
            operational["headcount"] = int(val)
    
    hc_growth = re.search(r'headcount[^.]*?(?:increase|up|growth)\s+(?:of\s+)?([\d.]+)%', all_text, re.IGNORECASE)
    if hc_growth:
        operational["headcount_yoy_growth_pct"] = float(hc_growth.group(1))
    
    return operational


# ============ Guidance Extraction ============

def extract_guidance(sections: dict, md_content: str) -> dict:
    """提取展望/指引"""
    guidance = {
        "revenue_range": None,  # e.g. {"low": 45000, "high": 48000, "unit": "$M"}
        "total_expenses_range": None,
        "capex_range": None,
        "tax_rate": None,
        "reality_labs_commentary": None,
        "raw_text": "",
    }
    
    # Find guidance text
    guidance_text = ""
    
    # From sections
    for key in ["guidance", "outlook"]:
        if key in sections:
            guidance_text += sections[key] + "\n"
    
    # Also search for "We expect" patterns in full text
    expect_matches = re.findall(r'We\s+expect[^.]+\.', md_content, re.IGNORECASE)
    for m in expect_matches:
        guidance_text += m + "\n"
    
    anticipate_matches = re.findall(r'We\s+anticipate[^.]+\.', md_content, re.IGNORECASE)
    for m in anticipate_matches:
        guidance_text += m + "\n"
    
    if guidance_text:
        guidance["raw_text"] = guidance_text[:2000]
        
        # Revenue range: "total revenue to be in the range of $45-48 billion"
        rev_range = re.search(r'revenue\s+(?:to\s+be\s+)?in the range of\s*[\$]?\s*([\d.]+)\s*[-–]\s*(?:[\$]?\s*)?([\d.]+)\s*(billion|B)', guidance_text, re.IGNORECASE)
        if rev_range:
            low_val, _ = clean_numeric(rev_range.group(1))
            high_val, _ = clean_numeric(rev_range.group(2))
            if low_val and high_val:
                guidance["revenue_range"] = {"low": low_val * 1000, "high": high_val * 1000, "unit": "$M"}
        
        # Expenses range
        exp_range = re.search(r'total expenses?\s+(?:to\s+be\s+)?in the range of\s*[\$]?\s*([\d.]+)\s*[-–]\s*(?:[\$]?\s*)?([\d.]+)\s*(billion|B)', guidance_text, re.IGNORECASE)
        if exp_range:
            low_val, _ = clean_numeric(exp_range.group(1))
            high_val, _ = clean_numeric(exp_range.group(2))
            if low_val and high_val:
                guidance["total_expenses_range"] = {"low": low_val * 1000, "high": high_val * 1000, "unit": "$M"}
        
        # Capex range
        capex_range = re.search(r'capital expenditures?\s+(?:will\s+be\s+)?in the range of\s*[\$]?\s*([\d.]+)\s*[-–]\s*(?:[\$]?\s*)?([\d.]+)\s*(billion|B)', guidance_text, re.IGNORECASE)
        if capex_range:
            low_val, _ = clean_numeric(capex_range.group(1))
            high_val, _ = clean_numeric(capex_range.group(2))
            if low_val and high_val:
                guidance["capex_range"] = {"low": low_val * 1000, "high": high_val * 1000, "unit": "$M"}
        
        # Tax rate
        tax = re.search(r'tax rate\s+(?:to\s+be\s+)?(?:in the\s+)?(?:low[- ])?(?:teens|mid[- ]teens|high[- ]teens|([\d.]+)%)', guidance_text, re.IGNORECASE)
        if tax:
            if tax.group(1):
                guidance["tax_rate"] = float(tax.group(1))
            elif "low" in tax.group(0).lower():
                guidance["tax_rate"] = "low-teens"
        
        # Reality Labs
        rl_text = re.search(r'reality labs[^.]+\.', guidance_text, re.IGNORECASE)
        if rl_text:
            guidance["reality_labs_commentary"] = rl_text.group(0).strip()
    
    return guidance


# ============ Qualitative Extraction ============

def extract_qualitative(sections: dict, md_content: str) -> dict:
    """提取定性信息"""
    qualitative = {
        "ceo_highlights": [],
        "ai_initiatives": [],
        "product_updates": [],
        "risks_and_challenges": [],
    }
    
    # CEO highlights from CEO section
    ceo_text = sections.get("ceo_remarks", "")
    if ceo_text:
        for line in ceo_text.split('\n'):
            stripped = line.strip()
            if stripped and not stripped.startswith('![') and len(stripped) > 30 and re.search(r'\d', stripped):
                qualitative["ceo_highlights"].append(stripped)
    
    # AI initiatives
    ai_keywords = ['llama', 'meta ai', 'generative ai', 'gen ai', 'machine learning',
                   'recommendation', 'ranking', 'large language model', 'llm',
                   'inference', 'training', 'gpu', 'cluster']
    
    for line in md_content.split('\n'):
        stripped = line.strip()
        if stripped and not stripped.startswith('!['):
            if any(kw in stripped.lower() for kw in ai_keywords) and len(stripped) > 30:
                if stripped not in qualitative["ai_initiatives"]:
                    qualitative["ai_initiatives"].append(stripped)
    
    # Product updates
    product_keywords = ['quest', 'ray-ban', 'orion', 'threads', 'reels', 'whatsapp',
                        'instagram', 'facebook', 'messenger', 'horizon']
    
    for line in md_content.split('\n'):
        stripped = line.strip()
        if stripped and not stripped.startswith('!['):
            if any(kw in stripped.lower() for kw in product_keywords) and len(stripped) > 30:
                if stripped not in qualitative["product_updates"]:
                    qualitative["product_updates"].append(stripped)
    
    # Risks
    risk_keywords = ['regulatory', 'headwind', 'risk', 'challenge', 'decline', 'decrease',
                     'loss', 'uncertainty', 'legal', 'litigation', 'restrict']
    
    for line in md_content.split('\n'):
        stripped = line.strip()
        if stripped and not stripped.startswith('![') and len(stripped) > 20:
            if any(kw in stripped.lower() for kw in risk_keywords):
                qualitative["risks_and_challenges"].append(stripped)
    
    # Limit
    qualitative["ceo_highlights"] = qualitative["ceo_highlights"][:15]
    qualitative["ai_initiatives"] = qualitative["ai_initiatives"][:20]
    qualitative["product_updates"] = qualitative["product_updates"][:20]
    qualitative["risks_and_challenges"] = qualitative["risks_and_challenges"][:15]
    
    return qualitative


# ============ Timeline Generation ============

def generate_timeline(all_structured: list) -> dict:
    """生成时间序列数据"""
    timeline = {
        "description": "Meta Platforms Quarterly Financial & Operational Timeline",
        "period_range": {},
        "reports_included": len(all_structured),
        "metrics": {},
        "computed_analytics": {}
    }
    
    sorted_data = sorted(
        [d for d in all_structured if d.get("metadata", {}).get("year")],
        key=lambda x: (x["metadata"]["year"], x["metadata"]["quarter"])
    )
    
    if not sorted_data:
        return timeline
    
    first = sorted_data[0]["metadata"]
    last = sorted_data[-1]["metadata"]
    timeline["period_range"] = {
        "start": f"{first['year']} {first['quarter']}",
        "end": f"{last['year']} {last['quarter']}"
    }
    
    # Collect metrics (deduplicate by period - only keep first occurrence per period)
    metric_collectors = {}
    seen_periods = {}
    
    for data in sorted_data:
        period = f"{data['metadata']['year']} {data['metadata']['quarter']}"
        
        # Only process best source per period (Press Release > Transcript > Presentation)
        report_priority = {"Press Release": 1, "Earnings Transcript": 2, 
                          "Prepared Remarks": 3, "Earnings Presentation": 4}
        current_priority = report_priority.get(data["metadata"].get("report_type", ""), 5)
        
        if period in seen_periods and seen_periods[period] <= current_priority:
            continue
        seen_periods[period] = current_priority
        
        # Financial metrics
        financial = data.get("financial", {})
        for section_name, section_data in financial.items():
            if isinstance(section_data, dict):
                for key, val in section_data.items():
                    if isinstance(val, dict) and "value" in val:
                        metric_name = f"financial.{section_name}.{key}"
                        if metric_name not in metric_collectors:
                            metric_collectors[metric_name] = []
                        # Check for duplicate period
                        existing_periods = [m["period"] for m in metric_collectors[metric_name]]
                        if period not in existing_periods:
                            metric_collectors[metric_name].append({
                                "period": period, "value": val["value"], "unit": val.get("unit", "")
                            })
                    elif isinstance(val, (int, float)) and val is not None and key != "by_geography":
                        metric_name = f"financial.{section_name}.{key}"
                        if metric_name not in metric_collectors:
                            metric_collectors[metric_name] = []
                        existing_periods = [m["period"] for m in metric_collectors[metric_name]]
                        if period not in existing_periods:
                            metric_collectors[metric_name].append({
                                "period": period, "value": val, "unit": "%"
                            })
        
        # Operational metrics
        operational = data.get("operational", {})
        for section_name, section_data in operational.items():
            if isinstance(section_data, dict):
                for key, val in section_data.items():
                    if isinstance(val, (int, float)) and val is not None:
                        metric_name = f"operational.{section_name}.{key}"
                        if metric_name not in metric_collectors:
                            metric_collectors[metric_name] = []
                        existing_periods = [m["period"] for m in metric_collectors[metric_name]]
                        if period not in existing_periods:
                            metric_collectors[metric_name].append({
                                "period": period, "value": val, "unit": ""
                            })
            elif isinstance(section_data, (int, float)) and section_data is not None:
                metric_name = f"operational.{section_name}"
                if metric_name not in metric_collectors:
                    metric_collectors[metric_name] = []
                existing_periods = [m["period"] for m in metric_collectors[metric_name]]
                if period not in existing_periods:
                    metric_collectors[metric_name].append({
                        "period": period, "value": section_data, "unit": ""
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
    logger.info("META Structured Data Extraction (Enhanced)")
    logger.info("=" * 60)
    
    STRUCTURED_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
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
            yq_info = parse_year_quarter(pdf_name)
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
            
            # 9. Extract operational metrics
            operational = extract_operational(sections, md_content)
            
            # 10. Extract guidance
            guidance = extract_guidance(sections, md_content)
            
            # 11. Extract qualitative
            qualitative = extract_qualitative(sections, md_content)
            
            # 12. Assemble final structure
            structured = {
                "metadata": {
                    "company": "Meta Platforms",
                    "ticker": "META",
                    "pdf_name": pdf_name,
                    "year": yq_info["year"],
                    "quarter": yq_info["quarter"],
                    "period_end": yq_info["period_end"],
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
                "operational": operational,
                "guidance": guidance,
                "qualitative": qualitative,
                "chart_data": {
                    "total_charts_processed": len(chart_data_list),
                    "categorized_charts": {k: len(v) for k, v in categorized_charts.items()},
                    "chart_details": categorized_charts,
                },
                "tables_extracted": md_tables[:10],
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
    parser = argparse.ArgumentParser(description="META Structured Data Extraction")
    parser.add_argument("--input-dir", type=str, default=None,
                       help="Override MineRU results directory")
    args = parser.parse_args()
    
    if args.input_dir:
        MINERU_OUTPUT_DIR = Path(args.input_dir)
    
    run_structured_extraction()
