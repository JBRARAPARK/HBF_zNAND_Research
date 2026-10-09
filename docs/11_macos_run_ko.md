# Mac에서 모델 실행과 후속 분석

2026-10-09. Apple Silicon과 Intel Mac에서 저장소를 내려받아 기존 평가와 32/64Plane 추가 진단을 실행하는 절차다. 수치 모델·테스트·병렬 실행 확인은 Python 표준 라이브러리만 사용한다. 그래프 재생성에만 matplotlib이 필요하다.

## 처음 실행

Python 3.10 이상과 Git이 필요하다. Python은 python.org의 macOS 설치본 또는 이미 사용 중인 환경을 사용한다. 재현 환경으로는 Python 3.12 또는 3.13을 권장한다. `/usr/bin/python3`가 요구 버전보다 낮으면 별도 설치한 Python을 선택한다.

터미널에서 다음을 실행한다. 이 저장소는 비공개이므로 접근 가능한 GitHub 계정의 Git 인증이 필요하다.

```sh
git clone https://github.com/JBRARAPARK/HBF_zNAND_Research.git
cd HBF_zNAND_Research
bash scripts/macos.sh setup
bash scripts/macos.sh smoke
bash scripts/macos.sh diagnostics
```

이미 checkout이 있다면 그 폴더에서 `git pull --ff-only`로 최신 커밋을 받은 뒤 같은 스크립트를 실행한다. Git 인증이 필요하면 GitHub CLI의 `gh auth login`과 `gh auth setup-git` 또는 기존 SSH/Git Credential Manager 설정을 사용한다.

`setup`은 저장소의 `.venv`를 만들며 외부 패키지를 설치하지 않는다. 이후 명령은 이 가상환경의 Python을 직접 실행하므로 `source .venv/bin/activate`를 따로 하지 않아도 된다. 기존에 정상적인 `.venv`가 있으면 재사용한다.

## 명령과 결과

| 명령 | 수행 내용 | 결과 |
|---|---|---|
| `bash scripts/macos.sh check` | 주소 기반 모델 테스트 42개 | 터미널 통과/실패 |
| `bash scripts/macos.sh smoke` | 테스트 42개 + 32/64Plane의 명시적 spawn 병렬 실행을 직렬 실행과 비교 | 2개 짧은 검증, 설정·CSV·manifest |
| `bash scripts/macos.sh diagnostics` | 같은 A2 부하의 Buffer·tR·maintenance·32/64Plane 진단 6개 | 상세 JSON, CSV, 설정, 모델 해시와 검증 기록 |
| `bash scripts/macos.sh replay A2` | 기존 관측 최고 설정, port당 8,192개 요청 | 결과 JSON과 요청별 trace |
| `bash scripts/macos.sh layout` | 8/16Plane 주소 배치 비교 | Mac 기본 브라우저에서 로컬 그림 열기 |
| `bash scripts/macos.sh report` | 저장된 기존 평가 CSV로 그래프와 결과 보고서 재생성 | PNG 4개, Markdown, saturation CSV |
| `bash scripts/macos.sh sweep` | 기존 기본·민감도 조건과 저장된 MQSim 배치 비교 | 기본값으로 1,248개 조건 재실행 |
| `bash scripts/macos.sh extended` | 상위 QD 2,048/4,096/8,192 비교 | 기본값으로 240개 조건, port당 8,192개 요청 |

새 결과는 매번 `results/local/<날짜>-<명령>-<프로세스번호>/`에 만든다. 터미널의 `Output:` 줄에서 실제 경로를 확인한다. 공통 `execution.json`에는 실행 시각, Python 버전, 운영체제, CPU 아키텍처, Git 커밋, 추적 파일의 변경 여부와 모델 해시를 저장한다. 이 폴더와 `.venv`는 Git에서 제외하며, 기존 실험 CSV를 덮어쓰지 않는다. 보관할 후속 실험은 조건을 정리한 뒤 별도 결과 폴더로 옮겨 커밋한다.

`smoke`는 port당 64개 요청인 설치·병렬 실행 확인이다. 아래 성능 수치를 검증하려면 기본 `diagnostics`의 4,096개 조건을 실행한다. 스크립트에는 `/Users/...` 절대 경로나 Apple Silicon의 Homebrew 경로를 강제하지 않았으며, 경로에 공백이 있어도 인자를 인용해 전달한다.

## A2와 Plane 확장의 기준 수치

기본 `diagnostics`는 4port, 16KiB stripe, QD 2,048 per port, Prefetch ON, 정확도 1, lead 10µs, seed 7, port당 4,096개 4KiB 요청, port 간 주소 중첩 0%다. 실제 장치의 실측이 아닌 모델 결과다.

| 설정 | 총 Plane | 기존 모델 처리량 GB/s |
|---|---:|---:|
| Buffer 8MiB | 32 | 72.265081 |
| Buffer 32MiB | 32 | 37.116439 |
| Buffer 8MiB | 64 | 87.965665 |
| Buffer 32MiB | 64 | 68.720863 |

