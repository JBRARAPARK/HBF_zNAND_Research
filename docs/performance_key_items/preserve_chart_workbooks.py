"""Restore unchanged source charts and their original embedded Excel data.

Artifact import/export retains values but drops workbook relationships. Copy
source chart XML and workbook bytes for the three unchanged charts. Refresh
the cached chart numbers from the original worksheet cells without changing
the workbook, formulas, referenced ranges or chart appearance.
The new placement chart remains a literal-data chart authored by Artifact Tool.
"""
from pathlib import Path
import posixpath
import sys
import io
import re
from zipfile import ZipFile,ZIP_DEFLATED
from lxml import etree

R='http://schemas.openxmlformats.org/package/2006/relationships'
O='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
C='http://schemas.openxmlformats.org/drawingml/2006/chart'
CT='http://schemas.openxmlformats.org/package/2006/content-types'
S='http://schemas.openxmlformats.org/spreadsheetml/2006/main'

def refresh_cache(chart_xml, workbook_bytes):
    from openpyxl.utils.cell import range_boundaries,get_column_letter
    with ZipFile(io.BytesIO(workbook_bytes)) as wb:
        book=etree.fromstring(wb.read('xl/workbook.xml'))
        rels={x.get('Id'):resolve('xl/workbook.xml',x.get('Target')) for x in etree.fromstring(wb.read('xl/_rels/workbook.xml.rels'))}
        sheets={x.get('name'):rels[x.get('{'+O+'}id')] for x in book.iter('{'+S+'}sheet')}
        strings=[]
        if 'xl/sharedStrings.xml' in wb.namelist():
            strings=[''.join(si.itertext()) for si in etree.fromstring(wb.read('xl/sharedStrings.xml'))]
        root=etree.fromstring(chart_xml)
        for ref in list(root.iter('{'+C+'}numRef'))+list(root.iter('{'+C+'}strRef')):
            formula=ref.find('{'+C+'}f').text
            sheet,cell_range=formula.rsplit('!',1);sheet=sheet.strip("'").replace("''", "'")
            cells={x.get('r'):x for x in etree.fromstring(wb.read(sheets[sheet])).iter('{'+S+'}c')}
            minc,minr,maxc,maxr=range_boundaries(cell_range)
            numeric=ref.tag.endswith('numRef');cache=ref.find('{'+C+('}numCache' if numeric else '}strCache'))
            for child in list(cache):
                if child.tag in ('{'+C+'}ptCount','{'+C+'}pt'):cache.remove(child)
            etree.SubElement(cache,'{'+C+'}ptCount',val=str((maxc-minc+1)*(maxr-minr+1)))
            index=0
            for row in range(minr,maxr+1):
                for col in range(minc,maxc+1):
                    cell=cells[get_column_letter(col)+str(row)]
                    value=cell.find('{'+S+'}v')
                    if cell.get('t')=='inlineStr':value=''.join(cell.find('{'+S+'}is').itertext())
                    elif cell.get('t')=='s':value=strings[int(value.text)]
                    else:value=value.text
                    pt=etree.SubElement(cache,'{'+C+'}pt',idx=str(index));etree.SubElement(pt,'{'+C+'}v').text=value;index+=1
        return etree.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True)

def relpath(part):return posixpath.join(posixpath.dirname(part),'_rels',posixpath.basename(part)+'.rels')
def resolve(part,target):return posixpath.normpath(posixpath.join(posixpath.dirname(part),target)).lstrip('/')
def charts(z,slide):
    part=f'ppt/slides/slide{slide}.xml'
    rels={r.get('Id'):resolve(part,r.get('Target')) for r in etree.fromstring(z.read(relpath(part)))}
    return [rels[c.get('{'+O+'}id')] for c in etree.fromstring(z.read(part)).iter('{'+C+'}chart')]

source,draft,destination=map(Path,sys.argv[1:])
with ZipFile(source) as src,ZipFile(draft) as old:
    data={n:old.read(n) for n in old.namelist()}
    restored=[]
    for slide in (9,14):
        before,after=charts(src,slide),charts(old,slide)
        assert len(before)==len(after)
        for idx,(old_chart,new_chart) in enumerate(zip(before,after),1):
            data[new_chart]=src.read(old_chart)
            relationships=etree.fromstring(src.read(relpath(old_chart)))
            for rel in relationships:
                assert rel.get('TargetMode')!='External'
                part=resolve(old_chart,rel.get('Target'))
                assert part.endswith('.xlsx')
                target=f'workbooks/source-slide{slide}-chart{idx}.xlsx'
                data[resolve(new_chart,target)]=src.read(part)
                data[new_chart]=refresh_cache(data[new_chart],src.read(part))
                rel.set('Target',target)
            data[relpath(new_chart)]=etree.tostring(relationships,xml_declaration=True,encoding='UTF-8',standalone=True)
            restored.append((slide,old_chart,new_chart))
    ct=etree.fromstring(data['[Content_Types].xml'])
    if not any(x.get('Extension')=='xlsx' for x in ct):
        etree.SubElement(ct,'{'+CT+'}Default',Extension='xlsx',ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    data['[Content_Types].xml']=etree.tostring(ct,xml_declaration=True,encoding='UTF-8',standalone=True)
    with ZipFile(destination,'w',ZIP_DEFLATED) as z:
        for n,b in data.items():z.writestr(n,b)
    print('Preserved original chart XML and workbook bytes:',restored)
