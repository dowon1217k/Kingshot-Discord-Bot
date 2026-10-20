# 1단계 테스트 실패 전수 조사 및 재검증

조사일: 2026-10-20 (한국 시간). 작업 브랜치: `feature/korean-alliance-bot`. 비교 대상은 1단계 커밋 `104bced`와 그 기준 원본 `main` 커밋 `2eaa40b`입니다. 원격 main의 최신 상태를 임의로 기준으로 삼지 않았습니다.

**53개가 모두 HTTP 403 예외로 실패했다는 해석은 정확하지 않습니다.** 실제 테스트의 직접 예외는 53개 모두 `RuntimeError: External networking is forbidden in tests`였습니다. 필요한 모델이 없는 상태에서 테스트 중 다운로드를 시도했고, `104bced`에 추가된 `tests/conftest.py:109`의 오프라인 소켓 차단이 먼저 작동했습니다. 이 차단을 제거한 원본 표본과 별도 다운로드 요청에서는 프록시 CONNECT 단계의 HTTP 403이 확인됐습니다. 모델 서버 자체가 요청을 거절했다고 단정할 수 없습니다.

실제 OCR 정확도 검증은 아직 완료하지 못했습니다. 모델 누락을 명확히 검출하고 안전하게 준비할 도구를 추가했으나, 외부 접근 차단을 코드로 우회하지 않았습니다. 실패를 성공·skip·xfail로 바꾸지 않았습니다.

## 1. 실패 유형과 개수

| 직접 실패 유형 | 출석 OCR | 곰 사냥 OCR | 합계 |
|---|---:|---:|---:|
| A: 모델 미설치 → 다운로드 시도 → 테스트 외부 연결 차단 RuntimeError | 41 | 12 | 53 |
| OCR 출력값·이름 매칭·DB·한국어화의 assertion 실패 | 0 | 0 | 0 |

두 번째 행은 차단을 통과한 후에도 문제가 없다는 뜻이 아닙니다. 누락 모델이 필요한 추론/최종 assertion까지 도달하지 못했으므로 숨겨진 정확도 오류는 아직 확인할 수 없습니다.

최초로 다운로드가 막힌 모델 기준 세분류:

| 최초 누락 모델 | 개수 |
|---|---:|
| `en_PP-OCRv4_rec_mobile.onnx` | 50 |
| `chinese_cht_PP-OCRv3_rec_mobile.onnx` | 1 |
| `japan_PP-OCRv4_rec_mobile.onnx` | 1 |
| `korean_PP-OCRv4_rec_mobile.onnx` | 1 |
| 합계 | 53 |

53개 각각의 이름·파일·오류 메시지·다운로드 URL·수정 전 전체 traceback·원본 대조 결과·수정 후 오류는 [기계 판독용 증거](../tests/fixtures/ocr_audit/phase1_failure_audit.json)에 저장했습니다. 경로의 저장소/가상환경 접두사만 `<repo>`/`<venv>`로 정규화했습니다. 환경변수 값이나 토큰은 수집하지 않았습니다. 아래 목록의 모든 행을 traceback 및 JUnit 결과와 대조했습니다.

## 2. 정확한 발생 위치와 HTTP 403

재현된 경로:

```text
출석: tests/test_attendance_ocr_layer2.py:81 (104bced)
  → tests/harness_attendance.py:45 → bear_track.ocr_bytes
곰 사냥: tests/test_layer2_ocr.py → tests/harness.py:run_ocr_pipeline
  → _ocr_bytes_sync → bear_track.ocr_bytes
공통:
  cogs/bear_track.py:934 → onnx_lifecycle.LazyOnnxModel.use/acquire
  → cogs/bear_track.py:801 RapidOCR(params=...)
  → RapidOCR ONNX inference engine: model path resolution
  → rapidocr/utils/download_file.py:40 DownloadFile.run
  → rapidocr/utils/download_file.py:70 requests.get(url, stream=True, timeout=60)
  → requests → urllib3 → socket.connect
  → tests/conftest.py:109 RuntimeError: External networking is forbidden in tests
```

