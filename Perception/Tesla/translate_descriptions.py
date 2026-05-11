"""
Translate Chinese chart descriptions to English.
Uses deep-translator (Google Translate backend) - fast and free.
"""

import os
import json
import time
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("translation.log", mode='w'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(os.path.expanduser("~/AI-Driven-Market-Digital-Twins"))
PERCEPTION_DIR = PROJECT_ROOT / "Perception" / "Tesla"
CHART_EXTRACTIONS_DIR = PERCEPTION_DIR / "parsed_output" / "chart_extractions"
STRUCTURED_DATA_DIR = PERCEPTION_DIR / "parsed_output" / "structured_data"

# Google Translate has a 5000 char limit per request
MAX_CHARS = 4500
# Delay between API calls to avoid rate limiting
DELAY = 1.0


def is_mostly_english(text: str) -> bool:
    """Check if text is predominantly English (>80% ASCII characters)."""
    if not text:
        return True
    ascii_count = sum(1 for c in text if ord(c) < 128)
    return ascii_count / len(text) > 0.8


def translate_text(text: str, translator) -> str:
    """Translate Chinese text to English using deep-translator."""
    if not text or not text.strip():
        return text

    if is_mostly_english(text):
        return text

    try:
        # If text is short enough, translate directly
        if len(text) <= MAX_CHARS:
            time.sleep(DELAY)
            translated = translator.translate(text)
            return translated

        # For long text, split by paragraphs and translate each
        paragraphs = text.split('\n')
        translated_parts = []
        current_batch = ""

        for para in paragraphs:
            if len(current_batch) + len(para) + 1 <= MAX_CHARS:
                current_batch += para + '\n'
            else:
                # Translate current batch
                if current_batch.strip():
                    time.sleep(DELAY)
                    translated_parts.append(translator.translate(current_batch.strip()))
                current_batch = para + '\n'

        # Translate remaining batch
        if current_batch.strip():
            time.sleep(DELAY)
            translated_parts.append(translator.translate(current_batch.strip()))

        return '\n'.join(translated_parts)

    except Exception as e:
        logger.warning(f"Translation failed: {e}. Retrying once...")
        time.sleep(3)
        try:
            # Retry once with shorter chunks
            if len(text) <= MAX_CHARS:
                translated = translator.translate(text)
                return translated
            else:
                # Split into smaller pieces
                chunks = []
                for i in range(0, len(text), 2000):
                    chunks.append(text[i:i+2000])
                results = []
                for chunk in chunks:
                    time.sleep(DELAY)
                    results.append(translator.translate(chunk))
                return ''.join(results)
        except Exception as e2:
            logger.error(f"Translation retry also failed: {e2}. Keeping original.")
            return text


def process_chart_extractions(translator):
    """Phase 1: Translate descriptions in chart_extractions JSON files."""
    logger.info("=" * 60)
    logger.info("Phase 1: Translating chart_extractions descriptions")
    logger.info("=" * 60)

    total_translated = 0
    total_skipped = 0
    files_processed = 0

    # Find all *_charts.json files
    chart_files = sorted(CHART_EXTRACTIONS_DIR.glob("*/*_charts.json"))
    logger.info(f"Found {len(chart_files)} chart JSON files")

    for i, chart_file in enumerate(chart_files, 1):
        logger.info(f"[{i}/{len(chart_files)}] Processing: {chart_file.name}")

        with open(chart_file, 'r', encoding='utf-8') as f:
            charts = json.load(f)

        file_translated = 0
        for j, chart in enumerate(charts):
            desc = chart.get("description", "")
            if desc and not is_mostly_english(desc):
                logger.info(f"  Translating chart {j+1}/{len(charts)}...")
                chart["description"] = translate_text(desc, translator)
                file_translated += 1
            else:
                total_skipped += 1

        # Overwrite file
        with open(chart_file, 'w', encoding='utf-8') as f:
            json.dump(charts, f, ensure_ascii=False, indent=2)

        total_translated += file_translated
        files_processed += 1
        logger.info(f"  Done: {file_translated} translated, {len(charts) - file_translated} skipped")

    # Also handle all_charts_summary.json if it exists
    summary_file = CHART_EXTRACTIONS_DIR / "all_charts_summary.json"
    if summary_file.exists():
        logger.info("Processing all_charts_summary.json...")
        with open(summary_file, 'r', encoding='utf-8') as f:
            summary = json.load(f)

        for chart in summary:
            desc = chart.get("description", "")
            if desc and not is_mostly_english(desc):
                chart["description"] = translate_text(desc, translator)
                total_translated += 1

        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

    logger.info(f"Phase 1 complete: {files_processed} files, {total_translated} translated, {total_skipped} skipped")
    return {"files": files_processed, "translated": total_translated, "skipped": total_skipped}


def process_structured_data(translator):
    """Phase 2: Translate descriptions in structured_data JSON files."""
    logger.info("=" * 60)
    logger.info("Phase 2: Translating structured_data descriptions")
    logger.info("=" * 60)

    total_translated = 0
    files_processed = 0

    # Find individual structured files (exclude all_structured_data.json)
    struct_files = sorted([
        f for f in STRUCTURED_DATA_DIR.glob("*_structured.json")
        if f.name != "all_structured_data.json"
    ])
    logger.info(f"Found {len(struct_files)} structured JSON files")

    for i, struct_file in enumerate(struct_files, 1):
        logger.info(f"[{i}/{len(struct_files)}] Processing: {struct_file.name}")

        with open(struct_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        file_translated = 0

        # Navigate to chart_data.categorized_charts
        chart_data = data.get("chart_data", {})
        categorized = chart_data.get("categorized_charts", {})

        for category, chart_list in categorized.items():
            if not isinstance(chart_list, list):
                continue
            for chart_entry in chart_list:
                desc = chart_entry.get("description", "")
                if desc and not is_mostly_english(desc):
                    chart_entry["description"] = translate_text(desc, translator)
                    file_translated += 1

        # Overwrite file
        with open(struct_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        total_translated += file_translated
        files_processed += 1
        logger.info(f"  Translated {file_translated} descriptions")

    logger.info(f"Phase 2 complete: {files_processed} files, {total_translated} translated")
    return {"files": files_processed, "translated": total_translated}


def regenerate_all_structured():
    """Phase 3: Regenerate all_structured_data.json from translated individual files."""
    logger.info("=" * 60)
    logger.info("Phase 3: Regenerating all_structured_data.json")
    logger.info("=" * 60)

    all_data_path = STRUCTURED_DATA_DIR / "all_structured_data.json"

    # Delete old file
    if all_data_path.exists():
        os.remove(all_data_path)
        logger.info("Deleted old all_structured_data.json")

    # Load all individual files
    struct_files = sorted([
        f for f in STRUCTURED_DATA_DIR.glob("*_structured.json")
        if f.name != "all_structured_data.json"
    ])

    all_data = []
    for f in struct_files:
        with open(f, 'r', encoding='utf-8') as fh:
            all_data.append(json.load(fh))

    # Write combined file
    with open(all_data_path, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)

    logger.info(f"Regenerated all_structured_data.json with {len(all_data)} reports")


def main():
    from deep_translator import GoogleTranslator

    logger.info("Starting Chinese -> English translation of chart descriptions")
    logger.info(f"Chart extractions dir: {CHART_EXTRACTIONS_DIR}")
    logger.info(f"Structured data dir: {STRUCTURED_DATA_DIR}")
    logger.info("Using: deep-translator (Google Translate)")

    # Initialize translator
    translator = GoogleTranslator(source='zh-CN', target='en')
    logger.info("Translator initialized successfully")

    # Phase 1: Chart extractions
    stats1 = process_chart_extractions(translator)

    # Phase 2: Structured data
    stats2 = process_structured_data(translator)

    # Phase 3: Regenerate aggregate
    regenerate_all_structured()

    # Summary
    logger.info("=" * 60)
    logger.info("TRANSLATION COMPLETE")
    logger.info(f"  Chart extractions: {stats1['translated']} descriptions translated")
    logger.info(f"  Structured data: {stats2['translated']} descriptions translated")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
