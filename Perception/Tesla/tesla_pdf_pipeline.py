"""
Tesla Update Deck PDF 解析 Pipeline
====================================
Step 1: MineRU 解析 PDF → 提取文本 + 图片
Step 2: Qwen2.5-VL 7B 分析图表 → 提取 CSV 数据
Step 3: 结构化信息抽取 → 提取财务指标
"""

import os
import sys
import json
import glob
import logging
import argparse
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("pipeline.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============ 路径配置 ============
PROJECT_ROOT = Path(os.path.expanduser("~/AI-Driven-Market-Digital-Twins"))
PERCEPTION_DIR = PROJECT_ROOT / "Perception" / "Tesla"
PDF_DIR = PERCEPTION_DIR / "01_Quarterly_Update_Deck"
OUTPUT_DIR = PERCEPTION_DIR / "parsed_output"

# MineRU 输出目录
MINERU_OUTPUT_DIR = OUTPUT_DIR / "mineru_results"
# 图表提取输出
CHART_OUTPUT_DIR = OUTPUT_DIR / "chart_extractions"
# 结构化数据输出
STRUCTURED_OUTPUT_DIR = OUTPUT_DIR / "structured_data"


def ensure_dirs():
    """创建所有输出目录"""
    for d in [OUTPUT_DIR, MINERU_OUTPUT_DIR, CHART_OUTPUT_DIR, STRUCTURED_OUTPUT_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    logger.info(f"输出目录已准备: {OUTPUT_DIR}")


def get_pdf_list():
    """获取所有待解析的PDF文件"""
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    logger.info(f"找到 {len(pdfs)} 个 PDF 文件")
    return pdfs


# ============ Step 1: MineRU 解析 PDF ============
def run_mineru_parse(pdf_path: Path, output_dir: Path):
    """
    使用 MineRU 解析单个 PDF
    提取: 文本(markdown)、图片、表格
    """
    from magic_pdf.data.data_reader_writer import FileBasedDataWriter, FileBasedDataReader
    from magic_pdf.data.dataset import PymuDocDataset
    from magic_pdf.model.doc_analyze_by_custom_model import doc_analyze
    from magic_pdf.config.enums import SupportedPdfParseMethod

    pdf_name = pdf_path.stem
    pdf_output_dir = output_dir / pdf_name
    pdf_output_dir.mkdir(parents=True, exist_ok=True)

    # 图片输出目录
    img_dir = pdf_output_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"MineRU 解析: {pdf_name}")

    try:
        # 读取 PDF 数据
        reader = FileBasedDataReader("")
        pdf_bytes = reader.read(str(pdf_path))

        # 创建数据集
        ds = PymuDocDataset(pdf_bytes)

        # 模型推理 - 使用自动检测模式
        infer_result = ds.apply(doc_analyze, ocr=True)

        # 解析 PDF
        pipe_result = infer_result.pipe_ocr_mode(
            FileBasedDataWriter(str(img_dir))
        )

        # 获取 markdown 内容
        md_content = pipe_result.get_markdown(str(img_dir))

        # 保存 markdown
        md_path = pdf_output_dir / f"{pdf_name}.md"
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        # 获取内容列表（结构化信息）
        content_list = pipe_result.get_content_list(str(img_dir))

        # 保存内容列表
        content_path = pdf_output_dir / f"{pdf_name}_content.json"
        with open(content_path, 'w', encoding='utf-8') as f:
            json.dump(content_list, f, ensure_ascii=False, indent=2)

        # 收集图片路径
        images = list(img_dir.glob("*.png")) + list(img_dir.glob("*.jpg"))

        logger.info(f"  完成: {len(images)} 张图片, markdown {len(md_content)} 字符")

        return {
            "pdf_name": pdf_name,
            "md_path": str(md_path),
            "content_path": str(content_path),
            "images": [str(img) for img in images],
            "image_dir": str(img_dir),
            "success": True
        }

    except Exception as e:
        logger.error(f"  MineRU 解析失败 [{pdf_name}]: {e}")
        return {
            "pdf_name": pdf_name,
            "success": False,
            "error": str(e)
        }


def run_mineru_all():
    """对所有 PDF 执行 MineRU 解析"""
    logger.info("=" * 60)
    logger.info("Step 1: MineRU PDF 解析")
    logger.info("=" * 60)

    pdfs = get_pdf_list()
    results = []

    for i, pdf in enumerate(pdfs):
        logger.info(f"[{i+1}/{len(pdfs)}] 处理: {pdf.name}")

        # 检查是否已解析
        output_check = MINERU_OUTPUT_DIR / pdf.stem / f"{pdf.stem}.md"
        if output_check.exists():
            logger.info(f"  跳过（已存在）: {pdf.stem}")
            results.append({
                "pdf_name": pdf.stem,
                "md_path": str(output_check),
                "image_dir": str(MINERU_OUTPUT_DIR / pdf.stem / "images"),
                "images": [str(p) for p in (MINERU_OUTPUT_DIR / pdf.stem / "images").glob("*.*")],
                "success": True
            })
            continue

        result = run_mineru_parse(pdf, MINERU_OUTPUT_DIR)
        results.append(result)

    # 保存解析汇总
    summary_path = MINERU_OUTPUT_DIR / "parse_summary.json"
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    success_count = sum(1 for r in results if r.get("success"))
    logger.info(f"MineRU 解析完成: {success_count}/{len(results)} 成功")

    return results


# ============ Step 2: Qwen2.5-VL 图表分析 ============
class ChartAnalyzer:
    """使用 Qwen2.5-VL 7B 分析图表"""

    def __init__(self, model_path="/hpc2hdd/home/wyu899/evo_prm/Qwen/Qwen2.5-VL-7B-Instruct"):
        self.model = None
        self.processor = None
        self.model_path = model_path

    def load_model(self):
        """加载 Qwen2.5-VL 模型"""
        from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor
        import torch

        logger.info(f"加载 Qwen2.5-VL 模型: {self.model_path}")

        self.processor = AutoProcessor.from_pretrained(self.model_path)
        self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            self.model_path,
            torch_dtype=torch.float16,
            device_map="auto",
        )
        logger.info("模型加载完成")

    def is_chart_image(self, image_path: str) -> bool:
        """判断图片是否为数据图表（而非产品图/装饰图）"""
        from PIL import Image
        import torch

        image = Image.open(image_path).convert("RGB")

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": (
                        "Is this image a data chart, graph, or table that contains numerical/financial data? "
                        "(e.g., bar chart, line chart, pie chart, financial table with numbers). "
                        "Answer ONLY 'YES' or 'NO'. Do not include any other text."
                    )}
                ]
            }
        ]

        text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.processor(
            text=[text],
            images=[image],
            return_tensors="pt",
            padding=True
        ).to(self.model.device)

        with torch.no_grad():
            output_ids = self.model.generate(**inputs, max_new_tokens=10)

        response = self.processor.batch_decode(
            output_ids[:, inputs.input_ids.shape[1]:],
            skip_special_tokens=True
        )[0].strip().upper()

        return "YES" in response

    def extract_chart_to_csv(self, image_path: str) -> dict:
        """将图表提取为 CSV 格式数据"""
        from PIL import Image
        import torch

        image = Image.open(image_path).convert("RGB")

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": (
                        "You are a financial data extraction expert. "
                        "Please extract ALL numerical data from this chart/table into CSV format.\n"
                        "Rules:\n"
                        "1. First row should be column headers\n"
                        "2. Use comma as separator\n"
                        "3. Include units in headers if visible (e.g., 'Revenue ($B)', 'Units (thousands)')\n"
                        "4. Extract ALL data points visible in the chart\n"
                        "5. If it's a time-series chart, use the time period as the first column\n"
                        "6. Output ONLY the CSV data, no explanation\n"
                        "Output the CSV data now:"
                    )}
                ]
            }
        ]

        text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.processor(
            text=[text],
            images=[image],
            return_tensors="pt",
            padding=True
        ).to(self.model.device)

        with torch.no_grad():
            output_ids = self.model.generate(**inputs, max_new_tokens=2048, temperature=0.1)

        csv_content = self.processor.batch_decode(
            output_ids[:, inputs.input_ids.shape[1]:],
            skip_special_tokens=True
        )[0].strip()

        return {
            "image_path": image_path,
            "csv_data": csv_content
        }

    def describe_chart(self, image_path: str) -> str:
        """生成图表描述（用于Q&A上下文）"""
        from PIL import Image
        import torch

        image = Image.open(image_path).convert("RGB")

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": (
                        "Please describe this financial chart/table in detail. Include:\n"
                        "1. What type of chart/visualization it is\n"
                        "2. What metrics/data it shows\n"
                        "3. Key trends, peaks, and notable data points\n"
                        "4. Time period covered\n"
                        "5. Any year-over-year changes or growth rates visible\n"
                        "Please respond in English."
                    )}
                ]
            }
        ]

        text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.processor(
            text=[text],
            images=[image],
            return_tensors="pt",
            padding=True
        ).to(self.model.device)

        with torch.no_grad():
            output_ids = self.model.generate(**inputs, max_new_tokens=1024, temperature=0.3)

        description = self.processor.batch_decode(
            output_ids[:, inputs.input_ids.shape[1]:],
            skip_special_tokens=True
        )[0].strip()

        return description

    def answer_question(self, image_path: str, question: str) -> str:
        """针对图表回答用户问题"""
        from PIL import Image
        import torch

        image = Image.open(image_path).convert("RGB")

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": (
                        f"Based on this financial chart/table, please answer the following question in Chinese:\n"
                        f"问题: {question}\n"
                        f"请用中文详细回答，并引用图表中的具体数据。"
                    )}
                ]
            }
        ]

        text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.processor(
            text=[text],
            images=[image],
            return_tensors="pt",
            padding=True
        ).to(self.model.device)

        with torch.no_grad():
            output_ids = self.model.generate(**inputs, max_new_tokens=1024, temperature=0.3)

        answer = self.processor.batch_decode(
            output_ids[:, inputs.input_ids.shape[1]:],
            skip_special_tokens=True
        )[0].strip()

        return answer