이 RuntimeError는 requests의 RequestException이 아니어서 라이브러리의 DownloadFileException 포장 이전에 그대로 전파됩니다.

테스트 소켓 차단 없이 원본의 `english_rank_top_001` 하나를 실행한 결과:

```text
http/client.py:1029 _tunnel
  OSError: Tunnel connection failed: 403 Forbidden
→ urllib3.exceptions.ProxyError / MaxRetryError
→ requests/adapters.py:723 requests.exceptions.ProxyError
→ rapidocr/utils/download_file.py:75 DownloadFileException:
  Failed to download https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.8.0/onnx/PP-OCRv4/rec/en_PP-OCRv4_rec_mobile.onnx
```

공식 모델 URL에 대한 curl HEAD와 사전 준비 도구의 실제 GET도 같은 CONNECT 403으로 실패했습니다. 샌드박스 밖 실행 권한으로 재시도해도 동일했습니다. 이는 HTTPS 대상에 연결하기 위한 프록시 터널이 거부된 것으로, 모델 원본의 HTTP 응답 또는 인증서 오류와 구분해야 합니다. TLS 검증은 계속 활성화했습니다.

모델 URL 공통 접두사:

`https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.8.0/onnx/PP-OCRv4/`

인식 모델은 `rec/<모델명>`, 검출은 `det/<모델명>`, 방향 분류는 `cls/<모델명>`입니다. 전체 URL과 공식 SHA256은 증거 JSON에도 있습니다.

## 3. 원본 main과 회귀 여부

원본은 `git archive 2eaa40b`로 `/tmp/kingshot-main-audit`에 읽기 비교용 소스 사본을 만들었습니다. Git worktree를 만들거나 main을 변경하지 않았습니다. Python·설치 라이브러리·모델 캐시·스크린샷·예상값을 동일하게 두고, 원본에 pytest 플러그인으로 같은 오프라인 소켓 차단을 적용했습니다.

| 조건 | 통과 | 실패 | 건너뜀 |
|---|---:|---:|---:|
| 원본 main, OCR 2개 파일, 동일 오프라인 정책 | 3 | 53 | 0 |
| 104bced 전체 재현 | 1,303 | 53 | 1 |
| 원본 main, 차단 fixture 없이 영문 OCR 표본 1개 | 0 | 1 (CONNECT 403 → DownloadFileException) | 0 |

두 소스에서 실패한 53개 nodeid와 최종 예외 메시지는 모두 일치했습니다. `get_ocr_model`, `ocr_bytes`, `_ocr_image_with_engine` 함수의 AST도 일치합니다. 원본 전체 테스트를 다 실행했다고 주장하지 않습니다. 비교 실행은 해당 OCR 파일들과 별도 네트워크 표본입니다.

판정: 한국어화로 OCR 계산 로직이 망가졌다는 증거는 없습니다. 다만 `104bced`가 오프라인 테스트 정책을 추가하면서 모델 사전 준비를 빠뜨린 것은 테스트 구성의 결함입니다. 원본 역시 이 환경의 정상 네트워크 경로에서는 모델을 받을 수 없었습니다. 실제 OCR 정확도 회귀 여부의 최종 판정은 모델 준비 후 동일한 통합 테스트를 재실행해야 가능합니다.

## 4. 라이브러리·모델·현재 캐시

이번 실행의 실제 버전은 Python 3.12.14, RapidOCR 3.8.4, ONNX Runtime 1.31.0입니다. requirements는 RapidOCR `>=3.8.1,<3.9` 범위입니다. 모델 이름의 PP-OCRv3/v4는 모델 계열이며 RapidOCR 패키지 버전과 다릅니다. 기본 검출·방향 분류 2개와 5개 언어 인식 모델을 사용합니다. 태국어 화면 fixture는 영문 숫자 인식 모델을 사용합니다. 한국어/일본어/중국어 fallback에도 영문 모델이 필요합니다.

