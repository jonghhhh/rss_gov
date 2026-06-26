# 대한민국 정부부처 RSS 실시간 수집기

대한민국 정책브리핑(korea.kr) 통합 RSS를 이용해 전 부처·청·위원회의 보도자료와 소식을
실시간 수집한다. 모든 피드 URL은 2026년 정부조직 개편을 반영한 공식 목록 기준이며,
`verify` 명령으로 작동 여부를 직접 검증한 뒤 사용한다.

> **핵심 한 줄**: RSS는 "최신분 + 켜둔 동안 누적"을 모으는 도구다. 과거 소급 수집(백필)은 RSS 구조상 불가능하다.

이 저장소는 두 가지로 쓸 수 있다.
1. **웹 뷰어(`index.html`)** — 설치 없이 브라우저에서 바로 실시간 모아보기. 기자용.
2. **CLI 수집기(`gov_rss_collector.py`)** — DB 저장·CSV 내보내기·첨부 다운로드 등 연구·코퍼스용.

---

## 🌐 웹 뷰어 (GitHub Pages) — 설치 불필요

**바로 사용**: <https://jonghhhh.github.io/rss_gov/>

`index.html` 하나로 동작하는 정적 웹앱이다. 서버·DB 없이 **브라우저에서 직접** korea.kr 통합 RSS를
받아 화면에 모아 보여준다(데이터를 저장하지 않는다).

기자용 실시간 뷰어로, 다음을 지원한다.
- **부처 복수 선택**: 부처·청·위원회를 체크박스로 자유롭게 다중 선택.
- **주제별 / 전체 선택**: 사회·경제·문화·외교안보·행정일반 버튼으로 일괄 선택, "전체 선택"도 가능.
- **키워드 포함/제외 필터**: 제목+본문 기준.
- **요약 → 본문 펼치기**: 카드에 요약을 보여주고, 클릭하면 본문 전문을 펼친다.
- **첨부 파일 URL 명기**: 본문을 펼치면 상세페이지를 즉석에서 읽어 hwpx/pdf **다운로드 URL**을 표기한다
  (파일을 내려받지는 않고 링크만 보여준다).
- **최신순 통합·중복 제거**: 여러 피드를 합쳐 게시 시각 최신순 정렬, `guid`로 중복 제거.
- **자동 새로고침**: 1·3·5·10분 주기로 갱신, 새 항목은 `NEW` 배지 표시.

> **CORS 우회**: korea.kr RSS는 교차출처 헤더(CORS)를 주지 않으므로, 브라우저에서 직접 받을 수 없다.
> 웹앱은 공개 CORS 프록시(corsproxy.io / allorigins)를 거쳐 받으며, 실패 시 다음 프록시로 자동 재시도한다.
> 프록시는 무료 공용 서비스라 가끔 느리거나 일부 피드가 실패할 수 있다(여러 부처를 한 번에 받을 때 일부 누락 가능).

### 로컬에서 열기
정적 파일이라 더블클릭으로도 열리지만, 일부 브라우저의 `file://` 보안정책 때문에 간단한 로컬 서버 권장.
```bash
python -m http.server 8000   # → http://localhost:8000 접속
```

---

## CLI 설치
```bash
pip install -r requirements.txt
```

## 명령 한눈에 보기
| 명령 | 끝나나? | 설명 |
|------|---------|------|
| `verify` | 끝남 | 전체(또는 선택) 피드의 작동 여부·항목 수·최신 게시일 점검 |
| `once`   | 끝남 | **1회만** 수집 후 종료 |
| `run`    | **안 끝남** | 지정 주기로 무한 모니터링(상주 프로세스, 기본 600초) |
| `enrich` | 끝남 | DB에 쌓인 미보강 보도자료의 첨부파일·부처코드 일괄 보강(backfill) |
| `export` | 끝남 | DB → CSV(`utf-8-sig`, 엑셀 호환) 내보내기 |
| `list`   | 끝남 | 사용 가능한 피드·주제 그룹 목록 출력 |

---

## 예시와 주의사항

