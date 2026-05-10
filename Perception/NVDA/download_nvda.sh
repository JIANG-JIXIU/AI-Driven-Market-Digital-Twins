#!/bin/bash
# NVIDIA Quarterly Presentations - Direct Download Script
# Uses wget for reliable large file downloads

OUTPUT_DIR=~/AI-Driven-Market-Digital-Twins/Perception/NVDA/01_Quarterly_Earnings_Presentation
mkdir -p "$OUTPUT_DIR"
cd "$OUTPUT_DIR"

echo "============================================================"
echo "Downloading NVIDIA Quarterly Presentations"
echo "============================================================"

BASE="https://s201.q4cdn.com/141608511/files"

# Each line: output_filename URL [alt_URL...]
declare -A DOWNLOADS=(
    # FY23 (Calendar 2022)
    ["NVDA_FY23_Q1_Earnings_Presentation.pdf"]="$BASE/doc_presentations/2022/05/NVDA-F1Q23-Investor-Presentation-FINAL.pdf"
    ["NVDA_FY23_Q2_Earnings_Presentation.pdf"]="$BASE/doc_presentations/2022/NVDA-F2Q23-Investor-Presentation-FINAL-(1).pdf"
    ["NVDA_FY23_Q3_Earnings_Presentation.pdf"]="$BASE/doc_financials/2023/q3/NVDA-F3Q23-Investor-Presentation_FINAL.pdf"
    ["NVDA_FY23_Q4_Earnings_Presentation.pdf"]="$BASE/doc_financials/2023/q4/NVDA-F4Q23-Investor-Presentation-FINAL.pdf"
    # FY24 (Calendar 2023)
    ["NVDA_FY24_Q1_Earnings_Presentation.pdf"]="$BASE/doc_financials/2024/q1/NVDA-F1Q24-Investor-Presentation-FINAL.pdf"
    ["NVDA_FY24_Q2_Earnings_Presentation.pdf"]="$BASE/doc_financials/2024/q2/nvda-f2q24-investor-presentation-final.pdf"
    ["NVDA_FY24_Q3_Earnings_Presentation.pdf"]="$BASE/doc_financials/2024/q3/NVDA-F3Q24-Investor-Presentation-FINAL.pdf"
    ["NVDA_FY24_Q4_Earnings_Presentation.pdf"]="$BASE/doc_financials/2024/q4/NVDA-F4Q24-Quarterly-Presentation-FINAL.pdf"
    # FY25 (Calendar 2024)
    ["NVDA_FY25_Q1_Earnings_Presentation.pdf"]="$BASE/doc_financials/2025/q1/NVDA-F1Q25-Quarterly-Presentation-FINAL.pdf"
    ["NVDA_FY25_Q2_Earnings_Presentation.pdf"]="$BASE/doc_financials/2025/q2/NVDA-F2Q25-Quarterly-Presentation-FINAL.pdf"
    ["NVDA_FY25_Q3_Earnings_Presentation.pdf"]="$BASE/doc_financials/2025/q3/NVDA-F3Q25-Quarterly-Presentation-FINAL.pdf"
    ["NVDA_FY25_Q4_Earnings_Presentation.pdf"]="$BASE/doc_financials/2025/q4/NVDA-F4Q25-Quarterly-Presentation-FINAL.pdf"
    # FY26 (Calendar 2025)
    ["NVDA_FY26_Q1_Earnings_Presentation.pdf"]="$BASE/doc_financials/2026/q1/NVDA-F1Q26-Quarterly-Presentation-FINAL.pdf"
    ["NVDA_FY26_Q2_Earnings_Presentation.pdf"]="$BASE/doc_financials/2026/q2/NVDA-F2Q26-Quarterly-Presentation-FINAL.pdf"
    ["NVDA_FY26_Q3_Earnings_Presentation.pdf"]="$BASE/doc_financials/2026/q3/NVDA-F3Q26-Quarterly-Presentation-FINAL.pdf"
    ["NVDA_FY26_Q4_Earnings_Presentation.pdf"]="$BASE/doc_financials/2026/q4/NVDA-F4Q26-Quarterly-Presentation-FINAL.pdf"
)

# Alternative URLs to try if primary fails
declare -A ALT_URLS=(
    ["NVDA_FY23_Q1_Earnings_Presentation.pdf"]="$BASE/doc_financials/2023/q1/NVDA-F1Q23-Investor-Presentation-FINAL.pdf"
    ["NVDA_FY23_Q2_Earnings_Presentation.pdf"]="$BASE/doc_financials/2023/q2/NVDA-F2Q23-Investor-Presentation-FINAL.pdf"
    ["NVDA_FY23_Q4_Earnings_Presentation.pdf"]="$BASE/doc_presentations/2023/02/NVDA-F4Q23-Investor-Presentation-FINAL.pdf"
    ["NVDA_FY24_Q1_Earnings_Presentation.pdf"]="$BASE/doc_presentations/2023/05/NVDA-F1Q24-Investor-Presentation-FINAL.pdf"
    ["NVDA_FY24_Q3_Earnings_Presentation.pdf"]="$BASE/doc_financials/2024/q3/nvda-f3q24-investor-presentation-final.pdf"
    ["NVDA_FY26_Q1_Earnings_Presentation.pdf"]="$BASE/doc_financials/2026/q1/nvda-f1q26-quarterly-presentation-final.pdf"
)

SUCCESS=0
FAIL=0

for filename in $(echo "${!DOWNLOADS[@]}" | tr ' ' '\n' | sort); do
    if [ -f "$filename" ]; then
        # Verify it's a valid PDF
        if head -c 5 "$filename" | grep -q '%PDF-'; then
            echo "[SKIP] $filename (exists)"
            SUCCESS=$((SUCCESS+1))
            continue
        else
            rm "$filename"
        fi
    fi

    url="${DOWNLOADS[$filename]}"
    echo "[TRY] $filename"

    # Try primary URL
    wget -q --timeout=60 --tries=3 -O "$filename" "$url" 2>/dev/null
    if [ -f "$filename" ] && head -c 5 "$filename" | grep -q '%PDF-'; then
        SIZE=$(du -h "$filename" | cut -f1)
        echo "  [OK] $SIZE (primary)"
        SUCCESS=$((SUCCESS+1))
        continue
    fi
    rm -f "$filename"

    # Try alternative URL
    alt_url="${ALT_URLS[$filename]}"
    if [ -n "$alt_url" ]; then
        wget -q --timeout=60 --tries=3 -O "$filename" "$alt_url" 2>/dev/null
        if [ -f "$filename" ] && head -c 5 "$filename" | grep -q '%PDF-'; then
            SIZE=$(du -h "$filename" | cut -f1)
            echo "  [OK] $SIZE (alt)"
            SUCCESS=$((SUCCESS+1))
            continue
        fi
        rm -f "$filename"
    fi

    echo "  [FAIL] Not found"
    FAIL=$((FAIL+1))
    sleep 1
done

echo ""
echo "============================================================"
echo "NVIDIA Download Complete: $SUCCESS success, $FAIL failed"
echo "============================================================"
ls -la "$OUTPUT_DIR"/*.pdf 2>/dev/null | wc -l
echo "PDF files downloaded"
