#!/usr/bin/env bash
# Bulk-sync a folder of books into the Calibre library and make sure every book
# has an .rsvp format. Robust against duplicates and mixed formats:
#   * adds with `--automerge ignore`, so a new format (mobi/pdf) of a book you
#     already have (as epub) merges into the existing record instead of making a
#     duplicate, and re-adding the same file is a no-op.
#   * then converts every book still missing .rsvp from its best source format
#     (prefer epub > mobi > azw3 > pdf; pdf uses --enable-heuristics).
# Handles the content-server lock automatically (stop service -> work -> start).
#
#   RSVP_LIB=~/CalibreLibrary ./rsvp-sync.sh ~/incoming-epubs [--new-only]
set -euo pipefail

LIB="${RSVP_LIB:-$HOME/CalibreLibrary}"
SERVICE="${CALIBRE_SERVICE:-calibre-server}"
SRC="${1:?usage: RSVP_LIB=.. rsvp-sync.sh <dir> [--new-only]}"
NEW_ONLY="${2:-}"

findargs=( -type f \( -iname '*.epub' -o -iname '*.mobi' -o -iname '*.pdf' \) )
[ "$NEW_ONLY" = "--new-only" ] && findargs+=( -mtime -1 )
files=()
while IFS= read -r -d '' f; do files+=( "$f" ); done \
  < <(find "$SRC" "${findargs[@]}" -print0)
echo "found ${#files[@]} source files under $SRC"
[ "${#files[@]}" -ge 1 ] || { echo "nothing to do"; exit 0; }

if systemctl --user is-active --quiet "$SERVICE" 2>/dev/null; then
  echo "stopping $SERVICE (releasing library lock)..."
  systemctl --user stop "$SERVICE"
fi

echo "adding to library (automerge=ignore, tag=rsvp)..."
calibredb add --automerge ignore --tags rsvp --library-path "$LIB" "${files[@]}" 2>&1 | tail -3

echo "ensuring every book has an .rsvp format..."
calibredb list --for-machine --fields id,formats --search "not formats:rsvp" \
  --library-path "$LIB" > /tmp/rsvp_missing.json
python3 - "$LIB" <<'PY'
import json, os, subprocess, sys, tempfile
lib = sys.argv[1]
books = json.load(open('/tmp/rsvp_missing.json'))
pref = ['epub', 'mobi', 'azw3', 'pdf', 'txt', 'htmlz', 'docx', 'fb2']
def ext(p): return os.path.splitext(p)[1].lower().lstrip('.')
ok = fail = 0
for b in books:
    fmts = {}
    for p in b.get('formats', []):
        fmts.setdefault(ext(p), p)
    src = next((fmts[e] for e in pref if e in fmts), None)
    if not src:
        continue
    out = tempfile.mktemp(suffix='.rsvp')
    cmd = ['ebook-convert', src, out]
    if ext(src) == 'pdf':
        cmd += ['--enable-heuristics']
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) == 0:
        print('  FAIL id', b['id'], '('+ext(src)+')'); fail += 1; continue
    subprocess.run(['calibredb', 'add_format', str(b['id']), out,
                    '--library-path', lib], capture_output=True)
    try: os.remove(out)
    except OSError: pass
    ok += 1
print(f"converted {ok}, failed {fail}, of {len(books)} books missing .rsvp")
PY

echo "starting $SERVICE..."
systemctl --user start "$SERVICE" || true
echo "rsvp-sync done."
