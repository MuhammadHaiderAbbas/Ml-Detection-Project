# Public website

The marketing website lives in [`site/`](../site). It is a static site (HTML, CSS and a small script, with no
build step), deployed to GitHub Pages by [`.github/workflows/pages.yml`](../.github/workflows/pages.yml) on every
push to `main` that touches the site. The "Request an evaluation" form saves to a Supabase table.

The product itself is **not** hosted on the website. Adaptive IDS is local-first software that runs on a
customer's own machine. The website explains it, shows the demo video and evidence, and collects evaluation
requests.

| Part | Where |
|---|---|
| Pages | `site/index.html`, `site/privacy.html`, `site/404.html` |
| Styles and script | `site/assets/css/site.css`, `site/assets/js/site.js` |
| Settings (Supabase URL and publishable key, LinkedIn, contact email) | `site/assets/js/config.js` |
| Images | `site/assets/img/` (screenshots from the running app, WebP) |
| Video | copied from `docs/demo/adaptive-ids-demo.mp4` at build time |
| Build | `python tools/site/build.py OUT_DIR SITE_URL [BASE_PATH]` |
| Database table | `tools/site/supabase-evaluation-requests.sql` (already applied) |
| Tests | `tests/test_site.py` |

## Publish it (one-time steps)

1. **Merge to `main`** (pull request from `claude/adaptive-ids-system-spec-jdp34l`).
2. **Make the repository public:** Settings → General → Danger Zone → Change visibility → Public. Free GitHub
   Pages needs a public repository. The licence stays "all rights reserved".
3. **Turn on Pages:** Settings → Pages → Build and deployment → Source: **GitHub Actions**.
4. **Run the "Website" workflow:** Actions → Website → Run workflow, or push any change under `site/`. The site
   appears at `https://muhammadhaiderabbas.github.io/Ml-Detection-Project/`.

## Connect your domain

Buy the domain, then:

1. **Set the domain in GitHub:** Settings → Pages → Custom domain → enter `adaptiveids.com` (or your choice) →
   Save. With an Actions deployment you don't need a `CNAME` file.
2. **At your domain registrar, add these DNS records:**

   | Type | Name / host | Value |
   |---|---|---|
   | A | @ | 185.199.108.153 |
   | A | @ | 185.199.109.153 |
   | A | @ | 185.199.110.153 |
   | A | @ | 185.199.111.153 |
   | AAAA | @ | 2606:50c0:8000::153 |
   | AAAA | @ | 2606:50c0:8001::153 |
   | AAAA | @ | 2606:50c0:8002::153 |
   | AAAA | @ | 2606:50c0:8003::153 |
   | CNAME | www | muhammadhaiderabbas.github.io |

3. **Wait for DNS,** usually minutes but up to 24 hours. When GitHub shows the DNS check as successful, tick
   **Enforce HTTPS**.
4. **Verify the domain** (recommended, stops anyone else claiming it on GitHub): your GitHub profile →
   Settings → Pages → Add a domain, then add the TXT record GitHub shows you.
5. **Re-run the Website workflow** so canonical links, the sitemap and the social-preview tags use the new
   domain.

## The request form

- **Where submissions go:** the table `public.adaptive_ids_evaluation_requests` in the Supabase project
  **MHaiderAbbas Portfolio** (London). To read them: Supabase dashboard → Table Editor →
  `adaptive_ids_evaluation_requests`.
- **What visitors can do:** add a row only. Row-level security stops anyone from reading, changing or deleting
  submissions with the public key, so the publishable key in `config.js` is safe to publish. Never put a
  secret or `service_role` key there.
- **Abuse limits:**
  - one request per email address per 10 minutes, and at most 100 an hour overall;
  - a hidden honeypot field silently drops simple bots.
- **Your obligations:** reply within the two working days the site promises. Delete requests older than 24
  months, as the privacy notice says:

  ```sql
  delete from public.adaptive_ids_evaluation_requests where created_at < now() - interval '24 months';
  ```

## Edit the site

- **Links and contact email:** fill `linkedinUrl` and (optionally) `contactEmail` in `site/assets/js/config.js`.
  Empty values hide the link. The contact email is also shown in the privacy notice.
- **Video:** replace `docs/demo/adaptive-ids-demo.mp4` (keep it under 12 MB, H.264). To use the upgraded
  video with the real-data chapter, put that file there.
- **Preview locally:**

  ```bash
  python tools/site/build.py _site http://127.0.0.1:8900
  python3 -m http.server 8900 --directory _site
  ```

- **Run the tests:** `python -m pytest tests/test_site.py` checks:
  - links and assets exist;
  - the Content Security Policy is strict, with no inline code;
  - the form's fields match the database table;
  - the config holds only public values;
  - the build fills every placeholder.

## Security notes

- **Content Security Policy:** each page sets a strict CSP in a meta tag: scripts and styles only from the site
  itself, and network requests only to the Supabase project. GitHub Pages can't set HTTP headers, so
  framing protection (`frame-ancestors`) isn't available there.
- **No tracking:** no cookies, analytics or third-party fonts, scripts or embeds.
