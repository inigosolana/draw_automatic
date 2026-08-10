#!/usr/bin/env python3
"""Detecta hosts cuya coord está lejos del centro de su municipio (mar/error de
signo/coords intercambiadas) y los recoloca en el municipio (tierra). --apply escribe."""
import sys, math, argparse
sys.path.insert(0,"/app"); sys.path.insert(0,"/app/data")
from app_factory import create_app
from generator.zabbix_client import ZabbixClient
from generator.glpi_client import GlpiClient
import zabbix_coords as Z

def km(a,b):
    R=6371.0; la1,lo1,la2,lo2=map(math.radians,[a[0],a[1],b[0],b[1]])
    h=math.sin((la2-la1)/2)**2+math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2
    return 2*R*math.asin(math.sqrt(h))

ap=argparse.ArgumentParser(); ap.add_argument("--apply",action="store_true"); ap.add_argument("--thr",type=float,default=35.0)
a=ap.parse_args()
app=create_app()
with app.app_context():
    zc=ZabbixClient.from_environment()
    sites,inv,weight=Z.build_glpi_index(GlpiClient.from_environment().list_entities())
    geo=Z.Geocoder()
    hs=zc._jsonrpc("host.get",{"output":["hostid","host"],"selectHostGroups":["name"],
                               "selectInventory":["location_lat","location_lon"]})
    routers=[h for h in hs if h["host"].upper().startswith(("FTTH","FTHH","BACKUP","BACK_UP","LTE_"))]
    flagged=[]; nomuni=0
    for h in routers:
        iv=h.get("inventory") or {}
        la=str(iv.get("location_lat") or "").strip(); lo=str(iv.get("location_lon") or "").strip()
        if not(la and lo): continue
        try: cur=(float(la),float(lo))
        except: continue
        prov=Z.group_province(h.get("hostgroups",[]))
        site,_=Z.match_host(h["host"],prov,sites,inv,weight)
        if not site or not site["town"]: continue
        bias=Z.PROV_CENTROID.get(site["prov"]) or Z.PROV_CENTROID.get(prov)
        ml,mo,_=geo.resolve("",site["town"],site["state"] or prov,bias,cache_only=True)
        if not(ml and mo):
            ml,mo,_=geo.resolve("",site["town"],site["state"] or prov,bias)  # red si hace falta
        if not(ml and mo): nomuni+=1; continue
        muni=(float(ml),float(mo))
        d=km(cur,muni)
        if d>a.thr:
            flagged.append((h["hostid"],h["host"],cur,muni,d))
    flagged.sort(key=lambda x:-x[4])
    print(f"routers revisados con coord: analizados | municipio no resoluble: {nomuni}")
    print(f"LEJOS de su municipio (>{a.thr} km) = posible mar/error: {len(flagged)}")
    for hid,n,cur,muni,d in flagged[:40]:
        print(f"  {d:6.0f}km  {n[:52]:52} {cur} -> muni {tuple(round(x,4) for x in muni)}")
    if a.apply and flagged:
        ok=err=0
        for hid,n,cur,muni,d in flagged:
            try:
                zc._jsonrpc("host.update",{"hostid":hid,"inventory_mode":"1",
                    "inventory":{"location_lat":f"{muni[0]:.6f}","location_lon":f"{muni[1]:.6f}"}}); ok+=1
            except Exception as e: err+=1
        print(f"\nRECOLOCADOS en su municipio: {ok} (errores {err})")
    geo.save()
