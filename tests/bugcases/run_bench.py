import re, subprocess, sys, os, glob
C=os.path.dirname(os.path.abspath(__file__)); TOOL=sys.argv[1] if len(sys.argv)>1 else os.path.join(C,'..','..','scripts','codemap.py'); TOOL=os.path.abspath(TOOL)
toks=lambda s: len(s)//4
def resolve(root, p):
    p=p.strip()
    if p.startswith("/rustc/") or p.startswith("node:") or "<" in p: return None
    for cand in (p, os.path.join(C,p), os.path.join(root,p)):
        if os.path.isfile(cand) and os.path.abspath(cand).startswith(root): return os.path.abspath(cand)
    base=os.path.basename(p)
    hits=[f for f in glob.glob(os.path.join(root,"**",base),recursive=True)]
    return hits[0] if hits else None
FR=[re.compile(r'File "([^"]+)", line (\d+)'),
    re.compile(r'\(([\w./$-]+\.(?:java|kt)):(\d+)\)'),
    re.compile(r'([\w./$-]+\.(?:php))\((\d+)\)'),
    re.compile(r'([\w./$-]+\.(?:js|ts|go|rb|rs|php|py)):(\d+)')]
def frames(text, root):
    out=[]
    for ln in text.splitlines():
        for pat in FR:
            m=pat.search(ln)
            if m:
                f=resolve(root,m.group(1))
                if f and (f,int(m.group(2))) not in out: out.append((f,int(m.group(2))))
                break
    return out
def window(fl,n):
    f,l=fl; lines=open(f).read().splitlines(); a=max(1,l-n); b=min(len(lines),l+n)
    return "\n".join(f"{i:4d} | {lines[i-1]}" for i in range(a,b+1))
def run(script, args, root, stdin=None):
    return subprocess.run([sys.executable,"-I",script]+args,capture_output=True,text=True,cwd=root).stdout
# (label, dir, kind, trace/query, bug string)
cases=[
 ("PY-1 deep trace, TypeError",         "py1","trace","py1.trace","_encoder(key + 1)"),
 ("PY-2 silent: sort order wrong",      "py2","find","sorted(","reverse=True"),
 ("PY-3 long fn, bug 15 lines above",   "py3","trace","py3.trace","end += 2"),
 ("PY-4 bug in CALLER (own line)",      "py4","trace","py4.trace",'+ "px"'),
 ("JS-1 Node TypeError, 7 frames",      "js","trace","js.trace","user.profile.name"),
 ("JS-2 lost this + node_modules",      "js2","trace","js2.trace","each(this.items, this.addPrice)"),
 ("JS-3 async chain",                   "js3","trace","js3.trace","row.name.trim()"),
 ("JS-4 silent: pagination, slice( x9", "js4","find","slice(","size - 1"),
 ("GO-1 panic, bug 4 lines above",      "go","trace","go.trace","len(chunks)-1"),
 ("GO-2 nil map, root cause NOT in trace","go2","trace","go2.trace","&Counter{name: name}"),
 ("JAVA-1 NPE (innermost first)",       "java1","trace","java1.trace","name.toUpperCase()"),
 ("RB-1 NoMethodError, bug in caller",  "rb1","trace","rb1.trace","key.to_sym"),
 ("PHP-1 DivisionByZero",               "php1","trace","php1.trace","intdiv($a, $b)"),
 ("RS-1 unwrap panic",                  "rs1","trace","rs1.trace","parse::<i32>().unwrap()"),
]
H=f"{'case':40} {'plain+-4':>11} {'plain+-8':>11} {'lazy-read':>11}"
print(H); tot={k:0 for k in "4 8 m".split()}; ok={k:0 for k in "4 8 m".split()}
for label,d,kind,src,bug in cases:
    root=os.path.join(C,d); norm=lambda s:s.replace(" ","")
    if kind=="trace":
        txt=open(os.path.join(C,src)).read(); fr=frames(txt,root)
        err="\n".join([l for l in txt.splitlines() if re.search(r'Error|panic|Exception|NoMethod',l)][:1])
        b=lambda n: err+"\n"+"\n".join(window(f,n) for f in fr)
        tf=os.path.join(C,src)
        m=run(TOOL,["trace",root,"--file",tf]+os.environ.get("XA","").split(),root)
    else:
        g=subprocess.run(["grep","-rn","--include=*.py","--include=*.js","-F",src,root],capture_output=True,text=True).stdout
        hits=[(x.split(":")[0],int(x.split(":")[1])) for x in g.splitlines() if x.split(":")[1].isdigit()]
        b=lambda n: g+"\n".join(window(h,n) for h in hits)
        m=run(TOOL,["find",root,src],root)
    cells=[b(4),b(8),m]
    row=[]
    for k,s in zip("4 8 m".split(),cells):
        p=norm(bug) in norm(s); tot[k]+=toks(s); ok[k]+=p; row.append(f"{toks(s):4d}t {'ok' if p else 'MISS'}")
    print(f"{label:40} "+" ".join(f"{c:>11}" for c in row))
    pass
print(f"TOTAL tokens/found  plain+-4: {tot['4']}/{ok['4']}  plain+-8: {tot['8']}/{ok['8']}  lazy-read: {tot['m']}/{ok['m']}  (of {len(cases)})")
