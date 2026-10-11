import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {FileBlob,PresentationFile} from '@oai/artifact-tool';
import {fileURLToPath,pathToFileURL} from 'node:url';

const here=path.dirname(fileURLToPath(import.meta.url));
const repo=path.resolve(here,'../..');
const workspace=process.env.ZNAND_BUILD_DIR || path.join(repo,'work/placement_qd_presentation');
const source=path.join(here,'performance_key_items_abc_ko.pptx');
const build=workspace;
const out=process.env.ZNAND_PRESENTATION_OUT || path.join(workspace,'output');
const skill=process.env.PRESENTATIONS_SKILL;
const runtime=process.env.CODEX_RUNTIME_DEPENDENCIES;
if(!skill || !runtime) throw Error('Set PRESENTATIONS_SKILL and CODEX_RUNTIME_DEPENDENCIES; see docs/17_placement_qd_crosscheck_ko.md');
const {applyPresentationChartFont,finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')));
const exp=path.join(repo,'results/znand/placement_qd_crosscheck');
await fs.mkdir(build,{recursive:true});
const read=async p=>JSON.parse(await fs.readFile(p,'utf8'));
const ablation=await read(path.join(exp,'comparison.json'));
const cross=Object.fromEntries((await read(path.join(exp,'crosscheck/summary.json'))).map(r=>[r.name,r]));
const bHistory=await read(path.join(repo,'results/znand/b_sequential/rows.json'));
const p=await PresentationFile.importPptx(await FileBlob.load(source));
const snapshot=(await p.inspect({select:'$.slides[*]',include:['id','index','elements.id','elements.kind','elements.text']})).records;
const F='Apple SD Gothic Neo';
const C={ink:'#172738',muted:'#586875',blue:'#126DCA',teal:'#008B82',gray:'#9AA9B5',grid:'#DFE6EB',pale:'#F1F5F8',navy:'#122C40'};
const n=(x,d=2)=>Number(x).toFixed(d);
const gb=(pat,variant)=>cross[`${pat}_${pat==='B'?variant.replace('qd65536','q65536'):variant}`].gbps;
const base=pat=>ablation.find(r=>r.pattern===pat);
const newSources=[path.join(exp,'comparison.json'),path.join(exp,'crosscheck/summary.json'),path.join(exp,'crosscheck.py')];

function text(s,name,value,x,y,w,h,size=24,color=C.ink,bold=false){
 const t=s.shapes.add({geometry:'textbox',name,position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 t.text=value;t.text.style={typeface:F,fontSize:size,color,bold,autoFit:'none',wrap:'square',verticalAlignment:'top',insets:0};return t;
}
function clean(i,title,sub,foot){
 const snap=snapshot[i];const s=p.resolve(snap.id);p.delete(snap.elements.map(e=>e.id));
 decorate(s,title,sub,foot,i+1);return s;
}
function decorate(s,title,sub,foot,page){
 s.background.fill='#FFFFFF';text(s,'title',title,56,46,1168,66,44,C.ink,true);
 text(s,'subtitle',sub,58,116,1164,62,24,C.muted);
 text(s,'footer',foot,56,674,1100,27,16,C.muted);text(s,'page',String(page).padStart(2,'0'),1170,674,52,27,16,C.muted);
}
function append(title,sub,foot){const s=p.slides.add({layoutId:p.slides.getItem(0).layoutId});decorate(s,title,sub,foot,p.slides.items.length);return s;}
function table(s,name,values,x,y,w,h,widths,size=23){
 const t=s.tables.add({rows:values.length,columns:values[0].length,left:x,top:y,width:w,height:h,columnWidths:widths,values});t.name=name;
 t.borders.assign({fill:C.grid,width:1,style:'solid'});
 t.cells.block({row:0,column:0,rowCount:values.length,columnCount:values[0].length}).assign({fill:'#FFFFFF',textStyle:{typeface:F,fontSize:size,color:C.ink},margins:{left:12,right:12,top:8,bottom:8},anchor:'center'});
 for(let r=0;r<values.length;r++){t.rows[r].height=h/values.length;for(let c=0;c<values[0].length;c++){const cell=t.getCell(r,c);cell.text.style={typeface:F,fontSize:size,color:r===0?'#FFFFFF':C.ink,bold:r===0,verticalAlignment:'middle',insets:10};cell.fill=r===0?C.navy:r%2===0?C.pale:'#FFFFFF';}}
 return t;
}
function chart(s,type,cfg){const c=s.charts.add(type,{chartFill:'#FFFFFF',chartLine:{fill:'none',width:0},plotAreaFill:'#FFFFFF',plotAreaLine:{fill:'none',width:0},xAxis:{textStyle:{fontSize:22,fill:C.muted},line:{fill:C.grid,width:1}},yAxis:{min:0,max:280,majorUnit:70,numberFormatCode:'0',textStyle:{fontSize:20,fill:C.muted},majorGridlines:{fill:C.grid,width:1}},...cfg,series:cfg.series.map(r=>({...r,values:r.values.map(v=>Number(Number(v).toFixed(6)))}))});applyPresentationChartFont(c,{fontFamily:F});return c;}
function notes(s,body,extra=[]){s.speakerNotes.text=body+'\n\nSources\n'+[...newSources,...extra].join('\n');}
function replace(i,old,value){const e=snapshot[i].elements.find(e=>e.text===old);if(!e)throw Error('Missing text '+old);p.resolve(e.id).text=value;}

// Preserve the editable architecture and placement drawings in the source deck.
replace(0,'현재 A1: head_locality / A2: locality','FIFO에서도 A1 / A2 / B 최고 성능 유지');
replace(0,'우회 32회 · A1 선두대기 48.64µs · PF OFF','핵심: 영역별 배치와 Port별 충분한 요청');
replace(0,'QD / Port\n현재 512','QD / Port\nA: 512');
replace(0,'정책·우회·대기\nPF ON/OFF','FIFO 검증\nPF OFF');
replace(0,'모델 구조도    2026-10-11    대표 기준: 4 Port · 총 64 Plane · 8MiB · QD512/Port · PF OFF','교차 검증 기준: 총 64 Plane, 8MiB, PF OFF. A의 QD512, B의 QD32,768/Port');
const flow=p.resolve(snapshot[3].elements.find(e=>e.kind==='table').id);
flow.cells.set(3,2,'FIFO에서도 최고 성능\n우회 기능은 필수 아님');
replace(3,'성능 개선 핵심 3가지    2026-10-11    현재 대표 실행 기준: 총 64 Plane, PF OFF','현재 모델의 자원과 데이터 흐름. 총 64 Plane, PF OFF');
notes(p.slides.getItem(0),'FIFO는 locality 및 head 우선 CA 재정렬을 끈 기존 모델 옵션이다. 물리 주소 매핑, QD, tR와 Data 중재는 유지했다. B의 QD는 32768/Port이다.');

{
 const s=clean(4,'최대 처리량을 만드는 조건','현재 64 Plane 모델에서는 데이터 배치와 Port별 요청 공급이 핵심입니다.','동일 조건 대조 실험. 처리량은 200–2,200µs의 고정 2ms 평균');
 table(s,'summary',[
 ['항목','확인한 결과','해석'],
 ['Data placement',`A1 ${n(gb('A1','native_layout'))}에서 ${n(base('A1').fifo_gbps)}GB/s\nFIFO와 QD512 고정, 배치만 변경`,'Channel 분산과 Plane 내부\n물리 주소 연속성이 핵심'],
 ['Port별 요청 공급',`A1 QD2,048 유지\n수락 순환으로 ${n(gb('A1','qd2048_fixed'))}에서 ${n(gb('A1','qd2048_rr'))}GB/s`,'충분한 병렬 요청과\n공유 버퍼의 편중 방지'],
 ['CA 우회32 기능','A1 / A2 / B 모두 FIFO와 동일\n기준 실행의 실제 우회 0회','현재 배치의 최고 성능에\n우회 기능은 필수 아님']
 ],56,195,1168,344,[270,455,443],24);
 text(s,'summary-note','QD의 적정값은 요청 크기와 버퍼 수락 정책에 따라 달라집니다.',60,569,1160,42,28,C.blue,true);
 text(s,'scope','현재의 정적 배치와 네 Port의 독립 영역 읽기에서 확인한 결과입니다.',60,621,1160,34,23,C.muted);
 notes(s,'데이터 배치 단독 대조는 snapshot 제거 이외의 Config를 유지한다. QD2,048 순환 수락은 별도 진단 정책이며 제품 기능으로 검증한 것이 아니다. 물리 자원과 전체 페이지 활용도 역시 전제 조건이다.');
}
{
 const s=clean(5,'Data placement만 바꾼 대조 실험','CA는 FIFO, QD는 512/Port로 고정했습니다. 같은 64 Plane에서 배치만 비교합니다.','4 Port, 8MiB, PF OFF, 기존 tR 유지. 고정 2ms 평균');
 chart(s,'bar',{position:{left:56,top:218,width:710,height:358},categories:['A1 순차','A2 국소 순열'],series:[{name:'기존 배치',values:['A1','A2'].map(pat=>gb(pat,'native_layout')),fill:C.gray},{name:'영역별 Plane 배치',values:['A1','A2'].map(pat=>base(pat).fifo_gbps),fill:C.blue}],hasLegend:true,legend:{position:'bottom',textStyle:{fontSize:21,fill:C.muted}},barOptions:{direction:'column',grouping:'clustered',gapWidth:100},dataLabels:{showValue:true,position:'outEnd',numberFormatCode:'0.00',textStyle:{fontSize:23,fill:C.ink,bold:true}}});
 text(s,'axis-label','Host 처리량 (GB/s)',60,183,700,32,23,C.muted);
 text(s,'takeaway','균형 있는 요청 수만으로는 부족',800,207,420,72,28,C.blue,true);
 text(s,'explanation',`기존 배치의 A1도 Port별로\n약 509~510개를 유지했지만\n처리량은 ${n(gb('A1','native_layout'))}GB/s였습니다.\n\n영역별 Plane 분리가\n물리 주소 점프를 줄입니다.`,800,292,420,240,25);
 text(s,'placement-scope','변경 항목은 정적 L2P 배치뿐입니다. Channel 및 페이지 내 offset 규칙은 유지했습니다.',60,610,1160,44,23,C.muted);
 notes(s,'기존 배치는 model.Mapper의 기본 매핑(snapshot 없음)이다. 영역별 배치는 기존 saturation snapshot이다. 같은 주소 스트림/기간/요청 크기/채널 수/Plane 수/버퍼/QD/FIFO/tR를 사용했다. 동적 FTL 최적화나 임의 부하의 보편적 최적값이 아니다.');
}
{
 const s=clean(6,'CA 우회를 꺼도 최고 성능 유지','기존 우회32 설정과 FIFO를 비교했습니다. 다른 장치 조건은 모두 같습니다.','64 Plane, 8MiB, PF OFF. A1/A2 QD512, B QD32,768/Port');
 table(s,'bypass-ablation',[
 ['워크로드','기존 우회32 (GB/s)','FIFO (GB/s)','변화'],
 ...ablation.map(r=>[r.pattern==='B'?'B: 64B 페이지 전체 읽기':r.pattern,n(r.baseline_gbps,3),n(r.fifo_gbps,3),'0.000%'])
 ],56,197,1168,280,[350,305,305,208],25);
 text(s,'zero-bypass','기존 설정에서도 세 조건 모두 실제 우회는 0회였습니다.',60,517,1160,46,30,C.blue,true);
 text(s,'equality','시간대별 처리량과 완료 요청의 평균·p99 지연도 같았습니다.\n이 결론은 현재의 개선된 배치와 워크로드에 적용합니다.',60,579,1160,73,25);
 notes(s,'FIFO는 연속 주소 및 urgent-head CA 재정렬을 끈다. Busy Plane 회피와 발행 가능한 요청 중 선택은 유지한다. 원본 core 변경 없음. 6개 실행으로 기존 세 baseline 재현 및 FIFO 대조를 완료했다. p99는 측정창 안에서 완료한 요청의 accepted-to-last-data 지연이다. 과거 32Plane 혼합 배치에서의 locality 이득을 부정하는 결과는 아니다.');
}
replace(7,'2. 데이터 배치가 Long tR를 줄이는 원리','데이터 배치가 Long tR를 줄이는 원리');
replace(8,'3. 버퍼와 Port별 Outstanding의 공동 조정','고정 수락 순서에서의 QD와 버퍼 편중');
replace(8,'8MiB에서는 QD 512/Port가 4개 Port의 동시 진행을 유지했습니다.','4KiB 읽기와 Port 0부터 수락하는 현재 정책에서는 QD512/Port가 유효했습니다.');
replace(8,'QD가 너무 크면 앞선 Port가\n공유 버퍼를 먼저 예약합니다.\n다른 Port의 실제 outstanding이\n줄면서 병렬성이 무너집니다.','고정 수락 순서에서 큰 QD는\n앞선 Port의 버퍼 선점을 허용합니다.\n다른 Port의 실제 요청 수가 줄어\n처리량이 떨어질 수 있습니다.');
notes(p.slides.getItem(8),'이 그래프는 기존 saturation 전체 sweep이다. QD 증가의 보편적 성능 저하를 뜻하지 않는다. 고정 수락 순서와 공유 버퍼 예약 정책의 상호작용이다. 본 추가 실험에서 QD2,048 FIFO 성능을 재현했고 순환 수락을 별도 대조했다.',[path.join(repo,'results/znand/saturation/sweep.csv')]);
replace(9,'현재 확인된 실행 기준','4KiB 읽기의 버퍼와 QD 기준');
{
 const s=clean(10,'비교 조건과 적용 범위','배치, CA 정책, QD, 수락 순서를 각각 분리해 비교했습니다.','기존 원자료와 추가 대조 실험의 경로는 슬라이드 노트에 기록');
 table(s,'scope',[
 ['대조 항목','바꾼 요소','유지한 요소'],
 ['Data placement','기본 매핑 / 영역별 Plane 배치','FIFO, QD512, 64Plane, 8MiB'],
 ['CA 우회','기존 우회32 정책 / FIFO','배치, QD, 버퍼, tR'],
 ['큰 QD의 영향','QD512 / 2,048 또는 32,768 / 65,536','배치, FIFO, 8MiB'],
 ['Port별 수락 공정성','고정 시작 Port / 순환 시작 Port','QD 상한, FIFO, 배치, 버퍼']
 ],56,196,1168,300,[280,440,448],23);
 text(s,'timing','tR: Short 2.00µs, Mid 2.08µs, Long 12.16µs, First/Group 20.69µs',60,527,1160,40,25,C.blue,true);
 text(s,'limits','4 Port 지속 공급, 가용률 85%, PF OFF, Port 내부 in-order를 유지했습니다.\n실제 UCIe 경로, Die/LUN 공유 제약과 동적 L2P를 포함한 제품 실측은 아닙니다.',60,589,1160,68,23,C.muted);
 notes(s,'추가 실험은 2.2ms 중 초기 200us를 제외한 고정 2ms 평균이다. QD와 요청 메타데이터의 RTL 비용은 여전히 추상화되어 있다. 순환 수락은 인과 확인용 진단 구현이다.');
}
// Replace the stale "not yet measured" B cells while retaining the source table.
replace(12,'A·B·C의 유효 데이터량과 측정 상태','A·B·C의 유효 데이터량과 측정 결과');
const abc=p.resolve(snapshot[12].elements.find(e=>e.kind==='table').id);
abc.cells.set(5,2,'31.457 (QD512)\n255.335 (QD32,768)');
replace(12,'기존 측정: 64 Plane, 8MiB, QD512/Port, PF OFF, 200–2,200µs 고정 평균    새 B 정식 측정 전','64 Plane, 8MiB, PF OFF, 고정 2ms 평균. 각 셀에 표시한 QD 조건을 구분');
replace(12,'B는 한 페이지에 요청이 모입니다. QD를 조정하며 실제 NAND 병렬성과 재사용을 확인합니다.','B의 QD32,768 × 64B와 A의 QD512 × 4KiB는 모두 Port당 2MiB입니다.');
replace(12,'기존 약 4GB/s는 C1/C2 결과입니다. 새 B의 성능으로 재사용하지 않습니다.','C1/C2의 약4GB/s는 물리 페이지의 일부만 사용하는 조건의 결과입니다.');
notes(p.slides.getItem(12),'B의 QD512와 QD32768 결과를 업데이트했다. QD는 요청 수이고 AXI ID 수가 아니다. 2MiB는 요청 payload 상한이며 물리 버퍼 점유량/메타데이터와 동일하지 않다.',[path.join(repo,'results/znand/b_sequential/rows.json')]);

{
 const s=append('큰 QD의 성능 저하는 수락 편중과 연결','QD2,048을 유지하고, 마지막 수락 다음 Port부터 순환하도록 순서만 바꿨습니다.','새 진단 실험: A1/A2, FIFO, 64 Plane, 8MiB, QD2,048/Port, 고정 2ms 평균');
 table(s,'admission',[
 ['패턴 / 수락 방식','처리량 (GB/s)','Port 0 / 1 / 2 / 3 실제 outstanding 평균'],
 ...['A1','A2'].flatMap(pat=>['fixed','rr'].map(kind=>{const r=cross[`${pat}_qd2048_${kind}`];return [`${pat} / ${kind==='fixed'?'고정 시작':'순환 시작'}`,n(r.gbps,3),r.per_port_outstanding.map(v=>n(v,1)).join(' / ')];}))
 ],56,193,1168,315,[285,225,658],23);
 text(s,'causal','같은 큰 QD에서도 버퍼 편중을 줄이면 약255GB/s를 회복합니다.',60,543,1160,44,29,C.blue,true);
 text(s,'exact-balance','Port당 상한은 64GB/s이므로 네 Port가 모두 충분히 동작해야 합니다.\n각 Port에 쌓인 요청 수가 정확히 같을 필요는 없습니다.',60,601,1160,62,24);
 notes(s,'새 round-robin 진단은 수락 성공 이후 시작 Port를 갱신한다. 용량 검사, 병합, QD 상한, 조회, NAND 스케줄링, 응답 순서를 유지한다. QD512에서도 round-robin 대조를 실행했다. 실제 제품/혼합 부하의 공정성 보장으로 일반화하지 않는다.');
}
{
 const s=append('64B 요청의 QD는 별도로 조정','페이지 전체를 읽는 B는 A보다 요청 하나의 크기가 64배 작습니다.','B: 8MiB, 64 Plane, PF OFF. QD65,536은 이번 추가 실험');
 const hist=[512,2048,8192,16384,32768].map(q=>bHistory.find(r=>r.qd_per_port===q));
 table(s,'b-qd',[
 ['QD / Port','고정 수락 (GB/s)','순환 수락 (GB/s)'],
 ...hist.map(r=>[r.qd_per_port.toLocaleString('en-US'),n(r.fixed_gbps,3),'미측정']),
 ['65,536',n(gb('B','qd65536_fixed'),3),n(gb('B','qd65536_rr'),3)]
 ],56,191,730,375,[210,260,260],23);
 text(s,'b-note','요청 개수와 데이터량을\n함께 봐야 합니다.',831,200,389,82,29,C.blue,true);
 text(s,'b-payload',`QD512 × 64B = 32KiB\nQD32,768 × 64B = 2MiB\n\nA의 QD512도 2MiB입니다.\n\nQD65,536도 ${n(gb('B','qd65536_fixed'))}GB/s\n큰 QD의 낙폭은 보편적이지 않습니다.`,831,310,389,245,24);
 text(s,'b-scope','QD512~32,768은 기존 우회32 결과이며, QD32,768의 FIFO 동일성을 재검증했습니다.',60,593,1160,33,22,C.muted);
 text(s,'metadata','QD는 미완료 요청 수입니다. 요청 상태 메타데이터 비용은 8MiB 데이터 버퍼에 포함하지 않습니다.',60,634,1160,32,21,C.muted);
 notes(s,'B는 페이지 내부 64B 연속 읽기이며 C1/C2 희소 부분 읽기와 구분한다. 하이픈 표시는 미측정이다. QD65536 fixed/RR 비교에서는 CA가 FIFO로 동일하다.',[path.join(repo,'results/znand/b_sequential/rows.json')]);
}
{
 const s=append('설계 판단과 현재의 기준점','현재 결과는 Data placement 우선, 충분한 요청 공급과 버퍼 편중 방지를 지지합니다.','현재 모델의 정적 배치와 지속 읽기 결과. 모든 워크로드의 전역 최적값은 아님');
 table(s,'recommendations',[
 ['설계 항목','현재 근거에 따른 판단'],
 ['Data placement','각 영역이 4채널을 사용하고 Plane 내부 연속성을 유지하도록 배치'],
 ['CA 스케줄러','현재 최고 성능은 FIFO로 유지. 우회32를 필수 조건에서 제외'],
 ['고정 수락 정책의 QD','8MiB 기준 A는 512/Port, B는 32,768/Port에서 약255GB/s'],
 ['수락 공정성','큰 QD 자체보다 버퍼 예약 편중이 문제. 순환 수락 대조에서 회복'],
 ['최적화 목표','요청 수를 계속 늘리기보다 각 Port의 공급 부족과 편중을 함께 확인']
 ],56,194,1168,366,[290,878],24);
 text(s,'next-design','기준값은 요청 크기와 수락 정책이 바뀌면 다시 측정해야 합니다.',60,594,1160,48,28,C.blue,true);
 notes(s,'적정 QD는 모델/부하/버퍼/수락 정책에 종속된다. 정확한 Port별 동일 QD 또는 동일 실제 점유가 필수는 아니다. 고정 수락 기준점은 측정한 범위 중 조건부 권장이다. 데이터 활용률, 물리 Plane 공급량, Host와 NAND 전송 상한 역시 전제다.');
}

await fs.mkdir(out,{recursive:true});
await fs.writeFile(path.join(build,'after_inspection.ndjson'),(await p.inspect({select:'$.slides[*]',include:['id','index','title','elements.id','elements.kind','elements.text','notes.text']})).ndjson);
await fs.mkdir(path.join(build,'previews'),{recursive:true});
for(const [i,s] of p.slides.items.entries()){
 const png=await p.export({slide:s,format:'png',scale:1});await fs.writeFile(path.join(build,'previews',`slide-${i+1}.png`),new Uint8Array(await png.arrayBuffer()));
}
const draft=path.join(build,'candidate.pptx');await(await PresentationFile.exportPptx(p)).save(draft);
const repaired=path.join(build,'candidate-with-source-workbooks.pptx');
execFileSync(path.join(runtime,'python/bin/python3'),[path.join(here,'preserve_chart_workbooks.py'),source,draft,repaired],{stdio:'inherit'});
const final=path.join(out,'zNAND_Performance_Placement_QD_Update_ko.pptx');
await finalizePresentation({workspaceDir:workspace,candidatePath:repaired,finalPath:final,
 pythonExecutable:path.join(runtime,'python/bin/python3'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...[2,4,5,7,8,9,10,11,12,13,15,16,17].flatMap(i=>['--require-native-table-slide',String(i)])],
 explicitTotalSlideCount:17,requiredNativeTableOwnerSlides:[2,4,5,7,8,9,10,11,12,13,15,16,17],requiredNativeChartOwnerSlides:[6,9,14],
 materializeLiteralChartWorkbooks:true,
 fontPolicy:{basis:'reference',families:[F],referencePath:source,referenceSha256:crypto.createHash('sha256').update(await fs.readFile(source)).digest('hex')},
 verifyArtifactToolImport:true,receiptPath:path.join(build,'final.validation.json')});
console.log(final);
