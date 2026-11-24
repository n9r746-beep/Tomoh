"""Build private slide editor backgrounds and geometry from the approved master.
Run at release time; the deployed app only serves the generated assets to section members.
"""
import json, zipfile, copy, subprocess
from pathlib import Path
from lxml import etree as E
NS={'p':'http://schemas.openxmlformats.org/presentationml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
root=Path('/vercel/source')
mapping=json.loads((root/'config/mapping_config.json').read_text())['mappings']
out=root/'app/slide_assets';out.mkdir(exist_ok=True)
z=zipfile.ZipFile('/vercel/master_template.pptx')
pres=E.fromstring(z.read('ppt/presentation.xml'));size=pres.find('p:sldSz',NS)
W,H=int(size.get('cx')),int(size.get('cy'))
def local_box(node):
 x=node.find('p:spPr/a:xfrm',NS)
 if x is None:x=node.find('p:xfrm',NS)
 if x is None:x=node.find('p:grpSpPr/a:xfrm',NS)
 if x is None:return None
 o=x.find('a:off',NS);e=x.find('a:ext',NS)
 if o is None or e is None:return None
 return [int(o.get('x')),int(o.get('y')),int(e.get('cx')),int(e.get('cy'))]
def box(node):
 b=local_box(node)
 if not b:return None
 for parent in node.iterancestors():
  if E.QName(parent).localname!='grpSp':continue
  t=parent.find('p:grpSpPr/a:xfrm',NS)
  o,e,c,d=(t.find('a:'+k,NS) for k in ['off','ext','chOff','chExt'])
  sx=int(e.get('cx'))/max(1,int(d.get('cx')));sy=int(e.get('cy'))/max(1,int(d.get('cy')))
  b=[int(o.get('x'))+(b[0]-int(c.get('x')))*sx,int(o.get('y'))+(b[1]-int(c.get('y')))*sy,b[2]*sx,b[3]*sy]
 return b
def empty(node):
 for t in node.findall('.//a:t',NS):t.text=''
def shape(sl,ident):
 for n in sl.xpath('.//p:sp|.//p:graphicFrame|.//p:pic',namespaces=NS):
  if n.xpath('.//p:cNvPr[@id=$id]',namespaces=NS,id=str(ident)):return n
 return None
manifest={'width':1600,'height':900,'slides':{}}
replaced={}
for sn in range(1,66):
 sl=E.fromstring(z.read(f'ppt/slides/slide{sn}.xml'))
 fields=[]
 for m in [m for m in mapping if m['slide_number']==sn]:
  n=shape(sl,m['object_id'])
  if n is None:continue
  b=box(n)
  if not b:continue
  target=n
  if m['object_type'] in ('table_cell','status_table_cell'):
   table=n.find('.//a:tbl',NS)
   rows=table.findall('a:tr',NS);cols=table.findall('a:tblGrid/a:gridCol',NS)
   ri,ci=m['row'],m['col'];tc=rows[ri].findall('a:tc',NS)[ci]
   totalw=sum(int(c.get('w')) for c in cols);totalh=sum(int(r.get('h')) for r in rows)
   b=[b[0]+b[2]*sum(int(c.get('w')) for c in cols[:ci])/totalw,b[1]+b[3]*sum(int(r.get('h')) for r in rows[:ri])/totalh,b[2]*int(cols[ci].get('w'))/totalw,b[3]*int(rows[ri].get('h'))/totalh]
   target=tc
  if m['object_type']=='table_rows':
   table=n.find('.//a:tbl',NS)
   for row in table.findall('a:tr',NS)[1:]:empty(row)
  elif m['object_type']=='image_replace':
   n.getparent().remove(n)
  else:empty(target)
  pt=target.find('.//a:rPr',NS)
  fs=float(pt.get('sz','1400'))/100 if pt is not None else 14
  fields.append({'key':m['field_key'],'kind':m['object_type'],'x':round(100*b[0]/W,4),'y':round(100*b[1]/H,4),'w':round(100*b[2]/W,4),'h':round(100*b[3]/H,4),'font':round(fs*1600/960,1)})
 manifest['slides'][str(sn)]={'number':sn,'fields':fields}
 replaced[f'ppt/slides/slide{sn}.xml']=E.tostring(sl,xml_declaration=True,encoding='UTF-8',standalone=True)
with zipfile.ZipFile('/vercel/blank_master.pptx','w',zipfile.ZIP_DEFLATED) as dest:
 for item in z.infolist():dest.writestr(item,replaced.get(item.filename,z.read(item.filename)))
(out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False))
print('geometry',sum(len(s['fields']) for s in manifest['slides'].values()),flush=True)
subprocess.run(['libreoffice','-env:UserInstallation=file:///vercel/lo-profile','--headless','--convert-to','pdf','--outdir','/vercel','/vercel/blank_master.pptx'],check=True,timeout=180)
# Render only slides used by the application's sections, including their section dividers.
import sqlite3
db=sqlite3.connect('/vercel/source/tomoh_local.db')
slides=set()
for row in db.execute('SELECT section_config_json FROM projects'):
 slides.update(json.loads(row[0] or '{}').get('slides',[]))
for sn in sorted(slides):
 subprocess.run(['pdftoppm','-f',str(sn),'-l',str(sn),'-scale-to-x','1600','-scale-to-y','900','-singlefile','-png','/vercel/blank_master.pdf',str(out/f'slide-{sn}')],check=True,timeout=45,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
manifest['slides']={k:v for k,v in manifest['slides'].items() if int(k) in slides}
(out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False))
print('rendered',sorted(slides),flush=True)