### 1) 전 피드 작동 검증 — 항상 가장 먼저
```bash
python gov_rss_collector.py verify
```
64개 피드의 상태·항목 수·최신 게시일을 표로 보여준다. 죽은 피드가 섞여 있으면
이후 수집에서 각 15초씩 타임아웃을 기다려 느려지므로, `--all` 수집 전 한 번 걸러두면 체감 속도가 다르다.

### 2) 전 부처 보도자료 통합 피드 1회 수집(기본값)
```bash
python gov_rss_collector.py once
```
인자를 안 주면 전 부처 보도자료 통합 피드(`pressrelease.xml`) 하나만 받는다.

### 3) 사회분야 부처만 10분 주기 모니터링
```bash
python gov_rss_collector.py run --theme 사회 --interval 600
```
`run`은 **끝나지 않는 상주 프로세스**다. 초기 동기화 후 600초마다 새 항목만 추가한다.
한 번만 받고 끝내려면 `once`를 쓴다. 종료는 `Ctrl+C`(현재 주기 마무리 후 안전 종료).

### 4) 특정 부처 + 키워드 필터 — `--feeds`의 정체와 중복 주의
```bash
# (A) 전 부처를 받되 키워드로 거른다 → 통합 피드만
python gov_rss_collector.py run --feeds 보도자료 --keywords 저출생 연금

# (B) 딱 이 두 부처만 본다 → 부처 피드만
python gov_rss_collector.py run --feeds 보건복지부 고용노동부 --keywords 저출생 연금
```
**`--feeds` 뒤에 오는 것은 "피드명" 목록**이다. 단, 성격이 다른 두 종류가 있다.
- `보도자료` = **전 부처 통합 피드**. 모든 부처 자료가 `[부처명]` 접두어와 함께 한 피드에 들어온다.
- `보건복지부`, `고용노동부` = **부처별 개별 피드**.

⚠️ `보도자료`와 부처 피드를 **함께 넣으면 중복 요청**이 된다(통합 피드에 이미 그 부처 자료가 포함됨).
DB에는 `guid` UNIQUE 제약 덕에 중복 적재되지 않지만, 같은 자료를 두 번 받아 비효율적이다.
키워드가 어느 부처에서 나올지 모르면 (A), 모니터링 대상 부처가 확실하면 (B)를 쓴다.
(`--theme 사회`는 사실 (B) 방식의 12개 부처 묶음이다.)

> **`--keywords`는 기간이 아니라 내용 필터다.** 받아온 항목 중 제목·본문 전문에 키워드가 있는 것만
> 남길 뿐, 수집 기간을 넓히지 않는다.

### 5) 슬랙/텔레그램 알림 — 신규 보도자료를 메신저로 푸시
```bash
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T.../B.../XXXX"
python gov_rss_collector.py run --theme 사회 --notify
```
환경변수가 설정된 채널로만 전송되며, 슬랙·텔레그램 둘 다 설정하면 동시 전송된다.
메시지 형식은 `[부처명] 제목` + 링크.

- **왜 환경변수인가**: 웹훅 URL·봇 토큰은 비밀값이라 코드에 박으면 안 된다. 미설정 시 알림은 그냥 건너뛴다.
- **초기 동기화는 알림을 보내지 않는다**: `run`을 처음 켜면 기존 수십 건이 조용히 기준선으로 적재되고,
  **그 이후 주기의 진짜 신규만** 알림이 간다(폭탄 방지). 반대로 `once --notify`는 기준선 개념이 없어
  빈 DB에서 쓰면 한꺼번에 쏟아진다 → `once`(알림 없이)로 채운 뒤 `run --notify`로 넘어가는 게 안전하다.
- **스팸 방지**: 전 부처를 `--notify`로 걸면 하루 수백 건이다. **키워드 필터와 함께** 쓰는 것이 실용적이다.
  ```bash
  python gov_rss_collector.py run --theme 사회 --keywords 저출생 연금 돌봄 --notify
  ```
- **전송 실패해도 수집은 계속된다**: 알림 오류는 경고 로그만 남기고 데이터 수집은 멈추지 않는다.

#### 슬랙 웹훅 발급
1. `api.slack.com/apps` → **Create New App** → From scratch → 앱 이름·워크스페이스 선택
2. **Incoming Webhooks** 토글 **On**
3. **Add New Webhook to Workspace** → 알림 받을 채널 선택 → 허용
4. 생성된 `https://hooks.slack.com/services/...` URL을 `SLACK_WEBHOOK_URL`에 넣는다
   (웹훅 하나가 채널 하나에 묶이므로, 채널을 나누려면 웹훅을 별도 발급)

