// Rebuild with the Codex bundled @oai/artifact-tool runtime.
// Copy this module to a private build directory with node_modules linked to that runtime.
// Usage: node build.mjs <repository-root> <new-output-directory>
import fs from 'node:fs/promises';
import path from 'node:path';
import { homedir } from 'node:os';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { Presentation, PresentationFile } from '@oai/artifact-tool';

const repo = path.resolve(process.argv[2]);
const out = path.resolve(process.argv[3]);
const build = path.join(repo, 'scratch/performance_key_items');
const skill = process.env.PRESENTATIONS_SKILL_DIR ?? path.join(homedir(), '.codex/plugins/cache/openai-primary-runtime/presentations/26.1007.11041/skills/presentations');
const python = process.env.PRESENTATIONS_RUNTIME_PYTHON ?? path.join(homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3');
process.env.RUNTIME_NODE_MODULES ??= path.join(homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const { applyPresentationChartFont, finalizePresentation } = await import(pathToFileURL(path.join(skill, 'container_tools/artifact_tool_utils.mjs')).href);
const e = JSON.parse(await fs.readFile(path.join(repo, 'docs/performance_key_items/evidence.json'), 'utf8'));
const F = 'Apple SD Gothic Neo';
const C = { bg:'#FFFFFF', ink:'#172738', muted:'#586875', blue:'#126DCA', teal:'#008B82', gray:'#9AA9B5', grid:'#DFE6EB', pale:'#F1F5F8', navy:'#122C40' };
const p = Presentation.create({slideSize:{width:1280,height:720}});
const num=(x,d=2)=>Number(x).toFixed(d);
const sat = n=>e.saturation[n];
const geom = n=>e.geometry_layout[n];
const sourceURL = rel=>`https://github.com/JBRARAPARK/HBF_zNAND_Research/blob/${e.source_commit}/${rel}`;
await fs.mkdir(out,{recursive:true});
await fs.mkdir(path.join(build,'previews'),{recursive:true});

function text(slide,name,value,x,y,w,h,size=24,color=C.ink,bold=false) {
  const s=slide.shapes.add({geometry:'textbox',name,position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
  s.text=value;
  s.text.style={typeface:F,fontSize:size,color,bold,autoFit:'none',wrap:'square',verticalAlignment:'top',insets:0};
  return s;
}
function base(title,subtitle,source) {
  const s=p.slides.add();s.background.fill=C.bg;
  text(s,'title',title,56,46,1168,66,44,C.ink,true);
  if(subtitle)text(s,'subtitle',subtitle,58,116,1164,60,24,C.muted);
  text(s,'footer',source,56,674,1100,27,16,C.muted);
  text(s,'page',String(p.slides.items.length).padStart(2,'0'),1170,674,52,27,16,C.muted);
  return s;
}
function notes(s,body,paths=[]) {
  s.speakerNotes.text=body+'\n\n출처\n'+paths.map(sourceURL).join('\n');
}
function table(s,name,values,x,y,w,h,widths,fontsize=24) {
  const t=s.tables.add({rows:values.length,columns:values[0].length,left:x,top:y,width:w,height:h,columnWidths:widths,values});
  t.name=name;
  t.borders.assign({fill:C.grid,width:1,style:'solid'});
  t.cells.block({row:0,column:0,rowCount:values.length,columnCount:values[0].length}).assign({
    fill:C.bg,textStyle:{typeface:F,fontSize:fontsize,color:C.ink},margins:{left:14,right:14,top:10,bottom:10},anchor:'center'
  });
  for(let r=0;r<values.length;r++) {
    t.rows[r].height=h/values.length;
    for(let c=0;c<values[0].length;c++) {
      const cell=t.getCell(r,c);
      cell.text.style={typeface:F,fontSize:fontsize,color:r===0?'#FFFFFF':C.ink,bold:r===0,verticalAlignment:'middle',insets:12};
      cell.fill=r===0?C.navy:(r%2===0?C.pale:C.bg);
    }
  }
  return t;
}
function chart(s,kind,config) {
  const ch=s.charts.add(kind,{
    chartFill:C.bg,chartLine:{fill:'none',width:0},plotAreaFill:C.bg,plotAreaLine:{fill:'none',width:0},
    xAxis:{textStyle:{fontSize:22,fill:C.muted},line:{fill:C.grid,width:1},majorGridlines:null},
    yAxis:{min:0,textStyle:{fontSize:20,fill:C.muted},majorGridlines:{fill:C.grid,width:1},numberFormatCode:'0'},
    ...config,
    // Six decimal places preserve measured precision while fitting Excel numeric cells.
    series:config.series.map(series=>({...series,values:series.values.map(v=>v===null?null:Number(Number(v).toFixed(6)))}))
  });
  applyPresentationChartFont(ch,{fontFamily:F});
  return ch;
}

// 1. Overall model structure replaces the original cover.
{
 const s=base('전체 구조와 데이터 흐름','4개의 독립 Port가 4채널 전체를 공유하며, 읽기 주소가 Channel과 Plane을 결정합니다.','성능 개선 핵심 3가지    2026-10-11    현재 대표 실행 기준: 총 64 Plane, PF OFF');
 table(s,'model-architecture',[
  ['처리 구간','주요 동작','자원과 순서 규칙'],
  ['1. Host IF','Port 0–3에서 독립적으로 읽기 요청','Port당 64GB/s\n합계 256GB/s'],
  ['2. Controller 수락','Port별 QD 확인, 공유 버퍼 예약\nL2P 조회로 물리 주소 확인','대표 설정: 8MiB\nQD 512/Port'],
  ['3. CA 스케줄링','발행 가능한 물리 페이지의 처리 순서 선택','연속 주소 우선\n필요 시 Port 선두 우선'],
  ['4. NAND Read','4채널 × 16Plane에서 sensing\n물리 페이지 크기는 16KiB','Plane당 page buffer 1개\n채널별 CA와 Data 경로'],
  ['5. Data와 반환','NAND 출력과 ECC 후 Controller buffer 준비\nPort별로 Host에 읽기 데이터 반환','Port 내부 in-order\n연결된 마지막 응답 후 버퍼 해제']
 ],56,184,1168,438,[228,564,376],23);
 text(s,'buffer-distinction','NAND page buffer는 Plane별 자원이며, Controller buffer는 여러 Port가 공유하는 임시 보관 공간입니다.',60,634,1160,30,22,C.muted);
 notes(s,'이 구조는 현재 시뮬레이터 기준이다. 4개 Port는 독립적인 요청/응답 주체로, 한 Port도 주소에 따라 모든 Channel을 사용할 수 있다. Port와 Channel을 고정 1:1로 연결하지 않는다. Host IF는 Port당 512bit, 1GHz로 64GB/s이며 합계256GB/s다. 요청 수락 시 QD와 버퍼 용량을 확인하고, 신규16KiB 물리 페이지 작업에 대한 공유 버퍼 공간을 예약한다. 동일 물리 페이지 요청은 기존 작업에 연결할 수 있다. Lookup 이후 물리 주소의 연속성과 Port 선두 대기를 고려해 CA를 발행한다. NAND는4채널, 채널당16Plane, Plane당page buffer1개다. NAND출력은16KiB 전체 페이지이며 ECC 후 Controller buffer의 데이터가 반환 가능해진다. Port별 FIFO 선두만 응답하며 연결된 마지막 응답이 끝나면 Controller buffer를 해제한다. 영구cache나LRU 정책은 적용하지 않았다. UCIe의 모든 프로토콜 계층을 상세 구현한 회로도가 아니라 본 평가 모델의 동작 구조다.',['znand/model.py','docs/12_controller_scheduling_ko.md','results/znand/saturation/RESULTS_KO.md']);
}

// 2. The three items
{
 const s=base('지금까지 효과를 확인한 3가지','발행 순서, 데이터 위치, 수락 가능한 요청의 분포를 각각 개선했습니다.','근거: locality, host_ceiling, saturation 실험 원자료');
 table(s,'three-items',[
  ['핵심 항목','해결한 병목','대표 처리량 (GB/s)'],
  ['1. 컨트롤러 스케줄링','물리 주소 점프로 인한\nLong tR의 반복','A2 37.08에서 118.26\n동일 조건의 CA 정책 비교'],
  ['2. Plane 확장과 배치','NAND 공급량 부족과\n같은 Plane의 영역 간 경합','64 Plane A2 189.32에서 234.99\n동일 자원에서 배치만 변경'],
  ['3. 버퍼와 QD의 공동 조정','요청 부족 또는 일부 Port의\n공유 버퍼 예약 편중','8MiB A1 68.86에서 255.37\nQD 2,048과 512/Port 비교']
 ],56,198,1168,346,[306,398,464],24);
 text(s,'measurement-caution','1·2번 수치는 유한 요청열의 전체 평균입니다.\n3번은 초기 구간을 제외한 지속 부하 평균이므로 개선율을 합산하지 않습니다.',60,577,1150,75,24,C.muted);
 notes(s,'세 항목 중 1번은 내부 스케줄러 변경, 2번은 물리 자원 확대와 L2P 배치 변경, 3번은 버퍼와 포트별 QD 설정의 조합이다. 3번 비교는 admission 알고리즘을 수정한 결과가 아니다. 1번은 PF ON, 32 Plane, 32MiB, QD2048, 16KiB stripe의 A2 case37. 2번은 PF OFF, 64 Plane, 32MiB, QD2048, A2의 snapshot만 변경한 쌍. 3번은 PF OFF, 64 Plane, 8MiB, 영역 배치 A1의 고정 2ms 평균이다.',['results/znand/locality/matched_comparison.csv','results/znand/host_ceiling/sweep.csv','results/znand/saturation/sweep.csv']);
}

// 3. Scheduling
{
 const l=e.locality;
 const s=base('1. 연속 물리 주소를 우선하는 스케줄링','tR 상수는 그대로 두고, Long tR이 발생하는 접근의 비율을 낮췄습니다.','조건: A2, 32 Plane, 32MiB, QD 2,048/Port, PF ON, 8,192요청/Port의 전체 평균');
 text(s,'chart-unit','Host 처리량 (GB/s)',62,185,620,33,22,C.muted);
 chart(s,'bar',{position:{left:56,top:223,width:620,height:280},categories:['기존 FIFO','연속 주소 우선'],series:[{name:'처리량',values:[+l.fifo_gbps,+l.locality_gbps],fill:C.blue,points:[{idx:0,fill:C.gray},{idx:1,fill:C.blue}]}],hasLegend:false,barOptions:{direction:'column',grouping:'clustered',gapWidth:120},yAxis:{min:0,max:140,majorUnit:35,textStyle:{fontSize:20,fill:C.muted},majorGridlines:{fill:C.grid,width:1}},dataLabels:{showValue:true,position:'outEnd',numberFormatCode:'0.00',textStyle:{fontSize:24,fill:C.ink,bold:true}}});
 table(s,'tr-mix',[['Long tR 비율','FIFO','연속 우선'],['전체 sensing 중',num(l.fifo_long_pct)+'%',num(l.locality_long_pct)+'%']],60,532,608,103,[228,190,190],23);
 text(s,'mechanism1','컨트롤러 CA 발행 단계에서 선택',722,192,500,48,28,C.blue,true);
 text(s,'mechanism1-detail','이미 발행 가능한 요청 중 같은 Plane의\n다음 물리 페이지를 먼저 읽습니다.\nShort 2.00µs 또는 Mid 2.08µs의\n접근을 더 많이 사용합니다.',722,252,500,156,24);
 text(s,'ordering','Host의 주소 발행 순서와\nPort 내부 in-order 반환은 유지합니다.',722,429,500,72,24);
 text(s,'bounded','우회 한도로 오래된 요청을 보호합니다.\nA1에는 오래 기다린 선두 요청의\n우선 처리도 적용했습니다.',722,542,500,102,24,C.muted);
 notes(s,`동일 조건의 CA 선택 정책만 비교한 case37. FIFO ${l.fifo_gbps} GB/s, locality ${l.locality_gbps} GB/s, 증가율 ${l.gain_pct}%. Long 비율 ${l.fifo_long_pct}%에서 ${l.locality_long_pct}%. locality에서는 같은 Group의 q+1만 연속 후보로 취급한다. 이미 busy인 Plane은 선점하지 않는다. 이 초기 비교의 bypass 한도는 8이다. 후속 실험은 32로 확대했다. A1에서 bypass32 locality 129.174 GB/s와 head_locality 134.339 GB/s를 비교한 추가 이득은 4.00%였으며, 그 전체 증가를 선두 우선 효과로 해석하지 않는다. A2는 선두 우선의 추가 효과가 작아서 locality를 유지했다. 과거 B 패턴에 선두 우선을 무조건 확대하면 성능이 떨어진 사례도 있다. 현재 B 지속 부하 실험은 A1과 조건을 맞춰 head_locality를 사용한다.`,['docs/12_controller_scheduling_ko.md','results/znand/locality/matched_comparison.csv','results/znand/head_locality/RESULTS_KO.md']);
}

// 4. Physical resources and measured placement benefit
{
 const b32=geom('A2_32Plane_baseline'),r32=geom('A2_32Plane_region_layout'),b64=geom('A2_64Plane_baseline'),r64=geom('A2_64Plane_region_layout');
 const s=base('2. 64 Plane과 영역별 데이터 배치','Plane 확장으로 공급 여력을 확보하고, 배치 개선으로 그 여력을 활용했습니다.','조건: A2, 4 Port, 32MiB, QD 2,048/Port, PF OFF, 8,192요청/Port의 전체 평균');
 text(s,'chart-unit','Host 처리량 (GB/s)',62,185,620,32,22,C.muted);
 chart(s,'bar',{position:{left:56,top:222,width:670,height:360},categories:['총 32 Plane','총 64 Plane'],series:[{name:'기존 배치',values:[+b32.bandwidth_gbps,+b64.bandwidth_gbps],fill:C.gray},{name:'영역 배치',values:[+r32.bandwidth_gbps,+r64.bandwidth_gbps],fill:C.blue}],hasLegend:true,legend:{position:'bottom',textStyle:{fontSize:22,fill:C.muted}},barOptions:{direction:'column',grouping:'clustered',gapWidth:95},yAxis:{min:0,max:280,majorUnit:70,textStyle:{fontSize:20,fill:C.muted},majorGridlines:{fill:C.grid,width:1}},dataLabels:{showValue:true,position:'outEnd',numberFormatCode:'0.00',textStyle:{fontSize:23,fill:C.ink,bold:true}}});
 text(s,'geometry','물리 자원 확대',775,193,438,44,28,C.blue,true);
 text(s,'geometry-detail','채널당 Plane을 8개에서 16개로\n늘렸습니다. 32 Plane의 공급량은\n가용률 100%와 최단 주기를 가정한\n낙관적 상한도 약 222.7GB/s입니다.',775,246,440,143,24);
 text(s,'layout','같은 64 Plane에서 배치 효과',775,421,438,44,28,C.blue,true);
 text(s,'layout-detail',`A2 처리량 ${num((+r64.bandwidth_gbps/+b64.bandwidth_gbps-1)*100)}% 증가\nLong sensing ${b64.count_tr_long}회에서 ${r64.count_tr_long}회\n총 sensing ${r64.count_sensing_reads}회 기준`,775,477,438,111,24);
 text(s,'separate-effects','Plane 증가는 자원 변경입니다. 같은 Plane 수 안의 두 막대가 배치만 바꾼 비교입니다.',60,619,1150,35,23,C.muted);
 notes(s,'32 Plane의 최단 주기 상한은 CA 0.1µs + Short tR 2µs + NAND Data/turnaround 0.254512µs로 계산한 낙관적 상한이다. 가용률 100%로 놓아도 약222.674GB/s이며 현재85%를 고려한 Short/Mid 교대 공급량은 약186.111GB/s다. 이 가용률을 실험 결과에서 다시 감산하면 안 된다. 32에서64 Plane으로 바꾸는 비교는 geometry 변경을 포함한다. 같은 geometry의 기존 배치와 영역 배치 쌍은 전체 config 중 snapshot만 다르다. 64 Plane A2 Long비율은1142/8196=13.93%에서3/8196=0.0366%이며 finite run 초기first sensing을 포함한다. 평균tR만 낮아졌으며 tR 상수는 바꾸지 않았다.',['results/znand/host_ceiling/sweep.csv','results/znand/host_ceiling/RESULTS_KO.md','results/znand/host_ceiling/timing_validation.json']);
}

// 5. Explicit mapping explanation, native table
{
 const s=base('2. 데이터 배치가 Long tR를 줄이는 원리','각 논리 영역은 4채널을 모두 쓰되, 채널 안에서 서로 다른 Plane 묶음을 사용합니다.','근거: host_ceiling의 영역별 L2P snapshot. 총 64 Plane 구성의 설명용 배치 표');
 table(s,'region-mapping',[
  ['논리 영역','Channel 0','Channel 1','Channel 2','Channel 3'],
  ['영역 0','Plane 0–3','Plane 0–3','Plane 0–3','Plane 0–3'],
  ['영역 1','Plane 4–7','Plane 4–7','Plane 4–7','Plane 4–7'],
  ['영역 2','Plane 8–11','Plane 8–11','Plane 8–11','Plane 8–11'],
  ['영역 3','Plane 12–15','Plane 12–15','Plane 12–15','Plane 12–15']
 ],56,200,1168,260,[232,234,234,234,234],24);
 text(s,'placement-why','한 Plane에 서로 먼 영역의 요청이 섞이면 물리 페이지 순서가 자주 끊깁니다.\n영역별 Plane 묶음을 분리하면 각 Plane에서 다음 페이지로 진행하기 쉬워집니다.',60,493,1150,85,25);
 text(s,'mapping-not-wiring','이 실험은 Port별로 다른 논리 영역을 읽습니다. Channel과 Plane 선택은 주소가 결정하며,\nPort를 특정 Channel에 고정하는 구조가 아닙니다.',60,592,1150,61,23,C.muted);
 notes(s,'표의 Plane 번호는 각 채널 내부 번호다. 동일하게 표시된 Plane 0은 채널별로 서로 다른 물리 자원이다. 영역 0은 채널당 Plane 0~3 등 4개 Plane을 사용하며, 4채널을 모두 활용한다. 비중첩 논리 영역을 각 Port가 읽는 합성 요청열에 맞춘 정적 L2P snapshot이다. 같은 물리 페이지의 offset 및 Channel 배치를 보존하고 Plane을 재배치한다. 64B 단위의 물리 분산이나 64B 단위 매핑을 추가하지 않았다. 동적 L2P와 편향 workload는 후속 검증이 필요하다.',['results/znand/host_ceiling/RESULTS_KO.md','results/znand/host_ceiling/snapshots/A2_64Plane.json']);
}

// 6. Buffer and QD
{
 const qds=[128,256,512,1024,2048];
 const s=base('3. 버퍼와 Port별 Outstanding의 공동 조정','8MiB에서는 QD 512/Port가 4개 Port의 동시 진행을 유지했습니다.','조건: 64 Plane, 영역 배치, PF OFF. 초기 200µs 제외 후 200–2,200µs 고정 평균');
 text(s,'chart-unit','8MiB 버퍼의 처리량 (GB/s)',60,181,690,32,22,C.muted);
 chart(s,'line',{position:{left:56,top:215,width:696,height:282},categories:qds.map(String),series:['A1','A2'].map((pat,i)=>({name:pat,values:qds.map(q=>+sat(`${pat}_b8_q${q}`).fixed_gbps),line:{fill:i?C.teal:C.blue,width:3},marker:{symbol:i?'diamond':'circle',size:8,fill:i?C.teal:C.blue}})),hasLegend:true,legend:{position:'bottom',textStyle:{fontSize:22,fill:C.muted}},xAxis:{title:{text:'설정 QD / Port',textStyle:{fontSize:20,fill:C.muted}},textStyle:{fontSize:20,fill:C.muted},line:{fill:C.grid,width:1}},yAxis:{min:0,max:275,majorUnit:55,textStyle:{fontSize:20,fill:C.muted},majorGridlines:{fill:C.grid,width:1}},lineOptions:{smooth:false}});
 text(s,'qd-effect','QD가 작으면 준비할 요청이 부족합니다.',795,191,427,73,26,C.blue,true);
 text(s,'qd-effect-2','QD가 너무 크면 앞선 Port가\n공유 버퍼를 먼저 예약합니다.\n다른 Port의 실제 outstanding이\n줄면서 병렬성이 무너집니다.',795,284,427,150,24);
 text(s,'actual-qd-caption','아래 표: 실제 outstanding 평균 (개)',795,466,427,34,21,C.muted);
 const pd=n=>JSON.parse(sat(n).fixed_actual_outstanding_per_port).map(v=>num(v,1));
 table(s,'actual-qd',[['A1 설정 QD/Port','Port 0 평균','Port 1 평균','Port 2 평균','Port 3 평균'],['512',...pd('A1_b8_q512')],['2,048',...pd('A1_b8_q2048')]],56,511,1168,132,[268,225,225,225,225],22);
 notes(s,'현재 admission은 Port 0, 1, 2, 3 순서이고, 요청 수락 시 공유 controller buffer를 예약한다. 버퍼와 Port별 QD 제한을 조합해 기존 admission의 편중을 줄인 결과다. 공정 중재 알고리즘을 구현한 결과는 아니다. 표는 설정 상한과 실제 평균 outstanding을 구분한다. A1 8MiB QD2048은 총 2029.55개, QD512는 총 2006.69개로 총합이 비슷해도 Port 분포가 다르다. A1 고정 평균은 68.857856에서 255.365922GB/s, A2는 71.888925에서 255.058330GB/s다. Actual outstanding은 수락된 AR에서 마지막 응답 완료 수를 뺀 값이며, Host 대기 요청은 포함하지 않는다. A1은 head_locality와 4KiB stripe, A2는 locality와 16KiB stripe를 사용한다.',['results/znand/saturation/sweep.csv','results/znand/saturation/RESULTS_KO.md']);
}

// 7. Current practical baseline
{
 const s=base('현재 확인된 실행 기준','8MiB와 QD 512/Port의 조합으로 A1/A2가 Host IF 256GB/s에 근접했습니다.','관측 범위: seed 7, 지속 부하 2.2ms. 아래 처리량은 초기 200µs를 제외한 고정 2ms 평균');
 table(s,'buffer-choices',[
  ['Controller buffer','QD / Port','A1 (GB/s)','A2 (GB/s)'],
  ['4MiB','256',num(sat('A1_b4_q256').fixed_gbps),num(sat('A2_b4_q256').fixed_gbps)],
  ['8MiB','512',num(sat('A1_b8_q512').fixed_gbps),num(sat('A2_b8_q512').fixed_gbps)],
  ['16MiB','512',num(sat('A1_b16_q512').fixed_gbps),num(sat('A2_b16_q512').fixed_gbps)]
 ],56,204,778,228,[274,164,170,170],24);
 text(s,'current-configuration','공통 조건',880,204,339,44,28,C.blue,true);
 text(s,'current-configuration-detail','4 Port, 4 Channel\n채널당 16 Plane\n영역별 L2P 배치\nPF OFF\nPort 내부 in-order',880,264,339,177,24);
 text(s,'buffer-choice-explanation','측정한 조합에서는 4MiB도 200GB/s를 넘었습니다.\n16MiB는 8MiB와 처리량이 비슷하므로, 현재 부하에서는 8MiB가 유효한 기준점입니다.',60,477,1154,86,25);
 text(s,'partial-read-limit','64B 부분 읽기 B1/B2는 같은 8MiB·QD512에서 약 4GB/s입니다.\n현재 모델의 전체 16KiB NAND 전송 중 유효 데이터가 256B여서, A의 수치를 그대로 적용할 수 없습니다.',60,578,1155,74,23,C.muted);
 notes(s,'이 표는 버퍼별 QD를 함께 선택한 결과다. 4MiB는 측정 조합 중 A1/A2가 모두 200GB/s를 넘긴 최소 용량이며, 모든 슬롯 수와 QD를 전수 탐색한 절대 하한은 아니다. 8MiB와 16MiB의 QD512 쌍은 같은 QD에서 버퍼를 비교할 수 있다. A1은 255.365922/255.371651, A2는 255.058330/255.211219GB/s다. 최고 500µs 값과 고정 2ms 값을 혼용하지 않는다. PF OFF이므로 Host 요청만으로 이 수치를 관측했다. Controller buffer는 16KiB 작업 단위로 예약하며 마지막 연결 응답 후 해제하는 임시 버퍼다. 지속적인 demand cache나 LRU를 새로 도입한 결과가 아니다. B1/B2는 연속된 64B 모두를 읽는 패턴이 아니고, 각 4KiB 논리 페이지의 64B만 읽는다. 16KiB 물리 페이지당 4개 64B, 즉 256B를 사용하므로 명목 효율은 1/64이다. 모델 내 NAND 부분 전송은 없다.',['results/znand/saturation/sweep.csv','results/znand/saturation/RESULTS_KO.md','results/znand/partial_saturation/RESULTS_KO.md']);
}

// 8. Measurement and bounds, traceable sources in notes
{
 const s=base('비교 조건과 적용 범위','각 실험 안의 전후 비교로 효과를 판단하고, 서로 다른 실험의 증가율은 합산하지 않습니다.','원자료 기준 커밋: '+e.source_commit.slice(0,7)+'    상세 경로와 설명은 슬라이드 노트 및 동봉 문서 참조');
 table(s,'comparison-contract',[
  ['자료의 비교','측정 방식','구분할 조건'],
  ['1. CA 스케줄링','8,192요청/Port의 전체 완료 평균','32 Plane, PF ON'],
  ['2. Plane과 배치','8,192요청/Port의 전체 완료 평균','32/64 Plane, PF OFF'],
  ['3. 버퍼와 QD','지속 공급 중 고정 2ms 평균','64 Plane, PF OFF, 종료 drain 제외']
 ],56,196,1168,228,[272,468,428],23);
 text(s,'tr-preserved','유지한 tR 입력값',60,460,1150,40,28,C.blue,true);
 text(s,'tr-values','Short 2.00µs    Mid 2.08µs    Long 12.16µs    First / Group 20.69µs',60,512,1150,40,24);
 text(s,'limits','가용률 85%와 Port 내부 순서 제약을 유지한 모델 결과입니다.\n다른 주소 편향, 동적 L2P, 실제 GC 및 Die/LUN 공유 자원은 별도 검증이 필요합니다.',60,579,1150,74,24,C.muted);
 notes(s,'증거 목록과 원문은 아래 고정 커밋 URL로 제공한다. 본 자료는 제품 실측 성능이나 HBF 사양의 공식 보장이 아니다. 모델은 4개의 독립 Port가 4채널 전체를 공유하며, Plane당 page buffer 1개와 물리 16KiB page를 사용한다. 가용률 85%는 100µs 주기의 명목 15µs Plane 휴지 구간으로 모델링했다. 실제 GC 쓰기/erase trace를 실행한 것은 아니다. 이전 maintenance OFF 실험은 B 패턴 낙폭 원인 확인을 위한 대조군이며, 성능 개선 기준으로 채택하지 않았다. Controller cache 및 64B 물리 분산도 채택하지 않았다. 후속 후보는 Port별 수락의 공정성, 주소 편향 및 동적 매핑에서의 재현성 검증이다. 이번 정리는 기존 결과만 사용했으며 성능 엔진이나 입력 tR을 수정하지 않았다.',['results/znand/locality/matched_comparison.csv','results/znand/host_ceiling/sweep.csv','results/znand/host_ceiling/timing_validation.json','results/znand/saturation/sweep.csv','results/znand/saturation/RESULTS_KO.md','results/znand/partial_dips/RESULTS_KO.md','docs/07_prefetch_tuning_ko.md']);
}

// 9. Logical workload definitions.
{
 const s=base('A·B 워크로드의 요청 크기와 접근 순서','아래 P1, P2는 각각 4KiB 논리 페이지입니다. NAND의 16KiB 물리 페이지와 구분합니다.','근거: model.py의 workload(), A/B 지속 부하 생성기. A2/B2는 3개 단위의 국소 순열');
 table(s,'workload-patterns',[
  ['패턴','요청당 반환','논리 페이지 접근 순서','패턴의 의미'],
  ['A1','4KiB','P1, P2, P3, P4, …','각 논리 페이지 전체를 순서대로 읽음'],
  ['A2','4KiB','P1, P3, P2, P4, P6, P5, …','3개씩 순서를 바꿔 페이지 전체를 읽음'],
  ['B1','64B','P1, P2, P3, P4, …','각 페이지의 시작 64B만 읽음'],
  ['B2','64B','P1, P3, P2, P4, P6, P5, …','B1과 크기는 같고 접근 순서만 바꿈'],
  ['B3','64B','P1, P3, P1(재방문), P2, …','P1 재방문 시 offset +64B를 읽음']
 ],56,191,1168,364,[105,165,465,433],23);
 text(s,'logical-not-physical','B3의 재방문은 같은 논리 페이지의 다른 데이터를 읽습니다.\n논리 페이지의 접근 순서와 실제 Channel·Plane·물리 페이지는 L2P 배치를 거쳐 연결됩니다.',60,579,1160,63,24);
 notes(s,'A1은 요청마다 다음 4KiB 논리 페이지를 읽고, A2는 3개 묶음의 0,2,1 순열을 반복한다. 예시의 페이지 번호는 1부터 표시했다. A2/B2는 전체 주소 영역의 균등 난수 접근이 아니다. B1/B2는 각 페이지의 offset 0에서 64B만 반환한다. B3는 3개 논리 페이지 묶음에서 0,2,0,1 순서로 읽고 세 번째 요청에만 offset 64를 적용한다. 그러므로 P1의 첫 64B와 재방문의 두 번째 64B는 다른 데이터지만 동일 논리 페이지에 속하며, 동일 물리 페이지로 매핑될 수 있다. NAND page buffer 또는 Controller buffer에서 재사용할 수 있는지는 그 시점의 상태에 따른다. 항상 hit이나 항상 새 tR을 가정하지 않는다. B3는 기존 유한 요청열 모델에 구현되어 있으나 최근 64 Plane의 2ms 지속 부하 비교에는 포함하지 않았다.',['znand/model.py','znand/saturation.py','znand/partial_saturation.py']);
}

// 10. Useful bytes and measured A/B performance.
{
 const b1=e.partial_saturation.B1_b8_q512,b2=e.partial_saturation.B2_b8_q512;
 const s=base('A·B의 유효 데이터량과 처리량','현재 모델은 64B 요청에도 NAND에서 물리 페이지 전체 16KiB를 출력합니다.','조건: 64 Plane, 영역 배치, 8MiB, QD512/Port, PF OFF. 200–2,200µs 고정 평균');
 table(s,'workload-byte-efficiency',[
  ['비교 항목','A1 / A2','B1 / B2'],
  ['Host 요청당 반환량','4KiB','64B'],
  ['물리 16KiB당 유효 데이터','4 × 4KiB = 16KiB','4 × 64B = 256B'],
  ['명목 유효 데이터 비율','100%','1/64 = 1.5625%'],
  ['Host 처리량 (GB/s)',`A1 ${num(sat('A1_b8_q512').fixed_gbps,3)} / A2 ${num(sat('A2_b8_q512').fixed_gbps,3)}`,`B1 ${num(b1.fixed_gbps,3)} / B2 ${num(b2.fixed_gbps,3)}`]
 ],56,189,1168,300,[345,410,413],24);
 text(s,'partial-read-meaning','B1/B2는 한 페이지 안의 64B를 모두 이어 읽는 부하가 아닙니다.\nB의 내부 NAND 전송은 약 257GB/s지만, Host가 사용하는 데이터는 그 일부입니다.',60,516,1158,74,24);
 text(s,'comparison-limits','A1/B1은 매핑과 장치 설정이 같습니다. A2/B2는 stripe와 CA 정책이 다릅니다.\nB3는 패턴 정의만 포함했으며, 이번 64 Plane 지속 부하의 성능 수치는 없습니다.',60,609,1158,56,22,C.muted);
 notes(s,'A1/A2의 16KiB당 유효 데이터는 4개의 4KiB 논리 요청 전체다. B1/B2는 각 4KiB 논리 페이지의 처음 64B만 읽으므로, 같은 물리 페이지의 4개 논리 영역을 다 사용해도 256B다. 명목 효율은 1/64이며, 실제 구간에서 반환한 Host 바이트와 완료한 NAND 전송량은 구간 경계 및 버퍼 체류 때문에 정확히 64배로 맞지 않을 수 있다. B1의 NAND 처리량은 256.778240GB/s, B2는 256.991232GB/s다. 8MiB와 QD512에서 A1/B1은 같은 4KiB stripe와 head_locality 프로파일 및 동일 매핑을 사용한다. A2는 16KiB stripe/locality, B2는 4KiB stripe/head_locality라 크기만의 효과를 분리한 쌍이 아니다. 작은 요청에 필요 없는 바이트를 더 반환하면 유효 성능이 자동으로 늘어나는 것은 아니다. 같은 물리 페이지에서 실제로 소비하는 데이터량과 재사용률이 중요하다. B3의 이전 32 Plane 유한 요청열 결과를 현재 64 Plane 지속 부하 표에 혼합하지 않았다.',['results/znand/saturation/sweep.csv','results/znand/partial_saturation/sweep.csv','results/znand/partial_saturation/RESULTS_KO.md','results/znand/partial_saturation/reference_validation.json']);
}

for(let i=0;i<p.slides.items.length;i++) {
  const s=p.slides.items[i], stem=`slide-${String(i+1).padStart(2,'0')}`;
  await fs.writeFile(path.join(build,'previews',stem+'.png'),new Uint8Array(await (await p.export({slide:s,format:'png',scale:1.5})).arrayBuffer()));
  await fs.writeFile(path.join(build,'previews',stem+'.layout.json'),await (await s.export({format:'layout'})).text());
}
const candidate=path.join(build,'candidate.pptx');
await (await PresentationFile.exportPptx(p)).save(candidate);
const finalPath=path.join(out,'performance_key_items_ko.pptx');
const result=await finalizePresentation({
  workspaceDir:repo,candidatePath:candidate,finalPath,pythonExecutable:python,
  integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),
  layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
  layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...[1,2,3,5,6,7,8,9,10].flatMap(n=>['--require-native-table-slide',String(n)])],
  requiredNativeTableOwnerSlides:[1,2,3,5,6,7,8,9,10],requiredNativeChartOwnerSlides:[3,4,6],
  materializeLiteralChartWorkbooks:true,
  fontPolicy:{basis:'design',families:[F],scriptFonts:{ea:F}},
  verifyArtifactToolImport:true,receiptPath:path.join(build,path.basename(out)+'.validation.json')
});
// Convert the validated deck using the bundled office runtime.
// This preserves editable chart/text rendering and avoids the runtime PDF font resolver.
const soffice = process.env.PRESENTATIONS_SOFFICE ?? path.join(homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override/soffice');
const fontCache = path.join(build, 'font-cache');
await fs.mkdir(fontCache, {recursive:true});
const xmlEscape = value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const bundledFonts = path.join(homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/native/libreoffice-headless/libreoffice/LibreOfficeDev.app/Contents/Resources/fonts/truetype');
const fontConfig = path.join(build, 'fonts.conf');
await fs.writeFile(fontConfig, '<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig><dir>/System/Library/Fonts</dir><dir>'+xmlEscape(bundledFonts)+'</dir><cachedir>'+xmlEscape(fontCache)+'</cachedir></fontconfig>');
execFileSync(soffice, ['--headless', '-env:UserInstallation='+pathToFileURL(path.join(build,'lo-profile')).href, '--convert-to', 'pdf', '--outdir', out, finalPath], {stdio:'pipe', timeout:60000, env:{...process.env,FONTCONFIG_FILE:fontConfig}});
await fs.access(path.join(out,'performance_key_items_ko.pdf'));
console.log(JSON.stringify({slides:p.slides.items.length,pptx:finalPath,pdf:path.join(out,'performance_key_items_ko.pdf'),validation:result},null,2));
