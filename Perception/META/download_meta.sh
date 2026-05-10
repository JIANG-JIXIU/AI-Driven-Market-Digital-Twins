#!/bin/bash
# Meta Platforms Quarterly Presentations - Direct Download Script
# Uses wget for reliable downloads

OUTPUT_DIR=~/AI-Driven-Market-Digital-Twins/Perception/META/01_Quarterly_Earnings_Presentation
mkdir -p "$OUTPUT_DIR"
cd "$OUTPUT_DIR"

echo "============================================================"
echo "Downloading Meta Quarterly Earnings Presentations"
echo "============================================================"

BASE="https://s21.q4cdn.com/399680738/files"

# Primary and alternative URLs for each quarter
declare -A DOWNLOADS=(
    # 2022
    ["META_2022_Q1_Earnings_Presentation.pdf"]="$BASE/doc_financials/2022/q1/Earnings-Presentation-Q1-2022.pdf"
    ["META_2022_Q2_Earnings_Presentation.pdf"]="$BASE/doc_financials/2022/q2/Q2-2022_Earnings-Presentation.pdf"
    ["META_2022_Q3_Earnings_Presentation.pdf"]="$BASE/doc_financials/2022/q3/Earnings-Presentation-Q3-2022.pdf"
    ["META_2022_Q4_Earnings_Presentation.pdf"]="$BASE/doc_financials/2022/q4/Earnings-Presentation-Q4-2022.pdf"
    # 2023
    ["META_2023_Q1_Earnings_Presentation.pdf"]="$BASE/doc_financials/2023/q1/Earnings-Presentation-Q1-2023.pdf"
    ["META_2023_Q2_Earnings_Presentation.pdf"]="$BASE/doc_financials/2023/q2/Earnings-Presentation-Q2-2023.pdf"
    ["META_2023_Q3_Earnings_Presentation.pdf"]="$BASE/doc_earnings/2023/q3/presentation/Earnings-Presentation-Q3-2023.pdf"
    ["META_2023_Q4_Earnings_Presentation.pdf"]="$BASE/doc_financials/2023/q4/Earnings-Presentation-Q4-2023.pdf"
    # 2024
    ["META_2024_Q1_Earnings_Presentation.pdf"]="$BASE/doc_financials/2024/q1/Earnings-Presentation-Q1-2024.pdf"
    ["META_2024_Q2_Earnings_Presentation.pdf"]="$BASE/doc_financials/2024/q2/Earnings-Presentation-Q2-2024.pdf"
    ["META_2024_Q3_Earnings_Presentation.pdf"]="$BASE/doc_financials/2024/q3/Earnings-Presentation-Q3-2024.pdf"
    ["META_2024_Q4_Earnings_Presentation.pdf"]="$BASE/doc_financials/2024/q4/Earnings-Presentation-Q4-2024.pdf"
    # 2025
    ["META_2025_Q1_Earnings_Presentation.pdf"]="$BASE/doc_financials/2025/q1/Earnings-Presentation-Q1-2025.pdf"
    ["META_2025_Q2_Earnings_Presentation.pdf"]="$BASE/doc_financials/2025/q2/Earnings-Presentation-Q2-2025.pdf"
    ["META_2025_Q3_Earnings_Presentation.pdf"]="$BASE/doc_financials/2025/q3/Earnings-Presentation-Q3-2025-Final.pdf"
    ["META_2025_Q4_Earnings_Presentation.pdf"]="$BASE/doc_financials/2025/q4/Earnings-Presentation-Q4-2025-FINAL.pdf"
    # 2026
    ["META_2026_Q1_Earnings_Presentation.pdf"]="$BASE/doc_financials/2026/q1/Earnings-Presentation-Q1-2026.pdf"
)

# Alternative URLs
declare -A ALT_URLS=(
    ["META_2022_Q1_Earnings_Presentation.pdf"]="$BASE/doc_financials/2022/q1/Q1-2022_Earnings-Presentation.pdf"
    ["META_2022_Q3_Earnings_Presentation.pdf"]="$BASE/doc_financials/2022/q3/Q3-2022_Earnings-Presentation.pdf"
    ["META_2022_Q4_Earnings_Presentation.pdf"]="$BASE/doc_financials/2022/q4/Q4-2022_Earnings-Presentation.pdf"
    ["META_2023_Q2_Earnings_Presentation.pdf"]="$BASE/doc_earnings/2023/q2/presentation/Earnings-Presentation-Q2-2023.pdf"
    ["META_2023_Q3_Earnings_Presentation.pdf"]="$BASE/doc_financials/2023/q3/Earnings-Presentation-Q3-2023.pdf"
    ["META_2024_Q1_Earnings_Presentation.pdf"]="$BASE/doc_earnings/2024/q1/presentation/Earnings-Presentation-Q1-2024.pdf"
    ["META_2024_Q2_Earnings_Presentation.pdf"]="$BASE/doc_earnings/2024/q2/presentation/Earnings-Presentation-Q2-2024.pdf"
    ["META_2024_Q4_Earnings_Presentation.pdf"]="$BASE/doc_financials/2024/q4/Earnings-Presentation-Q4-2024-FINAL.pdf"
    ["META_2025_Q1_Earnings_Presentation.pdf"]="$BASE/doc_financials/2025/q1/Earnings-Presentation-Q1-2025-FINAL.pdf"
    ["META_2025_Q2_Earnings_Presentation.pdf"]="$BASE/doc_financials/2025/q2/Earnings-Presentation-Q2-2025-FINAL.pdf"
    ["META_2025_Q3_Earnings_Presentation.pdf"]="$BASE/doc_financials/2025/q3/Earnings-Presentation-Q3-2025.pdf"
    ["META_2026_Q1_Earnings_Presentation.pdf"]="$BASE/doc_financials/2026/q1/Earnings-Presentation-Q1-2026-FINAL.pdf"
)

SUCCESS=0
FAIL=0

for filename in $(echo "${!DOWNLOADS[@]}" | tr ' ' '\n' | sort); do
    if [ -f "$filename" ]; then
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
echo "META Download Complete: $SUCCESS success, $FAIL failed"
echo "============================================================"
ls -la "$OUTPUT_DIR"/*.pdf 2>/dev/null | wc -l
echo "PDF files downloaded"