`replay A2`는 더 긴 8,192개 요청열이므로 비교 기준은 69.282479GB/s다. 요청열 길이가 다른 72.265081GB/s와 같은 실험으로 취급하지 않는다. 실행의 Python 버전과 모델 해시를 함께 확인한다. CPU가 빨라지면 시뮬레이션 완료 시간이 줄지만 모델의 Host/NAND 명목 대역폭 설정을 자동으로 바꾸지 않는다.

64Plane 두 조건만 실행하려면 다음을 사용한다.

```sh
bash scripts/macos.sh diagnostics --cases 64plane_8MiB 64plane_32MiB
```

## 그래프 재생성과 전체 평가

그래프가 필요할 때만 의존성을 설치한다.

```sh
bash scripts/macos.sh setup --plots
bash scripts/macos.sh report
```

`report`는 기존 `results/znand/full`과 `results/znand/extended` CSV를 읽어 새 출력 폴더에 보고서를 만든다. 추가 진단 6개는 별도 형식이며 문서 [08](08_host_if_bottleneck_ko.md)·[09](09_plane_expansion_layout_ko.md)와 해당 JSON/CSV로 확인한다. `report`가 새로운 성능 sweep을 실행하는 것은 아니다.

전체 1,488개 조건을 다시 계산하려면 다음 두 명령을 실행한다. 각각 새 폴더에 저장되며, 기본 worker 수는 2개다. 요청열이 길어 `smoke`보다 시간이 오래 걸린다.

```sh
bash scripts/macos.sh sweep --workers 2
bash scripts/macos.sh extended --workers 2
```

새 두 결과로 보고서를 만들려면 출력 경로를 지정한다. 아래 `NEW_FULL`과 `NEW_EXTENDED`는 각 명령의 `Output:`에 표시된 디렉터리로 바꾼다.

```sh
.venv/bin/python3 -m znand.report \
  --input NEW_FULL/sweep.csv \
  --extended NEW_EXTENDED/saturation.csv \
  --out results/local/new-full-report
```

이 보고서 생성기는 기존 full sweep의 모든 비교 그룹을 전제로 한다. `--quick` 또는 짧은 smoke 결과를 전체 보고서 입력으로 사용하지 않는다. `extended --per-port`는 실행 확인에 쓸 수 있지만 기존 성능 표의 8,192개 조건과 구분한다.

## Python과 저장 경로를 직접 선택

별도 설치한 Python을 쓰려면 `.venv`를 처음 만들 때 실행 파일을 지정한다.

```sh
ZNAND_PYTHON=/절대경로/python3.12 bash scripts/macos.sh setup
```

이미 만든 가상환경의 Python을 바꾸려면 새 가상환경 경로를 지정한다. 기존 폴더를 자동 삭제하거나 덮어쓰지 않는다.

```sh
ZNAND_PYTHON=/절대경로/python3.12 ZNAND_VENV=.venv-mac bash scripts/macos.sh setup
ZNAND_VENV=.venv-mac bash scripts/macos.sh smoke
```

`ZNAND_VENV`는 이후 실행에도 같은 값으로 지정한다. `.venv/`와 위 예시의 `.venv-mac/`는 Git에서 제외한다. 다른 이름으로 만든 가상환경은 필요하면 로컬 Git 제외 설정에 추가한다. 출력의 상위 폴더는 `ZNAND_RESULTS_DIR`로 바꿀 수 있다.

```sh
ZNAND_RESULTS_DIR="/절대경로/연구 결과" bash scripts/macos.sh diagnostics
```

## 확인한 범위

기존 수치 모델은 변경하지 않았다. macOS 기본 Bash 3.2에서 지원하는 문법으로 실행 스크립트를 작성했고, GNU 전용 `readlink -f`, `realpath`, `sha256sum`에 의존하지 않는다. Linux/Python 3.12.14에서 가상환경 생성, 모델 테스트 35개, 32/64Plane의 명시적 spawn 병렬 비교, 짧은 진단 6개, port당 16개인 상위 QD 240개 조건의 spawn 실행과 결과 검증을 통과했다. matplotlib 3.10.8로 그래프 4개를 재생성하고, 공백이 있는 저장소·가상환경 및 한글 출력 경로도 확인했다. 원본 모델과 입력 CSV의 해시가 유지되는 것을 확인했다. 실제 Mac의 실행 결과는 위 `smoke`와 `diagnostics`로 확인한다.

- [Python의 공식 macOS 실행 안내](https://docs.python.org/3/using/mac.html)
- [Python venv 공식 문서](https://docs.python.org/3/library/venv.html)
- [GitHub Git 인증 안내](https://docs.github.com/en/get-started/git-basics/caching-your-github-credentials-in-git)
