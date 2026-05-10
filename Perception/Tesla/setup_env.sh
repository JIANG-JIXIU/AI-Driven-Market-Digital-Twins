#!/bin/bash
# ============ MineRU + Qwen2.5-VL 环境安装脚本 ============
# 在 HPC 上执行: bash setup_env.sh

set -e

ENV_NAME="mineru_vlm"
echo "=========================================="
echo "安装环境: $ENV_NAME"
echo "=========================================="

# 检查环境是否已存在
if conda env list | grep -q "$ENV_NAME"; then
    echo "环境 $ENV_NAME 已存在，激活中..."
    source activate $ENV_NAME
else
    echo "创建 conda 环境..."
    conda create -n $ENV_NAME python=3.10 -y
    source activate $ENV_NAME
fi

echo "Python: $(python --version)"
echo "Pip: $(pip --version)"

# Step 1: 安装 PyTorch (CUDA 12.4)
echo ""
echo "[1/4] 安装 PyTorch..."
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124

# Step 2: 安装 MineRU (magic-pdf)
echo ""
echo "[2/4] 安装 MineRU (magic-pdf)..."
pip install "magic-pdf[full]"

# Step 3: 安装 Qwen2.5-VL 依赖
echo ""
echo "[3/4] 安装 Qwen2.5-VL 依赖..."
pip install transformers accelerate qwen-vl-utils pillow

# Step 4: 安装其他工具
echo ""
echo "[4/4] 安装其他工具..."
pip install pandas openpyxl gradio

# Step 5: 下载 MineRU 模型权重
echo ""
echo "[5] 初始化 MineRU 模型配置..."
python -c "
from magic_pdf.model.doc_analyze_by_custom_model import ModelSingleton
print('MineRU 模型初始化检查完成')
" 2>/dev/null || echo "MineRU 模型将在首次运行时自动下载"

# Step 6: 预下载 Qwen2.5-VL 模型
echo ""
echo "[6] 预下载 Qwen2.5-VL-7B-Instruct 模型..."
python -c "
from huggingface_hub import snapshot_download
snapshot_download('Qwen/Qwen2.5-VL-7B-Instruct', local_dir=None)
print('Qwen2.5-VL 模型下载完成')
" || echo "模型将在首次运行时下载（需要约15GB空间）"

echo ""
echo "=========================================="
echo "环境安装完成!"
echo "使用方法:"
echo "  source activate $ENV_NAME"
echo "  cd ~/AI-Driven-Market-Digital-Twins/Perception/Tesla"
echo "  sbatch run_pipeline.slurm"
echo "=========================================="
