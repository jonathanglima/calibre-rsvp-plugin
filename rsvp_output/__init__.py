#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Calibre output-format plugin: convert any input book to the rsvpnano .rsvp
format (https://github.com/ionutdecebal/rsvpnano).

Registers "RSVP" as an output format, so it appears in the
"Convert books -> Output format" dropdown. The produced .rsvp is stored as a
real format on the book, which means Calibre's Content Server serves it for
free at  /get/RSVP/<book_id>/<library>  -- the seam for the future rsvpnano
HTTP integration.

The .rsvp wire format (plain UTF-8 text with @-directives) is reproduced from
the canonical Kotlin converter in the rsvpnano repo:
  conversionCore/.../RsvpWriter.kt, RsvpConverter.kt, RsvpTextUtils.kt
"""

import re
import mimetypes

from calibre.customize.conversion import OutputFormatPlugin, OptionRecommendation

# Teach Python's mimetypes about .rsvp so Calibre's guess_type() resolves it.
# Calibre's OPDS feed (calibre/srv/opds.py) only emits an acquisition link for
# a format when guess_type('a.<ext>') is non-None; without this the .rsvp
# format is silently omitted from OPDS. Registered at import time so it also
# takes effect inside the calibre-server process.
RSVP_MIME = 'application/x-rsvp'
mimetypes.add_type(RSVP_MIME, '.rsvp')


WRAP_WIDTH = 96  # RsvpConverter.wrapWidth

# Typographic -> ASCII normalization, mirroring RsvpTextUtils.asciiReplacements.
# NOTE: accented / extended-Latin letters are intentionally NOT mapped -- the
# firmware preserves them.
ASCII_REPLACEMENTS = {
    # whitespace variants -> regular space
    u' ': u' ', u' ': u' ', u' ': u' ', u' ': u' ',
    u' ': u' ', u' ': u' ', u' ': u' ', u' ': u' ',
    u' ': u' ', u' ': u' ', u' ': u' ', u'​': u'',
    u'﻿': u'',
    # single quotes / apostrophes
    u'‘': u"'", u'’': u"'", u'‚': u"'", u'‛': u"'",
    u'′': u"'", u'´': u"'", u'`': u"'",
    # double quotes
    u'“': u'"', u'”': u'"', u'„': u'"', u'‟': u'"',
    u'″': u'"', u'«': u'"', u'»': u'"',
    # dashes / minus
    u'‐': u'-', u'‑': u'-', u'‒': u'-', u'–': u'-',
    u'—': u'-', u'―': u'-', u'−': u'-',
    # misc symbols
    u'…': u'...', u'•': u'*', u'·': u'*',
    u'©': u'(c)', u'®': u'(r)', u'™': u'(tm)',
    # ligatures
    u'ﬀ': u'ff', u'ﬁ': u'fi', u'ﬂ': u'fl',
    u'ﬃ': u'ffi', u'ﬄ': u'ffl', u'ﬅ': u'st', u'ﬆ': u'st',
}

_WS_RE = re.compile(r'\s+')

# Block-level tags whose text becomes one paragraph each.
BLOCK_TAGS = frozenset((
    'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'li', 'blockquote', 'pre', 'dd', 'dt',
    'figcaption', 'caption', 'div', 'td',
))
HEADING_TAGS = frozenset(('h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'title'))


def normalize_text(text):
    """ASCII-normalize typographic chars and collapse whitespace."""
    if not text:
        return u''
    out = [ASCII_REPLACEMENTS.get(ch, ch) for ch in text]
    return _WS_RE.sub(u' ', u''.join(out)).strip()


def output_tokens(text):
    """Split normalized text into output tokens (keep all non-empty)."""
    return [t for t in _WS_RE.split(text) if t]


def wrap_words(words, width=WRAP_WIDTH):
    """Greedy word wrap to `width` columns; words joined by single spaces."""
    lines = []
    current = []
    length = 0
    for w in words:
        add = len(w) if not current else len(w) + 1
        if current and length + add > width:
            lines.append(u' '.join(current))
            current = [w]
            length = len(w)
        else:
            current.append(w)
            length += add
    if current:
        lines.append(u' '.join(current))
    return lines


def escape_at(line):
    """A body line starting with '@' is escaped with an extra leading '@'."""
    return (u'@' + line) if line.startswith(u'@') else line


def filename_safe(value):
    """Mirror RsvpTextUtils.filenameSafe: keep [alnum _ -], else '-'."""
    mapped = u''.join(
        ch if (ch.isalnum() or ch in u' -_') else u'-'
        for ch in (value or u'')
    )
    collapsed = _WS_RE.sub(u' ', mapped).strip()
    return collapsed[:80] if collapsed else u'Untitled'


class RSVPOutput(OutputFormatPlugin):

    name = 'RSVP Output'
    author = 'Jonathan'
    description = ('Convert books to the rsvpnano .rsvp speed-reading format '
                   '(one-word-at-a-time RSVP reader).')
    version = (1, 0, 0)
    minimum_calibre_version = (5, 0, 0)

    file_type = 'rsvp'
    commit_name = 'rsvp_output'

    options = set((
        OptionRecommendation(
            name='rsvp_include_author',
            recommended_value=True,
            level=OptionRecommendation.LOW,
            help='Include an @author line in the .rsvp header (from book metadata).'),
        OptionRecommendation(
            name='rsvp_one_chapter_per_file',
            recommended_value=True,
            level=OptionRecommendation.LOW,
            help='Emit one @chapter per spine document. If disabled, the whole '
                 'book is written as a single @chapter using the book title.'),
    ))

    # ------------------------------------------------------------------ #

    def convert(self, oeb, output_path, input_plugin, opts, log):
        from calibre.ebooks.oeb.base import barename

        title = self._meta_first(oeb.metadata.title) or u'Untitled'
        authors = [self._text(a) for a in oeb.metadata.creator]
        authors = [a for a in authors if a]

        toc_titles = self._toc_title_map(oeb)

        lines = [u'@rsvp 1', u'@title ' + normalize_text(title)]
        if opts.rsvp_include_author and authors:
            lines.append(u'@author ' + normalize_text(u', '.join(authors)))

        wrote_any = False
        chapter_count = 0
        word_count = 0
        single_chapter_open = False

        for index, item in enumerate(oeb.spine):
            root = getattr(item, 'data', None)
            if root is None:
                continue

            paragraphs = self._extract_paragraphs(root, barename)
            if not paragraphs:
                continue

            if opts.rsvp_one_chapter_per_file:
                chapter_title = (toc_titles.get(self._base_href(item.href))
                                 or self._first_heading(root, barename)
                                 or (u'Section %d' % (index + 1)))
                lines.append(u'')
                lines.append(u'@chapter ' + normalize_text(chapter_title))
                chapter_count += 1
                first_para = True
            else:
                if not single_chapter_open:
                    lines.append(u'')
                    lines.append(u'@chapter ' + normalize_text(title))
                    single_chapter_open = True
                    chapter_count = 1
                    first_para = True
                else:
                    first_para = False

            for para in paragraphs:
                words = output_tokens(para)
                if not words:
                    continue
                word_count += len(words)
                if first_para:
                    first_para = False
                else:
                    lines.append(u'')
                    lines.append(u'@para')
                for wl in wrap_words(words):
                    lines.append(escape_at(wl))
                wrote_any = True

        if not wrote_any:
            log.warn('RSVP: no text content found; writing empty book.')
            chapter_count = max(chapter_count, 1)

        body = u'\n'.join(lines).strip() + u'\n'

        with open(output_path, 'wb') as f:
            f.write(body.encode('utf-8'))

        log('RSVP: wrote %d chapter(s), %d word(s) to %s'
            % (max(chapter_count, 1), word_count, output_path))

    # ------------------------------------------------------------------ #
    # helpers

    @staticmethod
    def _text(obj):
        try:
            return (u'%s' % obj).strip()
        except Exception:
            return u''

    @classmethod
    def _meta_first(cls, seq):
        for item in (seq or []):
            t = cls._text(item)
            if t:
                return t
        return u''

    @staticmethod
    def _base_href(href):
        if not href:
            return u''
        return (u'%s' % href).split('#')[0]

    def _toc_title_map(self, oeb):
        """Map base href -> first TOC title pointing at it."""
        mapping = {}
        try:
            for node in oeb.toc.iter():
                href = self._base_href(getattr(node, 'href', None))
                title = self._text(getattr(node, 'title', None))
                if href and title and href not in mapping:
                    mapping[href] = title
        except Exception:
            pass
        return mapping

    @staticmethod
    def _has_block_descendant(el, barename):
        for child in el.iterdescendants():
            tag = child.tag
            if isinstance(tag, str) and barename(tag) in BLOCK_TAGS:
                return True
        return False

    def _extract_paragraphs(self, root, barename):
        """Document-order text of leaf-ish block elements (no double-count)."""
        paragraphs = []
        for el in root.iter():
            tag = el.tag
            if not isinstance(tag, str):
                continue  # comments / processing instructions
            if barename(tag) not in BLOCK_TAGS:
                continue
            if self._has_block_descendant(el, barename):
                continue  # container; its children carry the text
            text = normalize_text(u''.join(el.itertext()))
            if text:
                paragraphs.append(text)
        return paragraphs

    def _first_heading(self, root, barename):
        for el in root.iter():
            tag = el.tag
            if not isinstance(tag, str):
                continue
            if barename(tag) in HEADING_TAGS:
                text = normalize_text(u''.join(el.itertext()))
                if text:
                    return text
        return None
