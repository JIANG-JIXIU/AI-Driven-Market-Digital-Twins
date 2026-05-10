"""
Meta Platforms IR Documents PDF Parse Pipeline
===============================================
Step 1: MineRU parse PDF -> extract text + images
Step 2: Qwen2.5-VL 7B analyze charts -> extract CSV data
Step 3: Structured info extraction -> extract financial metrics
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

# ============ Path Config ============
PROJECT_ROOT = Path(os.path.expanduser("~/AI-Driven-Market-Digital-Twins"))
PERCEPTION_DIR = PROJECT_ROOT / "Perception" / "META"
OUTPUT_DIR = PERCEPTION_DIR / "parsed_output"

# MineRU output
MINERU_OUTPUT_DIR = OUTPUT_DIR / "mineru_results"
# Chart extraction output
CHART_OUTPUT_DIR = OUTPUT_DIR / "chart_extractions"
# Structured data output
STRUCTURED_OUTPUT_DIR = OUTPUT_DIR / "structured_data"

# PDF directories to scan
PDF_SUBDIRS = [
    "01_Earnings_Presentation",
    "02_Earnings_Transcript",
    "03_Prepared_Remarks",
    "04_Press_Release",
]


def ensure_dirs():
    for d in [OUTPUT_DIR, MINERU_OUTPUT_DIR, CHART_OUTPUT_DIR, STRUCTURED_OUTPUT_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    logger.info(f"Output dirs ready: {OUTPUT_DIR}")


def get_pdf_list():
    """Get all PDF files from all subdirectories"""
    pdfs = []
    for subdir in PDF_SUBDIRS:
        pdf_dir = PERCEPTION_DIR / subdir
        if pdf_dir.exists():
            found = sorted(pdf_dir.glob("*.pdf"))
            pdfs.extend(found)
            if found:
                logger.info(f"  {subdir}: {len(found)} PDFs")
    logger.info(f"Total: {len(pdfs)} PDF files found")
    return pdfs


# ============ Step 1: MineRU Parse PDF ============
def run_mineru_parse(pdf_path: Path, output_dir: Path):
    from magic_pdf.data.data_reader_writer import FileBasedDataWriter, FileBasedDataReader
    from magic_pdf.data.dataset import PymuDocDataset
    from magic_pdf.model.doc_analyze_by_custom_model import doc_analyze

    pdf_name = pdf_path.stem
    pdf_output_dir = output_dir / pdf_name
    pdf_output_dir.mkdir(parents=True, exist_ok=True)

    img_dir = pdf_output_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"MineRU parsing: {pdf_name}")

    try:
        reader = FileBasedDataReader("")
        pdf_bytes = reader.read(str(pdf_path))

        ds = PymuDocDataset(pdf_bytes)
        infer_result = ds.apply(doc_analyze, ocr=True)

        pipe_result = infer_result.pipe_ocr_mode(
            FileBasedDataWriter(str(img_dir))
        )

        md_content = pipe_result.get_markdown(str(img_dir))

        md_path = pdf_output_dir / f"{pdf_name}.md"
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        content_list = pipe_result.get_content_list(str(img_dir))
        content_path = pdf_output_dir / f"{pdf_name}_content.json"
        with open(content_path, 'w', encoding='utf-8') as f:
            json.dump(content_list, f, ensure_ascii=False, indent=2)

        images = list(img_dir.glob("*.png")) + list(img_dir.glob("*.jpg"))
        logger.info(f"  Done: {len(images)} images, markdown {len(md_content)} chars")

        return {
            "pdf_name": pdf_name,
            "md_path": str(md_path),
            "content_path": str(content_path),
            "images": [str(img) for img in images],
            "image_dir": str(img_dir),
            "success": True
        }

    except Exception as e:
        logger.error(f"  MineRU parse failed [{pdf_name}]: {e}")
        return {
            "pdf_name": pdf_name,
            "success": False,
            "error": str(e)
        }


def run_mineru_all():
    logger.info("=" * 60)
    logger.info("Step 1: MineRU PDF Parsing")
    logger.info("=" * 60)

    pdfs = get_pdf_list()
    results = []

    for i, pdf in enumerate(pdfs):
        logger.info(f"[{i+1}/{len(pdfs)}] Processing: {pdf.name}")

        output_check = MINERU_OUTPUT_DIR / pdf.stem / f"{pdf.stem}.md"
        if output_check.exists():
            logger.info(f"  Skip (exists): {pdf.stem}")
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

    summary_path = MINERU_OUTPUT_DIR / "parse_summary.json"
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    success_count = sum(1 for r in results if r.get("success"))
    logger.info(f"MineRU parse done: {success_count}/{len(results)} success")

    return results


# ============ Step 2: Qwen2.5-VL Chart Analysis ============
class ChartAnalyzer:
    def __init__(self, model_path="/hpc2hdd/home/wyu899/evo_prm/Qwen/Qwen2.5-VL-7B-Instruct"):
        self.model = None
        self.processor = None
        self.model_path = model_path

    def load_model(self):
        from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor
        import torch

        logger.info(f"Loading Qwen2.5-VL model: {self.model_path}")
        self.processor = AutoProcessor.from_pretrained(self.model_path)
        self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            self.model_path,
            torch_dtype=torch.float16,
            device_map="auto",
        )
        logger.info("Model loaded")

    def is_chart_image(self, image_path: str) -> bool:
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
                        "5. If it is a time-series chart, use the time period as the first column\n"
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


def run_chart_extraction(mineru_results: list):
    logger.info("=" * 60)
    logger.info("Step 2: Qwen2.5-VL Chart Extraction")
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

        logger.info(f"\nAnalyzing {pdf_name}: {len(images)} images...")

        pdf_chart_dir = CHART_OUTPUT_DIR / pdf_name
        pdf_chart_dir.mkdir(parents=True, exist_ok=True)

        chart_results = []

        for img_path in images:
            if not os.path.exists(img_path):
                continue

            try:
                is_chart = analyzer.is_chart_image(img_path)
            except Exception as e:
                logger.warning(f"  Chart detection failed [{img_path}]: {e}")
                continue

            if not is_chart:
                logger.info(f"  Skip non-chart: {os.path.basename(img_path)}")
                continue

            logger.info(f"  Processing chart: {os.path.basename(img_path)}")

            try:
                csv_result = analyzer.extract_chart_to_csv(img_path)
                csv_filename = Path(img_path).stem + ".csv"
                csv_path = pdf_chart_dir / csv_filename
                with open(csv_path, 'w', encoding='utf-8') as f:
                    f.write(csv_result["csv_data"])
            except Exception as e:
                logger.warning(f"  CSV extraction failed: {e}")
                csv_result = {"csv_data": ""}
                csv_path = ""

            try:
                description = analyzer.describe_chart(img_path)
            except Exception as e:
                logger.warning(f"  Description generation failed: {e}")
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

        if chart_results:
            result_path = pdf_chart_dir / f"{pdf_name}_charts.json"
            with open(result_path, 'w', encoding='utf-8') as f:
                json.dump(chart_results, f, ensure_ascii=False, indent=2)
            logger.info(f"  {pdf_name}: extracted {len(chart_results)} charts")

        all_chart_results.extend(chart_results)

    summary_path = CHART_OUTPUT_DIR / "all_charts_summary.json"
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(all_chart_results, f, ensure_ascii=False, indent=2)

    logger.info(f"\nChart extraction done: {len(all_chart_results)} charts total")
    return all_chart_results


# ============ Step 3: Structured Data Extraction ============
def extract_tables_from_markdown(md_content: str) -> list:
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


def run_structured_extraction(mineru_results: list, chart_results: list = None):
    logger.info("=" * 60)
    logger.info("Step 3: Structured Data Extraction")
    logger.info("=" * 60)

    all_structured = []

    for result in mineru_results:
        if not result.get("success"):
            continue

        pdf_name = result["pdf_name"]
        md_path = result.get("md_path", "")

        if not md_path or not os.path.exists(md_path):
            continue

        logger.info(f"Extracting structured data: {pdf_name}")

        try:
            with open(md_path, 'r', encoding='utf-8') as f:
                md_content = f.read()

            # Get charts for this PDF
            pdf_charts = []
            if chart_results:
                pdf_charts = [c for c in chart_results if c.get("pdf_source") == pdf_name]
            else:
                charts_json = CHART_OUTPUT_DIR / pdf_name / f"{pdf_name}_charts.json"
                if charts_json.exists():
                    with open(charts_json, 'r', encoding='utf-8') as f:
                        pdf_charts = json.load(f)

            # Extract tables from markdown
            tables = extract_tables_from_markdown(md_content)

            # Build structured output
            structured = {
                "pdf_name": pdf_name,
                "source_file": str(result.get("md_path", "")),
                "text_content": md_content[:5000],
                "tables": tables,
                "charts": [{
                    "image_name": c.get("image_name", ""),
                    "csv_data": c.get("csv_data", ""),
                    "description": c.get("description", "")
                } for c in pdf_charts],
                "metadata": {
                    "total_images": len(result.get("images", [])),
                    "total_charts": len(pdf_charts),
                    "total_tables": len(tables),
                    "markdown_length": len(md_content)
                }
            }

            # Save individual structured file
            out_path = STRUCTURED_OUTPUT_DIR / f"{pdf_name}_structured.json"
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(structured, f, ensure_ascii=False, indent=2)

            all_structured.append(structured)
            logger.info(f"  {pdf_name}: {len(tables)} tables, {len(pdf_charts)} charts")

        except Exception as e:
            logger.error(f"  Structured extraction failed [{pdf_name}]: {e}")

    # Save summary
    summary_path = STRUCTURED_OUTPUT_DIR / "all_structured_summary.json"
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump({
            "total_documents": len(all_structured),
            "documents": [{"pdf_name": s["pdf_name"], "metadata": s["metadata"]} for s in all_structured]
        }, f, ensure_ascii=False, indent=2)

    logger.info(f"\nStructured extraction done: {len(all_structured)} documents")
    return all_structured


# ============ Main Entry ============
def main():
    parser = argparse.ArgumentParser(description="META IR PDF Parse Pipeline")
    parser.add_argument("--step", choices=["all", "mineru", "chart", "structure"],
                        default="all", help="Which step to run")
    args = parser.parse_args()

    ensure_dirs()

    if args.step == "all":
        mineru_results = run_mineru_all()
        chart_results = run_chart_extraction(mineru_results)
        run_structured_extraction(mineru_results, chart_results)

    elif args.step == "mineru":
        run_mineru_all()

    elif args.step == "chart":
        summary_path = MINERU_OUTPUT_DIR / "parse_summary.json"
        if summary_path.exists():
            with open(summary_path, 'r', encoding='utf-8') as f:
                mineru_results = json.load(f)
            run_chart_extraction(mineru_results)
        else:
            logger.error("No MineRU results found. Run mineru step first.")

    elif args.step == "structure":
        summary_path = MINERU_OUTPUT_DIR / "parse_summary.json"
        if summary_path.exists():
            with open(summary_path, 'r', encoding='utf-8') as f:
                mineru_results = json.load(f)
            run_structured_extraction(mineru_results)
        else:
            logger.error("No MineRU results found. Run mineru step first.")


if __name__ == "__main__":
    main()
