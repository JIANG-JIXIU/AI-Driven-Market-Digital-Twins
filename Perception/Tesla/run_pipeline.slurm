#!/bin/bash
#SBATCH --job-name=tesla_pdf_parse
#SBATCH --partition=i64m1tga800u
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --gres=gpu:a800:1
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --output=logs/tesla_parse_%j.out
#SBATCH --error=logs/tesla_parse_%j.err

# ============ Tesla PDF 解析 Pipeline SLURM 作业 ============
# 使用方式:
#   sbatch run_pipeline.slurm              # 运行全部步骤
#   sbatch --export=STEP=mineru run_pipeline.slurm   # 仅MineRU解析
#   sbatch --export=STEP=chart run_pipeline.slurm    # 仅图表提取
#   sbatch --export=STEP=structure run_pipeline.slurm # 仅结构化抽取

echo "=========================================="
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $SLURM_NODELIST"
echo "Start: $(date)"
echo "=========================================="

# 加载必要模块
source /usr/local/Modules/init/profile.sh
module load slurm
module load cuda/12.1

# 激活 conda 环境 (使用已有torch的attention_figure环境)
source activate attention_figure

# 进入项目目录
cd ~/AI-Driven-Market-Digital-Twins/Perception/Tesla

# 创建日志目录
mkdir -p logs

# 设置环境变量
export HF_HOME=~/.cache/huggingface
export TRANSFORMERS_CACHE=~/.cache/huggingface/transformers
export TORCH_HOME=~/.cache/torch
export HF_ENDPOINT=https://hf-mirror.com

# 默认运行全部步骤
STEP=${STEP:-all}

echo "运行步骤: $STEP"
echo "GPU 信息:"
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv

echo ""
echo "Python: $(python --version)"
echo "PyTorch CUDA: $(python -c 'import torch; print(torch.cuda.is_available())')"
echo ""
echo "开始运行 Pipeline..."
echo "=========================================="

python tesla_pdf_pipeline.py --step $STEP

echo ""
echo "=========================================="
echo "End: $(date)"
echo "Job finished."
