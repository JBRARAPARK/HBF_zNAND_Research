"""Relabel saved presentation text and chart series; retain numerical evidence."""
import re
import sys
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree as ET


def current(text):
    if text == 'Workload A / B':
        return 'A / B / C'
    parts=re.split(r'(https?://\S+)',text)
    for i in range(0,len(parts),2):
        parts[i]=re.sub(r'(?<![A-Za-z0-9_])B([123])(?![A-Za-z0-9_])',r'C\1',parts[i])
        parts[i]=re.sub(r'(?<![A-Za-z0-9_])B(?=[^A-Za-z0-9_]|$)','C',parts[i])
    return ''.join(parts)


def relabel_xml(payload):
    tree=ET.fromstring(payload);changed=False
    for e in tree.iter():
        if e.text and ET.QName(e).localname in ('t','v','lpstr'):
            value=current(e.text)
            if value != e.text:e.text=value;changed=True
    return ET.tostring(tree,xml_declaration=True,encoding='UTF-8',standalone=True) if changed else payload


src,out=sys.argv[1:]
with ZipFile(src) as z:data={n:z.read(n) for n in z.namelist()}
for n,b in list(data.items()):
    if n.endswith('.xml'):data[n]=relabel_xml(b)
    elif n.endswith('.xlsx'):
        with ZipFile(BytesIO(b)) as x:parts={k:x.read(k) for k in x.namelist()}
        changed=False
        for k,v in list(parts.items()):
            if k.endswith('.xml'):
                parts[k]=relabel_xml(v);changed |= parts[k]!=v
        if changed:
            stream=BytesIO()
            with ZipFile(stream,'w',ZIP_DEFLATED) as x:
                for k,v in parts.items():x.writestr(k,v)
            data[n]=stream.getvalue()
with ZipFile(out,'w',ZIP_DEFLATED) as z:
    for n,b in data.items():z.writestr(n,b)
