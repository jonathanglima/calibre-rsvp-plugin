#!/usr/bin/env bash
# rsvp-import.sh — headless workflow for a Calibre server box.
# For each EPUB (passed as a file, or found recursively under a directory):
# add it to the library (tagged 'rsvp'), convert it to .rsvp, and attach that
# format so Calibre's Content Server serves it. PDFs and other files ignored.
#
# Usage:
#   RSVP_LIB=/path/to/CalibreLibrary ./rsvp-import.sh book1.epub book2.epub
#   RSVP_LIB=/path/to/CalibreLibrary ./rsvp-import.sh ~/incoming-epubs/   # recurses
#
# Requires: calibre (calibredb, ebook-convert) + the RSVP Output plugin installed.
set -euo pipefail

LIB="${RSVP_LIB:?set RSVP_LIB to your Calibre library path}"
[ "$#" -ge 1 ] || { echo "usage: RSVP_LIB=/path/lib $0 <file.epub | directory> ..."; exit 1; }
mkdir -p "$LIB"

# Collect .epub paths from file args and (recursively) directory args.
epubs=()
for arg in "$@"; do
  if [ -d "$arg" ]; then
    while IFS= read -r -d '' f; do epubs+=("$f"); done \
      < <(find "$arg" -type f -iname '*.epub' -print0)
  elif [ -f "$arg" ]; then
    epubs+=("$arg")
  else
    echo "!! not found: $arg"
  fi
done
[ "${#epubs[@]}" -ge 1 ] || { echo "no .epub files found"; exit 1; }
echo "found ${#epubs[@]} epub(s) to import"
echo

ok=0
for epub in "${epubs[@]}"; do
  echo ">> $epub"
  id=$(calibredb add "$epub" --tags rsvp --library-path "$LIB" 2>/dev/null \
        | grep -oE '[0-9]+' | tail -1)
  if [ -z "${id:-}" ]; then echo "   add failed, skipping"; continue; fi
  tmp="$(mktemp --suffix=.rsvp)"
  if ebook-convert "$epub" "$tmp" >/dev/null 2>&1; then
    calibredb add_format "$id" "$tmp" --library-path "$LIB" >/dev/null 2>&1
    echo "   book id=$id  +RSVP format  +tag:rsvp"
    ok=$((ok + 1))
  else
    echo "   id=$id added, but RSVP conversion FAILED (kept EPUB only)"
  fi
  rm -f "$tmp"
done

echo
echo "imported $ok/${#epubs[@]}.  Serve with:  calibre-server \"$LIB\""
