"""Add overflow pages without reserializing any existing slide or shared asset."""
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from lxml import etree as E

P='http://schemas.openxmlformats.org/presentationml/2006/main'
A='http://schemas.openxmlformats.org/drawingml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
REL='http://schemas.openxmlformats.org/package/2006/relationships'
CT='http://schemas.openxmlformats.org/package/2006/content-types'

def overflow_entries(registry, bundle, fields):
    mappings={m.field_key:m for m in registry.mappings}
    groups=defaultdict(list)
    titles={p['project_code']:p['title_ar'] for p in bundle.get('projects',[])}
    for kind,items,index,text in [('achievement',bundle.get('achievements',[]),'slot_index','content_ar'),('task',[t for t in bundle.get('upcoming_tasks',[]) if t['task_kind']=='project_task'],'sequence_no','title_ar')]:
        for item in sorted(items,key=lambda x:(x['project_code'],x[index])):
            key=f"{kind}.{item['project_code']}.{item[index]}"
            m=mappings.get(key)
            if m and len(item[text]) <= m.validation.get('max_chars',100000):
                continue
            # An empty string clears a mapped placeholder instead of leaving stale template text.
            if m:
                fields[key]='التفاصيل في شريحة المتابعة'
            related=[x.slide_number for x in registry.mappings if x.field_key.startswith(f"{kind}.{item['project_code']}.")]
            anchor=min(related) if related else None
            groups[(anchor,item['project_code'],kind)].append((item[index],item[text]))
    return [(anchor,titles.get(code,code),kind,items) for (anchor,code,kind),items in groups.items()]

def _sub(parent,ns,tag,**attrs):
    return E.SubElement(parent,'{'+ns+'}'+tag,{k:str(v) for k,v in attrs.items()})

def _textbox(tree,ident,name,x,y,w,h,lines,size,color='243746',bold=False):
    sp=_sub(tree,P,'sp');nv=_sub(sp,P,'nvSpPr');_sub(nv,P,'cNvPr',id=ident,name=name);_sub(nv,P,'cNvSpPr',txBox=1);_sub(nv,P,'nvPr')
    props=_sub(sp,P,'spPr');xf=_sub(props,A,'xfrm');_sub(xf,A,'off',x=x,y=y);_sub(xf,A,'ext',cx=w,cy=h)
    geo=_sub(props,A,'prstGeom',prst='rect');_sub(geo,A,'avLst');_sub(props,A,'noFill');line=_sub(props,A,'ln');_sub(line,A,'noFill')
    body=_sub(sp,P,'txBody');bp=_sub(body,A,'bodyPr',wrap='square',anchor='t');_sub(bp,A,'normAutofit');_sub(body,A,'lstStyle')
    for text in lines:
        para=_sub(body,A,'p');pp=_sub(para,A,'pPr',algn='r',rtl=1);space=_sub(pp,A,'spcAft');_sub(space,A,'spcPts',val=900)
        run=_sub(para,A,'r');rp=_sub(run,A,'rPr',lang='ar-SA',sz=size,b=1 if bold else 0);fill=_sub(rp,A,'solidFill');_sub(fill,A,'srgbClr',val=color)
        for font in ('latin','ea','cs'):_sub(rp,A,font,typeface='29LT Azer')
        _sub(run,A,'t').text=text
    return sp

