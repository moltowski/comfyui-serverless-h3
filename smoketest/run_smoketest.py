#!/usr/bin/env python3
"""Soumet un workflow ComfyUI (format API) a un endpoint RunPod serverless et ecrit l'image.

    set RUNPOD_API_KEY=...            (PowerShell : $env:RUNPOD_API_KEY="...")
    python scripts/run_smoketest.py handoff/krea-smoketest.json

Sort les timings reels (delayTime / executionTime) et verifie que le job a VRAIMENT produit
quelque chose : un statut COMPLETED sans image est un echec, pas un succes (cf. handoff §4).
Stdlib uniquement, pas de requests.
"""
import argparse, base64, json, os, struct, sys, time, urllib.request, urllib.error

ENDPOINT = "0ccxrcn554agid"


def call(url, key, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("Authorization", "Bearer " + key)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit("HTTP %s sur %s : %s" % (e.code, url, e.read()[:500].decode("utf8", "replace")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow")
    ap.add_argument("--endpoint", default=ENDPOINT)
    ap.add_argument("--out", default=None)
    ap.add_argument("--seed", type=int, default=None,
                    help="force la seed du KSampler. INDISPENSABLE pour mesurer un worker chaud : "
                         "resoumettre la meme seed renvoie le CACHE de ComfyUI (~2 s, mesure vide).")
    a = ap.parse_args()

    key = os.environ.get("RUNPOD_API_KEY", "").strip()
    if not key:
        sys.exit("RUNPOD_API_KEY absent de l'environnement.")

    base = "https://api.runpod.ai/v2/" + a.endpoint
    wf = json.load(open(a.workflow, encoding="utf8"))
    if a.seed is not None:
        for n in wf.values():
            if "seed" in n.get("inputs", {}):
                n["inputs"]["seed"] = a.seed
        print("seed forcee a %d" % a.seed)

    h = call(base + "/health", key)
    w = h.get("workers", {})
    print("health: workers %s | queue %s" % (json.dumps(w), json.dumps(h.get("jobs", {}))))
    # MESURE 2026-07-28 : 3 workers "idle/ready" et pourtant executionTime = 197 s (chargement
    # complet des poids). Un worker provisionne n'a PAS les poids en memoire -> /health ne predit
    # pas si le job sera chaud. Seul executionTime le dit apres coup : ~14 s chaud, ~197 s froid.
    if not w.get("idle") and not w.get("ready"):
        print("-> aucun worker debout : demarrage + chargement des poids (~307 s attendu)")
    else:
        print("-> workers debout, mais 'idle' ne veut pas dire poids charges : lire executionTime")

    t0 = time.time()
    job = call(base + "/run", key, {"input": {"workflow": wf}})
    jid = job.get("id")
    if not jid:
        sys.exit("pas de job id : " + json.dumps(job)[:500])
    print("job %s soumis" % jid)

    last = None
    while time.time() - t0 < 1200:
        s = call(base + "/status/" + jid, key)
        st = s.get("status")
        if st != last:
            print("  [%4.0fs] %s" % (time.time() - t0, st), flush=True)
            last = st
        if st == "COMPLETED":
            break
        if st in ("FAILED", "CANCELLED", "TIMED_OUT"):
            sys.exit("job %s : %s" % (st, json.dumps(s.get("output") or s)[:800]))
        time.sleep(3)
    else:
        sys.exit("timeout : le job n'a pas fini en 20 min")

    d, e = s.get("delayTime"), s.get("executionTime")
    print("delayTime %s ms | executionTime %s ms | mur %.0f s" % (d, e, time.time() - t0))

    imgs = (s.get("output") or {}).get("images") or []
    if not imgs:
        sys.exit("COMPLETED mais AUCUNE image -> le graphe a ete ampute a la validation.\n"
                 "Sortie brute : " + json.dumps(s.get("output"))[:800])

    im = imgs[0]
    if im.get("type") == "base64":
        raw = base64.b64decode(im["data"])
    else:
        with urllib.request.urlopen(im["data"], timeout=180) as r:
            raw = r.read()

    out = a.out or os.path.join(os.path.dirname(a.workflow) or ".", "smoketest-out.png")
    open(out, "wb").write(raw)

    ok = raw[:8] == b"\x89PNG\r\n\x1a\n"
    dims = struct.unpack(">II", raw[16:24]) if ok else ("?", "?")
    print("ecrit %s | %d octets | PNG=%s | %sx%s" % (out, len(raw), ok, dims[0], dims[1]))


if __name__ == "__main__":
    main()
