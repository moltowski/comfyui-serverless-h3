#!/usr/bin/env python3
"""Applique la bascule serverless H3 sur RunPod via l'API GraphQL.

Necessite une cle API RunPod FULL-RIGHTS (droits write) :
    export RUNPOD_API_KEY="<cle full-rights>"     # PAS la cle read-only injectee sur les pods

    python apply_endpoints.py                 # DRY-RUN : affiche le plan, ne touche a rien
    python apply_endpoints.py --apply         # execute

Ce que ca fait (idempotent, lit la config actuelle et ne change que le necessaire) :
  1. Cree la template serverless H3 (image ghcr.io/moltowski/comfyui-serverless-h3:latest)
  2. Repointe l'endpoint comfygen (585v8zf3b3ihvt) dessus : GPU Blackwell 96, idle bas,
     workersMax 3, executionTimeout large (la video H3 est longue : ~15 min chaud, plus a froid)
  3. Baisse krea-serverless-test (0ccxrcn554agid) a workersMax 2 (quota total = 5)

Stdlib uniquement.
"""
import argparse, json, os, sys, urllib.request

KREA = "0ccxrcn554agid"
COMFYGEN = "585v8zf3b3ihvt"          # l'endpoint qu'on recycle en H3
VOLUME = "pnt4230ssw"                 # c-edge, EUR-IS-1
IMAGE = "ghcr.io/moltowski/comfyui-serverless-h3:latest"

# GPU : RTX PRO 6000 96 Go. On garde le meme id que comfygen exposait deja.
GPU_H3 = "BLACKWELL_96,-NVIDIA A100 80GB PCIe"
IDLE_H3 = 5                           # batch : idle bas (RunPod facture l'idle par worker)
WORKERS_H3 = 3
EXEC_TIMEOUT_H3 = 2400000            # 40 min : cold-load H3 + inference longue (a affiner apres mesure)


def gql(q, variables=None):
    key = os.environ.get("RUNPOD_API_KEY", "").strip()
    if not key:
        sys.exit("RUNPOD_API_KEY absent.")
    body = json.dumps({"query": q, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        "https://api.runpod.io/graphql?api_key=" + key,
        data=body, headers={
            "Content-Type": "application/json",
            # L'edge RunPod renvoie 403 sur le UA par defaut de urllib ("Python-urllib").
            # Toujours un UA navigateur (gotcha vault : cf. now.md 2026-08-07).
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        })
    with urllib.request.urlopen(req, timeout=45) as r:
        out = json.load(r)
    if out.get("errors"):
        sys.exit("GraphQL error: " + json.dumps(out["errors"]))
    return out["data"]


def endpoints():
    q = ("query{myself{endpoints{id name templateId gpuIds gpuCount networkVolumeId "
         "locations idleTimeout scalerType scalerValue workersMax workersMin executionTimeoutMs}}}")
    return {e["id"]: e for e in gql(q)["myself"]["endpoints"]}


def save_endpoint(inp):
    q = ("mutation($in:EndpointInput!){saveEndpoint(input:$in)"
         "{id name templateId gpuIds idleTimeout workersMax workersMin executionTimeoutMs}}")
    return gql(q, {"in": inp})["saveEndpoint"]


def create_template():
    q = ("mutation($in:SaveTemplateInput!){saveTemplate(input:$in){id name imageName}}")
    inp = {
        "name": "minimax-h3-serverless-worker",
        "imageName": IMAGE,
        "dockerArgs": "",
        "containerDiskInGb": 20,
        "volumeInGb": 0,          # serverless : les modeles viennent du network volume, pas d'un volume de template
        "volumeMountPath": "/workspace",
        "isServerless": True,
        "env": [
            {"key": "NETWORK_VOLUME_DEBUG", "value": "true"},
            {"key": "REFRESH_WORKER", "value": "false"},
            {"key": "COMFY_LOG_LEVEL", "value": "INFO"},
        ],
    }
    return gql(q, {"in": inp})["saveTemplate"]


def merged(ep, **changes):
    """Repart de la config actuelle de l'endpoint, n'ecrase que `changes`."""
    keys = ["id", "name", "templateId", "gpuIds", "gpuCount", "networkVolumeId",
            "locations", "idleTimeout", "scalerType", "scalerValue",
            "workersMin", "workersMax", "executionTimeoutMs"]
    inp = {k: ep[k] for k in keys if ep.get(k) is not None}
    inp.update(changes)
    return inp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="execute (sinon dry-run)")
    ap.add_argument("--template-id", help="reutiliser une template H3 existante au lieu d'en creer une")
    a = ap.parse_args()

    eps = endpoints()
    if KREA not in eps or COMFYGEN not in eps:
        sys.exit("endpoints krea/comfygen introuvables : " + ", ".join(eps))

    print("== ETAT ACTUEL ==")
    for i in (KREA, COMFYGEN):
        e = eps[i]
        print("  %-15s %s | tmpl %s | gpu %s | idle %s | wmax %s" %
              (e["id"], e["name"], e["templateId"], e["gpuIds"], e["idleTimeout"], e["workersMax"]))

    if not a.apply:
        print("\n== PLAN (dry-run, rien execute) ==")
        print("  1. creer template minimax-h3-serverless-worker -> image", IMAGE)
        print("  2. repoint %s : tmpl=<nouvelle> gpu=%s idle=%s wmax=%s exec=%sms"
              % (COMFYGEN, GPU_H3, IDLE_H3, WORKERS_H3, EXEC_TIMEOUT_H3))
        print("  3. %s : wmax -> 2" % KREA)
        print("\nRelancer avec --apply (cle full-rights requise).")
        return

    # 1. baisser krea d'abord (liberer le slot avant de monter comfygen)
    r = save_endpoint(merged(eps[KREA], workersMax=2))
    print("krea workersMax ->", r["workersMax"])

    # 2. template H3
    if a.template_id:
        tid = a.template_id
    else:
        t = create_template()
        tid = t["id"]
        print("template creee:", tid, t["name"])

    # 3. repoint comfygen
    r = save_endpoint(merged(eps[COMFYGEN], templateId=tid, gpuIds=GPU_H3,
                             idleTimeout=IDLE_H3, workersMax=WORKERS_H3,
                             executionTimeoutMs=EXEC_TIMEOUT_H3, name="minimax-h3-serverless"))
    print("comfygen -> H3:", json.dumps(r))
    print("\nOK. Verifier /health et lancer un smoketest H3.")


if __name__ == "__main__":
    main()
