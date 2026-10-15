# 한국 연맹용 파생 버전 · 1단계

원본: kingshot-project/Kingshot-Discord-Bot. 원저작자 Reloisback 및 기존 기여자의 표시와 LICENSE를 보존합니다. 이 버전은 한국 연맹 운영을 위한 수정본입니다.

## 안전 기본값

- 실행: `python main.py --no-update`. 인자 없이 실행해도 업데이트하지 않습니다.
- `--autoupdate` 또는 `--repair`는 원본 소스를 덮어쓸 수 있습니다. 한국어 수정본에서는 사용하지 마세요.
- Docker 시작 스크립트는 UPDATE=1을 명시해야 업데이트합니다. Compose는 이 저장소를 직접 빌드합니다. 저장소 루트에서 `docker compose -f docker/docker-compose.yml up -d --build`로 실행할 수 있습니다. Docker 이미지 빌드는 이번 환경에서 실행 검증하지 않았습니다.
- 실제 교환은 기본 꺼짐입니다. 감지와 대기 코드 저장 기능은 유지됩니다. 성공으로 가장하지 않으며 기존 성공 기록을 바꾸지 않습니다.
- 운영사 허용 여부를 확인한 운영자만 서버 환경변수 `KINGSHOT_ENABLE_LIVE_REDEMPTION=1`을 설정해 재시작하세요. 검증과 왕국 탐색도 실제 게임 API를 쓰므로 함께 제어합니다.
- 코드 공유는 기본 꺼짐입니다. `KINGSHOT_ENABLE_CODE_SHARING=1`과 `KINGSHOT_CODE_SHARING_URL`의 검증된 HTTPS 주소를 모두 설정하고 재시작해야 합니다. HTTP 주소나 리디렉션으로 우회하지 않습니다. 기존 HTTP 서비스의 HTTPS 지원은 확인되지 않았습니다. 공유를 켜면 코드 업로드·삭제 요청도 수행될 수 있습니다.
- Player Sync의 외부 HTTP 주소와 외부 OCR의 HTTP 주소도 차단합니다. Player Sync의 로컬 개발 서버 주소만 HTTP를 허용합니다. HTTPS를 지원하지 않으면 서비스를 연결하지 마세요.

## 처음 실행

Python 3.12를 설치하고 저장소 폴더에서 가상환경을 만든 뒤 `pip install -r requirements.txt`를 실행합니다. Windows는 `bot_venv\Scripts\python.exe`, Linux는 `bot_venv/bin/python`으로 실행하세요.

봇 토큰은 서버의 `DISCORD_BOT_TOKEN` 환경변수로 주입하세요. 이 값이 없으면 기존 `bot_token.txt`도 지원합니다. `.env.example`은 설명용이며 `.env`를 자동으로 읽지는 않습니다. 실제 토큰을 예제 파일에 쓰지 마세요. Message Content Intent를 활성화하고 필요한 채널 권한을 부여하세요.

`/settings`에서 연맹·관리자·회원 등록 및 교환코드 채널을 설정합니다. 연맹장에게는 해당 연맹의 Alliance Admin 권한을 부여하세요. `교환코드: ABC123`, `쿠폰: ABC123`, `코드: ABC123`와 기존 `Code: ABC123`를 인식합니다.

`db/`, 로그, 백업은 개인정보입니다. 접근 권한을 제한하고 DB를 안전하게 백업하세요. 이미 Git에 추적된 비밀은 ignore로 지워지지 않습니다. 유출 시 토큰을 폐기·재발급하고 이력도 별도로 처리해야 합니다.

## 번역과 검증

한국어 문자열은 `cogs/locales/ko.json`, 조회 함수는 `cogs/i18n.py`에 있습니다. 1단계 핵심 화면을 우선 번역했으며 전체 메뉴 번역은 후속 작업입니다. API 상태값·DB 스키마·컴포넌트 ID는 번역하지 않습니다.

개발용 `pip install pytest` 후 `MALLOC_ARENA_MAX=2 python -m pytest tests -q`를 실행합니다. 테스트는 외부 소켓 연결을 차단하며 로컬 테스트 서버만 허용합니다. 기존 모의 교환 테스트는 테스트 fixture에서만 실제 교환 분기를 활성화하며 실제 서버에 연결할 수 없습니다.
