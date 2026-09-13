"""Árvore HTML mínima com stdlib: find por classe/tag, texto, parágrafos."""
from html.parser import HTMLParser
import re, html as _h
VOID={"br","img","input","meta","link","hr","source","wbr"}
class N:
    def __init__(s,tag,attrs,parent=None): s.tag=tag; s.attrs=dict(attrs); s.kids=[]; s.parent=parent
    def cls(s): return s.attrs.get("class","").split()
    def walk(s):
        for k in s.kids:
            yield k
            if isinstance(k,N): yield from k.walk()
    def find(s,tag=None,cls=None,pred=None):
        for k in s.walk():
            if isinstance(k,N) and (tag is None or k.tag==tag) and (cls is None or cls in k.cls()) and (pred is None or pred(k)): return k
    def findall(s,tag=None,cls=None):
        return [k for k in s.walk() if isinstance(k,N) and (tag is None or k.tag==tag) and (cls is None or cls in k.cls())]
    def text(s):
        out=[]
        for k in s.kids:
            if isinstance(k,str): out.append(k)
            elif k.tag=="br": out.append("\n")
            elif k.tag in("p","div","h1","h2","h3","h4","li"): out.append("\n"+k.text()+"\n")
            else: out.append(k.text())
        return "".join(out)
    def paras(s):
        return [clean(p.text()) for p in s.findall("p") if clean(p.text())]
def clean(t): return re.sub(r"[ \t]+"," ",re.sub(r"\n\s*\n+","\n",t)).strip()
class P(HTMLParser):
    def __init__(s): super().__init__(convert_charrefs=True); s.root=N("root",[]); s.cur=s.root
    def handle_starttag(s,tag,attrs):
        n=N(tag,attrs,s.cur); s.cur.kids.append(n)
        if tag not in VOID: s.cur=n
    def handle_startendtag(s,tag,attrs): s.cur.kids.append(N(tag,attrs,s.cur))
    def handle_endtag(s,tag):
        n=s.cur
        while n is not s.root and n.tag!=tag: n=n.parent
        if n is not s.root: s.cur=n.parent
    def handle_data(s,d):
        if s.cur.tag not in("script","style"): s.cur.kids.append(d)
def parse(src): p=P(); p.feed(src); return p.root
