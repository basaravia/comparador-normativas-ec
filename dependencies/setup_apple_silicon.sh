#!/usr/bin/env bash
# =============================================================================
# setup_apple_silicon.sh
# Entorno completo para el Comparador de Normativas en Apple Silicon (M1/M2/M3/M4)
# Python 3.13.5 | 16 GB RAM | macOS Sequoia+
# =============================================================================
set -euo pipefail

ENV_NAME="normas_comparador"
DMR_BASE_URL="http://localhost:12434/engines/v1"

# Colores
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC}  $1"; }
fail() { echo -e "${RED}✗${NC} $1"; exit 1; }
step() { echo -e "\n${YELLOW}▶ $1${NC}"; }

# ─── 1. Homebrew ─────────────────────────────────────────────────────────────
step "Verificando Homebrew"
if ! command -v brew &>/dev/null; then
    warn "Homebrew no encontrado — instalando..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Agrega brew al PATH en zsh (Apple Silicon path)
    echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
    eval "$(/opt/homebrew/bin/brew shellenv)"
fi
ok "Homebrew $(brew --version | head -1)"

# ─── 2. Miniconda ────────────────────────────────────────────────────────────
step "Verificando Conda"
if ! command -v conda &>/dev/null; then
    warn "Conda no encontrado — instalando Miniconda para Apple Silicon..."
    curl -fsSL https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh -o /tmp/miniconda.sh
    bash /tmp/miniconda.sh -b -p "$HOME/miniconda3"
    rm /tmp/miniconda.sh
    "$HOME/miniconda3/bin/conda" init zsh
    # Recargar para esta sesión
    source "$HOME/miniconda3/etc/profile.d/conda.sh"
fi
ok "Conda $(conda --version)"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ─── 3. Entorno conda (creado directo desde environment.yml) ─────────────────
step "Configurando entorno conda '$ENV_NAME' desde environment.yml"

source "$(conda info --base)/etc/profile.d/conda.sh"

if conda env list | grep -q "^$ENV_NAME "; then
    warn "Entorno '$ENV_NAME' ya existe — actualizando dependencias"
    conda env update -n "$ENV_NAME" -f "$SCRIPT_DIR/environment.yml" --prune
else
    conda env create -f "$SCRIPT_DIR/environment.yml"
    ok "Entorno '$ENV_NAME' creado"
fi

conda activate "$ENV_NAME"
ok "Entorno activado: $(python --version)"

# Registrar el kernel de Jupyter con el mismo nombre del entorno
python -m ipykernel install --user --name "$ENV_NAME" --display-name "$ENV_NAME"
ok "Kernel Jupyter '$ENV_NAME' registrado"

# ─── 4. Verificar Docling + OCR ──────────────────────────────────────────────
step "Verificando Docling"
python -c "
from importlib.metadata import version
import docling, ocrmac  # noqa: F401 (valida que importen sin error)
print(f'  docling  : {version(\"docling\")}')
print(f'  ocrmac   : {version(\"ocrmac\")}')
import torch
mps_ok = torch.backends.mps.is_available()
print(f'  PyTorch  : {torch.__version__} | MPS disponible: {mps_ok}')
"
ok "Docling y OCR verificados"

# ─── 5. Docker Desktop + Docker Model Runner ─────────────────────────────────
step "Verificando Docker Desktop"

if ! command -v docker &>/dev/null; then
    warn "Docker no encontrado."
    echo ""
    echo "  Instala Docker Desktop para Mac (Apple Silicon):"
    echo "  → https://www.docker.com/products/docker-desktop/"
    echo ""
    echo "  Luego habilita Docker Model Runner en:"
    echo "  Docker Desktop → Settings → Features in development → Docker Model Runner → Enable"
    echo ""
    echo "  Una vez instalado, re-ejecuta este script."
    exit 1
fi
ok "Docker $(docker --version)"

