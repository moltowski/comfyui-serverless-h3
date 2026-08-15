# comfyui-serverless-h3 — MiniMax H3 (Hailuo 3.0) serverless worker
#
# Meme architecture que comfyui-serverless-krea (reference PROUVEE en prod) : handler
# officiel runpod/worker-comfyui, worker VIDE (aucun modele bake), modeles lus depuis le
# network volume c-edge (pnt4230ssw, EUR-IS-1), monte sur /runpod-volume en serverless.
#
# Delta vs Krea : ComfyUI epingle au SHA H3 (0.30.0) + les deux node packs H3 (KJNodes,
# MiniMax-H3-Turbo). Les nodes de generation H3 de base (MiniMaxH3ImageToVideo, etc.) sont
# NATIFS a ComfyUI 0.30.0 (comfy_extras/nodes_minimax_h3.py) — pas un pack tiers.
#
# ⚠️ LEÇON 2026-08-15 (1er smoketest KO) : ne PAS utiliser `pip` mais `uv pip`. Le base a
# DEUX venvs (comfy-cli -> /comfyui/.venv ; runtime start.sh -> /opt/venv). `pip` tout court
# installe dans le mauvais -> le node H3 plante a l'import au runtime ("Missing custom node").
# `uv pip` cible le venv de lancement (c'est ce que krea fait). En plus, le node H3 importe
# torchaudio, pas garanti dans le base -> on l'ajoute explicitement (cu128, matche le torch
# du base 5.8.6 qui est deja Blackwell/cu128 puisque krea tourne dessus sur RTX PRO 6000).

ARG BASE=runpod/worker-comfyui:5.8.6-base
FROM ${BASE}

# --- 1. Epingler ComfyUI au SHA H3 (0.30.0) ---
# On met a jour le clone git EXISTANT (/comfyui, pose par comfy-cli). Rejouer `comfy install`
# echoue sur un workspace existant (gotcha herite de krea). Assert de version = filet.
ARG COMFYUI_SHA=16e3f3034f2bba1fff6c70cbd759339778555cd6
RUN git -C /comfyui fetch --depth 1 origin "${COMFYUI_SHA}" && \
    git -C /comfyui checkout -q FETCH_HEAD && \
    uv pip install -r /comfyui/requirements.txt && \
    python -c "import sys; sys.path.insert(0,'/comfyui'); from comfyui_version import __version__ as v; print('ComfyUI', v); assert v.startswith('0.30'), v"

# --- 2. torchaudio (requis par comfy_extras/nodes_minimax_h3.py) ---
# Pin sur la version exacte du torch deja installe pour ne pas le perturber ; fallback non-pin.
RUN TV=$(python -c "import torch; print(torch.__version__.split('+')[0])") && \
    echo "torch=$TV" && \
    ( uv pip install --no-cache-dir "torchaudio==${TV}" --index-url https://download.pytorch.org/whl/cu128 || \
      uv pip install --no-cache-dir torchaudio --index-url https://download.pytorch.org/whl/cu128 ) && \
    python -c "import torchaudio; print('torchaudio', torchaudio.__version__)"

# --- 3. Node packs H3 (epingles aux revisions presentes sur le volume) ---
# Pas necessaires au t2v/i2v/r2v de base (nodes natifs), mais utiles pour le chemin turbo
# (DiffusionModelLoaderKJ + MiniMaxH3TurboLoRA/SigmaShift/TurboSampler).
ARG KJNODES_SHA=44fda83f307b7aee4a27ee268c86aaa74a5f5612
ARG H3TURBO_SHA=55f85c6dbe58b41aaf5ee610d225ecce0a00ee17
RUN cd /comfyui/custom_nodes && \
    git clone https://github.com/kijai/ComfyUI-KJNodes.git && \
    git -C ComfyUI-KJNodes checkout ${KJNODES_SHA} && \
    git clone https://github.com/Larryvrh/ComfyUI-MiniMax-H3-Turbo.git && \
    git -C ComfyUI-MiniMax-H3-Turbo checkout ${H3TURBO_SHA}
# Dependances des custom nodes dans le venv de lancement (idem krea).
RUN for r in /comfyui/custom_nodes/*/requirements.txt; do \
      [ -f "$r" ] && uv pip install --no-cache-dir -r "$r" || true; \
    done

# --- 4. Pointer ComfyUI vers les modeles du volume (monte sur /runpod-volume) ---
COPY extra_model_paths.yaml /comfyui/extra_model_paths.yaml

# --- NOTE sage attention ---
# Volontairement PAS active. worker-comfyui lance ComfyUI sans --use-sage-attention ni
# --enable-manager (les deux crashent H3). La vitesse vient de la turbo LoRA, pas de sage.