def _slide(width,height,title,kind,items,page):
    slide=E.Element('{'+P+'}sld',nsmap={'a':A,'r':R,'p':P},showMasterSp='0')
    cs=_sub(slide,P,'cSld');bg=_sub(cs,P,'bg');pr=_sub(bg,P,'bgPr');fill=_sub(pr,A,'solidFill');_sub(fill,A,'srgbClr',val='FFFFFF');_sub(pr,A,'effectLst')
    tree=_sub(cs,P,'spTree');nv=_sub(tree,P,'nvGrpSpPr');_sub(nv,P,'cNvPr',id=1,name='');_sub(nv,P,'cNvGrpSpPr');_sub(nv,P,'nvPr');gp=_sub(tree,P,'grpSpPr');xf=_sub(gp,A,'xfrm')
    for tag,attrs in [('off',{'x':0,'y':0}),('ext',{'cx':0,'cy':0}),('chOff',{'x':0,'y':0}),('chExt',{'cx':0,'cy':0})]:_sub(xf,A,tag,**attrs)
    margin=width//16
    _textbox(tree,2,'Continuation heading',margin,height//16,width-2*margin,height//6,[title+' — تابع'],2600,'007094',True)
    label='إنجازات الأسبوع الماضي' if kind=='achievement' else 'مهام الأسبوع القادم'
    _textbox(tree,3,'Section heading',margin,height//4,width-2*margin,height//10,[label],2100,'007094',True)
    _textbox(tree,4,'Additional entries',margin,height*36//100,width-2*margin,height*52//100,[f'{i}. {text}' for i,text in items],1800)
    _textbox(tree,5,'Page footer',margin,height*92//100,width-2*margin,height//16,[f'طموح | متابعة {page}'],1000,'637381')
    cm=_sub(slide,P,'clrMapOvr');_sub(cm,A,'masterClrMapping')
    return E.tostring(slide,xml_declaration=True,encoding='UTF-8',standalone=True)

def append_continuations(path,groups):
    if not groups:return 0
    path=Path(path)
    with zipfile.ZipFile(path) as z:
        infos=z.infolist();parts={i.filename:z.read(i.filename) for i in infos}
    pres=E.fromstring(parts['ppt/presentation.xml']);rels=E.fromstring(parts['ppt/_rels/presentation.xml.rels']);types=E.fromstring(parts['[Content_Types].xml'])
    ids=pres.find('{'+P+'}sldIdLst');original=list(ids);size=pres.find('{'+P+'}sldSz');width,height=int(size.get('cx')),int(size.get('cy'))
    slide_num=max(int(re.fullmatch(r'ppt/slides/slide(\d+)\.xml',n)[1]) for n in parts if re.fullmatch(r'ppt/slides/slide(\d+)\.xml',n))
    next_id=max(int(s.get('id')) for s in ids)+1
    rid=max([int(r.get('Id')[3:]) for r in rels if re.fullmatch(r'rId\d+',r.get('Id',''))]+[0])+1
    layout=next(n for n in parts if re.fullmatch(r'ppt/slideLayouts/slideLayout\d+\.xml',n))
    added={};count=0;tails={}
    for anchor,title,kind,items in groups:
        anchor=anchor or len(original)
        tail=tails.get(anchor,original[anchor-1])
        for offset in range(0,len(items),4):
            slide_num+=1;count+=1;name=f'ppt/slides/slide{slide_num}.xml'
            added[name]=_slide(width,height,title,kind,items[offset:offset+4],offset//4+1)
            sr=E.Element('{'+REL+'}Relationships',nsmap={None:REL});_sub(sr,REL,'Relationship',Id='rId1',Type=R+'/slideLayout',Target='../slideLayouts/'+Path(layout).name)
            added[f'ppt/slides/_rels/slide{slide_num}.xml.rels']=E.tostring(sr,xml_declaration=True,encoding='UTF-8',standalone=True)
            _sub(rels,REL,'Relationship',Id=f'rId{rid}',Type=R+'/slide',Target=f'slides/slide{slide_num}.xml')
            el=E.Element('{'+P+'}sldId',id=str(next_id));el.set('{'+R+'}id',f'rId{rid}');ids.insert(list(ids).index(tail)+1,el);tail=el
            _sub(types,CT,'Override',PartName='/'+name,ContentType='application/vnd.openxmlformats-officedocument.presentationml.slide+xml')
            rid+=1;next_id+=1
        tails[anchor]=tail
    for name,xml in [('ppt/presentation.xml',pres),('ppt/_rels/presentation.xml.rels',rels),('[Content_Types].xml',types)]:parts[name]=E.tostring(xml,xml_declaration=True,encoding='UTF-8',standalone=True)
    temp=path.with_suffix('.continued.tmp')
    with zipfile.ZipFile(temp,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for info in infos:z.writestr(info,parts[info.filename])
        for name,data in added.items():z.writestr(name,data)
    with zipfile.ZipFile(temp) as z:
        if z.testzip() is not None:raise ValueError('Invalid continuation package')
    temp.replace(path)
    return count
