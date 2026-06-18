#!/usr/bin/env python3
"""Standalone test for the RSVP output plugin's logic.

Stubs the `calibre.*` imports so the REAL plugin module can be imported and
exercised without a Calibre install. Builds a synthetic OEB-like book from
lxml XHTML trees, runs convert(), and asserts the .rsvp output matches the
format reproduced from the rsvpnano canonical converter.
"""
import sys
import types
import os
import tempfile

# --- stub calibre.customize.conversion ---------------------------------- #
conv = types.ModuleType('calibre.customize.conversion')


class OutputFormatPlugin(object):
    def __init__(self, *a, **k):
        pass


class OptionRecommendation(object):
    LOW = 1
    MED = 2
    HIGH = 3

    def __init__(self, name=None, recommended_value=None, level=None, help=None):
        self.name = name
        self.recommended_value = recommended_value
        self.level = level
        self.help = help


conv.OutputFormatPlugin = OutputFormatPlugin
conv.OptionRecommendation = OptionRecommendation

calibre = types.ModuleType('calibre')
customize = types.ModuleType('calibre.customize')
oeb_base = types.ModuleType('calibre.ebooks.oeb.base')


def barename(tag):
    # strip {namespace}
    return tag.split('}', 1)[1] if '}' in tag else tag


oeb_base.barename = barename
for name, mod in (
    ('calibre', calibre),
    ('calibre.customize', customize),
    ('calibre.customize.conversion', conv),
    ('calibre.ebooks', types.ModuleType('calibre.ebooks')),
    ('calibre.ebooks.oeb', types.ModuleType('calibre.ebooks.oeb')),
    ('calibre.ebooks.oeb.base', oeb_base),
):
    sys.modules[name] = mod

# --- import the real plugin --------------------------------------------- #
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'rsvp_output'))
import importlib.util
spec = importlib.util.spec_from_file_location(
    'rsvp_plugin', os.path.join(os.path.dirname(__file__), 'rsvp_output', '__init__.py'))
rsvp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rsvp)

from lxml import etree

# --- unit checks on pure helpers ---------------------------------------- #
assert rsvp.normalize_text(u'“Hi—there…”') == u'"Hi-there..."', \
    rsvp.normalize_text(u'“Hi—there…”')
assert rsvp.normalize_text(u'a  b') == u'a b'
assert rsvp.normalize_text(u'café naïve') == u'café naïve'  # accents kept
assert rsvp.filename_safe(u'A: B/C*?') == u'A- B-C--'
assert rsvp.filename_safe(u'') == u'Untitled'
assert rsvp.filename_safe(u'x' * 200) == u'x' * 80
assert rsvp.escape_at(u'@para later') == u'@@para later'
assert rsvp.escape_at(u'normal') == u'normal'
# greedy wrap at 96
long_words = ['word%02d' % i for i in range(40)]
for line in rsvp.wrap_words(long_words):
    assert len(line) <= rsvp.WRAP_WIDTH, repr(line)
assert ' '.join(rsvp.wrap_words(long_words)) == ' '.join(long_words)
print('helper unit checks: PASS')

# --- synthetic OEB book ------------------------------------------------- #
XHTML = 'http://www.w3.org/1999/xhtml'


def doc(html):
    return etree.fromstring(html.encode('utf-8'))


class FakeSpineItem:
    def __init__(self, href, html):
        self.href = href
        self.data = doc(html)


class FakeMetaItem:
    def __init__(self, v):
        self._v = v

    def __str__(self):
        return self._v


class FakeMeta:
    def __init__(self, title, authors):
        self.title = [FakeMetaItem(title)]
        self.creator = [FakeMetaItem(a) for a in authors]


class FakeTocNode:
    def __init__(self, href, title):
        self.href = href
        self.title = title
        self._children = []

    def iter(self):
        yield self
        for c in self._children:
            for n in c.iter():
                yield n


class FakeToc(FakeTocNode):
    def __init__(self, nodes):
        self.href = None
        self.title = None
        self._children = nodes


class FakeOeb:
    def __init__(self, metadata, spine, toc):
        self.metadata = metadata
        self.spine = spine
        self.toc = toc


class Log:
    def __call__(self, *a):
        print('[log]', *a)

    def warn(self, *a):
        print('[warn]', *a)


class Opts:
    rsvp_include_author = True
    rsvp_one_chapter_per_file = True


chap1 = ('<html xmlns="%s"><head><title>Intro</title></head><body>'
         '<h1>Chapter One</h1>'
         '<p>Hello “world” — this is a fairly long paragraph that should '
         'definitely exceed ninety six characters so that the greedy word wrapping logic '
         'has to split it across multiple physical lines under one para marker.</p>'
         '<p>Second paragraph here.</p>'
         '<div><p>Nested paragraph should not be double counted.</p></div>'
         '</body></html>') % XHTML

chap2 = ('<html xmlns="%s"><head><title>T2</title></head><body>'
         '<h2>Chapter Two</h2>'
         '<p>@directive-looking line must be escaped.</p>'
         '</body></html>') % XHTML

oeb = FakeOeb(
    FakeMeta('My Book', ['Jane Doe']),
    [FakeSpineItem('c1.xhtml', chap1), FakeSpineItem('c2.xhtml', chap2)],
    FakeToc([FakeTocNode('c1.xhtml', 'The Beginning'),
             FakeTocNode('c2.xhtml#frag', 'The Middle')]),
)

out = os.path.join(tempfile.mkdtemp(), 'book.rsvp')
RSVPOutput = rsvp.RSVPOutput
plugin = RSVPOutput.__new__(RSVPOutput)  # bypass plugin __init__ machinery
plugin.convert(oeb, out, None, Opts(), Log())

with open(out, 'rb') as f:
    raw = f.read()
text = raw.decode('utf-8')
print('\n===== generated .rsvp =====')
print(text)
print('===========================')

lines = text.split('\n')
assert lines[0] == '@rsvp 1', lines[0]
assert lines[1] == '@title My Book', lines[1]
assert lines[2] == '@author Jane Doe', lines[2]
assert lines[3] == '', 'blank line after header'
# chapter titles come from TOC
assert '@chapter The Beginning' in lines
assert '@chapter The Middle' in lines
# first paragraph after a chapter has NO @para before it. Here the <h1>
# heading is itself a block, so it is the first paragraph (no @para).
beg = lines.index('@chapter The Beginning')
assert lines[beg + 1] != '@para' and lines[beg + 1] == 'Chapter One', lines[beg + 1]
# wrapped lines all within width
for ln in lines:
    if ln and not ln.startswith('@'):
        assert len(ln) <= rsvp.WRAP_WIDTH, (len(ln), ln)
# smart quotes + em dash normalized
assert '"world"' in text and '“' not in text
# escaping of @-leading body line
assert '@@directive-looking line must be escaped.' in text
# subsequent paragraph got @para
assert '@para' in text
# nested paragraph counted exactly once
assert text.count('Nested paragraph should not be double counted.') == 1
# ends with single trailing newline, no leading blank
assert text.endswith('\n') and not text.startswith('\n')
print('\nconvert() format checks: PASS')

# --- single-chapter mode ------------------------------------------------ #
class Opts2(Opts):
    rsvp_one_chapter_per_file = False

out2 = os.path.join(tempfile.mkdtemp(), 'book2.rsvp')
plugin.convert(oeb, out2, None, Opts2(), Log())
t2 = open(out2, encoding='utf-8').read()
assert t2.count('@chapter') == 1, t2.count('@chapter')
assert '@chapter My Book' in t2
print('single-chapter mode: PASS')

print('\nALL TESTS PASSED')