#### 텔레그램 봇 설정 (토큰 + chat_id 둘 다 필요)
```bash
export TELEGRAM_BOT_TOKEN="123456789:ABCdef_your_token"
export TELEGRAM_CHAT_ID="987654321"
python gov_rss_collector.py run --theme 사회 --notify
```
1. **봇 토큰**: 텔레그램에서 `@BotFather` → `/newbot` → 이름·아이디 지정 → 토큰 발급
2. **chat_id**: 봇과 대화창을 열고 아무 메시지나 한 번 보낸 뒤(봇이 먼저 말을 못 걸어 필수),
   브라우저에서 `https://api.telegram.org/bot<토큰>/getUpdates` 접속 → `"chat":{"id": ...}` 값.
   개인은 양수, 그룹은 음수. (대안: `@userinfobot`에게 말 걸어 본인 id 확인)

### 6) 본문 전문 + 첨부 메타데이터까지(연구 코퍼스용)
```bash
python gov_rss_collector.py once --theme 사회 --full
```
`--full`은 신규 항목마다 상세페이지를 추가로 받아 첨부파일(hwpx/pdf) 메타데이터와 부처코드를 보강한다.
**본문 전문 자체는 `--full` 없이도 저장된다**(RSS `description`에 전문이 들어 있어 `content_full`에 적재).
`--full`은 어디까지나 "첨부 목록·다운로드 URL" 보강용이다.

### 7) 첨부파일(hwpx/pdf) 실제 다운로드까지 — ⏱️ 가장 무거운 조합
```bash
python gov_rss_collector.py once --full --download-files --files-dir corpus
```
**이 조합이 가장 오래 걸린다.** 항목마다 ① 상세페이지 요청(+0.4~1초 지연) ② 첨부 원본 파일 다운로드가
모두 일어나기 때문이다. 예컨대 첫 실행에서 50건·각 1~2첨부면 상세요청 50회 + 파일 70~100개 +
수십 MB 트래픽으로 **수 분**이 걸릴 수 있다.

권장 운용은 **"수집은 가볍게, 첨부는 나중에 분리"**다.
```bash
# (1) 평소엔 가볍게 수집 — 본문 전문은 어차피 RSS에 있음
python gov_rss_collector.py run --theme 사회 --interval 600

# (2) 한가할 때 첨부·코드만 일괄 보강(원본 다운로드 포함)
python gov_rss_collector.py enrich --limit 200 --download-files --files-dir corpus
```

### 8) 코퍼스 내보내기: 본문 전문 + 첨부 목록
```bash
python gov_rss_collector.py export --out gov_news.csv --full --attachments
#   → gov_news.csv             (본문 전문 content_full 포함)
#   → gov_news_attachments.csv (첨부 목록 별도)
```

---

## 수집 "기간"에 대한 중요한 이해

이 도구는 **기간을 지정해 과거를 긁어오는 백필러가 아니다.** RSS 피드는 항상 **최신 N건만** 담는
슬라이딩 윈도우이고, korea.kr 통합 보도자료 피드는 대략 최근 수십 건(체감 하루이틀치)만 노출한다.

- **첫 실행**: 그 순간 피드에 있는 최신분을 기준선으로 적재
- **이후**: 주기마다 다시 받아 **이전에 못 본 새 항목만** 추가

즉 수집 범위 = "프로그램이 켜져 있는 동안 피드를 거쳐 간 모든 항목". **켜두는 한 계속 누적**되지만
**켜기 전 과거는 못 가져온다.** 과거 한 달치 소급이 목표라면 RSS가 아니라 korea.kr 검색 결과
페이지네이션을 긁는 별도 수집기가 필요하다.

---

## "너무 오래 걸려요" 체크리스트
1. **`run`은 원래 안 끝난다** — 무한 모니터링 모드다. 단발이면 `once`를 쓴다.
2. **`--full` / `--download-files`를 뺀다** — 상세페이지 크롤링·파일 다운로드가 가장 큰 비용이다.
   첨부는 `enrich`로 분리한다.
