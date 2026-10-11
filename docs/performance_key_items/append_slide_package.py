"""Append one authored slide and its dependencies, preserving saved source parts.

This is package assembly only. The editable chart/text is authored with artifact-tool.
Usage: python append_slide_package.py source.pptx one_slide.pptx output.pptx
"""
import copy
import posixpath as pp
import re
import sys
from io import BytesIO
from decimal import Decimal
from openpyxl.utils.cell import range_boundaries, get_column_letter
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree as ET

src, donor, out = sys.argv[1:]
P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PKG = 'http://schemas.openxmlformats.org/package/2006/relationships'
CT = 'http://schemas.openxmlformats.org/package/2006/content-types'
AP = 'http://schemas.openxmlformats.org/officeDocument/2006/extended-properties'
VT = 'http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes'
def xml(b): return ET.fromstring(b)
def serialized(x): return ET.tostring(x, xml_declaration=True, encoding='UTF-8', standalone=True)
def relpart(n): return pp.join(pp.dirname(n), '_rels', pp.basename(n) + '.rels')
def target(n, t): return pp.normpath(pp.join(pp.dirname(n), t)) if not t.startswith('/') else t[1:]

with ZipFile(src) as z: original = {n:z.read(n) for n in z.namelist()}
with ZipFile(donor) as z: other = {n:z.read(n) for n in z.namelist()}
data = dict(original)
pres = xml(data['ppt/presentation.xml'])
rels = xml(data['ppt/_rels/presentation.xml.rels'])
donor_pres = xml(other['ppt/presentation.xml'])
donor_rels = xml(other['ppt/_rels/presentation.xml.rels'])
assert len(donor_pres.find(f'{{{P}}}sldIdLst')) == 1
first_id = donor_pres.find(f'{{{P}}}sldIdLst')[0].get(f'{{{R}}}id')
slide_part = target('ppt/presentation.xml',next(r.get('Target') for r in donor_rels if r.get('Id') == first_id))
mapping = {}
for n in other:
 if re.fullmatch(r'ppt/notesMasters/notesMaster\d+\.xml', n):
  existing=next((k for k in original if re.fullmatch(r'ppt/notesMasters/notesMaster\d+\.xml',k)),None)
  if existing: mapping[n]=existing

reserved = set(data)
newmasters=[]
def allocate(n):
 directory,base=pp.split(n)
 stem,ext=pp.splitext(base)
 m=re.fullmatch(r'(.*?)(\d+)',stem)
 if m:
  prefix=m.group(1)
  indexes=[int(v.group(1)) for k in reserved if pp.dirname(k)==directory and (v:=re.fullmatch(re.escape(prefix)+r'(\d+)'+re.escape(ext),pp.basename(k)))]
  result=pp.join(directory,prefix+str(max(indexes,default=0)+1)+ext)
 else:
  result=pp.join(directory,'graph14_'+base)
  if result in reserved: raise ValueError(result)
 reserved.add(result)
 return result

layout_ids=[int(e.get('id')) for k,v in original.items() if re.fullmatch(r'ppt/slideMasters/slideMaster\d+\.xml',k) for e in xml(v).findall(f'.//{{{P}}}sldLayoutId')]
next_layout_id=max(layout_ids,default=2147483648)+1
def clone(n):
 global next_layout_id
 if n in mapping:return mapping[n]
 dest=allocate(n);mapping[n]=dest
 payload=other[n]
 if re.fullmatch(r'ppt/slideMasters/slideMaster\d+\.xml',n):
  master=xml(payload)
  for e in master.findall(f'.//{{{P}}}sldLayoutId'):
   e.set('id',str(next_layout_id));next_layout_id+=1
  payload=serialized(master);newmasters.append(dest)
 data[dest]=payload
 rp=relpart(n)
 if rp in other:
  rr=xml(other[rp])
  for r in rr:
   if r.get('TargetMode')=='External':continue
   resolved=target(n,r.get('Target'))
   r.set('Target',pp.relpath(clone(resolved),pp.dirname(dest)))
  data[relpart(dest)]=serialized(rr)
 return dest

appended=clone(slide_part)
# State straight interpolation explicitly for consumers that smooth scatter lines
# when the optional smooth element is absent. Preserve all measured points.
chart_ns='http://schemas.openxmlformats.org/drawingml/2006/chart'
for source_part,dest in mapping.items():
 if '/charts/' in source_part and source_part.endswith('.xml') and dest not in original:
  chart=xml(data[dest])
  for ser in chart.findall(f'.//{{{chart_ns}}}scatterChart/{{{chart_ns}}}ser'):
   sm=ser.find(f'{{{chart_ns}}}smooth')
   if sm is None:sm=ET.SubElement(ser,f'{{{chart_ns}}}smooth')
   sm.set('val','0')
  data[dest]=serialized(chart)
def new_rel(typ,part):
 ids={r.get('Id') for r in rels}
 i=1
 while 'rId'+str(i) in ids:i+=1
 rid='rId'+str(i)
 ET.SubElement(rels,f'{{{PKG}}}Relationship',Id=rid,Type=R+'/'+typ,Target=pp.relpath(part,'ppt'))
 return rid