def run_chart_extraction(mineru_results: list):
    """对 MineRU 提取的图片执行图表分析"""
    logger.info("=" * 60)
    logger.info("Step 2: Qwen2.5-VL 图表提取与分析")
    logger.info("=" * 60)

    analyzer = ChartAnalyzer()
    analyzer.load_model()

    all_chart_results = []

    for result in mineru_results:
        if not result.get("success"):
            continue

        pdf_name = result["pdf_name"]
        images = result.get("images", [])

        if not images:
            continue

        logger.info(f"\n分析 {pdf_name} 的 {len(images)} 张图片...")

        pdf_chart_dir = CHART_OUTPUT_DIR / pdf_name
        pdf_chart_dir.mkdir(parents=True, exist_ok=True)

        chart_results = []

        for img_path in images:
            if not os.path.exists(img_path):
                continue

            # 判断是否为数据图表
            try:
                is_chart = analyzer.is_chart_image(img_path)
            except Exception as e:
                logger.warning(f"  判断图表类型失败 [{img_path}]: {e}")
                continue

            if not is_chart:
                logger.info(f"  跳过非图表: {os.path.basename(img_path)}")
                continue

            logger.info(f"  处理图表: {os.path.basename(img_path)}")

            # 提取 CSV 数据
            try:
                csv_result = analyzer.extract_chart_to_csv(img_path)
                csv_filename = Path(img_path).stem + ".csv"
                csv_path = pdf_chart_dir / csv_filename
                with open(csv_path, 'w', encoding='utf-8') as f:
                    f.write(csv_result["csv_data"])
            except Exception as e:
                logger.warning(f"  CSV提取失败: {e}")
                csv_result = {"csv_data": ""}
                csv_path = ""

            # 生成图表描述
            try:
                description = analyzer.describe_chart(img_path)
            except Exception as e:
                logger.warning(f"  描述生成失败: {e}")
                description = ""

            chart_info = {
                "image_path": img_path,
                "image_name": os.path.basename(img_path),
                "csv_path": str(csv_path),
                "csv_data": csv_result["csv_data"],
                "description": description,
                "pdf_source": pdf_name
            }
            chart_results.append(chart_info)

        # 保存该 PDF 的图表分析结果
        if chart_results:
            result_path = pdf_chart_dir / f"{pdf_name}_charts.json"
            with open(result_path, 'w', encoding='utf-8') as f:
                json.dump(chart_results, f, ensure_ascii=False, indent=2)
            logger.info(f"  {pdf_name}: 提取了 {len(chart_results)} 个图表")

        all_chart_results.extend(chart_results)

    # 保存全部图表结果汇总
    summary_path = CHART_OUTPUT_DIR / "all_charts_summary.json"
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(all_chart_results, f, ensure_ascii=False, indent=2)

    logger.info(f"\n图表提取完成: 共 {len(all_chart_results)} 个图表")
    return all_chart_results


# ============ Step 3: 结构化信息抽取 ============