| 모델 | 조사 시 상태 | RapidOCR 배포 메타데이터의 SHA256 |
|---|---|---|
| `ch_PP-OCRv4_det_mobile.onnx` | verified | `d2a7720d45a54257208b1e13e36a8479894cb74155a5efe29462512d42f49da9` |
| `ch_ppocr_mobile_v2.0_cls_mobile.onnx` | verified | `e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c` |
| `en_PP-OCRv4_rec_mobile.onnx` | missing | `e8770c967605983d1570cdf5352041dfb68fa0c21664f49f47b155abd3e0e318` |
| `ch_PP-OCRv4_rec_mobile.onnx` | verified | `48fc40f24f6d2a207a2b1091d3437eb3cc3eb6b676dc3ef9c37384005483683b` |
| `japan_PP-OCRv4_rec_mobile.onnx` | missing | `e1075a67dba758ecfc7ebc78a10ae61c95ac8fb66a9c86fab5541e33f085cb7a` |
| `korean_PP-OCRv4_rec_mobile.onnx` | missing | `ab151ba9065eccd98f884cf4d927db091be86137276392072edd4f9d43ad7426` |
| `chinese_cht_PP-OCRv3_rec_mobile.onnx` | missing | `779656d044ce388045e02ea9244724616194e63928606436cdfc6dc3c9528cc6` |

세 개의 기존 파일은 실제 SHA256을 검증했습니다. 나머지 네 개의 내용을 다른 모델로 대체하지 않았습니다. ONNX 내부 문자표를 사용하는 구성으로, 별도 인식 사전 다운로드는 현재 실패 지점이 아닙니다.

기존 pip 메타데이터 경고도 남아 있습니다. RapidOCR는 opencv-python을 의존성으로 선언하지만 원본 실행기는 opencv-python-headless로 교체합니다. cv2 import와 일반 테스트는 작동했고, 53개 traceback에는 이 경고가 직접 원인으로 나타나지 않았습니다. 이번 작업에서 의존성 선언을 바꾸거나 무관한 수정을 하지 않았습니다.

## 5. 실제 수정 내용

- `install/prepare_ocr_models.py`: 설치된 RapidOCR의 공식 URL/SHA256을 읽는 사전 준비 도구. 기본 실행은 로컬 확인만 하며 다운로드는 `--download`로 명시해야 합니다. `--source-dir`로 이미 보유한 로컬 파일을 검증·가져올 수도 있습니다. HTTPS/TLS 검증을 유지하고 HTTP redirect downgrade를 거부합니다. 임시 파일의 SHA256을 확인한 뒤에만 캐시를 교체하며 실패한 파일은 사용하지 않습니다.
- `tests/conftest.py`: 실제 이미지 추론 marker 등록 및 `cached_ocr_models` fixture. 네트워크 차단은 유지하고 모델이 없거나 손상되면 구체적인 OCRModelsUnavailable 예외로 실패합니다.
- `tests/test_layer2_ocr.py`, `tests/test_attendance_ocr_layer2.py`: 실제 통합 테스트임을 표시하고 모델 사전조건을 확인합니다. 이미지·예상값·추론·assertion은 삭제하거나 Mock으로 교체하지 않았습니다.
- `tests/test_ocr_model_assets.py`: 모의 HTTPS 응답/작은 바이트 fixture로 다운로드 opt-in, 검증된 로컬 복원, SHA256 불일치, HTTPS redirect, HTTP downgrade 거부, 403 보존, 캐시 보존/정리를 검사하는 13개 단위 테스트. 이 바이트를 진짜 ONNX로 사용하지 않습니다. 파서 경계 테스트는 OCR 결과만 명시적으로 모의합니다.
- `tests/README.md`: 준비/단위/통합 테스트 실행 방법과 결과 구분.
- 이 보고서와 `tests/fixtures/ocr_audit/phase1_failure_audit.json`: 전수 조사 증거.

애플리케이션 cogs, 한국어 번역, 실제 교환 비활성화 설정, DB 구조, API 상태값, Discord 컴포넌트 ID, LICENSE는 이번 조사에서 변경하지 않았습니다.

