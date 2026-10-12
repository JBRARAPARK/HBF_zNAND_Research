"""Audit and report production round-robin versus archived fixed admission."""
from pathlib import Path
import measure_die32_round_robin as measure
base=measure.base
ROOT=measure.ROOT
measure.audit()
rows=base.read(measure.OUT/'summary.json')
lines=['# 순환 수락을 기본 모델에 적용한32Plane 측정','',
'2026-10-12. 현재 `Simulator.admit()`는 **round-robin 수락**이다. 고정 Port 우선순위 옵션은 두지 않았다. 마지막으로 수락에 성공한 Port 다음부터 다음 호출을 시작한다. 수락 실패만으로 시작 위치를 옮기지 않는다. 한 호출에서 Port당 최대 한 요청을 확인하고, 자원이 충분하면 여러 Port가 함께 수락된다.','',
'예: 공유 공간이 한 요청분씩 생기고 네 Port가 모두 수락 가능하면 **0 → 1 → 2 → 3 → 0** 순서다. 빈 Port, QD 한도 도달, 미래 도착 요청, 공간 부족은 건너뛴다. 이것은 수락 기회를 순환시키는 규칙이며, 실제 outstanding을 무조건 균등하게 고정하는 규칙은 아니다.','',
'## 동일 조건 대조','',
'4 DIE × 2 독립 Channel × 4 Plane, 영역별 배치, 공유8MiB, PF OFF, CA FIFO, 기존 tR, 가용률85%를 유지했다. 이전 결과와 Config 및 주소 배치 snapshot이 동일하며, 생산 모델의 수락 로직만 바꿨다. 초기200µs를 제외한0.2–2.2ms 평균이다. QD는 Port당 설정 상한이다.','',
'| 요청 | QD/Port | 이전 고정 수락 GB/s | 현재 순환 수락 GB/s | 현재 Port별 GB/s | 후반1ms / 전반1ms 변화 |',
'|---|---:|---:|---:|---|---:|']
for s,r in zip(measure.cases(),rows):
    assert s['name']==r['name']
    before=base.read(ROOT/s['reference'])['windows']['fixed']['bandwidth_gbps']
    lines.append(f"| {r['pattern']} | {r['qd']:,} | {before:.3f} | {r['gbps']:.3f} | "+' / '.join(f'{v:.2f}' for v in r['per_port_gbps'])+f" | {r['second_vs_first_pct']:+.2f}% |")
lines+=['','측정한 큰 QD에서도 A1/A2/B는 모두 약185.82GB/s를 유지했고, 각 Port는 약46.45GB/s를 처리했다. 같은 배치에서 고정 수락의 고QD 성능 하락이 순환 수락으로 사라졌다. QD를 더 크게 설정해도 기준 QD보다 처리량이 높아지지는 않았으며, 실제 대기량과 버퍼 점유만 증가했다.','','## 실제 수락량과 해석','','| 요청 | QD/Port | Port별 실제 outstanding 평균 | 버퍼 평균 MiB | Long sensing 비율 |','|---|---:|---|---:|---:|']
for r in rows:
    lines.append(f"| {r['pattern']} | {r['qd']:,} | "+' / '.join(f'{v:,.1f}' for v in r['per_port_outstanding'])+f" | {r['buffer_mean_mib']:.3f} | {r['long_pct']:.3f}% |")
lines+=['',
'8MiB는16KiB 페이지512개의 공간이다. 따라서 QD 상한을 매우 크게 설정해도 수락된 요청이 전부 그 상한까지 쌓이지 않는다. 이 실험의 서로 다른 주소를 읽는 A는 페이지당4개 요청, B는 페이지당256개 요청을 공유하므로, 전체4Port 수락량의 이론적 예약 한도는 각각2,048개와131,072개다. 부분 페이지와 진행 상태 때문에 실제 점유는 더 작을 수 있다.','',
'이전 고정 수락의 고QD 성능 하락은 순환 수락 결과와 구분해서 해석해야 한다. 데이터 배치는 그대로 유지되므로 이 대조는 수락 정책의 효과를 보여 준다. 순환 수락이나 큰 QD만으로 배치가 나쁜 경우까지 최대 성능을 보장하지는 않는다. 본문 수치는 이 배치·부하·seed·측정 구간의 시뮬레이션 결과이며, 전역 최대값이나 무한 시간 정상 상태를 확정하지 않는다.','',
'## 검증·재현','',
'- 수락 순환, 빈 Port/QD/미래 도착 건너뛰기, 실패 시 포인터 유지, 동시 수락·Host 속도, 페이지 병합의5개 회귀 테스트를 추가했다. 전체96개 테스트가 통과했다.',
'- A1/A2/B/C1/C2의 기준 실행과 관측·최적화 실행5쌍에서 요청별 타임스탬프·카운터·버퍼 예약·시간축 일치를 확인했다.',
'- 7개 성능 측정에서 소스·snapshot·과거 결과 해시, 동일 Config, 수락−완료=outstanding, Port별 QD 상한,8MiB 용량, 주소 범위 및 시간창 집계를 검증했다.',
'- [원본 결과](../results/znand/die32_round_robin/summary.json), [검증](../results/znand/die32_round_robin/validation.json), [실행 manifest](../results/znand/die32_round_robin/manifest.json).','',
'```sh',
'python3 -B -m unittest discover -p "test_znand*.py"',
'python3 -B scripts/measure_die32_round_robin.py --workers 2',
'python3 -B scripts/report_die32_round_robin.py','```','',
'이전 고정 수락 원본은 보존했다. 당시 모델로 다시 실행하려면 변경 전 커밋 `87113d592f52773d9e11c6d7bde755a3ff350138`을 별도 checkout해야 한다. 과거 측정 스크립트·결과의 소스 해시는 현재 모델과 의도적으로 다르므로, 현재 모델로 과거 결과 파일을 덮어쓰면 안 된다.','']
(ROOT/'docs/21_die32_round_robin_ko.md').write_text('\n'.join(lines))
