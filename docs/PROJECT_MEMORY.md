# GridSense — Project Memory

Last updated: 2026-09-30 (session 1)

## How to resume in a new chat
Paste this whole file as the first message and say "continue GridSense".
Claude reads the public GitHub repo (no local access), gives scripts + commands,
Kamal runs them in the terminal and pastes the output back.
Update this file at the END of every session.

## Goal
Turn GridSense into a clean, production-grade energy-intelligence product.
Benchmark against private, government and open-source competitors
(e.g. ENTSO-E Transparency Platform, Energy-Charts, Electricity Maps) — to be researched in Phase 4.
Keep repo + git history professional. All work is done locally, then pushed.

## Environment
- Machine: kamal@kamal-HP-241-G1 (Linux), repo: /home/kamal/projects/gridsense
- Python 3.12.3, Node v20.20.2, npm 10.8.2, git 2.43.0
- Repo: github.com/kamal-lochan-sahu/gridsense (public, MIT, branch main)
- Live: frontend https://gridsense-eight.vercel.app (Vercel),
  backend https://gridsense-backend-k8pa.onrender.com (Render, free tier)
- Claude cannot fetch the Render backend (robots disallow) — ask Kamal to paste curl output.

## Baseline (audited 2026-09-30)
- Commit a0292fc, 35 commits, 2026-03-31 .. 2026-04-12, one author, conventional-commit style.
- Stack: FastAPI + requests + numpy | Next.js 16.2.3 + React 19 + Tailwind 4 + Recharts 3.
- No .env / key files ever committed (narrow pattern scan = 0 hits).
- A 3 MB icon-192.png blob exists in history (only real history bloat).

## Known issues (from code audit; * = inferred from code, not verified live)
1. Forecast is static: backend/models/predictions.json (24 pts, 11-12 Apr 2026), Germany only;
   prophet_model.pkl is never loaded. UI labels it "Next 24hr".
2. requirements.txt was UTF-16/CRLF (fixed in Phase 1; now 5 runtime deps).
3. parser ignores resolution/timestamps; frontend slice(-24) assumes hourly*.
4. Weather error fallback returns [0] => UI shows 0 C; card uses temperature[0] (midnight), labelled Live.
5. /energy calls ENTSO-E 4x sequentially, no cache/timeout; every refresh = 5 ENTSO-E calls.
6. Anomaly: global z-score on 24h data; UI always shows Germany only.
7. next-pwa still in package.json but unused; manifest not linked in layout; no service worker.
8. API_URL hardcoded in page.tsx; CORS "*"; no tests, CI, logging, error UI.
9. README claims (GPU T4 Colab, notebooks/) unverified / missing.
10. Hinglish comments, datetime.utcnow() deprecated, duplicated country maps, unused imports.

## Roadmap
- [x] Phase 0: audit (code + git history)
- [x] Phase 1: hygiene cleanup (merged to main 2026-09-30)
- [ ] Phase 2: correctness (parser, caching, timeouts, env-based API URL, error UI, tests, CI, PWA fix)
- [ ] Phase 3: real ML (scheduled retraining, all countries, better anomaly method)
- [ ] Phase 4: competitor research + new features

## Decisions
- History: recommendation = keep (clean already); optional filter-repo for the 3 MB blob at the end. Final call pending.
- Forecast approach (keep static Prophet vs live retraining): pending, needed before Phase 3.

## Open questions
- Does Kamal still have the Colab notebook (model_training.ipynb) locally?

## Session log
- 2026-09-30 S1: full repo read, audit, git-history audit, Phase 1 done (backup tag backup/pre-phase1), pushed and merged to main.