## 6. 수정 전후 전체 재실행

| 실행 | 통과 | pytest 실패 | 건너뜀 | 선택 제외 |
|---|---:|---:|---:|---:|
| 수정 전 104bced 전체 | 1,303 | 53 | 1 | 0 |
| 수정 후 전체 `python -m pytest tests -q -rs` | 1,316 | 53 | 1 | 0 |
| 수정 후 단위 범위 `python -m pytest tests -m 'not ocr_integration' -q -rs` | 1,316 | 0 | 1 | 53 |

수정 후 pytest 실패 53개는 전부 `OCRModelsUnavailable`이며, 이전과 같은 53개입니다. 새로 발생한 다른 실패는 0개입니다. 통과 수 +13은 새 단위 테스트 수이며 OCR 53개가 통과로 바뀐 것이 아닙니다.

중복 없는 의미상 집계: **검증 완료 통과 1,316 / 검증 assertion·코드 실패 0 / 기존 건너뜀 1 / 필수 모델 부재로 실제 OCR 검증 실행 불가 53 = 1,370개**. pytest의 exit code는 여전히 1이며 실행 불가 53개를 실패로 보고합니다. 전체 실행에서 이들을 deselect하거나 skip/xfail하지 않았습니다.

기존 건너뜀 1개는 `tests/test_python311_compat.py:128`의 별도 형제 저장소 `/workspace/bot` 부재 검사입니다. 현재 저장소의 Python 3.11 검사는 통과했습니다. SimCord UI suite는 원래 별도 `--sim` 실행 대상이며 이번 표의 기본 수집 범위에 포함되지 않습니다.

## 7. 남은 문제와 운영 영향

**53개를 해결 완료했다고 선언할 수 없습니다.** 공식 모델 서버로 향하는 프록시 경로가 막혀 있어 네 개의 검증된 모델을 확보하지 못했습니다. 모델이 준비되면 실제 이미지 통합 테스트가 그대로 실행되므로 가려져 있던 인식 정확도/파서 문제가 추가로 드러날 수 있습니다. 지금은 실제 OCR 검증 성공이나 100명 운영 준비 완료를 주장하지 않습니다.

한국어/영문 등의 이미지 기반 곰 사냥 피해량 추출과 출석·전투력 스크린샷 자동 집계가 해당됩니다. 일부 중국어 캐시가 있다고 전체 OCR이 작동하는 것도 아닙니다. UI가 다른 언어 fallback을 요청하면 같은 문제가 발생할 수 있습니다. UID 수동 등록·DB 관리·일정·알림은 이 모델을 요구하지 않습니다. 교환코드의 텍스트 인식 및 처리 로직은 모의 테스트를 통과했고 실제 교환 기본 비활성화는 유지했습니다. 게임 서버의 실제 보상 API·Discord 로그인·실제 100명 부하는 시험하지 않았습니다.

환경 설정의 기존 허용 목록을 보존하면서 `www.modelscope.cn`을 추가하는 초안을 저장했습니다. 초안 저장만으로 현재 네트워크가 바뀌거나 환경이 게시되는 것은 아닙니다. 환경 설정에서 검토·저장하고 환경을 게시한 후 다운로드를 재시도해야 합니다. 이후 실제 HTTPS redirect에 별도 목적지가 나타난다면 그 관찰 결과에 따라 추가 접근을 판단해야 합니다. 모델을 이미 갖고 있다면 외부 접근 없이 `--source-dir`로 복원할 수 있습니다.

준비 및 재검증 순서:

```bash
# 현재 프로젝트용 가상환경의 Python으로 실행
python install/prepare_ocr_models.py                  # 확인만, 누락이면 exit 1
python install/prepare_ocr_models.py --download       # 공식 HTTPS + SHA256
# 또는: python install/prepare_ocr_models.py --source-dir /path/to/verified-model-bundle
python -m pytest tests -m ocr_integration -q -rs
python -m pytest tests -q -rs
```