# Chart classification keywords (16 categories)
CHART_CATEGORY_KEYWORDS = {
    "revenue": ["revenue", "total revenue", "automotive revenue", "energy revenue", "services revenue", "sales"],
    "gross_profit": ["gross profit", "gross margin"],
    "operating": ["operating income", "operating expense", "opex", "operating margin", "sga", "r&d", "restructuring"],
    "net_income": ["net income", "net profit", "net earnings", "profit attributable"],
    "eps": ["earnings per share", "eps", "diluted eps", "basic eps"],
    "cash_flow": ["cash flow", "free cash flow", "fcf", "operating cash flow", "capital expenditure", "capex"],
    "deliveries": ["deliveries", "vehicles delivered", "total deliveries", "units delivered"],
    "production": ["production", "vehicles produced", "total production", "units produced"],
    "energy_storage": ["energy storage", "gwh", "megapack", "powerwall", "solar", "energy generation"],
    "capacity": ["capacity", "installed capacity", "factory capacity", "annualized"],
    "supercharger": ["supercharger", "connector", "charging station", "nacs"],
    "market_share": ["market share", "share of", "bev market"],
    "income_statement": ["statement of operations", "income statement", "cost of revenue", "total cost"],
    "balance_sheet": ["balance sheet", "total assets", "total liabilities", "stockholders equity", "current assets"],
    "cash_flow_statement": ["statement of cash flows", "cash flow statement", "investing activities", "financing activities"],
    "reconciliation": ["gaap", "non-gaap", "reconciliation", "adjusted", "stock-based compensation"],
}

# 章节分类关键词
SECTION_KEYWORDS = {
    "highlights": ["highlight", "summary", "q1 and fy", "q2 and fy", "q3 and fy", "q4 and fy", "update"],
    "financial_summary": ["financial summary", "financial highlights", "financial results", "revenue", "profitability", "cash"],
    "operational_summary": ["operational summary", "operational highlights", "operations"],
    "vehicle_capacity": ["capacity", "vehicle capacity", "factory", "us:", "apac:", "europe:"],
    "core_technology": ["core technology", "technology", "artificial intelligence", "vehicle and other software", "battery", "powertrain"],
    "other_highlights": ["other highlights", "other business", "regulatory credit", "supercharg", "energy generation", "services and other"],
    "outlook": ["outlook", "guidance", "forward", "looking ahead"],
    "key_metrics": ["key metrics", "key financial", "summary of"],
    "financial_statements": ["financial statement", "income statement", "balance sheet", "cash flow statement", "statement of operations"],
    "reconciliation": ["reconciliation", "gaap", "non-gaap"],
    "additional": ["additional", "supplemental", "appendix"],
    "legal": ["webcast", "certain terms", "forward-looking statements", "non-gaap financial information"],
}


def is_quarterly_period(period_str: str) -> bool:
    """判断时间标识是否为季度（而非年度）"""
    if not period_str:
        return False
    import re
    return bool(re.search(r'[Qq][1-4]|[1-4][Qq]', period_str))


def clean_numeric(value_str: str):
    """清理数值字符串，返回 (float_value, unit) 或 (None, '')"""
    if not value_str or not isinstance(value_str, str):
        return None, ""
    
    s = value_str.strip()
    if not s:
        return None, ""
    
    # 检测单位后缀
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
    
    # 移除前缀符号（>, <, ~, ≈）
    s = s.lstrip('>').lstrip('<').lstrip('~').lstrip('≈')
    
    # 移除非数字字符（保留小数点和负号）
    s = s.replace('$', '').replace(',', '').replace(' ', '')
    s = s.rstrip('BbMmKk%')
    s = s.replace('billion', '').replace('million', '').replace('thousand', '')
    
    # 处理括号表示负数: (123) -> -123
    if s.startswith('(') and s.endswith(')'):
        s = '-' + s[1:-1]
    
    # 移除残余的非数字前缀
    import re
    match = re.search(r'-?[\d.]+', s)
    if match:
        s = match.group(0)
    
    try:
        return float(s), unit
    except (ValueError, TypeError):
        return None, ""


def parse_csv_data(csv_raw: str) -> dict:
    """解析原始CSV字符串，返回 {headers, rows, parse_errors}"""
    import csv
    import io
    
    result = {"headers": [], "rows": [], "parse_errors": []}
    
    if not csv_raw or not csv_raw.strip():
        return result
    
    # 移除markdown code fence
    content = csv_raw.strip()
    if content.startswith('```'):
        lines = content.split('\n')
        # 移除第一行 ```csv 和最后一行 ```
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
        
        # 第一行为headers
        result["headers"] = [h.strip() for h in all_rows[0]]
        
        # 后续行为数据
        for i, row in enumerate(all_rows[1:], 1):
            if row and any(cell.strip() for cell in row):
                # 对齐到header长度
                cleaned_row = [cell.strip() for cell in row]
                result["rows"].append(cleaned_row)
    except Exception as e:
        result["parse_errors"].append(str(e))
    
    return result


def categorize_chart(chart_info: dict) -> list:
    """根据CSV headers + description对图表分类，返回类别列表（支持多类别）"""
    scores = {cat: 0 for cat in CHART_CATEGORY_KEYWORDS}
    
    # Signal A: CSV Headers (weight 3) - 跳过代码围栏获取真正的header行
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
    
    # Signal B: Description (weight 2)
    description = chart_info.get("description", "").lower()
    for cat, keywords in CHART_CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in description:
                scores[cat] += 2
    
    # Signal C: Image filename (weight 1) — usually not helpful but included
    image_name = chart_info.get("image_name", "").lower()
    for cat, keywords in CHART_CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw.replace(' ', '_') in image_name or kw.replace(' ', '') in image_name:
                scores[cat] += 1
    
    # 返回所有得分>=阈值的类别（支持多类别分配）
    threshold = 4
    categories = [cat for cat, score in scores.items() if score >= threshold]
    
    # 如果没有高分类别，降低阈值
    if not categories:
        threshold = 2
        categories = [cat for cat, score in scores.items() if score >= threshold]
    
    if not categories:
        return ["uncategorized"]
    
    return categories


def load_chart_data_for_pdf(pdf_name: str, chart_results_in_memory: list = None) -> list:
    """加载某个PDF对应的图表数据（从内存或磁盘）"""
    # 优先从内存加载
    if chart_results_in_memory:
        return [c for c in chart_results_in_memory if c.get("pdf_source") == pdf_name]
    
    # 从磁盘加载
    charts_json = CHART_OUTPUT_DIR / pdf_name / f"{pdf_name}_charts.json"
    if charts_json.exists():
        try:
            with open(charts_json, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"加载图表数据失败 [{pdf_name}]: {e}")
    
    return []


