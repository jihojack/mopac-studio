# ⚛ MOPAC Studio

분자를 직접 그리고, MOPAC 계산을 실행하고, HOMO/LUMO 오비탈을 3D로 확인하는 **로컬 웹 앱**입니다. Windows에서 사용·검증했으며, 화면은 웹 브라우저에서 열립니다.

![MOPAC Studio의 3D 분자 편집 화면](docs/images/editor.png)

## 설치하기 — Windows

### 1. 소스 다운로드

[최신 소스 ZIP 다운로드](https://github.com/jihojack/mopac-studio/archive/refs/heads/main.zip) → 압축을 풀어 주세요. Git 사용자는 다음 명령으로 받을 수도 있습니다.

```powershell
git clone https://github.com/jihojack/mopac-studio.git
cd mopac-studio
```

### 2. Python 설치

[Python 공식 사이트](https://www.python.org/downloads/)에서 **Python 3.11 64-bit**를 설치합니다. 설치 화면에서 **Add python.exe to PATH**와 Python Launcher를 선택하면 편리합니다. 지원 범위는 Python 3.11~3.13이며 3.11을 권장합니다.

### 3. 앱 설치 및 실행

1. **`Install.bat`**를 더블클릭합니다. 이 폴더의 `.venv`에 필요한 패키지를 설치하고 **공식 오픈소스 MOPAC 23.2.5도 자동 설치**합니다. 최초 설치에는 인터넷이 필요합니다.
2. **`Start.bat`** 또는 **`MopacStudio 실행.bat`**를 더블클릭합니다.
3. 자동으로 열린 브라우저 탭에서 사용합니다. 주소는 `http://127.0.0.1:5005`부터 사용 가능한 포트가 선택됩니다.

`Start.bat`도 설치되지 않은 패키지와 엔진을 자동 설치하므로 바로 실행해도 됩니다. 시스템 Python이나 Windows의 전역 설정을 변경하지 않습니다. 이미 설치한 엔진은 무결성을 확인하고 재사용하므로 매번 다운로드하지 않습니다.

콘솔 창 없이 사용하려면 **`Start-Background.bat`** 또는 **`MopacStudio 백그라운드 실행.bat`**를 사용합니다. 백그라운드 서버는 브라우저 연결이 약 90초간 없으면 종료됩니다. 최초 패키지 설치 때는 설치 창이 표시됩니다.

### Chrome 탭 없이 독립 앱 창으로 실행

**`Start-Desktop.bat`** 또는 **`MopacStudio 앱 실행.bat`**를 실행하세요. 첫 실행 때 프로젝트 전용 환경에 pywebview를 추가 설치하고, 다음부터 주소창·브라우저 탭 없는 **MOPAC Studio 전용 창**을 엽니다. 기존 `Start.bat`의 브라우저 실행도 유지합니다.

- Windows 10/11의 **WebView2 Runtime**이 필요합니다. 대부분의 최신 Windows에는 설치되어 있으며, 없으면 [Microsoft 공식 WebView2 페이지](https://developer.microsoft.com/microsoft-edge/webview2/)에서 설치할 수 있습니다.
- 앱 창에서도 같은 3D 편집·MOPAC 계산·내보내기를 사용합니다. 창을 닫으면 해당 로컬 서버도 종료됩니다. 진행 중인 계산은 완료한 후 종료할 수 있습니다.
- 종료할 때 저장하지 않은 편집 내용이 사라질 수 있음을 확인합니다. 먼저 저장하거나 내보내세요.
- 최초 설치에만 콘솔 창이 잠깐 표시될 수 있으며, 실행 오류는 메시지와 `desktop_run.log`에서 확인할 수 있습니다.
- 현재는 Python 기반 전용 창 실행 방식입니다. Python이 필요 없는 설치형 `.exe` 패키지는 아직 만들지 않았습니다.

> 이제 MOPAC을 별도로 찾아 설치할 필요가 없습니다. 다운로드를 생략하고 편집기만 사용하려면 `python launcher.py --no-engine` 또는 `Start.bat --no-engine`으로 실행하세요. Python 패키지는 먼저 설치되어 있어야 오프라인으로 사용할 수 있습니다.

## MOPAC 자동 설치와 기존 엔진 사용

기본 설치 엔진은 [공식 MOPAC 23.2.5](https://github.com/openmopac/mopac/releases/tag/v23.2.5)이며 **Apache 2.0**으로 배포됩니다. 설치기는 공식 GitHub의 압축 파일을 다운로드하고, 저장소에 고정한 SHA-256으로 검증한 뒤 `_engines/`에 설치합니다. 배포본의 실행 파일·런타임·LICENSE·인용 정보를 그대로 보존합니다. 엔진 파일은 Git에 올리지 않습니다.

자동 설치는 **Windows/Linux x86-64**를 지원합니다. 기본 엔진 버전은 검증한 버전으로 고정되어 자동으로 최신 버전으로 바뀌지 않습니다. 체크섬과 다운로드 주소는 [engine_setup.py](engine_setup.py)에 있습니다. 손상된 설치는 재설치하되 이전 파일은 `_engines/` 안에 별도 보존합니다.

공식 엔진에서 구조 최적화·생성엔탈피·원자 전하·쌍극자·진동·분자오비탈 생성 경로를 실제 API로 검증했습니다. 두 분자가 포함된 시스템의 HOMO/LUMO Cube 생성도 검사합니다. 모든 계산 메뉴·모든 화학종의 정확성이나 수렴을 보장하는 검증은 아닙니다.

**이미 설치한 엔진을 계속 사용하려면** 다음 방법으로 명시적으로 지정하세요. `MOPAC_EXE`가 설정되어 있으면 자동 다운로드보다 우선합니다.

**방법 A — 환경 변수로 지정**

PowerShell에서 실제 설치 경로를 지정하고 같은 창에서 실행하세요.

```powershell
$env:MOPAC_EXE = 'C:\실제설치경로\MOPAC2016.exe'
python launcher.py
```

계속 사용하려면 Windows의 **환경 변수 편집 → 사용자 변수**에서 `MOPAC_EXE`에 실행 파일의 전체 경로를 등록한 뒤 앱을 다시 실행합니다. 필요한 DLL은 MOPAC 배포판의 원래 폴더 구조를 유지하세요.

**기존 포터블 폴더 구조도 지원**

```text
작업폴더/
├─ mopac-studio/
│  ├─ Start.bat
│  └─ app.py
└─ mopac2016/
   ├─ MOPAC2016.exe
   └─ ...배포판에 포함된 런타임 파일
```

엔진 검색 순서는 **`MOPAC_EXE` → 자동 설치한 엔진 → 기존 포터블 경로 → 시스템 PATH**입니다. 앱 내부의 `mopac2016/MOPAC2016.exe`도 검색합니다. 기존 MOPAC2016 파일은 변경하지 않습니다. 설치된 최신 엔진 대신 2016을 사용하려면 `MOPAC_EXE`를 지정하세요.

Linux x86-64에서는 `python3.11 launcher.py --setup-only`로 설치하고 `python3.11 launcher.py`로 실행할 수 있습니다. macOS/ARM은 자동 설치 대상이 아니므로 직접 설치한 엔진의 `MOPAC_EXE`를 지정하거나 `--no-engine`을 사용하세요.

## 처음 사용하기

### SMILES로 시작

왼쪽 SMILES 입력란에 `CCO`(에탄올), `O`(물), `c1ccccc1`(벤젠) 등을 입력하고 **생성**을 누릅니다. PubChem 이름/CID 검색도 지원하며, 검색에는 인터넷이 필요합니다.

### 구조 파일 여러 개를 일괄 계산

1. 탐색기에서 구조 파일 여러 개를 화면에 끌어다 놓습니다. 상단 **일괄 계산 → 구조 파일 선택**으로도 추가할 수 있습니다.
2. 자동으로 열리는 창에서 MOPAC 계산 항목, 전하, 공통 스핀다중도, COSMO 유전율을 선택합니다. 기본 항목은 평형 구조 계산입니다.
3. **선택한 파일 계산**을 누르면 파일별·계산별로 순서대로 실행하며 진행 상황과 실패 이유를 표시합니다. 실패한 파일도 목록에 남기고 나머지는 계속 진행합니다.
4. 완료 후 `workspace/exports/batch_*.zip`을 자동 저장합니다. **완료 후 ZIP 다운로드**가 선택돼 있으면 다운로드도 시작합니다. **결과 폴더 열기**로 저장 위치를 열 수 있습니다.

- 지원: XYZ, MOL, SDF, PDB, Cartesian MOP/DAT/ARC, Studio 내보내기 JSON. **SDF의 모든 레코드**를 따로 계산합니다. XYZ는 파일당 한 프레임을 사용하세요.
- 파일당 10 MB, 총 100 MB, 최대 200개 파일·500개 구조입니다. 같은 이름의 파일은 서로 다른 번호 폴더에 저장되어 덮어쓰지 않습니다.
- 파일에 들어 있는 좌표와 원자를 사용하며 **수소를 자동 추가하지 않습니다**. 수소가 포함된 계산용 구조를 준비하세요. Studio 편집 초안 JSON은 먼저 계산에 적용해 저장해야 합니다.
- 기본 전하는 MOL/SDF/PDB/JSON의 구조 전하이며 XYZ/MOP/DAT/ARC는 기본 0입니다. 이온이나 라디칼은 전하·공통 스핀다중도를 확인하고, 조건이 다른 파일은 나누어 실행하세요. **파일의 전하 사용**을 해제하면 입력한 공통 전하를 적용합니다.
- ZIP에는 원본 업로드, 구조별 입력 XYZ, 다시 열 수 있는 `session.json`, 전체 파일의 값을 모은 `results.csv`, 구조별 상세 CSV, MOPAC 입력·출력·오비탈 파일과 전체 성공/실패 `summary.csv`·`manifest.json`이 포함됩니다. 3D 캡처·Cube 등가면은 자동 생성하지 않습니다. 최적화 좌표는 각 결과의 `optimized_atoms`와 MOPAC 출력에 보관됩니다.
- 일괄 계산 창을 X로 닫아도 진행은 유지됩니다. 상단 버튼으로 다시 확인하세요. **현재 계산 후 중단**을 누르면 현재 MOPAC 항목이 끝난 뒤 남은 항목을 중단하고 완료된 결과 ZIP을 저장합니다. 앱 창은 계산·내보내기가 끝난 뒤 종료할 수 있습니다.
- 현재 편집 중인 구조·좌표·실행 취소 기록과 결과 패널은 일괄 계산으로 바뀌지 않습니다. 같은 서버에서는 한 번에 한 묶음을 실행하며, 페이지 새로고침 후 같은 브라우저에서는 최근 묶음의 진행 상태를 복원합니다. 서버가 종료된 작업은 재개되지 않으며 기존 파일은 `workspace/batches/`와 `workspace/runs/`에 남습니다.

### 원자와 결합을 직접 그리기

1. **화면에서 3D 그리기**를 누릅니다.
2. **원자 배치**에서 원소를 선택하고 빈 화면을 클릭합니다. 원자는 자동으로 결합하지 않습니다.
3. **결합**에서 결합 차수를 선택하고 원자 두 개를 차례로 클릭해 연결합니다.
4. **원자 이동**에서 원자를 드래그합니다. Shift+드래그는 깊이 방향이며 X/Y/Z축 고정도 가능합니다.
5. 필요하면 **결합 구조 정리 (MMFF/UFF)**를 사용합니다. 이 단계는 원래 배치한 좌표를 바꿀 수 있습니다.
6. **수소 추가 → 계산에 적용**을 누릅니다. 이 동작은 사용자가 배치한 원자의 좌표를 유지하면서 수소를 보완합니다.

Ctrl+Z와 **실행 취소**로 원자·결합 수정 및 이동을 되돌릴 수 있습니다. **원자 배치와 선택 원자 변경 모두 118개 원소**를 제공하며, 기호·한글 이름·원자번호를 표시합니다. Fe·Cu·Zn 등은 목록에서 바로 선택할 수 있습니다. 기본 PM7 지원 70개와 표시·편집용 48개를 나누어 표시합니다. 계산 범위는 [MOPAC 공식 PM7 원소표](https://openmopac.net/Manual/elements_in_PM7.html)를 따르며, 현재 계산 옵션에 없는 SPARKLE 모델과 특수 더미 원자는 자동으로 대신 사용하지 않습니다.

기존 12개 원소(H, B, C, N, O, F, Si, P, S, Cl, Br, I)는 수소를 자동 보완합니다. **금속 등 확장 원소에는 수소를 임의로 붙이지 않습니다.** 금속이 포함된 구조를 다시 편집할 때는 명시된 수소도 보존합니다. 단독 원자도 공으로 표시됩니다. MMFF/UFF 매개변수가 없는 구조는 입력 좌표를 유지하고 보정 불가를 안내합니다. 금속 배위결합·산화수·스핀 상태는 별도로 확인해야 하며, 현재 결합 도구는 단일·이중·삼중 결합을 지원합니다. 표시·편집용 원소는 저장·내보내기가 가능하며 기본 PM6/PM7 계산 요청 시 지원 범위를 안내합니다.

**편집기의 X는 현재 구조를 보존하고 닫기**입니다. 다시 열면 이어서 편집할 수 있습니다. 닫힌 편집 초안은 수소/원자가 검사가 끝나지 않았으므로 계산 버튼이 비활성화됩니다. 다시 열어 **계산에 적용**하세요.

편집 초안은 **현재 탭 메모리**에 보존됩니다. 새로고침·종료 전에 왼쪽 저장 버튼으로 파일을 남겨 주세요. 저장한 구조와 계산 결과는 `workspace/`에 보관되며 Git에 포함되지 않습니다.

### 구조·계산 정보 내보내기

상단 **내보내기**에서 다음 형식을 선택합니다. 파일은 `workspace/exports/`에 새 이름으로 저장되며 기존 파일을 덮어쓰지 않습니다.

| 형식 | 내용 |
|---|---|
| 전체 ZIP | XYZ·MOL·SDF 구조, 정밀 좌표·결과 JSON, 결과 CSV, 현재 3D 화면 PNG, 선택한 원본 계산 파일 |
| JSON | 현재 원자·좌표·명시된 결합·초안 상태·선택한 계산 결과. 파일 목록에서 다시 열어 구조를 복원할 수 있음 |
| XYZ | 원자와 좌표. 결합 정보는 포함하지 않음 |
| MOL / SDF | 원자 좌표와 명시된 결합. 파일 형식에 따라 좌표 소수 자릿수가 줄어들 수 있음 |
| CSV | 현재 결과 패널의 계산 값을 항목별 표로 저장. Excel에서 한글을 읽도록 UTF-8 BOM 포함 |
| PNG | 현재 3D 뷰어에 보이는 분자·오비탈·라벨·쌍극자 화면 |

내보내기는 수소를 추가하거나 구조를 재최적화하지 않습니다. 편집 중인 초안도 좌표와 결합을 그대로 저장합니다. **💾 빠른 저장**도 편집 중에는 JSON 초안을 저장하므로 계산에 적용할 필요가 없습니다.

ZIP의 계산 결과는 **현재 결과 패널에 표시된 카드 기준**입니다. `현재 결과 패널의 계산 정보 포함`과 `ZIP에 원본 계산 파일도 포함`을 선택할 수 있습니다. 표시된 구조와 각 계산의 입력/최적화 좌표는 다를 수 있으므로 원본 `.mop`과 JSON의 계산 입력도 함께 확인하세요.

### 파일 탐색기에서 열기

- 왼쪽 **폴더 열기**: 전체 `workspace` 저장 폴더를 엽니다.
- 파일 트리의 폴더 옆 **↗**: 해당 폴더를 엽니다.
- 계산 결과의 **계산 폴더 열기**: 해당 계산의 원본 파일 위치를 엽니다.
- 내보내기 완료 후 **저장된 파일 폴더 열기**: 만든 파일이 있는 폴더를 엽니다. **파일 다운로드**로 별도 사본을 받을 수도 있습니다.

### 계산과 오비탈 보기

**계산하기**에서 전체 전하·스핀 다중도와 계산 종류를 선택합니다. 결과 카드에서 HOMO, LUMO 등의 버튼을 누르면 해당 오비탈의 등가면을 표시합니다. 파랑과 빨강은 파동함수의 서로 반대 위상이며, 전하의 부호를 뜻하지 않습니다. 등가면 슬라이더로 표시 범위를 조절할 수 있습니다.

주요 계산: 구조 최적화, 생성엔탈피, 원자 전하, 쌍극자, 결합차수, 분자오비탈, 진동·IR, 열화학, 용매화 등 22개 메뉴. IP/EA 일부 값은 오비탈 에너지 기반 근사이며, 전이상태·IRC에는 적절한 초기 구조가 필요합니다. pKa 메뉴는 PM6를 사용합니다. 메뉴가 제공된다고 모든 분자·조건에서 수렴하는 것은 아닙니다.

### 여러 분자 배치

서로 연결하지 않은 여러 분자를 배치하고 **분자 조각 이동**으로 상대 위치를 조절할 수 있습니다. 모든 원자는 한 시스템으로 계산에 들어갑니다. 화면은 선택한 **MO 하나**를 표시하므로, 분자 간 거리가 멀면 오비탈이 한 분자 쪽에만 나타날 수 있습니다. 다른 MO를 선택하면 반대쪽에 나타날 수 있습니다.

각 분자의 HOMO를 자동으로 동시에 표시하거나 상호작용 에너지 `E(복합체) − ΣE(단독 분자)`를 자동 산출하는 기능은 아직 없습니다.

## 문제 해결

| 증상 | 확인할 내용 |
|---|---|
| `python`을 찾을 수 없음 | Python 3.11 64-bit 설치 및 PATH/Python Launcher 설정 |
| 패키지 설치 실패 | 인터넷 연결 확인 후 설치 창의 오류를 확인하고 `Install.bat` 재실행 |
| MOPAC 다운로드/체크섬 오류 | 인터넷 연결을 확인하고 `Install.bat` 재실행. 편집기만 쓰려면 `--no-engine` 사용 |
| MOPAC 실행 파일을 찾을 수 없음 | `Install.bat` 재실행. 직접 지정한 경우 `MOPAC_EXE` 경로 확인 |
| MMFF/UFF 정리 실패 | 현재 초안은 유지됩니다. 겹친 원자·비정상 결합 거리를 수정하고 재시도 |
| 수소 보정 생략 경고 | 입력 원자의 좌표는 유지됩니다. 수소 배치를 확인하고 계산에 적용 |
| 편집기 API 404 | 오래된 서버 탭을 닫고 현재 폴더의 실행 버튼으로 새로 열린 주소 사용 |
| 수정 후에도 예전 오류 발생 | 구조를 저장하고 실행 중인 서버를 종료한 뒤 재실행. 브라우저 새로고침만으로 Python 코드는 교체되지 않습니다 |
| 백그라운드 실행 문제 | `app_run.log` 확인 또는 `Start.bat`로 실행해 오류 확인 |
| 앱 창이 열리지 않음 | `desktop_run.log`와 WebView2 Runtime 확인. `Start.bat` 브라우저 모드 사용 가능 |

외부 Avogadro는 선택 기능입니다. 기본 설치 경로 외에는 `AVOGADRO_EXE` 환경 변수로 실행 파일을 지정할 수 있습니다. 내장 3D 편집기는 Avogadro 없이 작동합니다.

앱은 `127.0.0.1`에서 로컬 파일을 읽고 계산을 실행하는 개인용 도구입니다. 공개 서버 배포와 사용자 인증 기능은 제공하지 않습니다.

## 개발 및 테스트

```powershell
python launcher.py --setup-only
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

선택적인 브라우저 회귀 테스트는 Node.js 및 Playwright 설치 후 실행합니다. 앱은 별도 창에서 먼저 실행하세요.

```powershell
npm install --no-save --package-lock=false playwright
npx playwright install chromium
node tests/browser_recovery.cjs http://127.0.0.1:5005
node tests/browser_export.cjs http://127.0.0.1:5005
node tests/browser_batch.cjs http://127.0.0.1:5005
node tests/browser_elements.cjs http://127.0.0.1:5005
```

앱 서버가 다른 포트를 골랐다면 실제 주소를 사용하세요. 설치된 Chrome/Edge를 쓸 때는 `MOPAC_BROWSER`에 실행 파일 전체 경로를 지정할 수 있습니다. Node.js와 Playwright는 일반 앱 사용자에게 필요하지 않습니다.

GitHub Actions는 Windows/Linux 및 Python 3.11/3.12에서 Python 테스트와 JavaScript 구문 검사를 실행합니다. 두 운영체제의 Python 3.11 작업은 공식 MOPAC 자동 설치와 실제 API 계산·HOMO/LUMO 생성 통합 테스트도 수행합니다.

실제 엔진 통합 테스트만 실행하려면:

```powershell
python engine_setup.py
$env:RUN_MOPAC_INTEGRATION = '1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_mopac_integration.py -v
```

## 파일 구성

```text
app.py                 로컬 서버와 API
launcher.py            독립 환경 생성·의존성 설치·실행
engine_setup.py        공식 MOPAC 다운로드·체크섬 검증·독립 설치
structure.py           SMILES/PubChem/파일 구조 변환
editor_3d.py            직접 그린 구조 검증·수소 추가·안전한 힘장 보정
element_data.py         공통 원소 목록·한글 이름·기본 PM7 지원 범위
mopac_runner.py        MOPAC 실행 파일 검색·입력 생성·실행·결과 파싱
batch_calculations.py   구조 파일 일괄 계산·진행 기록·결과 ZIP 생성
mo_cube.py             MGF 오비탈 → Cube 변환
static/                3Dmol.js, 편집기 및 화면 코드
templates/             앱 화면
tests/                 Python·브라우저 회귀 테스트
workspace/             사용자 구조 및 계산 결과 (Git 제외)
```

버전과 수정 이력은 [CHANGELOG.md](CHANGELOG.md), 포함된 외부 코드의 고지문은 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 확인하세요.

## English quick start

MOPAC Studio is a local browser interface for molecular drawing, MOPAC calculations, and orbital isosurfaces. On Windows, install **64-bit Python 3.11**, download and extract this repository, then run **Install.bat** and **Start.bat**. Python dependencies are installed into a project-local `.venv`, and the official **MOPAC 23.2.5** engine is downloaded, SHA-256 verified, and installed automatically into `_engines/`.

Automatic engine installation supports **Windows/Linux x86-64**. The official distribution's license and runtime files are preserved; engine binaries are not committed to Git. Real-engine API tests cover geometry, energy, charges, dipole, vibrations and HOMO/LUMO generation. Existing MOPAC2016 installations can still be selected using `MOPAC_EXE`. Use `--no-engine` for editor-only use or to skip engine downloads. Save your draft before refreshing or closing the browser.