네트워크 차단을 풀기 위해 TLS·체크섬 검증을 끄거나, 다른 모델/기록된 결과로 실제 OCR 테스트를 위장하지 않습니다. 이 조사에서는 PR 생성·병합이나 2단계 기능 개발을 수행하지 않았습니다.

## 부록: 실패한 53개 전수 목록

아래의 A는 수정 전 `RuntimeError: External networking is forbidden in tests`를 뜻합니다. 출석 파일의 수정 전 진입 위치는 75~81행, 곰 사냥 파일은 95~105행입니다. 현재 파일의 동일 테스트에는 marker와 사전조건 호출만 추가됐습니다. 각 행의 전체 traceback과 현재 예외 메시지는 증거 JSON에 있습니다.

| 번호 | 파일 및 전체 테스트 이름 | 최초 다운로드 실패 모델 | 유형 및 main 대조 |
|---:|---|---|---|
| 1 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[alliance_showdown_001]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 2 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[alliance_showdown_002]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 3 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[alliance_showdown_003]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 4 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[alliance_showdown_004]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 5 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[alliance_showdown_005]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 6 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[alliance_showdown_006]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 7 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[alliance_showdown_007]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 8 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[alliance_showdown_008]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 9 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[canyon_clash_l1_001]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 10 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[canyon_clash_l1_002]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 11 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[canyon_clash_l1_003]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 12 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[canyon_clash_l2_001]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 13 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[canyon_clash_l2_002]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 14 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[canyon_clash_l2_003]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 15 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[canyon_registration_001]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 16 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[canyon_registration_002]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 17 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[canyon_registration_003]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 18 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[foundry_battle_l1_001]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 19 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[foundry_battle_l1_002]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 20 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[foundry_battle_l1_003]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 21 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[foundry_battle_l1_004]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 22 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[foundry_battle_l2_001]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 23 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[foundry_battle_l2_002]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 24 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[foundry_battle_l2_003]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 25 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[foundry_battle_l2_004]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 26 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[foundry_registration_001]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 27 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[foundry_registration_002]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 28 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[foundry_registration_003]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 29 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[power_rankings_001]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 30 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[power_rankings_002]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 31 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[power_rankings_003]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 32 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[power_rankings_004]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 33 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[power_rankings_005]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 34 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[power_rankings_006]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 35 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[power_rankings_007]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 36 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[power_rankings_008]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 37 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[power_rankings_009]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 38 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[power_rankings_010]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 39 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[power_rankings_011]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 40 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[power_rankings_012]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 41 | `tests/test_attendance_ocr_layer2.py::test_fixture_extraction[power_rankings_013]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 42 | `tests/test_layer2_ocr.py::test_fixture_extraction[chinese_simp_rank_top_001]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 43 | `tests/test_layer2_ocr.py::test_fixture_extraction[chinese_trad_rank_top_002]` | `chinese_cht_PP-OCRv3_rec_mobile.onnx` | A · 원본 동일 |
| 44 | `tests/test_layer2_ocr.py::test_fixture_extraction[english_personal_rewards_003]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 45 | `tests/test_layer2_ocr.py::test_fixture_extraction[english_rank_bottom_001]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 46 | `tests/test_layer2_ocr.py::test_fixture_extraction[english_rank_bottom_003]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 47 | `tests/test_layer2_ocr.py::test_fixture_extraction[english_rank_top_001]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 48 | `tests/test_layer2_ocr.py::test_fixture_extraction[english_rank_top_003]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 49 | `tests/test_layer2_ocr.py::test_fixture_extraction[english_summary_001]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 50 | `tests/test_layer2_ocr.py::test_fixture_extraction[english_summary_003]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 51 | `tests/test_layer2_ocr.py::test_fixture_extraction[japanese_summary_001]` | `japan_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 52 | `tests/test_layer2_ocr.py::test_fixture_extraction[korean_rank_bottom_001]` | `korean_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
| 53 | `tests/test_layer2_ocr.py::test_fixture_extraction[thai_rank_bottom_001]` | `en_PP-OCRv4_rec_mobile.onnx` | A · 원본 동일 |
