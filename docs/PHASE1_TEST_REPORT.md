# 1단계 검증 결과

실제 게임 서버로 보상 교환 요청을 보내지 않았습니다. 테스트에서는 외부 TCP 연결을 차단하고, 기존 모의 교환 테스트에서만 교환 분기를 활성화했습니다. 로컬 테스트 HTTP 서버는 허용합니다.

## 결과

| 검증 | 결과 |
|---|---|
| `python -m pytest tests -q` | 1,303 통과, 53 실패, 1 건너뜀 |
| OCR 이미지 2개 파일 제외 일반 회귀 테스트 | 1,300 통과, 1 건너뜀 |
| 마지막 안내 문구 변경 후 회원 등록·코드 감지·안전 기본값·검증 저장 회귀 테스트 | 46 통과 |
| 신규 `tests/test_korean_safety.py` | 21개 포함, 통과 |
| Python 3.11 문법 파싱, compileall | 통과 |
| `git diff --check`, 시작 셸 문법, Docker Compose 설정 검증 | 통과 |
| 기존 주요 모듈 SQL 리터럴·명시적 컴포넌트 ID 비교 | 동일 |
| LICENSE 원문 | 변경 없음 |

전체 테스트의 53개 실패는 모두 OCR 모델 다운로드가 테스트의 외부 연결 차단에 걸린 사례입니다. 필요한 모델 파일이 사전 설치되어 있지 않습니다. 별도로 모델 배포 URL에 TLS 검증을 유지한 HEAD 요청을 보냈으나 `www.modelscope.cn` 접근이 프록시에서 HTTP 403으로 거부됐습니다. 이를 통과한 테스트로 간주하지 않았습니다. 게임 API 요청과 무관합니다.

`pip check`에서는 RapidOCR가 요구하는 `opencv-python` 대신 기존 실행기의 자동 처리로 `opencv-python-headless`가 설치된 메타데이터 경고도 확인했습니다. 실제 일반 회귀 테스트는 위와 같이 통과했으나 OCR 준비 완료를 주장하지 않습니다.

기존 테스트에서 영어 문구를 검증하던 기대값은 한국어 문구로 갱신했습니다. API 오류 분류 테스트의 모의 HTTP 함수에는 리디렉션 차단 옵션을 추가했습니다. 기존 성공·실패 판정과 데이터 검증을 없애지 않았습니다.

## 재실행

가상환경에서 `pip install -r requirements.txt pytest`를 실행한 다음:

```bash
python -m pytest tests -q
python -m pytest tests -q --ignore=tests/test_layer2_ocr.py --ignore=tests/test_attendance_ocr_layer2.py
```

두 번째 명령은 OCR 이미지 추론 테스트를 제외합니다. 텍스트 파서·일반 출석·회원 관리·교환코드 테스트는 포함합니다. SimCord 화면 테스트는 별도 의존성과 `--sim` 옵션이 필요한 선택 테스트로 이번에는 실행하지 않았습니다. Docker 이미지를 빌드하거나 실제 Discord에 로그인하지 않았습니다.

실제 서버 연결·실제 수령·100명 부하 테스트 결과로 해석하면 안 됩니다. 운영사 허용 여부가 확인될 때까지 실제 교환은 기본 비활성화를 유지하세요.
