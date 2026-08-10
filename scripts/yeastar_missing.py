import csv, sys, math
from collections import defaultdict
sys.path.insert(0,"/app"); sys.path.insert(0,"/app/data")
from app_factory import create_app
from generator.zabbix_client import ZabbixClient
import zabbix_coords as Z
app=create_app()
with app.app_context():
    c=ZabbixClient.from_environment()
    hs=c._jsonrpc("host.get",{"output":["host"]})
    ftth=[h["host"] for h in hs if h["host"].upper().startswith(("FTTH","FTHH"))]
    inv=defaultdict(set)
    for i,n in enumerate(ftth):
        for t in Z.toks(n,drop_prov=True): inv[t].add(i)
    N=max(1,len(ftth)); weight={t:math.log(N/len(s)) for t,s in inv.items()}
    htoks=sorted(inv.keys())
    def best(t):  # token match exacto o por prefijo (tolera acentos mangleados '?')
        if t in inv: return t, weight[t]
        if len(t)>=5:
            cs=[(h,weight[h]) for h in htoks if (h.startswith(t) or t.startswith(h)) and abs(len(h)-len(t))<=4]
            if cs: return max(cs,key=lambda x:x[1])
        return None,0.0
    def matched(name):
        ct=Z.toks(name,drop_prov=True)
        if not ct: return True
        nw=defaultdict(float); mw=defaultdict(float)
        for t in ct:
            h,w=best(t)
            if not h or w<=0: continue
            for i in inv[h]:
                nw[i]+=w
                if w>mw[i]: mw[i]=w
        if not nw: return False
        bi=max(nw,key=lambda i:nw[i])
        return nw[bi]>=4.0 and mw[bi]>=3.0
    rows=[r for r in csv.reader(open("/app/data/yeastar_fibras.csv"),delimiter="|") if len(r)>=5]
    miss=[(r[0],r[1],r[2],r[3],"SI" if r[4]=="t" else "NO") for r in rows if not matched(r[1])]
    w=csv.writer(open("/app/data/fibras_no_creadas.csv","w",newline=""))
    w.writerow(["cif","cliente","proveedor","n_fibra","tiene_backup"])
    for m in miss: w.writerow(m)
    cb=sum(1 for m in miss if m[4]=="SI")
    print(f"clientes con fibra activa en Yeastar: {len(rows)} | NO creados en Zabbix: {len(miss)} (con backup {cb} / sin backup {len(miss)-cb})")
    for m in miss: print("   "," | ".join(m))
