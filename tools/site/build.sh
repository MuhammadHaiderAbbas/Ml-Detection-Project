#!/usr/bin/env bash
# Assembles the public website into OUT_DIR for GitHub Pages (or a local preview).
#   tools/site/build.sh OUT_DIR SITE_URL [BASE_PATH]
#   e.g. tools/site/build.sh _site https://adaptiveids.com
#        tools/site/build.sh _site https://user.github.io/Ml-Detection-Project /Ml-Detection-Project
# SITE_URL fills canonical links, the sitemap and social-preview tags; BASE_PATH is the path the
# site is served under ("" for a custom domain), used by the 404 page.
set -euo pipefail
out=${1:?output directory}
site_url=${2:?site URL, e.g. https://adaptiveids.com}
base_path=${3:-}
site_url=${site_url%/}
base_path=${base_path%/}
root=$(cd "$(dirname "$0")/../.." && pwd)

rm -rf "$out"
mkdir -p "$out"
cp -R "$root/site/." "$out/"
mkdir -p "$out/assets/video"
cp "$root/docs/demo/adaptive-ids-demo.mp4" "$out/assets/video/adaptive-ids-demo.mp4"
find "$out" -type f \( -name '*.html' -o -name '*.xml' -o -name '*.txt' \) -print0 |
  xargs -0 sed -i -e "s#%%SITE_URL%%#${site_url}#g" -e "s#%%BASE_PATH%%#${base_path}#g"
if grep -rq '%%[A-Z_]*%%' "$out" --include='*.html' --include='*.xml' --include='*.txt'; then
  echo "unreplaced placeholders remain" >&2; exit 1
fi
echo "Built $out for $site_url"
