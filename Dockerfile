# comfyui-serverless-h3 — MiniMax H3 (Hailuo 3.0) serverless worker
#
# Inspire de comfyui-serverless-krea, meme architecture : handler officiel
# runpod/worker-comfyui, worker VIDE (aucun modele bake), modeles lus depuis le
# network volume c-edge. Seul delta vs Krea : ComfyUI epingle au SHA H3 (0.30.0)
# au lieu de 0.26.0 + les deux node packs H3.
#
# Volume c-edge (pnt4230ssw, EUR-IS-1) : contient deja tous les modeles H3
# (fl2va, ref2va), le TE qwen3vl_32b int8, les 2 VAE et les 2 turbo LoRAs.
# En serverless il se monte sur /runpod-volume.

# Base worker-comfyui (handler + runtime). DOIT supporter Blackwell sm_120 (RTX PRO 6000) :
# torch cu128 / >=2.7. Voir la note torch plus bas si la base est trop ancienne.
ARG BASE=runpod/worker-comfyui:5.4.0-base
FROM ${BASE}

# --- 1. Epingler ComfyUI a la revision qui fait tourner H3 sur le pod ---
# v0.30.0-3-g16e3f303 = nodes MiniMax H3 natifs. La base livre ComfyUI dans /comfyui ;
# on checkout le SHA plutot que de reinstaller (`comfy install` echoue sur un workspace
# existant — gotcha herite de Krea).
ARG COMFYUI_SHA=16e3f3034f2bba1fff6c70cbd759339778555cd6
RUN cd /comfyui \
 && git fetch origin ${COMFYUI_SHA} \
 && git checkout ${COMFYUI_SHA} \
 && pip install --no-cache-dir -r requirements.txt

# --- 2. Node packs H3 (epingles aux revisions presentes sur le volume) ---
ARG KJNODES_SHA=44fda83f307b7aee4a27ee268c86aaa74a5f5612
ARG H3TURBO_SHA=55f85c6dbe58b41aaf5ee610d225ecce0a00ee17
RUN cd /comfyui/custom_nodes \
 && git clone https://github.com/kijai/ComfyUI-KJNodes.git \
 && git -C ComfyUI-KJNodes checkout ${KJNODES_SHA} \
 && ( [ -f ComfyUI-KJNodes/requirements.txt ] && pip install --no-cache-dir -r ComfyUI-KJNodes/requirements.txt || true ) \
 && git clone https://github.com/Larryvrh/ComfyUI-MiniMax-H3-Turbo.git \
 && git -C ComfyUI-MiniMax-H3-Turbo checkout ${H3TURBO_SHA} \
 && ( [ -f ComfyUI-MiniMax-H3-Turbo/requirements.txt ] && pip install --no-cache-dir -r ComfyUI-MiniMax-H3-Turbo/requirements.txt || true )

# --- 3. Pointer ComfyUI vers les modeles du volume (monte sur /runpod-volume) ---
COPY extra_model_paths.yaml /comfyui/extra_model_paths.yaml

# --- NOTE Blackwell (sm_120) ---
# L'endpoint tourne sur RTX PRO 6000 96 Go. Si la base worker-comfyui n'est pas en
# torch cu128, la sortie DiT plantera au lancement. Dans ce cas, decommenter :
# RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cu128 \
#     torch torchvision torchaudio
#
# --- NOTE sage attention ---
# Volontairement PAS active. worker-comfyui lance ComfyUI sans --use-sage-attention ni
# --enable-manager (les deux crashent H3). La vitesse vient de la turbo LoRA, pas de sage ;
# sage reste un toggle node-level (DiffusionModelLoaderKJ) qu'on pourra activer plus tard.
