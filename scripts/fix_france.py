#!/usr/bin/env python3
"""Reverse-geocodifica los hosts de la franja fronteriza NE (Bidasoa) y recoloca
en su municipio español los que caen en Francia (country_code != es)."""
import sys,time,json,urllib.request,urllib.parse
sys.path.insert(0,"/app"); sys.path.insert(0,"/app/data")
from app_factory import create_app
from generator.zabbix_client import ZabbixClient
from generator.glpi_client import GlpiClient
import zabbix_coords as Z

def rev(lat,lon):
    u="https://nominatim.openstreetmap.org/reverse?"+urllib.parse.urlencode({"lat":lat,"lon":lon,"format":"json","zoom":"8","accept-language":"es"})
    r=urllib.request.Request(u,headers={"User-Agent":"ausarta-rev/1.0"})
    try:
        d=json.load(urllib.request.urlopen(r,timeout=15))
        return (d.get("address") or {}).get("country_code","")
    except Exception as e: return "ERR"

app=create_app()
with app.app_context():
    c=ZabbixClient.from_environment()
    sites,inv,weight=Z.build_glpi_index(GlpiClient.from_environment().list_entities())
    geo=Z.Geocoder()
    hs=c._jsonrpc("host.get",{"output":["hostid","host"],"selectInventory":["location_lat","location_lon"],"selectHostGroups":["name"]})
    ne=[]
    for h in hs:
        if not h["host"].upper().startswith(("FTTH","FTHH","BACKUP","BACK_UP","LTE_")): continue
        iv=h.get("inventory") or {}
        la=str(iv.get("location_lat") or "").strip(); lo=str(iv.get("location_lon") or "").strip()
        if not(la and lo): continue
        try: a=float(la); o=float(lo)
        except: continue
        if 43.25<=a<=43.60 and -1.95<=o<=-1.25: ne.append((h,a,o))
    print(f"franja NE: {len(ne)} hosts a reverse-checkear",flush=True)
    fr=0; fixed=0
    for h,a,o in ne:
        cc=rev(a,o); time.sleep(1.1)
        if cc=="es" or cc=="ERR": continue
        fr+=1
        prov=Z.group_province(h.get("hostgroups",[]))
        site,_=Z.match_host(h["host"],prov,sites,inv,weight)
        print(f"  FRANCIA({cc}) {h['host'][:50]} {a},{o}  town={site['town'] if site else '?'}",flush=True)
        if not site or not site["town"]: continue
        bias=Z.PROV_CENTROID.get(site["prov"]) or Z.PROV_CENTROID.get(prov)
        ml,mo,_=geo.resolve("",site["town"],site["state"] or prov,bias)
        if ml and mo:
            c._jsonrpc("host.update",{"hostid":h["hostid"],"inventory_mode":"1","inventory":{"location_lat":f"{float(ml):.6f}","location_lon":f"{float(mo):.6f}"}})
            fixed+=1; print(f"     -> recolocado en {site['town']} {ml},{mo}",flush=True)
    geo.save()
    print(f"\n== FRANCIA encontrados {fr} | recolocados {fixed} ==")
