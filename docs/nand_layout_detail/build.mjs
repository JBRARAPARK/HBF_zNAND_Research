import fs from 'node:fs/promises';
import path from 'node:path';
import {homedir} from 'node:os';
// Run from repository root using the bundled Node runtime.
// Copy this source into scratch/nand_layout_detail with a node_modules link to the bundled runtime.
// Pass a fresh output directory as the first argument when regenerating; finalized files are not overwritten.
import {Presentation,PresentationFile} from '@oai/artifact-tool';
const repo=process.cwd(), out=path.resolve(process.argv[2] || path.join(repo,'docs/nand_layout_detail')), build=path.join(repo,'scratch/nand_layout_detail');
const skill=homedir()+'/.codex/plugins/cache/openai-primary-runtime/presentations/26.1009.11318/skills/presentations';
const deps=homedir()+'/.cache/codex-runtimes/codex-primary-runtime/dependencies';
process.env.RUNTIME_NODE_MODULES=deps+'/node/node_modules';
await fs.mkdir(out,{recursive:true});
await fs.mkdir(build,{recursive:true});
const {finalizePresentation}=await import(skill+'/container_tools/artifact_tool_utils.mjs');
const p=Presentation.create({slideSize:{width:1280,height:720}}), F='Apple SD Gothic Neo';
const C={ink:'#172738',blue:'#126DCA',teal:'#008B82',muted:'#586875',orange:'#B76B13',pale:'#F1F5F8',grid:'#B9CBD8'};
let s, count=0;
function text(t,x,y,w,h=36,size=23,color=C.ink,bold=false){const z=s.shapes.add({geometry:'textbox',name:'text-'+count++,position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});z.text=t;z.text.style={typeface:F,fontSize:size,color,bold,autoFit:'none',wrap:'square',insets:0};return z;}
function box(t,x,y,w,h,color=C.blue,fill='#FFFFFF',size=23){s.shapes.add({geometry:'rect',name:'block-'+count++,position:{left:x,top:y,width:w,height:h},fill,line:{fill:color,width:1.6}});if(t)text(t,x+12,y+12,w-24,h-24,size,color,true);}
function line(x,y,w,h=2,color=C.blue){s.shapes.add({geometry:'rect',position:{left:x,top:y,width:w,height:h},fill:color,line:{fill:'none',width:0}});}
function arrow(x,y,w=35,color=C.blue){s.shapes.add({geometry:'rightArrow',position:{left:x,top:y,width:w,height:19},fill:color,line:{fill:'none',width:0}});}
function slide(title,sub,n){s=p.slides.add();s.background.fill='#FFFFFF';text(title,56,38,1168,60,42,C.ink,true);text(sub,58,109,1164,54,22,C.muted);text('HBF zNAND 모델 해석 | 64 Plane 구성 | 제품의 실제 die floorplan은 미확정',56,674,1100,24,16,C.muted);text(String(n).padStart(2,'0'),1175,674,50,24,16,C.muted);s.speakerNotes.text='근거: https://github.com/JBRARAPARK/HBF_zNAND_Research/blob/8495ed5/znand/model.py\nhttps://github.com/JBRARAPARK/HBF_zNAND_Research/blob/8495ed5/docs/09_plane_expansion_layout_ko.md\n이 도식은 시뮬레이터의 자원 및 주소 모델이다. 실제 zNAND 제품의 배선, 셀 단면, Die/LUN 제약을 확정하지 않는다.';}
slide('NAND 채널 내부의 Plane과 공유 경로','4 Channel × 16 Plane = 총 64개 독립 sensing 자원. 아래는 CH0을 확대한 모델 구조입니다.',1);
box('Controller\nCA 스케줄러\nData 수신',56,217,210,252,C.ink,C.pale,26);
box('',320,185,900,350,C.grid);text('CH0   ·   CH1–CH3도 동일한 구성',342,202,820,35,27,C.ink,true);
text('공유 CA 경로',345,254,230,30,21,C.blue,true);line(345,293,824,3);arrow(273,282,36);
for(let j=0;j<4;j++){let x=350+j*210;line(x+82,295,2,33);box(['Plane 0','Plane 1','Plane 2 … 14','Plane 15'][j],x,328,180,100,C.blue,C.pale,23);text('독립 busy / tR\n16KiB page buffer',x+12,369,165,52,19,C.ink);line(x+82,430,2,35,C.teal);}
line(345,465,824,3,C.teal);text('공유 Data 경로   ·   채널당 80.1125 GB/s 설정',345,486,790,32,23,C.teal,true);
s.shapes.add({geometry:'leftArrow',position:{left:273,top:448,width:36,height:19},fill:C.teal,line:{fill:'none',width:0}});
text('독립적인 sensing은 겹칠 수 있지만, 같은 채널의 출력 전송은 직렬화됩니다.',58,555,1150,38,27,C.ink,true);
text('Die/LUN은 모델에 없음. 2 Plane/Die를 가정하면 8 Die/Channel로 해석할 수 있으나 구현 확정값은 아닙니다.\nPlane page buffer 합계: 64 × 16KiB = 1MiB. Controller buffer 8MiB와는 별도 자원입니다.',58,607,1150,55,21,C.muted);
slide('Plane 내부의 주소 계층과 페이지 배치','코드의 plane-local 페이지 번호 q를 Group, WL, Block, SSL, E/O로 분해한 논리 배치입니다.',2);
box('',56,185,770,385,C.grid);text('한 Plane의 주소 공간',77,204,700,35,28,C.ink,true);
box('Group g',82,257,715,275,C.blue,'#F7FAFD',25);text('WL 420 … 0  (q가 증가하면 WL 감소)',104,309,660,35,25,C.ink,true);
for(let b=0;b<2;b++){let x=106+b*340;box('Block '+b,x,363,315,140,C.teal,'#FFFFFF',23);text('SSL 0 … 5',x+15,404,270,32,23,C.ink);text('각 SSL: Even / Odd 16KiB page',x+15,453,290,33,20,C.muted);}
text('모델의 순차 탐색',860,196,356,35,28,C.blue,true);
text('E/O 2개\nSSL 6개\nBlock 2개\nWL 421개\nGroup 증가',862,250,342,234,29,C.ink);
text('한 Group = 10,104 pages\n= 157.875MiB / Plane',860,502,365,61,25,C.teal,true);
text('q 예시',58,593,120,30,24,C.ink,true);text('0: WL420/B0/SSL0/E     1: …/O     2: WL420/B0/SSL1/E',185,590,1015,34,23,C.ink);
text('12: WL420/B1/SSL0/E     24: WL419/B0/SSL0/E     10,104: 다음 Group',185,630,1015,33,22,C.muted);
s.speakerNotes.text+='\naddress(q): r=q%10104; (q//10104,420-r//24,(r%24)//12,(r%12)//2,r%2). 10104=421*2*6*2. 10104*16384/2**20=157.875MiB. Group은 모델상의 주소 묶음이다. Group 개수나 유한 물리 용량은 제한하지 않는다. SSL/E/O는 모델의 주소 라벨이며 실제품의 스트링 수나 셀 배치를 의미하지 않는다.';
slide('Plane의 읽기와 두 버퍼의 역할','요청 주소가 같은 페이지라도 데이터가 남아 있는 위치에 따라 통과하는 단계가 달라집니다.',3);
const xs=[56,300,544,788,1032];const labels=['CA 명령','Array sensing','Page buffer','Data + ECC','Controller buffer'];
for(let i=0;i<5;i++){box(labels[i],xs[i],235,194,95,i===2?C.teal:C.blue,C.pale,24);if(i<4)arrow(xs[i]+201,274,35);}
text('채널당 공유\n0.1µs',67,345,188,70,24,C.muted);
text('Plane별 독립\ntR 분류 적용',311,345,188,70,24,C.muted);
text('Plane당 16KiB\n마지막 sensing q',555,345,190,70,23,C.teal);
text('16KiB 전체 전송\n그 뒤 ECC 0.2µs',799,345,188,70,22,C.muted);
text('8MiB 설정\nHost: 4KiB / 64B',1043,345,188,70,22,C.muted);
text('① Controller buffer hit',57,457,410,36,26,C.ink,true);text('준비된 페이지를 재사용. 새 NAND 읽기/전송 없이 응답 대기',491,460,731,38,23,C.ink);
text('② NAND page buffer hit',57,507,410,36,26,C.teal,true);text('sensing 생략. 출력 CA와 16KiB Data 전송은 다시 수행',491,510,731,38,23,C.ink);
text('③ 두 버퍼 모두 miss',57,557,410,36,26,C.blue,true);text('CA, tR, 전송, ECC를 거친 후 Port별 in-order 응답',491,560,731,38,23,C.ink);
text('tR 모델: First / Group 20.69µs · Short 2.00µs · Mid 2.08µs · Long 12.16µs',57,624,1175,35,23,C.muted);
s.speakerNotes.text+='\nNAND transfer duration=16384/(80.1125*1000)+0.05=약0.2545µs. Page-buffer hit도 CA 0.1µs, 전체 페이지 출력, ECC 0.2µs를 수행한다. Plane busy는 transferred 시 해제된다. Controller 항목은 마지막 참조 응답 이후 해제되므로 영구 캐시가 아니다. 페이지 버퍼 hit는 sensing된 q와 일치할 때만 가능하며 maintenance/상태 제약이 추가될 수 있다. tR는 실측 보장값이 아닌 Config 값이다.';
for(let i=0;i<p.slides.items.length;i++)await fs.writeFile(path.join(out,`nand_layout_${i+1}.png`),new Uint8Array(await(await p.export({slide:p.slides.items[i],format:'png',scale:1.5})).arrayBuffer()));
const candidate=path.join(build,'candidate.pptx');await(await PresentationFile.exportPptx(p)).save(candidate);
await finalizePresentation({workspaceDir:repo,candidatePath:candidate,finalPath:path.join(out,'nand_layout_detail_ko.pptx'),pythonExecutable:deps+'/python/bin/python3',integrityValidatorPath:skill+'/container_tools/inspect_presentation_package_integrity.py',layoutValidatorPath:skill+'/container_tools/inspect_presentation_layout_geometry.py',layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit'],explicitTotalSlideCount:3,fontPolicy:{basis:'design',families:[F]},verifyArtifactToolImport:true,receiptPath:path.join(build,'validation.json')});
console.log('Created 3-slide NAND layout detail deck');