slides=pres.find(f'{{{P}}}sldIdLst')
ET.SubElement(slides,f'{{{P}}}sldId',id=str(max(int(e.get('id')) for e in slides)+1),attrib={f'{{{R}}}id':new_rel('slide',appended)})
masters=pres.find(f'{{{P}}}sldMasterIdLst')
for master in newmasters:
 ET.SubElement(masters,f'{{{P}}}sldMasterId',id=str(max(int(e.get('id')) for e in masters)+1),attrib={f'{{{R}}}id':new_rel('slideMaster',master)})
data['ppt/presentation.xml']=serialized(pres)
data['ppt/_rels/presentation.xml.rels']=serialized(rels)

types=xml(data['[Content_Types].xml'])
known={e.get('PartName') for e in types if e.tag.endswith('Override')}
exts={e.get('Extension') for e in types if e.tag.endswith('Default')}
for e in xml(other['[Content_Types].xml']):
 if e.tag.endswith('Override') and e.get('PartName')[1:] in mapping:
  newname='/'+mapping[e.get('PartName')[1:]]
  if newname not in known:
   c=copy.deepcopy(e);c.set('PartName',newname);types.append(c);known.add(newname)
 elif e.tag.endswith('Default') and e.get('Extension') not in exts:
  types.append(copy.deepcopy(e));exts.add(e.get('Extension'))
data['[Content_Types].xml']=serialized(types)
if 'docProps/app.xml' in data:
 app=xml(data['docProps/app.xml'])
 for tag in ['Slides','Notes']:
  e=app.find(f'{{{AP}}}{tag}')
  if e is not None:e.text=str(len(slides))
 hp=app.find(f'{{{AP}}}HeadingPairs/{{{VT}}}vector')
 if hp is not None:
  for i,e in enumerate(hp):
   if e.find(f'{{{VT}}}lpstr') is not None and e.find(f'{{{VT}}}lpstr').text=='Slide Titles':
    hp[i+1][0].text=str(len(slides))
 titles=app.find(f'{{{AP}}}TitlesOfParts/{{{VT}}}vector')
 if titles is not None:
  ET.SubElement(titles,f'{{{VT}}}lpstr').text='시간별 성능과 A·B의 병목'
  titles.set('size',str(len(titles)))
 data['docProps/app.xml']=serialized(app)

allowed={'ppt/presentation.xml','ppt/_rels/presentation.xml.rels','[Content_Types].xml','docProps/app.xml'}
assert all(data[k]==v for k,v in original.items() if k not in allowed)

# PowerPoint serializes double-valued chart caches with extra binary-float digits.
# Refresh only numerically equivalent caches from their existing workbook cells.
# Keep the workbook, formulas, slide geometry and displayed values unchanged.
C='http://schemas.openxmlformats.org/drawingml/2006/chart'
X='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
repairs=[]
for part in original:
 if not re.fullmatch(r'ppt/charts/chart\d+\.xml',part):continue
 chart=xml(data[part]);rr=xml(data[relpart(part)])
 wbrel=next((r for r in rr if r.get('Type').endswith('/package')),None)
 if wbrel is None:continue
 with ZipFile(BytesIO(data[target(part,wbrel.get('Target'))])) as wb:
  book=xml(wb.read('xl/workbook.xml'))
  wr=xml(wb.read('xl/_rels/workbook.xml.rels'))
  sheets={}
  for sh in book.findall(f'{{{X}}}sheets/{{{X}}}sheet'):
   rel=next(r for r in wr if r.get('Id')==sh.get(f'{{{R}}}id'))
   sheet=xml(wb.read(target('xl/workbook.xml',rel.get('Target'))))
   sheets[sh.get('name')]={c.get('r'):c for c in sheet.findall(f'.//{{{X}}}c')}
  changed=False
  for ref in chart.findall(f'.//{{{C}}}numRef'):
   formula=ref.findtext(f'{{{C}}}f');name,ran=formula.rsplit('!',1)
   name=name.strip("'").replace("''", "'")
   c1,r1,c2,r2=range_boundaries(ran.replace('$',''))
   cells=[f'{get_column_letter(c)}{r}' for r in range(r1,r2+1) for c in range(c1,c2+1)]
   for pt in ref.findall(f'{{{C}}}numCache/{{{C}}}pt'):
    address=cells[int(pt.get('idx'))];cell=sheets[name][address]
    assert cell.find(f'{{{X}}}f') is None, 'Formula cells require explicit recalculation'
    raw=cell.findtext(f'{{{X}}}v');v=pt.find(f'{{{C}}}v')
    if v.text!=raw:
     assert abs(Decimal(v.text)-Decimal(raw))<Decimal('1e-10'), 'Substantive cache/workbook difference'
     repairs.append((part,address,v.text,raw));v.text=raw;changed=True
  if changed:data[part]=serialized(chart)
print(f'Normalized {len(repairs)} equivalent numeric cache strings; source workbook data unchanged')
with ZipFile(out,'w',ZIP_DEFLATED) as z:
 for n,b in data.items():z.writestr(n,b)
print(f'Appended {appended}; {len(slides)} slides; original slide/layout/workbook parts preserved, equivalent numeric caches refreshed')