def parse_sections(md_content: str) -> dict:
    """将MD内容按章节分段，返回 section_key -> text content"""
    import re
    
    sections = {}
    lines = md_content.split('\n')
    
    current_section = "highlights"  # 默认开头为highlights
    current_lines = []
    
    for line in lines:
        # 检测markdown标题
        header_match = re.match(r'^#{1,3}\s+(.+)', line)
        if header_match:
            # 保存当前章节
            if current_lines:
                text = '\n'.join(current_lines).strip()
                if text:
                    if current_section in sections:
                        sections[current_section] += '\n\n' + text
                    else:
                        sections[current_section] = text
            
            # 分类新章节
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
    
    # 保存最后一个章节
    if current_lines:
        text = '\n'.join(current_lines).strip()
        if text:
            if current_section in sections:
                sections[current_section] += '\n\n' + text
            else:
                sections[current_section] = text
    
    return sections


def extract_tables_from_markdown(md_content: str) -> list:
    """从 Markdown 中提取所有表格"""
    import re
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
            tables.append({
                "table_index": i,
                "headers": headers,
                "data": data_rows
            })

    return tables


def extract_all_highlights(md_content: str, sections: dict) -> dict:
    """全文提取highlights: bullet_points + key_metrics_mentioned"""
    import re
    
    highlights = {
        "bullet_points": [],
        "key_metrics_mentioned": []
    }
    
    # 扩展关键词列表
    financial_terms = [
        'revenue', 'profit', 'margin', 'income', 'cash flow', 'deliveries',
        'production', 'gwh', 'eps', 'growth', 'capacity', 'deployed',
        'supercharger', 'connectors', 'free cash flow', 'capex', 'ebitda',
        'regulatory credit', 'fsd', 'autopilot', 'cybertruck', 'semi',
        'megapack', 'powerwall', 'solar', 'optimus', 'dojo', 'market share',
        'record', 'vehicles', 'energy storage', 'cogs'
    ]
    
    # 从highlights章节提取bullet points
    highlight_text = sections.get("highlights", "")
    lines = md_content.split('\n')
    
    for line in lines:
        stripped = line.strip()
        # 跳过图片引用和空行
        if not stripped or stripped.startswith('!['):
            continue
        
        line_lower = stripped.lower()
        # 提取包含财务/运营关键词且有数字的行
        if any(term in line_lower for term in financial_terms):
            if re.search(r'\d', stripped):
                highlights["bullet_points"].append(stripped)
                
                # 尝试提取具体指标
                # 匹配模式: keyword ... $XX.XB 或 XX% 或 XX,XXX
                metric_patterns = [
                    (r'revenue[^.]*?[\$]?\s*([\d,]+\.?\d*)\s*(B|M|billion|million|%)', 'revenue'),
                    (r'([\d,]+\.?\d*)\s*%\s*(operating margin|gross margin|margin)', 'margin'),
                    (r'deliveries[^.]*?([\d,]+\.?\d*)\s*(K|k|thousand|vehicles)?', 'deliveries'),
                    (r'production[^.]*?([\d,]+\.?\d*)\s*(K|k|thousand|vehicles)?', 'production'),
                    (r'([\d,]+\.?\d*)\s*GWh', 'energy_storage'),
                    (r'free cash flow[^.]*?[\$]?\s*([\d,]+\.?\d*)\s*(B|M|billion|million)?', 'free_cash_flow'),
                    (r'eps[^.]*?[\$]?\s*([\d,]+\.?\d*)', 'eps'),
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


def extract_qualitative(sections: dict) -> dict:
    """提取定性信息：core_technology, outlook, other_highlights, risks"""
    import re
    
    qualitative = {
        "core_technology": [],
        "outlook": [],
        "other_highlights": [],
        "risks_and_challenges": []
    }
    
    # 提取各章节的文本内容（过滤掉图片引用）
    def clean_section_text(text):
        lines = []
        for line in text.split('\n'):
            stripped = line.strip()
            if stripped and not stripped.startswith('![') and not stripped.startswith('---'):
                lines.append(stripped)
        return lines
    
    # Core Technology
    for key in ["core_technology"]:
        if key in sections:
            qualitative["core_technology"] = clean_section_text(sections[key])
    
    # Outlook
    if "outlook" in sections:
        qualitative["outlook"] = clean_section_text(sections["outlook"])
    
    # Other Highlights
    if "other_highlights" in sections:
        qualitative["other_highlights"] = clean_section_text(sections["other_highlights"])
    
    # Risks - 从全文中提取包含负面词汇的语句
    risk_keywords = ['decline', 'decreased', 'reduced', 'lower', 'challenge', 'risk',
                     'headwind', 'pressure', 'unfavorable', 'negative', 'loss', 'impacted by']
    
    all_text = '\n'.join(sections.values())
    for line in all_text.split('\n'):
        stripped = line.strip()
        if stripped and not stripped.startswith('!['):
            line_lower = stripped.lower()
            if any(kw in line_lower for kw in risk_keywords) and re.search(r'\d', stripped):
                qualitative["risks_and_challenges"].append(stripped)
    
    return qualitative


def extract_metrics_from_csv(parsed_csv: dict, category: str) -> dict:
    """从解析后的CSV中提取结构化指标"""
    metrics = {
        "time_series": [],
        "latest_values": {},
        "raw_data": {"headers": parsed_csv["headers"], "rows": parsed_csv["rows"][:20]}  # 保留前20行
    }
    
    headers = parsed_csv["headers"]
    rows = parsed_csv["rows"]
    
    if not headers or not rows:
        return metrics
    
    # 检测是否是时间序列数据（第一列包含时间标识）
    import re
    time_pattern = re.compile(r'(Q[1-4]|20\d{2}|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|FY)', re.IGNORECASE)
    
    first_col_is_time = False
    if rows:
        time_matches = sum(1 for row in rows if row and time_pattern.search(row[0]))
        if time_matches >= len(rows) * 0.5:
            first_col_is_time = True
    
    if first_col_is_time:
        # 时间序列: 第一列是时间，后续列是指标
        # 需要过滤掉"YoY"、"Change"等汇总行
        summary_keywords = ["yoy", "y/y", "change", "growth", "vs", "qoq"]
        
        for row in rows:
            if not row or len(row) < 2:
                continue
            period = row[0].strip()
            # 跳过汇总/比较行
            if any(kw in period.lower() for kw in summary_keywords):
                continue
            entry = {"period": period}
            for i, header in enumerate(headers[1:], 1):
                if i < len(row):
                    value, unit = clean_numeric(row[i])
                    if value is not None:
                        entry[header] = {"value": value, "unit": unit}
            if len(entry) > 1:  # 至少有period + 一个值
                metrics["time_series"].append(entry)
        
        # latest_values = 最后一行（已过滤掉YoY行）
        if metrics["time_series"]:
            metrics["latest_values"] = metrics["time_series"][-1]
    else:
        # 非时间序列（如财务报表：行=line item, 列=period）
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


def build_financial_data(categorized_charts: dict, sections: dict, md_tables: list) -> dict:
    """构建financial子schema，融合chart CSV + MD表格 + 文本"""
    import re
    
    financial = {
        "revenue": {"total_revenue": None, "automotive_revenue": None, "energy_revenue": None, 
                    "services_revenue": None, "regulatory_credits": None, "quarterly_trend": []},
        "profitability": {"gross_profit": None, "gross_margin_pct": None, "automotive_gross_margin_pct": None,
                          "operating_income": None, "operating_margin_pct": None, 
                          "net_income_gaap": None, "net_income_non_gaap": None, "quarterly_trend": []},
        "per_share": {"eps_gaap": None, "eps_non_gaap": None},
        "cash_flow": {"operating_cash_flow": None, "capital_expenditure": None, 
                      "free_cash_flow": None, "quarterly_trend": []},
        "balance_sheet": {"cash_and_equivalents": None, "total_debt": None, 
                          "total_assets": None, "total_liabilities": None, "stockholders_equity": None},
        "income_statement_data": [],
        "balance_sheet_data": [],
        "cash_flow_statement_data": [],
        "gaap_to_non_gaap_reconciliation": []
    }
    
    def get_latest_metric(parsed, key_patterns):
        """从parsed_metrics的latest_values中按关键词模式提取值"""
        latest = parsed.get("latest_values", {})
        for key, val in latest.items():
            if key == "period":
                continue
            if not isinstance(val, dict) or "value" not in val:
                continue
            key_lower = key.lower()
            for pattern in key_patterns:
                if pattern in key_lower:
                    return val
        return None
    
    # 季度数据优先机制
    _q_locked = set()
    
    def set_fin_val(section, field, val, period_str):
        """设置财务值，季度数据优先于年度数据"""
        key = f"{section}.{field}"
        is_q = is_quarterly_period(period_str)
        current = financial[section][field]
        if current is None:
            financial[section][field] = val
            if is_q:
                _q_locked.add(key)
        elif is_q and key not in _q_locked:
            financial[section][field] = val
            _q_locked.add(key)
    
    # 从chart CSV提取
    for category, charts in categorized_charts.items():
        for chart in charts:
            parsed = chart.get("parsed_metrics", {})
            latest = parsed.get("latest_values", {})
            period_str = latest.get("period", "") if isinstance(latest, dict) else ""
            
            if category == "revenue":
                if parsed.get("time_series"):
                    financial["revenue"]["quarterly_trend"].extend(parsed["time_series"])
                
                # 从latest_values中精确匹配字段
                for key, val in latest.items():
                    if key == "period" or not isinstance(val, dict) or "value" not in val:
                        continue
                    key_lower = key.lower()
                    is_pct = val.get("unit") == "%"
                    
                    if ("total revenues" in key_lower or "total revenue" in key_lower) and not is_pct:
                        set_fin_val("revenue", "total_revenue", val, period_str)
                    elif "total automotive" in key_lower and not is_pct:
                        set_fin_val("revenue", "automotive_revenue", val, period_str)
                    elif ("automotive sales" in key_lower or "automotive revenue" in key_lower) and not is_pct:
                        if not financial["revenue"]["automotive_revenue"]:
                            set_fin_val("revenue", "automotive_revenue", val, period_str)
                    elif ("energy" in key_lower and ("generation" in key_lower or "storage" in key_lower or "revenue" in key_lower)) and not is_pct:
                        set_fin_val("revenue", "energy_revenue", val, period_str)
                    elif ("service" in key_lower and ("revenue" in key_lower or "other" in key_lower)) and not is_pct:
                        set_fin_val("revenue", "services_revenue", val, period_str)
                    elif "regulatory" in key_lower and "credit" in key_lower and not is_pct:
                        set_fin_val("revenue", "regulatory_credits", val, period_str)
            
            elif category == "gross_profit":
                for key, val in latest.items():
                    if key == "period" or not isinstance(val, dict) or "value" not in val:
                        continue
                    key_lower = key.lower()
                    if "margin" in key_lower and val.get("unit") == "%":
                        set_fin_val("profitability", "gross_margin_pct", val, period_str)
                    elif "profit" in key_lower and val.get("unit") != "%":
                        set_fin_val("profitability", "gross_profit", val, period_str)
            
            elif category == "operating":
                if parsed.get("time_series"):
                    financial["profitability"]["quarterly_trend"].extend(parsed["time_series"])
                for key, val in latest.items():
                    if key == "period" or not isinstance(val, dict) or "value" not in val:
                        continue
                    key_lower = key.lower()
                    if "margin" in key_lower and val.get("unit") == "%":
                        set_fin_val("profitability", "operating_margin_pct", val, period_str)
                    elif ("income" in key_lower or "profit" in key_lower) and val.get("unit") != "%":
                        set_fin_val("profitability", "operating_income", val, period_str)
            
            elif category == "net_income":
                for key, val in latest.items():
                    if key == "period" or not isinstance(val, dict) or "value" not in val:
                        continue
                    key_lower = key.lower()
                    # key必须含"net income"/"net profit"才设值（防止其他字段污染）
                    if "net income" not in key_lower and "net profit" not in key_lower and "net earnings" not in key_lower:
                        continue
                    # 跳过TTM值
                    if "ttm" in key_lower:
                        continue
                    if "non-gaap" in key_lower or "non_gaap" in key_lower:
                        set_fin_val("profitability", "net_income_non_gaap", val, period_str)
                    elif val.get("unit") != "%":
                        set_fin_val("profitability", "net_income_gaap", val, period_str)
            
            elif category == "eps":
                for key, val in latest.items():
                    if key == "period" or not isinstance(val, dict) or "value" not in val:
                        continue
                    key_lower = key.lower()
                    # EPS值通常绝对值 < 10, 且key必须含"per share"或"eps"
                    if abs(val.get("value", 0)) > 20:
                        continue  # 不是EPS，可能是shares数或其他大数值
                    if "per share" not in key_lower and "eps" not in key_lower:
                        continue  # key必须明确是EPS
                    if "non-gaap" in key_lower or "non_gaap" in key_lower:
                        set_fin_val("per_share", "eps_non_gaap", val, period_str)
                    else:
                        set_fin_val("per_share", "eps_gaap", val, period_str)
            
            elif category == "cash_flow":
                if parsed.get("time_series"):
                    financial["cash_flow"]["quarterly_trend"].extend(parsed["time_series"])
                for key, val in latest.items():
                    if key == "period" or not isinstance(val, dict) or "value" not in val:
                        continue
                    key_lower = key.lower()
                    # 跳过TTM（trailing twelve months）标记的值，只取单季度
                    if "ttm" in key_lower:
                        continue
                    if "free" in key_lower and ("cash" in key_lower or "flow" in key_lower):
                        set_fin_val("cash_flow", "free_cash_flow", val, period_str)
                    elif "operating" in key_lower and ("cash" in key_lower or "activit" in key_lower):
                        set_fin_val("cash_flow", "operating_cash_flow", val, period_str)
                    elif "capital" in key_lower or "capex" in key_lower:
                        set_fin_val("cash_flow", "capital_expenditure", val, period_str)
            
            elif category == "income_statement":
                financial["income_statement_data"].append(parsed.get("latest_values", {}))
            
            elif category == "balance_sheet":
                data = parsed.get("latest_values", {})
                financial["balance_sheet_data"].append(data)
                for key, val in data.items():
                    if key == "period" or not isinstance(val, dict) or "value" not in val:
                        continue
                    key_lower = key.lower()
                    if "cash" in key_lower and ("equivalent" in key_lower or "investment" in key_lower):
                        financial["balance_sheet"]["cash_and_equivalents"] = val
                    elif "total assets" in key_lower:
                        financial["balance_sheet"]["total_assets"] = val
                    elif "total liabilities" in key_lower:
                        financial["balance_sheet"]["total_liabilities"] = val
                    elif "debt" in key_lower:
                        financial["balance_sheet"]["total_debt"] = val
                    elif "stockholders" in key_lower or "equity" in key_lower:
                        financial["balance_sheet"]["stockholders_equity"] = val
            
            elif category == "cash_flow_statement":
                financial["cash_flow_statement_data"].append(parsed.get("latest_values", {}))
            
            elif category == "reconciliation":
                financial["gaap_to_non_gaap_reconciliation"].append(parsed.get("latest_values", {}))
    
    # 从MD表格补充（如果chart CSV中未覆盖）
    for table in md_tables:
        headers_lower = [h.lower() for h in table.get("headers", [])]
        header_str = ' '.join(headers_lower)
        
        if any(kw in header_str for kw in ["revenue", "income", "cost"]):
            if not financial["income_statement_data"]:
                financial["income_statement_data"].append({
                    "headers": table["headers"],
                    "data": table["data"]
                })
        elif any(kw in header_str for kw in ["assets", "liabilities", "equity"]):
            if not financial["balance_sheet_data"]:
                financial["balance_sheet_data"].append({
                    "headers": table["headers"],
                    "data": table["data"]
                })
    
    # 从文本中补充（regex fallback）
    fin_text = sections.get("financial_summary", "")
    if fin_text and not financial["revenue"]["total_revenue"]:
        match = re.search(r'revenue[^.]*?[\$]\s*([\d,]+\.?\d*)\s*(B|billion)', fin_text, re.IGNORECASE)
        if match:
            value, unit = clean_numeric(match.group(1))
            if value is not None:
                financial["revenue"]["total_revenue"] = {"value": value, "unit": "B"}
    
    return financial


def build_operational_data(categorized_charts: dict, sections: dict, md_tables: list) -> dict:
    """构建operational子schema"""
    import re
    
    operational = {
        "deliveries": {"total": None, "model_3_y": None, "other_models": None, 
                       "cybertruck": None, "quarterly_trend": [], "yoy_growth_pct": None},
        "production": {"total": None, "model_3_y": None, "other_models": None,
                       "quarterly_trend": [], "yoy_growth_pct": None},
        "capacity": {"total_installed_annual": None, "by_factory": []},
        "energy_storage": {"gwh_deployed": None, "quarterly_trend": [], "yoy_growth_pct": None},
        "supercharger": {"stations": None, "connectors": None, "quarterly_trend": []}
    }
    
    # 追踪哪些字段已被季度数据填充（季度数据优先于年度数据）
    _q_locked = set()
    
    def set_val(section, field, val, period_str):
        """设置值，季度数据优先"""
        key = f"{section}.{field}"
        is_q = is_quarterly_period(period_str)
        current = operational[section][field]
        if current is None:
            operational[section][field] = val
            if is_q:
                _q_locked.add(key)
        elif is_q and key not in _q_locked:
            operational[section][field] = val
            _q_locked.add(key)
    
    for category, charts in categorized_charts.items():
        for chart in charts:
            parsed = chart.get("parsed_metrics", {})
            latest = parsed.get("latest_values", {})
            period_str = latest.get("period", "") if isinstance(latest, dict) else ""
            
            if category == "deliveries":
                if parsed.get("time_series"):
                    for entry in parsed["time_series"]:
                        delivery_entry = {"period": entry.get("period", "")}
                        for key, val in entry.items():
                            if key == "period":
                                continue
                            if "deliver" in key.lower():
                                delivery_entry[key] = val
                        if len(delivery_entry) > 1:
                            operational["deliveries"]["quarterly_trend"].append(delivery_entry)
                
                for key, val in latest.items():
                    if key == "period" or not isinstance(val, dict) or "value" not in val:
                        continue
                    key_lower = key.lower()
                    if val.get("unit") == "%":
                        continue
                    if "total" in key_lower and "deliver" in key_lower:
                        set_val("deliveries", "total", val, period_str)
                    elif ("model 3" in key_lower or "model y" in key_lower or "3/y" in key_lower) and "deliver" in key_lower:
                        set_val("deliveries", "model_3_y", val, period_str)
                    elif "other" in key_lower and "deliver" in key_lower:
                        set_val("deliveries", "other_models", val, period_str)
                    elif "cybertruck" in key_lower and "deliver" in key_lower:
                        set_val("deliveries", "cybertruck", val, period_str)
            
            elif category == "production":
                if parsed.get("time_series"):
                    for entry in parsed["time_series"]:
                        prod_entry = {"period": entry.get("period", "")}
                        for key, val in entry.items():
                            if key == "period":
                                continue
                            if "produc" in key.lower():
                                prod_entry[key] = val
                        if len(prod_entry) > 1:
                            operational["production"]["quarterly_trend"].append(prod_entry)
                
                for key, val in latest.items():
                    if key == "period" or not isinstance(val, dict) or "value" not in val:
                        continue
                    key_lower = key.lower()
                    if val.get("unit") == "%":
                        continue
                    if "total" in key_lower and "produc" in key_lower:
                        set_val("production", "total", val, period_str)
                    elif ("model 3" in key_lower or "model y" in key_lower or "3/y" in key_lower) and "produc" in key_lower:
                        set_val("production", "model_3_y", val, period_str)
                    elif "other" in key_lower and "produc" in key_lower:
                        set_val("production", "other_models", val, period_str)
            
            elif category == "capacity":
                for key, val in latest.items():
                    if key == "period" or not isinstance(val, dict) or "value" not in val:
                        continue
                    key_lower = key.lower()
                    if "total" in key_lower:
                        operational["capacity"]["total_installed_annual"] = val
                    elif val.get("value", 0) > 0:
                        operational["capacity"]["by_factory"].append({"factory": key, "capacity": val})
            
            elif category == "energy_storage":
                if parsed.get("time_series"):
                    for entry in parsed["time_series"]:
                        es_entry = {"period": entry.get("period", "")}
                        for key, val in entry.items():
                            if key == "period":
                                continue
                            key_lower = key.lower()
                            if "energy" in key_lower or "gwh" in key_lower or "storage" in key_lower or "deploy" in key_lower:
                                es_entry[key] = val
                        if len(es_entry) > 1:
                            operational["energy_storage"]["quarterly_trend"].append(es_entry)
                
                for key, val in latest.items():
                    if key == "period" or not isinstance(val, dict) or "value" not in val:
                        continue
                    key_lower = key.lower()
                    if val.get("unit") == "%":
                        continue
                    if "gwh" in key_lower or "deployed" in key_lower or "energy storage" in key_lower:
                        set_val("energy_storage", "gwh_deployed", val, period_str)
            
            elif category == "supercharger":
                if parsed.get("time_series"):
                    operational["supercharger"]["quarterly_trend"].extend(parsed["time_series"])
                for key, val in latest.items():
                    if key == "period" or not isinstance(val, dict) or "value" not in val:
                        continue
                    key_lower = key.lower()
                    if "station" in key_lower:
                        set_val("supercharger", "stations", val, period_str)
                    elif "connector" in key_lower:
                        set_val("supercharger", "connectors", val, period_str)
    
    # 从文本补充
    op_text = sections.get("operational_summary", "") + sections.get("highlights", "")
    if op_text:
        yoy_match = re.search(r'deliveries?\s+(?:grew|increased)\s+([\d.]+)%\s*(?:YoY|year.over.year)', op_text, re.IGNORECASE)
        if yoy_match:
            operational["deliveries"]["yoy_growth_pct"] = float(yoy_match.group(1))
        
        yoy_match = re.search(r'energy\s+storage[^.]*?([\d.]+)\s*GWh', op_text, re.IGNORECASE)
        if yoy_match and not operational["energy_storage"]["gwh_deployed"]:
            operational["energy_storage"]["gwh_deployed"] = {"value": float(yoy_match.group(1)), "unit": "GWh"}
    
    return operational


def compute_period_end(year: int, quarter: str) -> str:
    """计算季度结束日期"""
    quarter_end = {"Q1": "03-31", "Q2": "06-30", "Q3": "09-30", "Q4": "12-31"}
    q = quarter if quarter else "Q4"
    return f"{year}-{quarter_end.get(q, '12-31')}" if year else ""


def parse_year_quarter(pdf_name: str) -> dict:
    """从文件名解析年份和季度"""
    import re
    match = re.search(r'(\d{4})_Q(\d)', pdf_name)
    if match:
        return {"year": int(match.group(1)), "quarter": f"Q{match.group(2)}"}
    return {"year": None, "quarter": None}


def generate_timeline(all_structured: list) -> dict:
    """生成以指标为中心的时间序列数据，含计算分析"""
    timeline = {
        "description": "Tesla Quarterly Financial & Operational Timeline",
        "period_range": {},
        "reports_included": len(all_structured),
        "metrics": {},
        "computed_analytics": {}
    }
    
    # 按时间排序
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
    
    # 收集所有数值型指标
    metric_collectors = {}
    
    for data in sorted_data:
        period = f"{data['metadata']['year']} {data['metadata']['quarter']}"
        
        # 收集financial指标
        financial = data.get("financial", {})
        for section_name, section_data in financial.items():
            if isinstance(section_data, dict):
                for key, val in section_data.items():
                    if isinstance(val, dict) and "value" in val:
                        metric_name = f"{section_name}.{key}"
                        if metric_name not in metric_collectors:
                            metric_collectors[metric_name] = []
                        metric_collectors[metric_name].append({
                            "period": period,
                            "value": val["value"],
                            "unit": val.get("unit", "")
                        })
        
        # 收集operational指标
        operational = data.get("operational", {})
        for section_name, section_data in operational.items():
            if isinstance(section_data, dict):
                for key, val in section_data.items():
                    if isinstance(val, dict) and "value" in val:
                        metric_name = f"{section_name}.{key}"
                        if metric_name not in metric_collectors:
                            metric_collectors[metric_name] = []
                        metric_collectors[metric_name].append({
                            "period": period,
                            "value": val["value"],
                            "unit": val.get("unit", "")
                        })
    
    timeline["metrics"] = metric_collectors
    
    # 计算分析指标
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
        
        # CAGR（需要至少4个季度的数据）
        if len(values) >= 4 and values[0] != 0 and values[0] > 0 and values[-1] > 0:
            years = len(values) / 4.0
            try:
                cagr = (values[-1] / values[0]) ** (1 / years) - 1
                analytics["cagr_pct"] = round(cagr * 100, 2)
            except (ValueError, ZeroDivisionError):
                pass
        
        # Trend direction
        if len(values) >= 8:
            first_avg = sum(values[:4]) / 4
            last_avg = sum(values[-4:]) / 4
        elif len(values) >= 4:
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
        else:
            analytics["trend_direction"] = "flat"
        
        timeline["computed_analytics"][metric_name] = analytics
    
    return timeline


def extract_structured_data(mineru_results: list, chart_results: list = None):
    """从 MineRU 解析结果 + Chart CSV 中提取结构化投资决策数据"""
    logger.info("=" * 60)
    logger.info("Step 3: 结构化财务信息抽取（增强版）")
    logger.info("=" * 60)

    from datetime import datetime

    all_structured = []

    for result in mineru_results:
        if not result.get("success"):
            continue

        pdf_name = result["pdf_name"]
        md_path = result.get("md_path", "")

        if not md_path or not os.path.exists(md_path):
            continue

        logger.info(f"抽取结构化数据: {pdf_name}")

        with open(md_path, 'r', encoding='utf-8') as f:
            md_content = f.read()

        # 1. 解析年份/季度
        year_quarter = parse_year_quarter(pdf_name)
        year = year_quarter.get("year")
        quarter = year_quarter.get("quarter")

        # 2. 章节解析
        sections = parse_sections(md_content)

        # 3. 加载图表数据
        chart_data_list = load_chart_data_for_pdf(pdf_name, chart_results)

        # 4. 对每个图表: 解析CSV + 分类 + 提取指标
        categorized_charts = {}
        for chart_info in chart_data_list:
            categories = categorize_chart(chart_info)  # 现在返回列表
            parsed_csv = parse_csv_data(chart_info.get("csv_data", ""))
            metrics = extract_metrics_from_csv(parsed_csv, categories[0])
            
            chart_entry = {
                "image_name": chart_info.get("image_name", ""),
                "categories": categories,
                "description": chart_info.get("description", ""),
                "headers": parsed_csv["headers"],
                "data_rows": parsed_csv["rows"][:10],  # 限制存储大小
                "parsed_metrics": metrics
            }
            
            # 同一个图表分配到多个类别
            for category in categories:
                if category not in categorized_charts:
                    categorized_charts[category] = []
                categorized_charts[category].append(chart_entry)

        # 5. 提取MD中的markdown表格
        md_tables = extract_tables_from_markdown(md_content)

        # 6. 提取highlights
        highlights = extract_all_highlights(md_content, sections)

        # 7. 提取定性信息
        qualitative = extract_qualitative(sections)

        # 8. 构建financial和operational数据
        financial = build_financial_data(categorized_charts, sections, md_tables)
        operational = build_operational_data(categorized_charts, sections, md_tables)

        # 9. 组装完整schema
        structured = {
            "metadata": {
                "pdf_name": pdf_name,
                "year": year,
                "quarter": quarter,
                "period_end": compute_period_end(year, quarter),
                "report_type": "Quarterly Update Deck",
                "extraction_timestamp": datetime.now().isoformat(),
                "data_completeness": {
                    "text_sections_found": len(sections),
                    "charts_processed": len(chart_data_list),
                    "md_tables_found": len(md_tables),
                    "metrics_extracted": sum(
                        len(charts) for charts in categorized_charts.values()
                    )
                }
            },
            "highlights": highlights,
            "financial": financial,
            "operational": operational,
            "qualitative": qualitative,
            "chart_data": {
                "total_charts_processed": len(chart_data_list),
                "categorized_charts": categorized_charts
            },
            "data_sources": {
                "text_extracted_metrics": [k for k in sections.keys() if k != "_unclassified"],
                "chart_extracted_metrics": list(categorized_charts.keys()),
                "sections_found": list(sections.keys()),
                "charts_by_category": {k: len(v) for k, v in categorized_charts.items()}
            }
        }

        all_structured.append(structured)

        # 保存单个文件
        output_path = STRUCTURED_OUTPUT_DIR / f"{pdf_name}_structured.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(structured, f, ensure_ascii=False, indent=2)
        
        logger.info(f"  完成: {len(chart_data_list)} 图表, {len(md_tables)} 表格, {len(sections)} 章节")

    # 保存汇总
    summary_path = STRUCTURED_OUTPUT_DIR / "all_structured_data.json"
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(all_structured, f, ensure_ascii=False, indent=2)

    # 生成时间序列
    timeline = generate_timeline(all_structured)
    timeline_path = STRUCTURED_OUTPUT_DIR / "financial_timeline.json"
    with open(timeline_path, 'w', encoding='utf-8') as f:
        json.dump(timeline, f, ensure_ascii=False, indent=2)

    logger.info(f"结构化数据抽取完成: {len(all_structured)} 份报告")
    return all_structured


# ============ Q&A 交互接口 ============
def run_qa_interface():
    """启动图表问答交互界面"""
    logger.info("=" * 60)
    logger.info("图表 Q&A 交互模式")
    logger.info("=" * 60)

    # 加载图表索引
    charts_summary_path = CHART_OUTPUT_DIR / "all_charts_summary.json"
    if not charts_summary_path.exists():
        logger.error("未找到图表数据，请先运行解析和图表提取步骤")
        return

    with open(charts_summary_path, 'r', encoding='utf-8') as f:
        charts = json.load(f)

    if not charts:
        logger.error("没有可用的图表数据")
        return

    # 显示可用图表
    print("\n可用图表列表:")
    print("-" * 60)
    for i, chart in enumerate(charts):
        print(f"  [{i}] {chart['pdf_source']} - {chart['image_name']}")
        if chart.get('description'):
            print(f"      描述: {chart['description'][:80]}...")
    print("-" * 60)

    # 加载模型
    analyzer = ChartAnalyzer()
    analyzer.load_model()

    # 交互循环
    while True:
        print("\n输入格式: <图表编号> <问题> (输入 'quit' 退出)")
        user_input = input(">>> ").strip()

        if user_input.lower() in ['quit', 'exit', 'q']:
            break

        try:
            parts = user_input.split(' ', 1)
            chart_idx = int(parts[0])
            question = parts[1] if len(parts) > 1 else "请描述这个图表的主要信息"

            if 0 <= chart_idx < len(charts):
                chart = charts[chart_idx]
                print(f"\n正在分析图表: {chart['image_name']}...")
                answer = analyzer.answer_question(chart['image_path'], question)
                print(f"\n回答: {answer}")
            else:
                print(f"无效编号，请输入 0-{len(charts)-1}")
        except (ValueError, IndexError):
            print("格式错误，请输入: <图表编号> <问题>")


# ============ 主入口 ============
def main():
    parser = argparse.ArgumentParser(description="Tesla Update Deck PDF 解析 Pipeline")
    parser.add_argument("--step", type=str, default="all",
                       choices=["all", "mineru", "chart", "structure", "qa"],
                       help="运行步骤: all=全部, mineru=仅PDF解析, chart=仅图表提取, structure=仅结构化抽取, qa=问答模式")
    parser.add_argument("--model", type=str, default="/hpc2hdd/home/wyu899/evo_prm/Qwen/Qwen2.5-VL-7B-Instruct",
                       help="Qwen2.5-VL 模型路径")
    args = parser.parse_args()

    ensure_dirs()

    if args.step in ["all", "mineru"]:
        mineru_results = run_mineru_all()
    else:
        # 加载已有结果
        summary_path = MINERU_OUTPUT_DIR / "parse_summary.json"
        if summary_path.exists():
            with open(summary_path, 'r', encoding='utf-8') as f:
                mineru_results = json.load(f)
        else:
            logger.error("未找到 MineRU 解析结果，请先运行 --step mineru")
            return

    if args.step in ["all", "chart"]:
        chart_results = run_chart_extraction(mineru_results)

    if args.step in ["all", "structure"]:
        chart_results_param = chart_results if (args.step == "all" and 'chart_results' in locals()) else None
        structured_results = extract_structured_data(mineru_results, chart_results_param)

    if args.step == "qa":
        run_qa_interface()

    logger.info("\nPipeline 完成!")
    logger.info(f"输出目录: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