step "Verificando Docker Model Runner (DMR)"
if ! curl -sf --max-time 5 "$DMR_BASE_URL/models" &>/dev/null; then
    warn "Docker Model Runner no responde en $DMR_BASE_URL"
    echo ""
    echo "  Asegúrate de que:"
    echo "  1. Docker Desktop está corriendo"
    echo "  2. Model Runner está habilitado en Settings → Features in development"
    echo ""
    echo "  Luego re-ejecuta: bash dependencies/setup_apple_silicon.sh"
    exit 1
fi
ok "Docker Model Runner activo"

# ─── 6. Descargar modelos DMR ────────────────────────────────────────────────
step "Descargando modelos Docker Model Runner"

# Función: descarga solo si el modelo no está ya cargado
pull_model() {
    local model="$1"
    local label="$2"
    if curl -sf --max-time 5 "$DMR_BASE_URL/models" | grep -q "$(echo "$model" | sed 's|.*/||' | cut -d: -f1)"; then
        ok "$label ya disponible"
    else
        warn "$label no encontrado — descargando (puede tardar varios minutos)..."
        docker model pull "$model"
        ok "$label descargado"
    fi
}

# Embedding principal (768d, 530 MB)
pull_model "ai/granite-embedding-multilingual:latest" "granite-embedding-multilingual (768d, 530 MB)"

# LLM para análisis comparativo (4.74 GB — carga en GPU M-series vía Metal)
pull_model "ai/gemma4:latest" "gemma4 (4.74 GB, requiere ~5 GB GPU RAM)"

# Reranker post-FAISS (1.19 GB)
pull_model "ai/qwen3-reranker-vllm:0.6B" "qwen3-reranker-vllm 0.6B (1.19 GB)"

# ─── 7. Test rápido end-to-end ───────────────────────────────────────────────
step "Test rápido de conectividad"

python -c "
import numpy as np, httpx, json

# Test embedding
resp = httpx.post(
    'http://localhost:12434/engines/v1/embeddings',
    json={'model': 'ai/granite-embedding-multilingual:latest', 'input': ['test']},
    timeout=15.0,
)
vec = np.array(resp.json()['data'][0]['embedding'])
print(f'  Embedding OK — dim={len(vec)}, norma={np.linalg.norm(vec):.3f}')

# Test LLM
resp = httpx.post(
    'http://localhost:12434/engines/v1/chat/completions',
    json={'model': 'docker.io/ai/gemma4:latest',
          'messages': [{'role':'user','content':'Di solo: OK'}],
          'max_tokens': 10},
    timeout=60.0,
)
content = resp.json()['choices'][0]['message']['content']
print(f'  LLM OK — gemma4 responde: {content[:30]}')
"

# ─── Resumen ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Entorno listo. Para activarlo:${NC}"
echo -e "${GREEN}    conda activate $ENV_NAME${NC}"
echo -e "${GREEN}  Para ejecutar el notebook:${NC}"
echo -e "${GREEN}    jupyter nbconvert --to notebook --execute --inplace \\${NC}"
echo -e "${GREEN}      --ExecutePreprocessor.timeout=3600 master.ipynb${NC}"
echo -e "${GREEN}════════════════════════════════════════════════${NC}"
echo ""

# ─── Notas de rendimiento Apple Silicon ──────────────────────────────────────
echo "Configuración recomendada para 16 GB RAM:"
echo "  MAX_WORKERS=1   (gemma4 es secuencial en DMR)"
echo "  LLM_MAX_TOKENS=4096   (limita cadena CoT de gemma4)"
echo "  ManualParser device='cpu'   (MPS inestable en conversión en vivo)"
echo "  Embedding: granite 768d   (menor huella que qwen3 2560d)"
echo ""
echo "Modelos activos en GPU simultaneamente:"
echo "  granite-embedding: ~530 MB"
echo "  gemma4:            ~4.74 GB"
echo "  qwen3-reranker:    ~1.19 GB"
echo "  ─────────────────────────────"
echo "  Total DMR:         ~6.5 GB"
echo "  OS + Python:       ~4.5 GB"
echo "  Margen libre:      ~5 GB de 16 GB"
