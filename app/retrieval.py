import math
import re
import subprocess
from pathlib import Path
from .config import ROOT, SAG_COMMAND, SAG_JEV_URL, SAG_JEV_KEY

def tokenize(text: str) -> list[str]:
    lowered=text.lower()
    chinese=[c for c in lowered if '\u4e00'<=c<='\u9fff']
    grams=[chinese[i]+chinese[i+1] for i in range(len(chinese)-1)]
    words=re.findall(r'[a-z0-9]{2,}',lowered)
    return grams+words

def retrieve(query: str) -> str:
    try:
        import os
        env=os.environ.copy()
        if SAG_JEV_URL: env['SAG_JEV_URL']=SAG_JEV_URL
        if SAG_JEV_KEY: env['SAG_JEV_KEY']=SAG_JEV_KEY
        result=subprocess.run([SAG_COMMAND,query,'-m','5'],cwd=ROOT,text=True,capture_output=True,timeout=10,env=env)
        if result.returncode==0 and result.stdout.strip(): return result.stdout.strip()
    except (OSError,subprocess.TimeoutExpired):
        pass
    docs=[]
    for path in sorted((ROOT/'knowledge').glob('*.md')):
        parts=[p.strip() for p in path.read_text(encoding='utf-8').split('\n\n') if p.strip()]
        for part in parts:
            if part.startswith('#') and len(part.splitlines())==1: continue
            docs.append((path,part,tokenize(part)))
    terms=tokenize(query)
    if not terms or not docs:return '暂时无法连接知识检索服务，请稍后再试。'
    n=len(docs); avgdl=max(sum(len(tokens) for _,_,tokens in docs)/n,1)
    df={term:sum(1 for _,_,tokens in docs if term in tokens) for term in set(terms)}
    scored=[]
    for path,paragraph,tokens in docs:
        dl=len(tokens); score=0.0
        for term in terms:
            tf=tokens.count(term)
            if not tf: continue
            idf=math.log(1+(n-df[term]+0.5)/(df[term]+0.5))
            score+=idf*(tf*2.2)/(tf+1.2*(0.25+0.75*dl/avgdl))
        if score: scored.append((score,path,paragraph))
    if not scored:return '暂时无法连接知识检索服务，请稍后再试。'
    scored.sort(key=lambda row:row[0],reverse=True)
    score,path,paragraph=scored[0]
    return f'{paragraph}\n\n来源：{path.relative_to(ROOT)}'
