"""Analyze matched 8MiB growth steps and whether reserved capacity is binding."""
from pathlib import Path
import csv,json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    out=Path('results/znand/buffer_growth');manifest=json.loads((out/'manifest.json').read_text())
    rows=list(csv.DictReader((out/'sweep.csv').open()));assert len(rows)==manifest['validated_rows']==45
    n=lambda r,k:float(r.get(k) or 0)
    def pick(p,m,q=None):
        a=[r for r in rows if r['pattern']==p and int(r['buffer_mib'])==m and (q is None or int(r['outstanding'])==q)]
        return max(a,key=lambda r:n(r,'bandwidth_gbps'))
    capacity_checks=[]
    for p in ('A1','A2'):
        reference=pick(p,40,2048)
        compared=[pick(p,m,2048) for m in (40,48,56,64)]
        excluded={'case_id','buffer_mib','buffer_pages','source'}
        differing=sorted({k for r in compared for k in r if k not in excluded and r[k]!=reference[k]})
        capacity_checks.append(dict(pattern=p,outstanding=2048,compared_mib=[40,48,56,64],
            reserved_peak_mib=n(reference,'buffer_peak_pages')/64,
            all_have_free_capacity=all(n(r,'buffer_peak_pages')<n(r,'buffer_pages') for r in compared),
            all_without_buffer_stalls=all(n(r,'count_buffer_admission_stalls')==0 for r in compared),
            all_other_saved_fields_equal=not differing,differing_fields=differing))
    (out/'capacity_check.json').write_text(json.dumps(capacity_checks,indent=2)+'\n')
    summary=[]
    for p in ('A1','A2','B1','B2','B3'):
        reference=pick(p,32)
        for m in (32,40,48,56,64):
            r=pick(p,m)
            summary.append(dict(pattern=p,buffer_mib=m,outstanding=r['outstanding'],bandwidth_gbps=n(r,'bandwidth_gbps'),
                change_vs_32_pct=100*(n(r,'bandwidth_gbps')/n(reference,'bandwidth_gbps')-1),
                reserved_peak_mib=n(r,'buffer_peak_pages')/64,peak_outstanding=r['peak_outstanding'],
                mean_offer_latency_us=n(r,'mean_offer_latency_us'),p99_offer_latency_us=n(r,'p99_offer_latency_us'),
                mean_admission_wait_us=n(r,'mean_admission_wait_us'),mean_return_wait_us=n(r,'mean_return_wait_us'),
                long_pct=100*n(r,'count_tr_long')/n(r,'count_sensing_reads'),
                buffer_admission_stalls=int(n(r,'count_buffer_admission_stalls')),prefetch_dropped_buffer=int(n(r,'count_prefetch_dropped_buffer'))))
    with (out/'summary.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,list(summary[0]),lineterminator='\n');w.writeheader();w.writerows(summary)
    fig,axs=plt.subplots(1,2,figsize=(11,4))
    for ax,p in zip(axs,('A1','A2')):
        for q in (2048,4096,8192):
            vals=[pick(p,m,q) for m in (32,40,48,56,64)]
            ax.plot((32,40,48,56,64),[n(r,'bandwidth_gbps') for r in vals],marker='o',label=f'QD {q}/port')
        ax.set_title(p+(', 4KiB stripe' if p=='A1' else ', 16KiB stripe'));ax.set_xlabel('Shared buffer (MiB)');ax.set_ylabel('Useful host GB/s');ax.set_xticks((32,40,48,56,64));ax.legend();ax.grid(alpha=.3)
    fig.suptitle('4 ports, 32 planes, locality, PF ON, 8192 requests/port');fig.tight_layout();fig.savefig(out/'growth.png',dpi=160);plt.close(fig)
    lines=['# Locality 정책에서 Controller buffer 8MiB 단위 확대','',
        '이번 비교 범위에서는 32MiB가 다섯 패턴 모두 가장 높은 처리량을 보였다. A1/A2는 QD2,048/port에서 각각 118.780/118.257GB/s였고, 40MiB부터는 각각 110.653/111.147GB/s로 6.84%/6.01% 감소했다. 같은 QD에서 40~64MiB의 예약 peak는 약 34MiB이며 수락 실패가 없어, 추가 용량으로 해소할 버퍼 제한이 남지 않았다. 이 결과만으로 물리 용량을 확대하기보다 reservation과 내부 발행 정책을 분리해 튜닝하는 쪽이 우선이다.','',
        '4port·32Plane·locality 정책·PF ON(합성 정확도 100%, 선행 10μs)·port당 8,192개 요청·seed 7·port별 비중첩 주소를 유지했다. 32·40·48·56·64MiB를 비교하며 A1/A2는 QD2,048/4,096/8,192를 모두 평가했다. B1/B2/B3는 QD8,192로 고정한 보조 비교다. Stripe는 A1/B1/B2가 4KiB, A2/B3가 16KiB로 고정했다. MiB는 1,048,576 bytes이며 공유 버퍼 전체 용량이다.','',
        '총 45개 비교 조건이다. 기존 동일 모델·동일 조건 6개를 재사용하고 신규 39개를 실행했다. 기존 결과의 모델 해시를 확인했고 저장된 45행의 요청량·대역폭 상한·지연 분해·자원 제한을 검증했다.','',
        '## 처리량 요약','',
        'A1/A2는 평가한 세 QD 중 최고값이며 B계열은 고정 QD8,192 결과다. 단위는 GB/s다.','',
        '| 패턴 | 32MiB | 40MiB | 48MiB | 56MiB | 64MiB |','|---|---:|---:|---:|---:|---:|']
    for p in ('A1','A2','B1','B2','B3'):
        lines.append('| '+p+' | '+' | '.join(f"{n(pick(p,m),'bandwidth_gbps'):.3f}" for m in (32,40,48,56,64))+' |')
    lines+=['','![Buffer growth](growth.png)','','## A1/A2의 Outstanding별 비교','','| 패턴 | QD/port | 32MiB | 40MiB | 48MiB | 56MiB | 64MiB |','|---|---:|---:|---:|---:|---:|---:|']
    for p in ('A1','A2'):
        for q in (2048,4096,8192):lines.append('| '+p+f' | {q} | '+' | '.join(f"{n(pick(p,m,q),'bandwidth_gbps'):.3f}" for m in (32,40,48,56,64))+' |')
    lines+=['','## 각 용량의 최고 처리량 조건과 자원 사용','','예약 peak는 실제 payload뿐 아니라 미도착 데이터의 예약 공간을 포함한다. QD peak는 port별 최댓값 중 최대이며 전체 port 합계가 아니다. Buffer stall은 실패한 수락 시도 횟수이며 시간 비율이 아니다. 평균·p99 offer 지연은 요청 제시부터 최종 반환까지로, 수락 대기도 포함한다.','','| 패턴 | 용량 MiB | QD/port | 실제 QD peak/port | 예약 peak MiB | Buffer stall 횟수 | 평균 offer μs | p99 offer μs | Long % |','|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in summary:
        lines.append(f"| {r['pattern']} | {r['buffer_mib']} | {r['outstanding']} | {r['peak_outstanding']} | {r['reserved_peak_mib']:.3f} | {r['buffer_admission_stalls']} | {r['mean_offer_latency_us']:.2f} | {r['p99_offer_latency_us']:.2f} | {r['long_pct']:.2f} |")
    lines+=['','## 버퍼 병목 판정','','A1/A2의 기존 최고 조건인 QD2,048/port를 고정해 확인했다. 용량·case ID·출처 필드를 제외한 모든 저장 필드를 비교했으며 결과는 [capacity_check.json](capacity_check.json)에 보관한다.','']
    for check in capacity_checks:
        if all(check[k] for k in ('all_have_free_capacity','all_without_buffer_stalls','all_other_saved_fields_equal')):
            lines.append(f"- {check['pattern']}: 40~64MiB에서 예약 peak {check['reserved_peak_mib']:.3f}MiB, buffer 수락 실패 0회다. 모든 성능 지표·계수가 완전히 같으므로 이 조건에서는 40MiB를 넘는 추가 공간이 사용되지 않았다.")
        else:
            lines.append(f"- {check['pattern']}: 40~64MiB 결과는 동일한 여유 공간 조건으로 묶이지 않으므로 위 표와 원본 지표를 각각 확인해야 한다.")
    lines+=['','32→40MiB의 같은 QD2,048 조건에서는 다음 변화가 관측됐다. Return wait는 데이터·조회 준비 후 R 시작까지의 시간이며 port in-order 선두 대기와 반환 경로 대기가 포함된다.','','| 패턴 | 용량 MiB | GB/s | Long % | 평균 return wait μs | 평균 수락 대기 μs |','|---|---:|---:|---:|---:|---:|']
    for p in ('A1','A2'):
        for m in (32,40):
            r=pick(p,m,2048)
            lines.append(f"| {p} | {m} | {n(r,'bandwidth_gbps'):.3f} | {100*n(r,'count_tr_long')/n(r,'count_sensing_reads'):.2f} | {n(r,'mean_return_wait_us'):.2f} | {n(r,'mean_admission_wait_us'):.2f} |")
    lines+=['','용량 확대는 수락·Prefetch 진입 순서도 바꾼다. 이때 Long sensing 비율과 반환 대기가 함께 증가했다. 각 요인의 인과 기여도를 분리한 실험은 아니므로 Long tR 하나만으로 감소분 전체를 설명하지 않는다. Buffer 수락 실패가 0회여도 Outstanding 한도에 의한 수락 대기는 남을 수 있다.','',
        '다음 튜닝에서는 물리 용량과 예약 window를 분리하고, port 선두 응답 진행을 고려한 내부 발행 및 Prefetch 진입량을 비교한다. 외부 port 내부 in-order 반환은 유지한다. 요청 수·주소 범위를 늘려 현재 유한 요청열에 대한 민감도도 확인한다.']
    lines+=['','## 해석 시 주의','','- 물리 buffer 용량과 admission 예약 한도는 기존 모델처럼 결합되어 있다. 변화에는 수락·발행 순서의 변화도 포함된다.','- 예약 peak가 용량에 도달했다고 처리량의 유일한 병목이 buffer라는 뜻은 아니다. 여유 공간, 수락 실패, QD 증가 효과와 처리량을 함께 본다.','- QD8,192는 port당 전체 요청 수와 같다. 본 결과는 유한 요청열의 비교이며 장시간 정상 상태나 전역 최대 성능을 보장하지 않는다.','- B계열은 QD8,192 단일 값으로 확인했으므로 B계열의 최적 QD를 탐색한 결과는 아니다.','- 32Plane·locality 우회 8회·age 1,000μs·PF 후보 상한 128개·평균 목표 가용률 85%를 유지했다. 64Plane 확장, 실제 GC, 동적 L2P, 실제 예측기는 평가하지 않았다.','',
        '## 재현','', '```sh','python3 -m znand.buffer_growth','python3 -m znand.buffer_growth_report','```','',
        '중간 결과가 있으면 조건과 모델 해시를 검증한 뒤 남은 조건만 실행한다. 그림 재생성에는 matplotlib이 필요하다. 원본: [sweep.csv](sweep.csv), [summary.csv](summary.csv), [cases.json](cases.json), [manifest.json](manifest.json).']
    (out/'RESULTS_KO.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
