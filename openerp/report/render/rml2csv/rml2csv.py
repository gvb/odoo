#!/usr/bin/env python
# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2009, P. Christeas, Tiny SPRL (<http://tiny.be>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

import sys
import StringIO
from lxml import etree

import utils

Font_size= 10.0

def verbose(text):
    sys.stderr.write(text+"\n")

class textbox(object):
    """A box containing plain text.
    It can have an offset, in chars.
    Lines can be either text strings, or textbox'es, recursively.
    Due to the simplistic limitations of CSV, recursive things get flattened.
    """
    def __init__(self, x=0, y=0):
        self.posx = x
        self.posy = y
        self.lines = []
        self.curline = ''
        self.intable = False
        self.endspace = False

    def newline(self):
        self.lines.append(self.curline)
        self.curline = ''

    def flushline(self):
        if len(self.curline):
            self.lines.append(self.curline)
        self.curline = ''

    def appendtxt(self, txt):
        """Append some text to the current line.
           Mimic the HTML behaviour, where all whitespace evaluates to
           a single space."""
        if not txt:
            return
        bs = es = False
        if txt[0].isspace():
            bs = True
        if txt[len(txt)-1].isspace():
            es = True
        if bs and not self.endspace:
            self.curline += " "
        self.curline += txt.strip().replace("\n"," ").replace("\t"," ")
        if es:
            self.curline += " "
        self.endspace = es

    def rendertxt(self, xoffset=0):
        return '\n'.join(self.lines)

class _flowable(object):
    def __init__(self, template, doc,localcontext):
        self._tags = {
            '1title': self._tag_title,
            '1spacer': self._tag_spacer,
            'para': self._tag_para,
            'font': self._tag_font,
            'section': self._tag_section,
            '1nextFrame': self._tag_next_frame,
            'blockTable': self._tag_table,
            '1pageBreak': self._tag_page_break,
            '1setNextTemplate': self._tag_next_template,
        }
        self.template = template
        self.doc = doc
        self.localcontext = localcontext
        self.nitags = []
        self.tbox = None

    def warn_nitag(self,tag):
        if tag not in self.nitags:
            verbose("Unknown tag \"%s\", please implement it." % tag)
            self.nitags.append(tag)

    def _tag_page_break(self, node):
        return "\n"

    def _tag_next_template(self, node):
        return ''

    def _tag_next_frame(self, node):
        return "\n"

    def _tag_title(self, node):
        """TODO: Probably broken"""
        return rec_render_cnodes(node)

    def _tag_spacer(self, node):
        length = 1 + int(utils.unit_get(node.get('length'))) / 35
        return "\n"*length

    def _tag_table(self, node):
        self.tb.newline()
        self.tb.intable = True
        for n in utils._child_get(node,self):
            if n.tag == 'tr':
                for m in utils._child_get(n,self):
                    if m.tag == 'td':
                        self.tb.appendtxt('"')
                        self.rec_render_cnodes(m)
                        self.tb.appendtxt('",')
                self.tb.newline()
        self.tb.intable = False
        return

    def _tag_para(self, node):
        # Ignored: styles
        self.rec_render_cnodes(node)
        if not self.tb.intable:
            self.tb.newline()

    def _tag_section(self, node):
        # Ignored: styles
        self.rec_render_cnodes(node)
        if not self.tb.intable:
            self.tb.newline()

    def _tag_font(self, node):
        """We ignore fonts."""
        self.rec_render_cnodes(node)

    def rec_render_cnodes(self,node):
        """Render child nodes."""
        self.tb.appendtxt(utils._process_text(self, node.text or ''))
        for n in utils._child_get(node,self):
            self.rec_render(n)
        self.tb.appendtxt(utils._process_text(self, node.tail or ''))

    def rec_render(self,node):
        """Recursive render: fill out lines array with text of current node."""
        if node.tag is not None:
            if node.tag in self._tags:
                self._tags[node.tag](node)
            else:
                self.warn_nitag(node.tag)

    def render(self, node):
        """Render a textbox."""
        self.tb = textbox()
        self.rec_render_cnodes(node)
        result = self.tb.rendertxt()
        del self.tb
        return result

class _rml_tmpl_tag(object):
    """Template tags are ignored."""
    def __init__(self, *args):
        pass
    def tag_start(self):
        return ''
    def tag_end(self):
        return False
    def tag_stop(self):
        return ''
    def tag_mergeable(self):
        return True

class _rml_tmpl_frame(_rml_tmpl_tag):
    """Template frames are ignored."""
    def __init__(self, posx, width):
        pass
    def tag_start(self):
        return ''
    def tag_end(self):
        return True
    def tag_stop(self):
        return ''
    def tag_mergeable(self):
        return False
    def merge(self, frame):
        """Merges are ignored."""
        pass

class _rml_tmpl_draw_string(_rml_tmpl_tag):
    def __init__(self, node, style):
        self.posx = utils.unit_get(node.get('x'))
        self.posy =  utils.unit_get(node.get('y'))
        aligns = {
            'drawString': 'left',
            'drawRightString': 'right',
            'drawCentredString': 'center'
        }
        align = aligns[node.localName]
        self.pos = [(self.posx, self.posy, align, utils.text_get(node), style.get('td'), style.font_size_get('td'))]

    def tag_start(self):
        return "draw string \"%s\" @(%d,%d)..\n" %("txt",self.posx,self.posy)

    def merge(self, ds):
        self.pos += ds.pos

