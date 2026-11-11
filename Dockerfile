# comfyui-serverless-h3 — MiniMax H3 (Hailuo 3.0) serverless worker, VIDEO
#
# Meme architecture que comfyui-serverless-krea : handler officiel runpod/worker-comfyui,
# worker VIDE (aucun modele bake), modeles lus depuis le network volume c-edge (pnt4230ssw,
# EUR-IS-1), monte sur /runpod-volume en serverless.
#
# Regle (2026-11-11) : UNE seule version de ComfyUI pour tous nos workers, toujours la derniere.
# H3 tourne en NATIF uniquement (nodes ComfyUI de base) : pas de pack Turbo ni KJNodes
# (inutilises dans nos workflows). Le correctif audio natif (PR ComfyUI #15243) est inclus
# depuis v0.30.x+ ; il est dans 0.45.
#
# ⚠️ LEÇON 2026-08-15 : `uv pip`, pas `pip`. Le base a DEUX venvs (comfy-cli -> /comfyui/.venv ;
# runtime start.sh -> /opt/venv). `pip` tout court installe dans le mauvais -> le node H3 plante
# a l'import au runtime ("Missing custom node"). Le node H3 importe torchaudio, pas garanti
# dans le base -> on l'ajoute explicitement (cu128).

ARG BASE=runpod/worker-comfyui:5.8.6-base
FROM ${BASE}

# --- 1. ComfyUI epingle a v0.45.0 (meme version que le worker image) ---
# On met a jour le clone git EXISTANT (/comfyui, pose par comfy-cli). Rejouer `comfy install`
# echoue sur un workspace existant. Assert de version + presence du node H3 natif = filet.
ARG COMFYUI_SHA=989d93d0d968e704c589ce0146bb18c77f6b50cc
RUN git -C /comfyui fetch --depth 1 origin "${COMFYUI_SHA}" && \
    git -C /comfyui checkout -q FETCH_HEAD && \
    uv pip install --no-cache-dir -r /comfyui/requirements.txt && \
    python -c "import sys; sys.path.insert(0,'/comfyui'); from comfyui_version import __version__ as v; print('ComfyUI', v); assert v.startswith('0.45'), v" && \
    grep -q "MiniMaxH3ReferenceToVideo" /comfyui/comfy_extras/nodes_minimax_h3.py

# --- 2. torchaudio (requis par comfy_extras/nodes_minimax_h3.py) ---
# Pin sur la version exacte du torch deja installe pour ne pas le perturber ; fallback non-pin.
RUN TV=$(python -c "import torch; print(torch.__version__.split('+')[0])") && \
    echo "torch=$TV" && \
    ( uv pip install --no-cache-dir "torchaudio==${TV}" --index-url https://download.pytorch.org/whl/cu128 || \
      uv pip install --no-cache-dir torchaudio --index-url https://download.pytorch.org/whl/cu128 ) && \
    python -c "import torchaudio; print('torchaudio', torchaudio.__version__)"

# --- 3. Pointer ComfyUI vers les modeles du volume (monte sur /runpod-volume) ---
COPY extra_model_paths.yaml /comfyui/extra_model_paths.yaml

# --- NOTE sage attention ---
# Volontairement PAS active. worker-comfyui lance ComfyUI sans --use-sage-attention ni
# --enable-manager (les deux crashent H3).
