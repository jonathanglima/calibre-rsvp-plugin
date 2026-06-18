# Calibre → RSVP Output Plugin

A Calibre **output-format plugin** that converts any book Calibre can read
(EPUB, MOBI, AZW3, PDF, …) into the **`.rsvp`** format used by the
[rsvpnano](https://github.com/ionutdecebal/rsvpnano) hardware speed-reading
device.

It registers `RSVP` as an output format, so it appears in
**Convert books → Output format**. The produced `.rsvp` is stored as a real
format on the book, which means Calibre's built-in **Content Server serves it
over the network for free** — the seam for a RomM-style "device pulls files
over the LAN" workflow.

## Format provenance

The `.rsvp` wire format is reproduced 1:1 from the canonical Kotlin converter
in the rsvpnano repo, under
`RSVPNanoCompanion/conversionCore/src/commonMain/kotlin/com/rsvpnano/converters/`:

| Source file        | What was reproduced |
|--------------------|---------------------|
| `RsvpWriter.kt`    | header directives, `@chapter`/`@para` markers, `@`-escaping, `trim()+"\n"`, UTF-8 |
| `RsvpConverter.kt` | `wrapWidth = 96`, chapter/paragraph event flow, `filenameSafe` |
| `RsvpTextUtils.kt` | `asciiReplacements` map, `\s+` tokenization, `filenameSafe()` |

Validated against `testdata/conversion/sample-expected.rsvp`.

### `.rsvp` structure

```
@rsvp 1
@title <title>
@author <author>          (optional)
@source <file>            (optional; this plugin omits it)
                          <- blank line
@chapter <title>
<first paragraph text>    <- NO @para before the first paragraph in a chapter

@para
<next paragraph, words joined by spaces, greedy-wrapped at 96 columns,
multiple wrapped lines stay under the one @para>
```

- Plain **UTF-8** text, whole file `.strip()` + trailing `\n`.
- Typographic chars normalized to ASCII (`“”`→`"`, `–—`→`-`, `…`→`...`,
  ligatures→`fi`/`fl`/…, nbsp→space, `©`→`(c)`). **Accented/extended-Latin
  letters are preserved.**
- A body line that begins with `@` is escaped with an extra leading `@`.
- The firmware generates `.ridx`/`.rdat` sidecars **on-device**; this plugin
  only writes the `.rsvp`.

## Install

```bash
calibre-customize -b ./rsvp_output          # build from source dir
# or
calibre-customize -a RSVP_Output.zip        # install the packaged zip
```

Restart Calibre. Develop with `calibre-debug -g` (GUI + console for tracebacks).

## Use

- GUI: select books → **Convert books** → Output format → **RSVP**.
- CLI: `ebook-convert book.epub book.rsvp`

Options (Conversion dialog → RSVP Output, or `--rsvp-*` on the CLI):

- `rsvp_include_author` (default on) — emit `@author` from metadata.
- `rsvp_one_chapter_per_file` (default on) — one `@chapter` per spine
  document; off = whole book as one `@chapter` titled with the book title.

## Serve over the network (RomM-style)

```bash
calibre-server --port 8080 /path/to/Calibre\ Library
# add auth: --enable-auth --manage-users   (then create users interactively)
```

Listens on all interfaces; reachable at `http://<host-lan-ip>:8080` and
advertised via Bonjour/Zeroconf.

A rsvpnano network client discovers and downloads `.rsvp` via the **ajax API**
(verified working):

| Endpoint | Purpose |
|----------|---------|
| `GET /ajax/library-info` | library ids (`default_library`) |
| `GET /ajax/search?query=...&library_id=<lib>` | → `book_ids` |
| `GET /ajax/book/<id>?library_id=<lib>` | metadata; `.rsvp` appears under `other_formats` → `/get/rsvp/<id>/<lib>` |
| `GET /get/RSVP/<id>/<lib>` | download the `.rsvp` bytes |

### OPDS

Calibre's OPDS feed (`calibre/srv/opds.py`) only emits an acquisition link for
a format when `guess_type('a.<ext>')` is non-None. `.rsvp` has no MIME type by
default, so it would be omitted. This plugin registers one at import time:

```python
mimetypes.add_type('application/x-rsvp', '.rsvp')
```

`calibre-server` imports enabled plugin modules at startup, so the type is
registered inside the server process and **OPDS lists `.rsvp` as an
acquisition link** (verified):

```xml
<link type="application/x-rsvp" href="/get/rsvp/<id>/<lib>"
      rel="http://opds-spec.org/acquisition" length="475" .../>
```

So the device client can crawl **either** OPDS (`/opds`, standard Atom, gives
per-format acquisition links) **or** the ajax API above. OPDS is usually the
easier target for a handheld; it's also Bonjour-advertised for auto-discovery.

## Scoping what the device syncs — tag and saved-search convention

The rsvpnano device pulls only the books that match a configurable query, passed
to `GET /ajax/search?query=<q>&library_id=<lib>`. The recommended convention is
a Calibre **tag**:

```
tag:rsvp
```

Add this tag to any book you want the device to download. The device stores the
query as the `searchQuery` setting (NVS key `cal_query`); the default shipped
value is `tag:rsvp`.

If you prefer a richer filter — e.g. a subset of titles, or books not yet read —
you can use any Calibre **saved search** as the query value. Create the saved
search in Calibre under *Search → Save current search*, then set `searchQuery`
to `search:<saved-search-name>`. Any valid Calibre search expression works; the
device passes it verbatim to the server.

The device only downloads books that have an `.rsvp` format stored on them. If a
book matches the search query but has no `.rsvp` format, the ajax API returns no
`rsvp` key under `other_formats` and the device skips it silently. So the
recommended workflow is:

1. Tag books you want on the device with `rsvp` (or build a saved search).
2. Convert them to `.rsvp` via **Convert books → Output format → RSVP** (or CLI
   `ebook-convert`). This stores the `.rsvp` format on the book in Calibre.
3. Start `calibre-server`; the plugin's MIME registration ensures `.rsvp` is
   served over the content server and listed in OPDS acquisition links.
4. On the device, trigger **Settings → Calibre → Sync from Calibre**.

The device client uses the ajax API (`/ajax/search`, `/ajax/book/<id>`,
`/get/rsvp/<id>/<lib>`) rather than OPDS, but the MIME registration this plugin
provides makes both paths work. See the
[firmware Calibre sync docs](https://github.com/ionutdecebal/rsvpnano/blob/feat/calibre-sync/docs/calibre-sync.md)
for the full end-to-end setup (issue #9).

## Known limitations

- Chapter granularity = spine document. With an auto-generated TOC, `@chapter`
  titles may fall back to the book title; real headings still appear in body
  text. Properly-authored EPUB TOCs produce correct chapter titles.
- No long-word splitting (matches the upstream converter).
- Python reimplementation; for byte-parity regression testing, diff against the
  repo's `testdata/conversion/*.rsvp`.

## Test

```bash
python3 test_rsvp.py      # stubs calibre.*, exercises the real plugin logic
```