3. **피드 범위를 좁힌다** — 피드마다 0.4~1초 지연이 있어 `--all`(64개)은 한 주기 30~60초다.
4. **`verify`로 죽은 피드를 먼저 걸러낸다** — 죽은 피드는 15초씩 타임아웃을 기다려 체감 지연의 주범이다.
5. (정 급하면) 코드 상단 `FETCH_DELAY_RANGE = (0.4, 1.0)`을 줄일 수 있으나 서버 예의상 권하지 않는다.

---

## 운용 팁 — 환경변수 영속화
`export`는 현재 셸 세션에서만 유효하다(터미널 닫으면 사라짐). 상시 운용 시 셋 중 하나를 쓴다.
- **`.env` 파일**: 키를 모아두고 실행 직전 `set -a; source .env; set +a`. `.env`는 반드시 `.gitignore`에 추가.
- **systemd 서비스**: 24시간 운용이면 `Environment=` 항목에 키를 넣어 데몬 등록(재부팅에도 복원).
- **cron**: 주기 실행이면 crontab 상단에 변수 정의.

---

## 핵심 설계
- **피드 카탈로그**: 통합 콘텐츠 10종 + 부처 26 + 청 18 + 위원회 10 = 총 64개 피드 내장.
- **부처 자동분류**: 통합 피드 제목의 `[부처명]` 접두어를 정규식으로 추출.
- **본문 전문**: RSS `description`에 본문 전체가 들어 있어 `content_full`에 저장(`summary`는 미리보기 앞 300자).
- **상세페이지 보강(`--full`/`enrich`)**: 첨부파일(hwpx/pdf)의 파일명·유형·다운로드 URL·`fileId`/`tblKey`와
  부처코드(`repCode`)를 `attachments` 테이블에 적재. 첨부 링크는 `download.do?fileId=...`의 `fileId`
  기준으로 그룹화해 중복(바로보기/내려받기)을 제거한다.
- **첨부 다운로드(`--download-files`)**: hwpx/pdf 원본을 `--files-dir`에 저장하고 로컬 경로를 DB에 기록.
- **중복 방지**: 뉴스는 `guid`, 첨부는 `(guid, file_id)` UNIQUE 제약. 재실행해도 신규만 적재.
- **조건부 GET**: 피드별 `ETag`/`Last-Modified`를 캐시해 304(변경없음) 시 트래픽 절감.
- **하위호환**: 구버전 DB는 실행 시 신규 컬럼이 자동 추가(ALTER)된다.
- **예의 크롤링**: User-Agent 명시, 타임아웃, 피드/요청 간 무작위 지연(0.4~1.0초).
- **주제 그룹**: 사회/경제/문화/외교안보/행정일반 — korea.kr 주제 분류 기준.

## DB 스키마
- `news(guid PK, feed_name, dept, title, link, published, summary, content_full, repcode, enriched, collected_at)`
- `attachments(file_id, guid, tbl_key, file_name, file_type, download_url, viewer_url, local_path, PK(guid,file_id))`
- `feed_cache(feed_name PK, etag, modified, last_checked)`

## 코퍼스 활용 메모
- 본문 텍스트는 **공공누리 1유형(출처표시)** 으로 자유이용 가능(단, 사진·동영상 등은 별도 권리 확인 필요).
- hwpx 본문 텍스트가 필요하면 다운로드 파일을 별도 파싱한다(예: `python-hwpx`/`hwp5`/`olefile` 등).
  RSS 전문(`content_full`)만으로도 대부분의 텍스트 분석에는 충분하다.

## 주의
- korea.kr는 부처별 사이트 RSS가 폐기·이전된 경우가 많아도 **통합 RSS로 일원화**되어 안정적이다.
  따라서 부처 개별 홈페이지 RSS 대신 본 통합 피드를 신뢰 출처로 사용한다.
- 피드 구조나 부처명은 정부조직 개편 시 변할 수 있으므로 주기적으로 `verify`로 점검한다.
- 첨부 파서는 상세페이지의 `download.do` 링크 패턴에 의존한다. korea.kr이 다운로드 URL 구조를 바꾸면
  코드의 `DOWNLOAD_RE` 정규식 조정이 필요하다.
