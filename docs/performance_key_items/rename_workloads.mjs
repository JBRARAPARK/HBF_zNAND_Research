// Current A/B/C deck. Preserve saved slides and replace only the definition tables.
// Run a copy under scratch linked to bundled node_modules.
// Usage: node rename_workloads.mjs <repository-root> <new-output-directory>
import fs from 'node:fs/promises';
import path from 'node:path';
import {homedir} from 'node:os';
import {execFileSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';
import {Presentation,PresentationFile,FileBlob} from '@oai/artifact-tool';
const repo=path.resolve(process.argv[2]),out=path.resolve(process.argv[3]);
const build=path.join(repo,'scratch/performance_key_items/workloads-v2');
const deps=path.join(homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies');
const skill=path.join(homedir(),'.codex/plugins/cache/openai-primary-runtime/presentations/26.1007.11041/skills/presentations');
process.env.RUNTIME_NODE_MODULES??=path.join(deps,'node/node_modules');
const python=path.join(deps,'python/bin/python3');
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
await fs.mkdir(build,{recursive:true});await fs.mkdir(out,{recursive:true});
const source=path.join(repo,'docs/performance_key_items/performance_key_items_with_graph_ko.pptx');
const sourceDeck=await PresentationFile.importPptx(await FileBlob.load(source));
if(sourceDeck.slides.items.length!==14)throw new Error('Expected 14-slide source');
for(const i of [11,12])await fs.writeFile(path.join(build,`source-${i+1}.png`),new Uint8Array(await(await sourceDeck.export({slide:sourceDeck.slides.items[i],format:'png',scale:1.25})).arrayBuffer()));
const p=Presentation.create({slideSize:{width:1280,height:720}});
const F='Apple SD Gothic Neo',C={ink:'#172738',muted:'#586875',navy:'#122C40',grid:'#DFE6EB',pale:'#F1F5F8',blue:'#126DCA'};
function text(s,name,value,x,y,w,h,size=24,color=C.ink,bold=false){
 const t=s.shapes.add({geometry:'textbox',name,position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 t.text=value;t.text.style={typeface:F,fontSize:size,color,bold,autoFit:'none',wrap:'square',verticalAlignment:'top',insets:0};return t;
}
function base(title,subtitle,footer,page){
 const s=p.slides.add();s.background.fill='#FFFFFF';
 text(s,'title',title,56,46,1168,66,44,C.ink,true);
 text(s,'subtitle',subtitle,58,116,1164,64,24,C.muted);
 text(s,'footer',footer,56,674,1100,27,16,C.muted);
 text(s,'page',String(page),1170,674,52,27,16,C.muted);return s;
}
function table(s,values,y,h,widths,size=22){
 const t=s.tables.add({rows:values.length,columns:values[0].length,left:56,top:y,width:1168,height:h,columnWidths:widths,values});
 t.borders.assign({fill:C.grid,width:1,style:'solid'});
 t.cells.block({row:0,column:0,rowCount:values.length,columnCount:values[0].length}).assign({fill:'#FFFFFF',textStyle:{typeface:F,fontSize:size,color:C.ink},margins:{left:12,right:12,top:8,bottom:8},anchor:'center'});
 for(let r=0;r<values.length;r++){
  t.rows[r].height=h/values.length;
  for(let c=0;c<values[0].length;c++){
   const cell=t.getCell(r,c);cell.text.style={typeface:F,fontSize:size,color:r===0?'#FFFFFF':C.ink,bold:r===0,verticalAlignment:'middle',insets:12};
   cell.fill=r===0?C.navy:r%2===0?C.pale:'#FFFFFF';
  }
 }return t;
}
{
 const s=base('A·B·C 워크로드의 요청 크기와 접근 순서','P는 4KiB 논리 페이지입니다. 새 B는 페이지 전체를 64B씩 읽고, 기존 B1/B2/B3는 C로 옮겼습니다.','현재 이름(schema 2)    기존 원자료의 B1/B2/B3 = 현재 C1/C2/C3',12);
 table(s,[
  ['패턴','요청당 반환','접근 순서','한 논리 페이지에서 읽는 양'],
  ['A1','4KiB','P1, P2, P3, P4, …','전체 4KiB를 요청 1개로'],
  ['A2','4KiB','P1, P3, P2, P4, P6, P5, …','전체 4KiB, 페이지 순서 변경'],
  ['B (신규)','64B','P1: offset 0, 64, …, 4032\n이후 P2, P3, …','전체 4KiB를 요청 64개로'],
  ['C1','64B','P1, P2, P3, P4, …','각 페이지의 시작 64B'],
  ['C2','64B','P1, P3, P2, P4, P6, P5, …','각 페이지의 시작 64B'],
  ['C3','64B','P1, P3, P1(offset +64B), P2, …','P1 재방문에서 다른 64B']
 ],194,376,[142,158,472,396],22);
 text(s,'new-b-scope','B는 페이지 내 연속 읽기입니다. C1/C2는 페이지마다 일부만 읽습니다.',60,591,1160,32,25,C.blue,true);
 text(s,'state-rule','버퍼 재사용과 tR 발생 여부는 기존 모델 상태로 결정합니다. 항상 hit을 가정하지 않습니다.',60,634,1160,30,22,C.muted);
 s.speakerNotes.text='2026-10-11 사용자 결정으로 새64B 페이지내 연속읽기를 B, 기존B1/B2/B3를C1/C2/C3로 정의했다. B는하나의패턴이며 새로운B1/B2분류는추가하지않았다. 요청마다64B이며4KiB논리페이지의offset0부터4032까지64개요청후다음페이지로이동한다. C1/C2는offset0만읽고 C3는P1재방문시offset64를읽는다. A2/C2는3개단위국소순열이다. NAND물리페이지는16KiB다. 기존모델의버퍼수명,tR,출력량과in-order를유지한다.\n\n출처: docs/15_workload_naming_ko.md, znand/workloads.py. 고객 원문의B식별자는문서전사와과거원자료에보존했다.';
}
{
 const s=base('A·B·C의 유효 데이터량과 측정 상태','새 B와 C는 모두 64B 요청이지만, 준비한 페이지에서 실제 소비하는 데이터량이 다릅니다.','기존 측정: 64 Plane, 8MiB, QD512/Port, PF OFF, 200–2,200µs 고정 평균    새 B 정식 측정 전',13);
 table(s,[
  ['비교 항목','A1 / A2','B (신규)','C1 / C2'],
  ['Host 요청당 반환량','4KiB','64B','64B'],
  ['논리 4KiB당 요청 수','1개','64개','1개'],
  ['물리 16KiB당 유효 데이터','16KiB','16KiB','256B'],
  ['명목 유효 데이터 비율','100%','100%','1/64 = 1.5625%'],
  ['Host 평균 (GB/s)','A1 255.366\nA2 255.058','정식 측정 전','C1 3.995\nC2 4.001']
 ],191,342,[360,269,270,269],22);
 text(s,'new-b-qd','같은 QD512/Port에서도 대기 payload는 A가 2MiB, B/C가 32KiB입니다.',60,558,1160,34,25,C.blue,true);
 text(s,'new-b-parallel','B는 한 페이지에 요청이 모입니다. QD를 조정하며 실제 NAND 병렬성과 재사용을 확인합니다.',60,602,1160,34,22,C.ink);
 text(s,'new-b-results','기존 약 4GB/s는 C1/C2 결과입니다. 새 B의 성능으로 재사용하지 않습니다.',60,641,1160,27,22,C.muted);
 s.speakerNotes.text='B의전체페이지소비는완료된긴스트림의명목바이트활용도다. 관측경계·요청병합·버퍼수명·재출력에따라실측Host/NAND효율은100%와다를수있다. 실제항상hit이나tR1회를강제하지않는다. B의정식2ms성능sweep은아직실행하지않았다. 기능검증시험수치를최대성능으로사용하지않는다. QD는요청개수기준이므로512×4096=2MiB,512×64=32KiB다. 기존C1/C2수치는명칭만바꿨고모델실행값은그대로다. A1/C1의장치설정은동일하지만A2/C2는stripe와CA정책이다르다. C3의최근64Plane지속부하수치는없다.\n\n출처: docs/15_workload_naming_ko.md, docs/performance_key_items/graph_evidence.json, results/znand/workloads_v2/partial_saturation.csv.';
}
for(let i=0;i<2;i++)await fs.writeFile(path.join(build,`new-${i+12}.png`),new Uint8Array(await(await p.export({slide:p.slides.items[i],format:'png',scale:1.5})).arrayBuffer()));
const candidate=path.join(build,'definitions-candidate.pptx');await(await PresentationFile.exportPptx(p)).save(candidate);
const validators={workspaceDir:repo,pythonExecutable:python,integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit'],verifyArtifactToolImport:true,fontPolicy:{basis:'design',families:[F],scriptFonts:{ea:F}}};
const definitions=path.join(out,'definitions.pptx');
await finalizePresentation({...validators,candidatePath:candidate,finalPath:definitions,explicitTotalSlideCount:2,requiredNativeTableOwnerSlides:[1,2],layoutArgs:[...validators.layoutArgs,'--require-native-table-slide','1','--require-native-table-slide','2'],receiptPath:path.join(build,path.basename(out)+'-definitions.validation.json')});
const renamed=path.join(build,'renamed-base.pptx'),merged=path.join(build,'merged-candidate.pptx');
execFileSync(python,[path.join(repo,'docs/performance_key_items/rename_workload_labels.py'),source,renamed]);
execFileSync(python,[path.join(repo,'docs/performance_key_items/append_slide_package.py'),renamed,definitions,merged,'12,13'],{stdio:'inherit'});
const finalPath=path.join(out,'performance_key_items_abc_ko.pptx');
await finalizePresentation({...validators,candidatePath:merged,finalPath,explicitTotalSlideCount:14,requiredNativeTableOwnerSlides:[12,13],layoutArgs:[...validators.layoutArgs,'--require-native-table-slide','12','--require-native-table-slide','13'],requiredNativeChartOwnerSlides:[6,7,9,14],receiptPath:path.join(build,path.basename(out)+'-deck.validation.json')});
const fontConfig=path.join(build,'fonts.conf');
const xmlEscape=value=>value.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const libreOfficeFonts=path.join(deps,'native/libreoffice-headless/libreoffice/LibreOfficeDev.app/Contents/Resources/fonts/truetype');
await fs.writeFile(fontConfig,`<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig><dir>/System/Library/Fonts</dir><dir>${xmlEscape(libreOfficeFonts)}</dir><cachedir>${xmlEscape(path.join(build,'font-cache'))}</cachedir></fontconfig>`);
execFileSync(path.join(deps,'bin/override/soffice'),['--headless','-env:UserInstallation='+pathToFileURL(path.join(build,'lo-profile')).href,'--convert-to','pdf','--outdir',out,finalPath],{stdio:'pipe',timeout:60000,env:{...process.env,FONTCONFIG_FILE:fontConfig}});
console.log(JSON.stringify({pptx:finalPath,pdf:finalPath.replace(/pptx$/,'pdf'),slides:14}));
