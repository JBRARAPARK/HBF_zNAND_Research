// Append an editable performance graph without rewriting the saved source slides.
// Run a copy of this module in a private build directory linked to the bundled node_modules.
// Usage: node append_graph.mjs <repository-root> <new-output-directory>
import fs from 'node:fs/promises';
import path from 'node:path';
import { homedir } from 'node:os';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
import { Presentation, PresentationFile, FileBlob } from '@oai/artifact-tool';

const repo=path.resolve(process.argv[2]), out=path.resolve(process.argv[3]);
const build=path.join(repo,'scratch/performance_key_items/graph-v14');
const deps=path.join(homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies');
const skill=path.join(homedir(),'.codex/plugins/cache/openai-primary-runtime/presentations/26.1007.11041/skills/presentations');
const python=path.join(deps,'python/bin/python3');
process.env.RUNTIME_NODE_MODULES ??= path.join(deps,'node/node_modules');
const {applyPresentationChartFont,finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const src=path.join(repo,'docs/performance_key_items/performance_key_items_with_diagram_ko.pptx');
const evidence=JSON.parse(await fs.readFile(path.join(repo,'docs/performance_key_items/graph_evidence.json'),'utf8'));
await fs.mkdir(out,{recursive:true});
await fs.mkdir(build,{recursive:true});

// Read the actual saved source. Package assembly below preserves its bytes.
const original=await PresentationFile.importPptx(await FileBlob.load(src));
await fs.writeFile(path.join(build,'source-inspection.ndjson'),(await original.inspect({select:'$.slides[*]',include:['id','index','title','layout']})).ndjson);
if(original.slides.items.length!==13) throw new Error('Expected the saved 13-slide source deck');
const p=Presentation.create({slideSize:{width:1280,height:720}}),s=p.slides.add();
const F='Apple SD Gothic Neo', C={ink:'#172738',muted:'#586875',blue:'#126DCA',teal:'#008B82',grid:'#DFE6EB'};
s.background.fill='#FFFFFF';
function txt(name,value,x,y,w,h,size=24,color=C.ink,bold=false){
 const t=s.shapes.add({geometry:'textbox',name,position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 t.text=value;t.text.style={typeface:F,fontSize:size,color,bold,autoFit:'none',wrap:'square',verticalAlignment:'top',insets:0};return t;
}
txt('title','시간별 성능과 A·B의 병목',56,46,1168,66,44,C.ink,true);
txt('conditions','4 Port / 64 Plane / 8MiB / QD512/Port / PF OFF / 가용률 85% / 기존 tR 유지',58,116,1164,34,23,C.muted);
txt('measurement','초기 200µs 제외, 0.2–2.2ms 지속 부하. 곡선은 25µs 평균이며 종료 drain은 없습니다.',58,153,1164,32,22,C.muted);
txt('a-heading','A1 / A2  ·  4KiB 반환',58,196,565,35,28,C.ink,true);
txt('b-heading','B1 / B2  ·  64B 반환',658,196,565,35,28,C.ink,true);
function plot(pats,x,max,step){
 const ch=s.charts.add('scatter',{
  position:{left:x,top:235,width:566,height:257},
  series:pats.map((pat,i)=>({name:pat,smooth:false,values:evidence.data[pat].gbps.map(v=>+v.toFixed(6)),xValues:evidence.data[pat].time_ms,line:{fill:i?C.teal:C.blue,width:2.3},marker:{symbol:'none'}})),
  scatterOptions:{style:'line'},hasLegend:true,legend:{position:'bottom',overlay:false,textStyle:{fontSize:20,fill:C.ink}},
  xAxis:{min:0.2,max:2.2,majorUnit:0.5,numberFormatCode:'0.0',title:{text:'시간 (ms)',textStyle:{fontSize:18,fill:C.muted}},textStyle:{fontSize:18,fill:C.muted},line:{fill:C.grid,width:1},majorGridlines:null},
  yAxis:{min:0,max,majorUnit:step,numberFormatCode:'0',title:{text:'Host GB/s',textStyle:{fontSize:18,fill:C.muted}},textStyle:{fontSize:18,fill:C.muted},majorGridlines:{fill:C.grid,width:1},line:{fill:C.grid,width:1}},
  chartFill:'#FFFFFF',chartLine:{fill:'none',width:0},plotAreaFill:'#FFFFFF',plotAreaLine:{fill:'none',width:0}
 });
 applyPresentationChartFont(ch,{fontFamily:F});
}
plot(['A1','A2'],56,280,70);plot(['B1','B2'],656,6,2);
const a=evidence.data.A1,a2=evidence.data.A2,b=evidence.data.B1,b2=evidence.data.B2;
const n=v=>v.toLocaleString('en-US');
txt('a-mean',`2ms 평균  A1 ${a.mean_gbps.toFixed(2)} / A2 ${a2.mean_gbps.toFixed(2)} GB/s`,60,498,570,30,23,C.blue,true);
txt('b-mean',`2ms 평균  B1 ${b.mean_gbps.toFixed(3)} / B2 ${b2.mean_gbps.toFixed(3)} GB/s`,660,498,566,30,23,C.teal,true);
txt('a-counts',`완료 ${n(a.completed_requests)} / ${n(a2.completed_requests)}건\n실제 outstanding 평균 ${a.outstanding_mean.toFixed(1)} / ${a2.outstanding_mean.toFixed(1)}건`,60,536,575,55,21,C.muted);
txt('b-counts',`완료 ${n(b.completed_requests)} / ${n(b2.completed_requests)}건\n실제 outstanding 평균 ${b.outstanding_mean.toFixed(1)} / ${b2.outstanding_mean.toFixed(1)}건`,660,536,566,55,21,C.muted);
txt('a-insight','A는 Host 상한 256GB/s의 약 99.6–99.8%\n추가 병렬성보다 남은 대기 구간 축소가 관건',60,604,572,57,22,C.ink,true);
txt('b-insight','B는 명목 유효 비율 1/64로 약 4GB/s\n주기적 하락은 maintenance와 in-order 선두 대기',660,604,570,57,22,C.ink,true);
txt('footer','모델 결과 / 좌우 Y축 다름 / A1·B1·B2: stripe 4KiB, A2: 16KiB / 요청 수·outstanding은 4 Port 합계',56,677,1110,25,15.5,C.muted);
txt('page','14',1170,674,52,27,16,C.muted);
s.speakerNotes.text=`저장된 원시 CSV 4개에서 200–2200µs의 80개 25µs bin을 사용했다. 각 점은 bin 중심 시각이고 y값은 실제 Host payload bytes/time이다. 2ms 평균과 완료 요청 수는 sweep.csv와 재계산으로 검증했다. 선은 점을 이어 보여주며 추가 평활화는 하지 않았다. 시간별 그래프는 초기 200µs와 종료 drain을 제외한 지속 입력 조건이다. 최고 구간 선택이 아니라 고정 2ms 전체를 보여준다. GB/s는 decimal GB/s다. 좌우 Y축은 각각 0–280, 0–6이다.\n\n표시 순서 A1/A2, B1/B2. Device outstanding은 수락된 요청 중 최종 응답이 끝나지 않은 요청 수의 시간 평균이며 Host 대기열을 포함하지 않는다. 완료 건수와 outstanding은 모두 4 Port 합계다. QD512는 Port별 상한이다. A 평균/Host IF 256GB/s 비율은 A1 ${(a.mean_gbps/256*100).toFixed(4)}%, A2 ${(a2.mean_gbps/256*100).toFixed(4)}%이다.\n\nB1/B2는 각 4KiB 논리 페이지 시작 64B를 요청한다. 한 16KiB 물리 페이지의 4개 영역에서 총256B만 사용해 명목 유효 비율이1/64이다. 실제 내부 NAND 전송은 약257GB/s, Long tR 비율은0%로 관측했다. A1/B1은 동일 매핑과 장치 설정이고 A2/B2는 stripe와CA정책이 달라 완전히 크기만 비교한 쌍은 아니다. B의 약4GB/s는 이 전체16KiB 출력 모델의 결과이며 모든64B workload의 상한이 아니다.\n\n주기적 하락의 원인은 별도 partial_dips 대조실험에서 확인했다. 가용률85%를 100µs 주기의Plane off로 모델링했고 in-order 선두가 늦어지면 준비된 후속응답도 대기한다. maintenance OFF 대조에서 큰 주기적 하락이 사라졌다. 이는 실제 NAND GC의 고유 주기를 주장하지 않는다. A의 데이터는4KiB 단위로 반환해 Host IF를 거의 계속 채우므로 동일한 지연 요인이 그래프에 덜 드러난다. B 곡선이 단기 약4GB/s 공급량 위로 오르는 구간은 준비된 버퍼 데이터를 몰아서 반환하는 현상이다.\n\n출처\n`+
Object.values(evidence.data).map(d=>`https://github.com/JBRARAPARK/HBF_zNAND_Research/blob/${evidence.source_commit}/${d.source}`).join('\n')+`\nhttps://github.com/JBRARAPARK/HBF_zNAND_Research/blob/${evidence.source_commit}/results/znand/partial_dips/RESULTS_KO.md`;
await fs.writeFile(path.join(build,'graph-preview.png'),new Uint8Array(await(await p.export({slide:s,format:'png',scale:1.5})).arrayBuffer()));
await fs.writeFile(path.join(build,'graph.layout.json'),await(await s.export({format:'layout'})).text());
const candidate=path.join(build,'graph-candidate.pptx');
await(await PresentationFile.exportPptx(p)).save(candidate);
const validators={workspaceDir:repo,pythonExecutable:python,integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit'],verifyArtifactToolImport:true};
const graph=path.join(out,'graph-slide.pptx');
await finalizePresentation({...validators,candidatePath:candidate,finalPath:graph,explicitTotalSlideCount:1,requiredNativeChartOwnerSlides:[1],materializeLiteralChartWorkbooks:true,fontPolicy:{basis:'design',families:[F],scriptFonts:{ea:F}},receiptPath:path.join(build,path.basename(out)+'-graph.validation.json')});
const merged=path.join(build,'merged-candidate.pptx');
execFileSync(python,[path.join(repo,'docs/performance_key_items/append_slide_package.py'),src,graph,merged],{stdio:'inherit'});
const finalPath=path.join(out,'performance_key_items_with_graph_ko.pptx');
await finalizePresentation({...validators,candidatePath:merged,finalPath,explicitTotalSlideCount:14,requiredNativeChartOwnerSlides:[6,7,9,14],materializeLiteralChartWorkbooks:false,fontPolicy:{basis:'reference',families:[F],scriptFonts:{ea:F},referencePath:src,referenceSha256:createHash('sha256').update(await fs.readFile(src)).digest('hex')},receiptPath:path.join(build,path.basename(out)+'-deck.validation.json')});
const bundledFonts=path.join(deps,'native/libreoffice-headless/libreoffice/LibreOfficeDev.app/Contents/Resources/fonts/truetype');
const fontCache=path.join(build,'font-cache');
await fs.mkdir(fontCache,{recursive:true});
const escapeXml=v=>v.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const fontConfig=path.join(build,'fonts.conf');
await fs.writeFile(fontConfig,'<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig><dir>/System/Library/Fonts</dir><dir>'+escapeXml(bundledFonts)+'</dir><cachedir>'+escapeXml(fontCache)+'</cachedir></fontconfig>');
execFileSync(path.join(deps,'bin/override/soffice'),['--headless','-env:UserInstallation='+pathToFileURL(path.join(build,'lo-profile')).href,'--convert-to','pdf','--outdir',out,finalPath],{stdio:'pipe',timeout:60000,env:{...process.env,FONTCONFIG_FILE:fontConfig}});
await fs.copyFile(path.join(build,'graph-preview.png'),path.join(out,'performance_time_insights_ko.png'));
console.log(JSON.stringify({pptx:finalPath,pdf:finalPath.replace(/pptx$/,'pdf'),slides:14}));
