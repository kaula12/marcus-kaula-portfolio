# Marcus Kaula — Dynamic Portfolio & Admin CMS

Full-stack portfolio website with Swiss-editorial typography, project video & image uploads, optional external project links, CV viewer, certificates gallery, journey timeline, engineering journal, and a personal visual gallery.

## Quick Start (Local Development)

```bash
pip install -r backend/requirements.txt
cp .env.example .env
uvicorn backend.main:app --reload --port 8000
```

Open **http://localhost:8000** in your browser.
- If `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are left blank in `.env`, the app runs seamlessly using local SQLite (`backend/portfolio.db`) and `backend/uploads/`.

## Supabase Storage & PostgreSQL Setup (Recommended for Production)

1. Open your Supabase project and go to **SQL Editor**.
2. Paste and run the full script in `backend/supabase_schema.sql`.
3. Copy your **Project URL** and **Service Role Key** from **Project Settings → API** into `.env` (or your cloud host's environment variables on Render/Railway/Fly.io):
   ```env
   SUPABASE_URL=https://your-project-id.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
   SUPABASE_BUCKET=portfolio-media
   ADMIN_PASSCODE=your-strong-passcode
   ```
4. Check `GET /api/health` — it will report `"backend": "supabase"` once connected.

## Pushing to GitHub Safely

- `.gitignore` is preconfigured to block `.env`, `__pycache__/`, and virtual environments so your Supabase keys and secrets are never committed.
- Always share `.env.example` in the repo, never `.env`.

## Private Admin Studio Access (Hidden from Public Visitors)

The Admin Studio button is completely hidden from the public navigation bar. Open the passcode prompt using any of these three private triggers:
1. **Keyboard Shortcut:** Press `Ctrl + Shift + L` (or `Cmd + Shift + L` on Mac) anywhere on the site.
2. **URL Parameter:** Visit `/?studio=1` (automatically stripped from the address bar).
3. **Secret Brand Tap:** Triple-click the small green square next to **MARCUS KAULA** in the top-left header.

- Default passcode: `kaula12` (change it in **Profile & Hero** inside Admin Studio).
- **Projects:** Leave the GitHub URL blank to hide the GitHub button; add Live Deployment or any custom external links (`Label | https://...`) under **Other Links**.
- **Gallery / Photos:** Upload personal photos with captions, dates, tags, and locations in the **Gallery / Photos** tab.
