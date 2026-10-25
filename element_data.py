"""Shared editor palette and standard PM6/PM7 element coverage.

MOPAC coverage: https://openmopac.net/Manual/elements_in_PM7.html
Lanthanide SPARKLE models and special dummy/sparkle symbols are not enabled
by Studio's default calculation options. Display support is independent.
"""
from rdkit import Chem

AUTO_H_ELEMENTS = frozenset(('H', 'B', 'C', 'N', 'O', 'F', 'Si', 'P', 'S', 'Cl', 'Br', 'I'))
_NAMES = '''수소 헬륨 리튬 베릴륨 붕소 탄소 질소 산소 플루오린 네온
나트륨 마그네슘 알루미늄 규소 인 황 염소 아르곤 칼륨 칼슘
스칸듐 타이타늄 바나듐 크로뮴 망가니즈 철 코발트 니켈 구리 아연
갈륨 저마늄 비소 셀레늄 브로민 크립톤 루비듐 스트론튬 이트륨 지르코늄
나이오븀 몰리브데넘 테크네튬 루테늄 로듐 팔라듐 은 카드뮴 인듐 주석
안티모니 텔루륨 아이오딘 제논 세슘 바륨 란타넘 세륨 프라세오디뮴 네오디뮴
프로메튬 사마륨 유로퓸 가돌리늄 터븀 디스프로슘 홀뮴 어븀 툴륨 이터븀
루테튬 하프늄 탄탈럼 텅스텐 레늄 오스뮴 이리듐 백금 금 수은
탈륨 납 비스무트 폴로늄 아스타틴 라돈 프랑슘 라듐 악티늄 토륨
프로트악티늄 우라늄 넵투늄 플루토늄 아메리슘 퀴륨 버클륨 캘리포늄 아인슈타이늄 페르뮴
멘델레븀 노벨륨 로렌슘 러더포듐 더브늄 시보귬 보륨 하슘 마이트너륨 다름슈타튬
뢴트게늄 코페르니슘 니호늄 플레로븀 모스코븀 리버모륨 테네신 오가네손'''.split()
assert len(_NAMES) == 118
_PT = Chem.GetPeriodicTable()
ELEMENTS = tuple({'number': z, 'symbol': _PT.GetElementSymbol(z), 'name': _NAMES[z-1],
                  'radius': _PT.GetRcovalent(z), 'auto_h': _PT.GetElementSymbol(z) in AUTO_H_ELEMENTS,
                  'pm7': z <= 57 or 71 <= z <= 83}
                 for z in range(1, 119))
ELEMENT_SYMBOLS = frozenset(e['symbol'] for e in ELEMENTS)
STANDARD_MOPAC_ELEMENTS = frozenset(e['symbol'] for e in ELEMENTS if e['pm7'])


def unsupported_elements(mol):
    return sorted({a.get('symbol', '') for a in mol.get('atoms', [])} - STANDARD_MOPAC_ELEMENTS)
