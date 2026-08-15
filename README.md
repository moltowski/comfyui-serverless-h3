# comfyui-serverless-h3

> **Statut 2026-08-15 : LIVE + validé bout-en-bout.** Endpoint `585v8zf3b3ihvt`
> (`minimax-h3-serverless`) → image `ghcr.io/moltowski/comfyui-serverless-h3:latest`
> (template `dfg9p4xxv9`), GPU RTX PRO 6000 Blackwell, volume c-edge, idle 5s, wmax 3.
> Smoketest t2v+audio OK : mp4 h264 384×672 3,04s + aac 32kHz stéréo. Mesures : cold-load
> `delayTime` ~58 s (avec standby, pas un vrai froid), `executionTime` ~118 s (3s@384×672, 10 steps).
>
> ⭐ **Piège résolu (1er build KO = "Missing custom node: MiniMax H3 Image to Video")** : le node
> H3 est NATIF à ComfyUI 0.30.0 (`comfy_extras/nodes_minimax_h3.py`) mais plantait à l'import.
> Fix = **`uv pip` (pas `pip`** : le base a 2 venvs, comfy-cli `/comfyui/.venv` vs runtime `/opt/venv`)
> + **base `5.8.6-base`** + **`torchaudio`** explicite (importé par le node). Cf. Dockerfile.
>
> ⚠️ **API RunPod** : `apply_endpoints.py` (GraphQL) fait krea 3→2 + crée la template, mais
> **GraphQL `saveEndpoint` ignore `templateId`** → le repoint de l'endpoint se fait via **REST v1**
> (`PATCH https://rest.runpod.io/v1/endpoints/{id}` Bearer, clé `rpa_...`). Refresh d'image =
> bump env du template (nouveau release) pour recycler les workers standby.

Worker serverless RunPod pour **MiniMax H3** (Hailuo 3.0) — video T2V / I2V / R2V + audio natif.

Inspire de `comfyui-serverless-krea`, meme architecture : handler officiel
`runpod/worker-comfyui`, worker **vide** (aucun modele bake), modeles lus depuis le
network volume **c-edge** (`pnt4230ssw`, EUR-IS-1). En serverless le volume se monte sur
`/runpod-volume`. Seul delta vs Krea : ComfyUI epingle au SHA H3 (0.30.0) + les 2 node packs H3.

## Pourquoi H3 est un BON candidat serverless (contrairement a Krea image)

Sur une image Krea, le chargement des poids a froid (~183 s) ecrase l'inference (~14 s) =
ratio 13:1 -> serverless mauvais pour des images isolees. **La video H3 inverse ce ratio** :
l'inference d'un clip 10 s coute ~932 s (normal) / ~450 s (turbo), donc la taxe de reveil
redevient ~1:1. La video est batch/parallelisable = pile la forme ou le serverless gagne
(cf. vault `cout-serverless.md` : "endpoint batch = idle bas", "serverless achete du parallelisme").

## Contenu deja present sur le volume c-edge (rien a copier)

- DiT : `minimax_h3_fl2va_pruned_int8_convrot` (t2v/i2v) + `minimax_h3_ref2va_pruned_int8_convrot` (r2v)
- TE : `qwen3vl_32b_minimax_h3_int8_convrot`
- VAE : `minimax_h3_video_vae_fp16` + `minimax_h3_audio_vae_fp32`
- Turbo LoRAs : `minimax_h3_turbo_4step_ckpt500` + `..._ema_ckpt850`
- Nodes : `ComfyUI-KJNodes` + `ComfyUI-MiniMax-H3-Turbo`
- ComfyUI du volume : `v0.30.0-3-g16e3f303` (le Dockerfile bake exactement ce SHA)

## Build

CI GitHub Actions -> GHCR (`.github/workflows/build.yml`). Push sur `main` build et pousse
`ghcr.io/moltowski/comfyui-serverless-h3:latest`.

Pins (= revisions du volume, capturees 2026-08-08) :
| Composant | Revision |
|---|---|
| ComfyUI | `16e3f3034f2bba1fff6c70cbd759339778555cd6` |
| ComfyUI-KJNodes | `44fda83f307b7aee4a27ee268c86aaa74a5f5612` |
| ComfyUI-MiniMax-H3-Turbo | `55f85c6dbe58b41aaf5ee610d225ecce0a00ee17` |

⚠️ **Point a verifier au 1er build : Blackwell sm_120.** L'endpoint tourne sur RTX PRO 6000.
La base `runpod/worker-comfyui` doit etre en torch cu128 (>=2.7). Sinon decommenter le bloc
torch cu128 du Dockerfile. Le pod de ref tourne torch 2.10 cu128.

## Deploiement RunPod (quota = 5 workers, deja plein)

Etat actuel : comfygen (2 workers) + krea (3) = 5. On **recycle l'endpoint comfygen**
(`585v8zf3b3ihvt`, deja sur c-edge + Blackwell 96) et on prend 1 worker a krea.

`apply_endpoints.py` fait les 3 operations avec une cle **full-rights** (la cle injectee sur
les pods est read-only : `saveEndpoint` renvoie `Unauthorized`) :

```bash
export RUNPOD_API_KEY="<cle full-rights>"
python apply_endpoints.py            # dry-run : affiche le plan
python apply_endpoints.py --apply    # execute
```

1. **krea** `0ccxrcn554agid` : workersMax 3 -> 2
2. **template** `minimax-h3-serverless-worker` : image ci-dessus, disk 20 Go, env
   `NETWORK_VOLUME_DEBUG/REFRESH_WORKER/COMFY_LOG_LEVEL`
3. **comfygen** `585v8zf3b3ihvt` -> repointe sur la template H3 : GPU Blackwell 96,
   idle 5 s, workersMax 3, executionTimeout 40 min

A defaut de cle full-rights : tout est faisable a la main dans la console RunPod avec ces valeurs.

## Soumettre un job

Handler = worker-comfyui : schema `{"input":{"workflow": <workflow FORMAT API>}}`. La sortie
mp4 revient en base64 sous la cle `images` de `output` (gotcha H3 : SaveVideo sort sous `images`).
Le client `scripts/run_smoketest.py` du vault marche tel quel (ecrire `.mp4` au lieu de `.png`).

⚠️ Les 3 templates `workflows/h3_{t2v,i2v,r2v}.json` de l'agent sont en **format UI** -> les
exporter en **format API** avant de les envoyer ici, et y porter le cablage "turbo propre"
(DiffusionModelLoaderKJ + MiniMaxH3TurboLoRA + SigmaShift + TurboSampler) — cf.
`wiki/minimax-h3-turbo-sage.md`.

## Etat (2026-08-15)

- [x] 1er build CI + verif Blackwell/torch (base 5.8.6 cu128, OK sur RTX PRO 6000)
- [x] Workflows en format API (ils l'etaient deja ; smoketest fixture core-only ajoute)
- [x] Cle full-rights -> endpoints appliques (krea 3->2, template H3, comfygen repointe via REST v1)
- [x] 1er cold-load mesure : delayTime ~58 s (AVEC standby, donc pas un vrai froid)
- [ ] **Vrai cold-load** scale-from-zero (met workersMin/standby a 0, attend le drain, puis 1 job) -> ferme le chiffrage
- [ ] **Pic VRAM** a la reso prod (~1,2 MP) -> confirme le tier GPU (48 vs 96)
- [ ] Cabler le **turbo propre** (DiffusionModelLoaderKJ + MiniMaxH3TurboLoRA + SigmaShift + TurboSampler)
- [ ] Brancher l'endpoint dans l'agent (`COMFY_VIDEO_URL` = serverless au lieu d'un pod)