class _rml_tmpl_draw_lines(_rml_tmpl_tag):
    def __init__(self, node, style):
        coord = [utils.unit_get(x) for x in utils.text_get(node).split(' ')]
        self.ok = False
        self.posx = coord[0]
        self.posy = coord[1]
        self.width = coord[2]-coord[0]
        self.ok = coord[1]==coord[3]
        self.style = style
        self.style = style.get('hr')

    def tag_start(self):
        return "draw lines..\n"

class _rml_stylesheet(object):
    def __init__(self, stylesheet, doc):
        self.doc = doc
        self.attrs = {}
        self._tags = {}
        self.result = ''

    def render(self):
        return ''

class _rml_draw_style(object):
    def __init__(self):
        self.style = {}
        self._styles = {}

    def update(self, node):
        pass

    def font_size_get(self,tag):
        return 12

    def get(self,tag):
        return ''

class _rml_template(object):
    def __init__(self, localcontext, out, node, doc, images=None, path='.', title=None):
        self.localcontext = localcontext
        self.frame_pos = -1
        self.frames = []
        self.template_order = []
        self.page_template = {}
        self.loop = 0
        self._tags = {
            'drawString': _rml_tmpl_draw_string,
            'drawRightString': _rml_tmpl_draw_string,
            'drawCentredString': _rml_tmpl_draw_string,
            'lines': _rml_tmpl_draw_lines
        }
        self.style = _rml_draw_style()
        for pt in node.findall('pageTemplate'):
            frames = {}
            id = pt.get('id')
            self.template_order.append(id)
            for tmpl in pt.findall('frame'):
                posy = int(utils.unit_get(tmpl.get('y1'))) #+utils.unit_get(tmpl.get('height')))
                posx = int(utils.unit_get(tmpl.get('x1')))
                frames[(posy,posx,tmpl.get('id'))] = _rml_tmpl_frame(posx, utils.unit_get(tmpl.get('width')))
            for tmpl in node.findall('pageGraphics'):
                for n in tmpl.getchildren():
                    if n.nodeType==n.ELEMENT_NODE:
                        if n.localName in self._tags:
                            t = self._tags[n.localName](n, self.style)
                            frames[(t.posy,t.posx,n.localName)] = t
                        else:
                            self.style.update(n)
            keys = frames.keys()
            keys.sort()
            keys.reverse()
            self.page_template[id] = []
            for key in range(len(keys)):
                if key > 0 and keys[key-1][0] == keys[key][0]:
                    if type(self.page_template[id][-1]) == type(frames[keys[key]]):
                        if self.page_template[id][-1].tag_mergeable():
                            self.page_template[id][-1].merge(frames[keys[key]])
                        continue
                self.page_template[id].append(frames[keys[key]])
        self.template = self.template_order[0]

    def _get_style(self):
        return self.style

    def set_next_template(self):
        self.template = self.template_order[(self.template_order.index(name)+1) % self.template_order]
        self.frame_pos = -1

    def set_template(self, name):
        self.template = name
        self.frame_pos = -1

    def frame_start(self):
        result = ''
        frames = self.page_template[self.template]
        ok = True
        while ok:
            self.frame_pos += 1
            if self.frame_pos>=len(frames):
                self.frame_pos=0
                self.loop=1
                ok = False
                continue
            f = frames[self.frame_pos]
            result+=f.tag_start()
            ok = not f.tag_end()
            if ok:
                result+=f.tag_stop()
        return result

    def frame_stop(self):
        frames = self.page_template[self.template]
        f = frames[self.frame_pos]
        result=f.tag_stop()
        return result

    def start(self):
        return ''

    def end(self):
        return ''

class _rml_doc(object):
    def __init__(self, node, localcontext=None, images=None, path='.', title=None):
        self.localcontext = {} if localcontext is None else localcontext
        self.etree = node
        self.filename = self.etree.get('filename')
        self.result = ''

    def render(self, out):
        #el = self.etree.findall('docinit')
        #if el:
            #self.docinit(el)

        #el = self.etree.findall('stylesheet')
        #self.styles = _rml_styles(el,self.localcontext)

        el = self.etree.findall('template')
        self.result =""
        if len(el):
            pt_obj = _rml_template(self.localcontext, out, el[0], self)
            stories = utils._child_get(self.etree, self, 'story')
            for story in stories:
                if self.result:
                    self.result += '\n'
                f = _flowable(pt_obj, story, self.localcontext)
                self.result += f.render(story)
                del f
        else:
            self.result = "<cannot render w/o template>"
        self.result += '\n'
        out.write(self.result)

def parseString(rml, localcontext=None, fout=None, images=None, path='.', title=None):
    node = etree.XML(rml)
    r = _rml_doc(node, localcontext, images, path, title=title)
    if fout:
        fp = file(fout,'wb')
        r.render(fp)
        fp.close()
        return fout
    else:
        fp = StringIO.StringIO()
        r.render(fp)
        return fp.getvalue()

def trml2csv_help():
    print 'Usage: rml2csv input.rml >output.html'
    print 'Render the standard input (RML) and output an TXT file'
    sys.exit(0)

if __name__=="__main__":
    if len(sys.argv)>1:
        if sys.argv[1]=='--help':
            trml2pdf_help()
        print parseString(file(sys.argv[1], 'r').read()).encode('iso8859-7')
    else:
        print 'Usage: trml2csv input.rml >output.pdf'
        print 'Try \'trml2csv --help\' for more information.'

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
