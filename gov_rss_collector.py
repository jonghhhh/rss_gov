#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gov_rss_collector.py
대한민국 정부부처 보도자료·소식 실시간 RSS 수집기

- 출처: 대한민국 정책브리핑(korea.kr) 통합 RSS (https://www.korea.kr/etc/rss.do)
- 모든 피드 URL은 2026년 정부조직 개편 반영 공식 목록 기준이며, verify 명령으로 작동 여부를 검증한다.
- SQLite 영구 저장 + 중복 방지, 주제/키워드 필터, 조건부 GET(ETag/Last-Modified),
  슬랙·텔레그램 알림(선택), 무한 루프 모니터링을 지원한다.

사용 예:
    python gov_rss_collector.py verify              # 전체 피드 작동 검증
    python gov_rss_collector.py once                # 1회 수집
    python gov_rss_collector.py once --theme 사회   # 사회분야 부처만 1회 수집
    python gov_rss_collector.py run --interval 600  # 10분 주기 모니터링
    python gov_rss_collector.py run --feeds 보도자료 보건복지부 고용노동부 --keywords 저출생 연금
    python gov_rss_collector.py export --out news.csv
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import random
import re
import signal
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import feedparser
import requests
from bs4 import BeautifulSoup

# ──────────────────────────────────────────────────────────────────────────
# 1. 피드 카탈로그 (korea.kr 공식 목록, 2026 정부조직 반영)
#    key = 표시명, value = RSS URL
# ──────────────────────────────────────────────────────────────────────────
BASE = "https://www.korea.kr/rss"

# (1) 정책포털 콘텐츠 유형별
FEEDS_CONTENT: dict[str, str] = {
    "보도자료": f"{BASE}/pressrelease.xml",      # ← 전 부처 보도자료 통합(핵심)
    "정책뉴스": f"{BASE}/policy.xml",
    "부처브리핑": f"{BASE}/ebriefing.xml",
    "청와대브리핑": f"{BASE}/president.xml",
    "국무회의브리핑": f"{BASE}/cabinet.xml",
    "사실은이렇습니다": f"{BASE}/fact.xml",
    "연설문": f"{BASE}/speech.xml",
    "정책칼럼": f"{BASE}/column.xml",
    "이슈인사이트": f"{BASE}/insight.xml",
    "전문자료": f"{BASE}/expdoc.xml",
}

# (2) 부처별
FEEDS_DEPT: dict[str, str] = {
    "국무조정실": f"{BASE}/dept_opm.xml",
    "재정경제부": f"{BASE}/dept_moef.xml",
    "과학기술정보통신부": f"{BASE}/dept_msit.xml",
    "교육부": f"{BASE}/dept_moe.xml",
    "외교부": f"{BASE}/dept_mofa.xml",
    "통일부": f"{BASE}/dept_unikorea.xml",
    "법무부": f"{BASE}/dept_moj.xml",
    "국방부": f"{BASE}/dept_mnd.xml",
    "행정안전부": f"{BASE}/dept_mois.xml",
    "국가보훈부": f"{BASE}/dept_mpva.xml",
    "문화체육관광부": f"{BASE}/dept_mcst.xml",
    "농림축산식품부": f"{BASE}/dept_mafra.xml",
    "산업통상부": f"{BASE}/dept_motir.xml",
    "보건복지부": f"{BASE}/dept_mw.xml",
    "기후에너지환경부": f"{BASE}/dept_mcee.xml",
    "고용노동부": f"{BASE}/dept_moel.xml",
    "성평등가족부": f"{BASE}/dept_mogef.xml",
    "국토교통부": f"{BASE}/dept_molit.xml",
    "해양수산부": f"{BASE}/dept_mof.xml",
    "중소벤처기업부": f"{BASE}/dept_mss.xml",
    "기획예산처": f"{BASE}/dept_mpb.xml",
    "인사혁신처": f"{BASE}/dept_mpm.xml",
    "법제처": f"{BASE}/dept_moleg.xml",
    "식품의약품안전처": f"{BASE}/dept_mfds.xml",
    "국가데이터처": f"{BASE}/dept_mods.xml",
    "지식재산처": f"{BASE}/dept_moip.xml",
}

# (3) 청
FEEDS_AGENCY: dict[str, str] = {
    "국세청": f"{BASE}/dept_nts.xml",
    "관세청": f"{BASE}/dept_customs.xml",
    "조달청": f"{BASE}/dept_pps.xml",
    "우주항공청": f"{BASE}/dept_kasa.xml",
    "재외동포청": f"{BASE}/dept_oka.xml",
    "검찰청": f"{BASE}/dept_spo.xml",
    "병무청": f"{BASE}/dept_mma.xml",
    "방위사업청": f"{BASE}/dept_dapa.xml",
    "경찰청": f"{BASE}/dept_npa.xml",
    "소방청": f"{BASE}/dept_nfa.xml",
    "국가유산청": f"{BASE}/dept_khs.xml",
    "농촌진흥청": f"{BASE}/dept_rda.xml",
    "산림청": f"{BASE}/dept_forest.xml",
    "질병관리청": f"{BASE}/dept_kdca.xml",
    "기상청": f"{BASE}/dept_kma.xml",
    "행정중심복합도시건설청": f"{BASE}/dept_macc.xml",
    "새만금개발청": f"{BASE}/dept_sda.xml",
    "해양경찰청": f"{BASE}/dept_kcg.xml",
}

# (4) 위원회 + 대통령 소속 위원회
FEEDS_COMMITTEE: dict[str, str] = {
    "방송미디어통신위원회": f"{BASE}/dept_kmcc.xml",
    "원자력안전위원회": f"{BASE}/dept_nssc.xml",
    "공정거래위원회": f"{BASE}/dept_ftc.xml",
    "금융위원회": f"{BASE}/dept_fsc.xml",
    "국민권익위원회": f"{BASE}/dept_acrc.xml",
    "개인정보보호위원회": f"{BASE}/dept_pipc.xml",
    "국민통합위원회": f"{BASE}/dept_k_cohesion.xml",
    "저출산고령사회위원회": f"{BASE}/dept_betterfuture.xml",
    "경제사회노동위원회": f"{BASE}/dept_esdc.xml",
    "국가기후위기대응위원회": f"{BASE}/dept_pcccr.xml",
}

# 전체 피드 통합
ALL_FEEDS: dict[str, str] = {
    **FEEDS_CONTENT, **FEEDS_DEPT, **FEEDS_AGENCY, **FEEDS_COMMITTEE
}

# ──────────────────────────────────────────────────────────────────────────
# 2. 주제별 부처 그룹 (korea.kr 주제 분류: 경제/사회/문화/외교안보 기준)
#    --theme 옵션으로 해당 그룹 부처 피드만 선택 수집한다.
# ──────────────────────────────────────────────────────────────────────────
THEMES: dict[str, list[str]] = {
    "사회": [
        "보건복지부", "고용노동부", "교육부", "기후에너지환경부", "성평등가족부",
        "질병관리청", "식품의약품안전처", "저출산고령사회위원회", "경제사회노동위원회",
        "행정안전부", "소방청", "경찰청",
    ],
    "경제": [
        "재정경제부", "기획예산처", "산업통상부", "중소벤처기업부", "국토교통부",
        "해양수산부", "농림축산식품부", "과학기술정보통신부", "금융위원회",
        "공정거래위원회", "국세청", "관세청", "조달청",
    ],
    "문화": [
        "문화체육관광부", "국가유산청",
    ],
    "외교안보": [
        "외교부", "통일부", "국방부", "국가보훈부", "병무청", "방위사업청",
    ],
    "행정일반": [
        "국무조정실", "행정안전부", "인사혁신처", "법제처", "법무부", "검찰청",
        "국민권익위원회", "개인정보보호위원회",
    ],
}

# ──────────────────────────────────────────────────────────────────────────
# 3. 환경설정
# ──────────────────────────────────────────────────────────────────────────
DB_PATH = os.getenv("GOV_RSS_DB", "gov_news.db")
USER_AGENT = "gov-rss-collector/1.0 (+research; contact: example@univ.ac.kr)"
REQUEST_TIMEOUT = 15
FETCH_DELAY_RANGE = (0.4, 1.0)   # 피드 간 예의상 지연(초)
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK_URL", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("gov_rss")

# 제목 접두어 "[부처명]" 추출용 정규식 (통합 피드에서 부처 분류)
TITLE_DEPT_RE = re.compile(r"^\[(?P<dept>[^\]]+)\]\s*(?P<title>.*)$", re.DOTALL)


# ──────────────────────────────────────────────────────────────────────────
# 4. 데이터 모델
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class NewsItem:
    feed_name: str
    dept: str
    title: str
    link: str
    published: str        # ISO8601 문자열
    summary: str          # HTML 제거 본문(앞부분, 미리보기용)
    guid: str
    content_full: str = ""   # HTML 제거 본문 전문(RSS description 기반)
    repcode: str = ""        # 부처 코드(상세페이지 enrich 시 채움)
    collected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class Attachment:
    guid: str            # 소속 보도자료 guid
    file_id: str
    tbl_key: str
    file_name: str
    file_type: str       # hwp/hwpx/pdf/xlsx/...
    download_url: str
    viewer_url: str
    local_path: str = ""


# ──────────────────────────────────────────────────────────────────────────
# 5. 저장소 (SQLite)
# ──────────────────────────────────────────────────────────────────────────
class Store:
    def __init__(self, path: str = DB_PATH):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS news (
                guid         TEXT PRIMARY KEY,
                feed_name    TEXT,
                dept         TEXT,
                title        TEXT,
                link         TEXT,
                published    TEXT,
                summary      TEXT,
                content_full TEXT,
                repcode      TEXT,
                enriched     INTEGER DEFAULT 0,
                collected_at TEXT
            )
            """
        )
        # 조건부 GET 캐시(ETag / Last-Modified)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS feed_cache (
                feed_name     TEXT PRIMARY KEY,
                etag          TEXT,
                modified      TEXT,
                last_checked  TEXT
            )
            """
        )
        # 첨부파일 메타데이터
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS attachments (
                file_id      TEXT,
                guid         TEXT,
                tbl_key      TEXT,
                file_name    TEXT,
                file_type    TEXT,
                download_url TEXT,
                viewer_url   TEXT,
                local_path   TEXT,
                PRIMARY KEY (guid, file_id)
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_news_dept ON news(dept)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_news_pub ON news(published)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_att_guid ON attachments(guid)")
        self.conn.commit()
        self._migrate()

    def _migrate(self) -> None:
        """구버전 DB에 신규 컬럼이 없으면 추가한다(하위호환)."""
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(news)")}
        for col, ddl in (
            ("content_full", "ALTER TABLE news ADD COLUMN content_full TEXT"),
            ("repcode", "ALTER TABLE news ADD COLUMN repcode TEXT"),
            ("enriched", "ALTER TABLE news ADD COLUMN enriched INTEGER DEFAULT 0"),
        ):
            if col not in cols:
                self.conn.execute(ddl)
        self.conn.commit()

    def exists(self, guid: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM news WHERE guid = ?", (guid,))
        return cur.fetchone() is not None

    def insert(self, item: NewsItem) -> bool:
        """신규면 저장 후 True, 중복이면 False."""
        try:
            self.conn.execute(
                """INSERT INTO news
                   (guid, feed_name, dept, title, link, published, summary,
                    content_full, repcode, enriched, collected_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                (item.guid, item.feed_name, item.dept, item.title, item.link,
                 item.published, item.summary, item.content_full, item.repcode,
                 item.collected_at),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def insert_attachment(self, att: Attachment) -> bool:
        try:
            self.conn.execute(
                """INSERT INTO attachments
                   (file_id, guid, tbl_key, file_name, file_type,
                    download_url, viewer_url, local_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (att.file_id, att.guid, att.tbl_key, att.file_name, att.file_type,
                 att.download_url, att.viewer_url, att.local_path),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def mark_enriched(self, guid: str, repcode: str | None = None) -> None:
        if repcode:
            self.conn.execute(
                "UPDATE news SET enriched = 1, repcode = ? WHERE guid = ?", (repcode, guid)
            )
        else:
            self.conn.execute("UPDATE news SET enriched = 1 WHERE guid = ?", (guid,))
        self.conn.commit()

    def set_local_path(self, guid: str, file_id: str, path: str) -> None:
        self.conn.execute(
            "UPDATE attachments SET local_path = ? WHERE guid = ? AND file_id = ?",
            (path, guid, file_id),
        )
        self.conn.commit()

    def get_unenriched(self, limit: int = 100) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT guid, link FROM news WHERE COALESCE(enriched,0) = 0 "
            "ORDER BY published DESC LIMIT ?", (limit,)
        ).fetchall()

    def get_cache(self, feed_name: str) -> tuple[str | None, str | None]:
        row = self.conn.execute(
            "SELECT etag, modified FROM feed_cache WHERE feed_name = ?", (feed_name,)
        ).fetchone()
        return (row["etag"], row["modified"]) if row else (None, None)

    def set_cache(self, feed_name: str, etag: str | None, modified: str | None) -> None:
        self.conn.execute(
            """INSERT INTO feed_cache (feed_name, etag, modified, last_checked)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(feed_name) DO UPDATE SET
                 etag=excluded.etag, modified=excluded.modified, last_checked=excluded.last_checked""",
            (feed_name, etag, modified, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def export_csv(self, out_path: str, include_full: bool = False) -> int:
        base_cols = ["feed_name", "dept", "title", "link", "published", "summary", "collected_at"]
        cols = base_cols + (["content_full"] if include_full else [])
        select = ", ".join(cols)
        rows = self.conn.execute(
            f"SELECT {select} FROM news ORDER BY published DESC"
        ).fetchall()
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for r in rows:
                w.writerow([r[c] for c in cols])
        return len(rows)

    def export_attachments_csv(self, out_path: str) -> int:
        rows = self.conn.execute(
            """SELECT a.guid, n.dept, n.title, a.file_name, a.file_type,
                      a.download_url, a.viewer_url, a.local_path
               FROM attachments a LEFT JOIN news n ON a.guid = n.guid
               ORDER BY n.published DESC"""
        ).fetchall()
        cols = ["guid", "dept", "title", "file_name", "file_type",
                "download_url", "viewer_url", "local_path"]
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for r in rows:
                w.writerow([r[c] for c in cols])
        return len(rows)

    def close(self) -> None:
        self.conn.close()


# ──────────────────────────────────────────────────────────────────────────
# 6. 유틸
# ──────────────────────────────────────────────────────────────────────────
def clean_html(raw: str, limit: int | None = None) -> str:
    """description의 HTML 태그를 제거하고 공백을 정리한다."""
    if not raw:
        return ""
    text = BeautifulSoup(raw, "html.parser").get_text(separator=" ")
    text = re.sub(r"\s+", " ", text).strip()
    if limit:
        text = text[:limit]
    return text


def parse_dept(feed_name: str, entry) -> tuple[str, str]:
    """
    부처명과 정제된 제목을 반환한다.
    - 통합 피드(보도자료 등)는 제목 접두어 '[부처명]'에서 추출한다.
    - 부처별 피드는 feed_name 자체가 부처명이다.
    """
    raw_title = (getattr(entry, "title", "") or "").strip()
    if feed_name in FEEDS_DEPT or feed_name in FEEDS_AGENCY or feed_name in FEEDS_COMMITTEE:
        return feed_name, raw_title
    m = TITLE_DEPT_RE.match(raw_title)
    if m:
        return m.group("dept").strip(), m.group("title").strip()
    return feed_name, raw_title


def to_iso(entry) -> str:
    """published_parsed(struct_time) → ISO8601. 없으면 현재시각."""
    st = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if st:
        return datetime(*st[:6], tzinfo=timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def entry_guid(entry) -> str:
    return (getattr(entry, "id", "") or getattr(entry, "link", "") or "").strip()


# ──────────────────────────────────────────────────────────────────────────
# 7. 상세페이지 보강(Enrichment) — 첨부파일 메타데이터 + 부처코드
#    본문 전문은 RSS description에 이미 있으므로 여기서는 첨부/코드만 보강한다.
# ──────────────────────────────────────────────────────────────────────────
DOWNLOAD_RE = re.compile(r"/common/download\.do\?fileId=(?P<fid>\d+)&(?:amp;)?tblKey=(?P<tbl>\w+)")
REPCODE_RE = re.compile(r"repCode=([A-Z0-9]+)")
EXT_RE = re.compile(r"\.([A-Za-z0-9]{2,5})$")
_SKIP_LINK_TEXT = {"바로보기", "내려받기", "다운로드", "미리보기", ""}


def parse_detail_html(html: str, base: str = "https://www.korea.kr") -> dict:
    """
    보도자료 상세페이지 HTML에서 부처코드와 첨부파일 메타데이터를 추출한다.
    첨부파일은 download.do 링크의 fileId로 그룹화해 중복(바로보기/내려받기)을 제거한다.
    """
    soup = BeautifulSoup(html, "html.parser")

    repcode = ""
    m = REPCODE_RE.search(html)
    if m:
        repcode = m.group(1)

    atts: dict[str, dict] = {}
    for a in soup.find_all("a", href=True):
        dm = DOWNLOAD_RE.search(a["href"])
        if not dm:
            continue
        fid, tbl = dm.group("fid"), dm.group("tbl")
        text = a.get_text(" ", strip=True)
        rec = atts.setdefault(fid, {
            "file_id": fid, "tbl_key": tbl, "file_name": "", "file_type": "",
            "download_url": f"{base}/common/download.do?fileId={fid}&tblKey={tbl}",
            "viewer_url": f"{base}/common/docViewer.do?fileId={fid}&tblKey={tbl}",
        })
        # 파일명: '바로보기/내려받기'가 아닌 실제 파일명(가장 긴 텍스트) 채택
        if text not in _SKIP_LINK_TEXT and len(text) > len(rec["file_name"]):
            rec["file_name"] = text
            em = EXT_RE.search(text)
            if em:
                rec["file_type"] = em.group(1).lower()
    return {"repcode": repcode, "attachments": list(atts.values())}


class Enricher:
    """상세페이지를 크롤링해 첨부파일·부처코드를 DB에 적재한다."""

    def __init__(self, store: Store, session: requests.Session | None = None):
        self.store = store
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def enrich(self, guid: str, link: str,
               download_files: bool = False, files_dir: str = "files") -> int:
        """단일 보도자료 보강. 적재된 첨부 수를 반환."""
        if not link:
            self.store.mark_enriched(guid)
            return 0
        try:
            resp = self.session.get(link, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            log.warning("상세페이지 요청 실패 [%s]: %s", guid[-12:], e)
            return 0

        detail = parse_detail_html(resp.text)
        n = 0
        for a in detail["attachments"]:
            att = Attachment(
                guid=guid, file_id=a["file_id"], tbl_key=a["tbl_key"],
                file_name=a["file_name"], file_type=a["file_type"],
                download_url=a["download_url"], viewer_url=a["viewer_url"],
            )
            if self.store.insert_attachment(att):
                n += 1
            if download_files:
                self._download(att, files_dir)
        self.store.mark_enriched(guid, detail["repcode"] or None)
        return n

    def _download(self, att: Attachment, files_dir: str) -> None:
        """첨부파일을 내려받아 로컬 경로를 DB에 기록한다."""
        Path(files_dir).mkdir(parents=True, exist_ok=True)
        # 안전한 파일명 구성
        safe = re.sub(r"[\\/:*?\"<>|]", "_", att.file_name) or f"{att.file_id}"
        if not EXT_RE.search(safe) and att.file_type:
            safe = f"{safe}.{att.file_type}"
        dest = Path(files_dir) / f"{att.file_id}_{safe}"
        try:
            with self.session.get(att.download_url, timeout=REQUEST_TIMEOUT, stream=True) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(8192):
                        f.write(chunk)
            self.store.set_local_path(att.guid, att.file_id, str(dest))
            log.info("첨부 저장: %s", dest.name)
        except requests.RequestException as e:
            log.warning("첨부 다운로드 실패 [%s]: %s", att.file_id, e)

    def backfill(self, limit: int = 100,
                 download_files: bool = False, files_dir: str = "files") -> int:
        """DB에서 아직 보강되지 않은 보도자료를 일괄 보강한다."""
        rows = self.store.get_unenriched(limit)
        total = 0
        log.info("보강 대상 %d건", len(rows))
        for row in rows:
            total += self.enrich(row["guid"], row["link"], download_files, files_dir)
            time.sleep(random.uniform(*FETCH_DELAY_RANGE))
        return total


# ──────────────────────────────────────────────────────────────────────────
# 8. 수집기
# ──────────────────────────────────────────────────────────────────────────
class Collector:
    def __init__(self, store: Store, session: requests.Session | None = None,
                 enricher: "Enricher | None" = None):
        self.store = store
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.enricher = enricher

    def fetch_feed(self, feed_name: str, url: str):
        """조건부 GET으로 피드를 받아 feedparser 객체를 반환. 304면 None."""
        etag, modified = self.store.get_cache(feed_name)
        headers = {}
        if etag:
            headers["If-None-Match"] = etag
        if modified:
            headers["If-Modified-Since"] = modified
        resp = self.session.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 304:
            return None  # 변경 없음
        resp.raise_for_status()
        new_etag = resp.headers.get("ETag")
        new_modified = resp.headers.get("Last-Modified")
        if new_etag or new_modified:
            self.store.set_cache(feed_name, new_etag, new_modified)
        return feedparser.parse(resp.content)

    def collect_one(
        self,
        feed_name: str,
        url: str,
        keywords: list[str] | None = None,
        exclude: list[str] | None = None,
        summary_limit: int = 300,
        notify: bool = False,
    ) -> list[NewsItem]:
        """단일 피드 수집 → 신규 항목 리스트 반환."""
        new_items: list[NewsItem] = []
        try:
            parsed = self.fetch_feed(feed_name, url)
        except requests.RequestException as e:
            log.warning("❌ [%s] 요청 실패: %s", feed_name, e)
            return new_items
        if parsed is None:
            log.debug("· [%s] 변경 없음(304)", feed_name)
            return new_items
        if parsed.bozo and not parsed.entries:
            log.warning("⚠️  [%s] 파싱 경고: %s", feed_name, parsed.bozo_exception)
            return new_items

        for entry in parsed.entries:
            guid = entry_guid(entry)
            if not guid or self.store.exists(guid):
                continue
            dept, title = parse_dept(feed_name, entry)
            raw_desc = getattr(entry, "summary", "")
            content_full = clean_html(raw_desc)              # 본문 전문(미절단)
            summary = content_full[:summary_limit]           # 미리보기용

            # 키워드 필터 (제목+본문 전문 기준)
            haystack = f"{title} {content_full}"
            if keywords and not any(k in haystack for k in keywords):
                continue
            if exclude and any(k in haystack for k in exclude):
                continue

            item = NewsItem(
                feed_name=feed_name, dept=dept, title=title,
                link=(getattr(entry, "link", "") or "").strip(),
                published=to_iso(entry), summary=summary, guid=guid,
                content_full=content_full,
            )
            if self.store.insert(item):
                new_items.append(item)
        return new_items

    def collect(
        self,
        feeds: dict[str, str],
        keywords: list[str] | None = None,
        exclude: list[str] | None = None,
        notify: bool = False,
        full: bool = False,
        download_files: bool = False,
        files_dir: str = "files",
    ) -> list[NewsItem]:
        """여러 피드 1회 수집. full=True면 신규 항목의 상세페이지를 보강한다."""
        collected: list[NewsItem] = []
        for name, url in feeds.items():
            items = self.collect_one(name, url, keywords, exclude, notify=notify)
            for it in items:
                _print_item(it)
                if full and self.enricher:
                    n = self.enricher.enrich(it.guid, it.link, download_files, files_dir)
                    if n:
                        print(f"📎 첨부 {n}건 보강")
                if notify:
                    dispatch_notification(it)
            collected.extend(items)
            time.sleep(random.uniform(*FETCH_DELAY_RANGE))
        return collected


# ──────────────────────────────────────────────────────────────────────────
# 9. 출력 / 알림
# ──────────────────────────────────────────────────────────────────────────
def _print_item(it: NewsItem) -> None:
    print("-" * 70)
    print(f"📌 출처 : {it.feed_name}  |  🏛️  부처 : {it.dept}")
    print(f"📣 제목 : {it.title}")
    print(f"📅 게시 : {it.published}")
    print(f"🔗 링크 : {it.link}")
    if it.summary:
        print(f"📝 요약 : {it.summary[:150]}…")


def dispatch_notification(it: NewsItem) -> None:
    """슬랙/텔레그램 환경변수가 설정된 경우에만 전송한다."""
    text = f"[{it.dept}] {it.title}\n{it.link}"
    if SLACK_WEBHOOK:
        try:
            requests.post(SLACK_WEBHOOK, json={"text": text}, timeout=10)
        except requests.RequestException as e:
            log.warning("슬랙 전송 실패: %s", e)
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": text,
                      "disable_web_page_preview": False},
                timeout=10,
            )
        except requests.RequestException as e:
            log.warning("텔레그램 전송 실패: %s", e)


# ──────────────────────────────────────────────────────────────────────────
# 10. 피드 선택 / 검증
# ──────────────────────────────────────────────────────────────────────────
def resolve_feeds(
    names: list[str] | None,
    theme: str | None,
    use_all: bool,
) -> dict[str, str]:
    """CLI 인자로부터 수집 대상 피드 사전을 구성한다."""
    if use_all:
        return dict(ALL_FEEDS)
    if theme:
        if theme not in THEMES:
            raise SystemExit(f"알 수 없는 주제: {theme} (가능: {', '.join(THEMES)})")
        return {n: ALL_FEEDS[n] for n in THEMES[theme] if n in ALL_FEEDS}
    if names:
        feeds = {}
        for n in names:
            if n in ALL_FEEDS:
                feeds[n] = ALL_FEEDS[n]
            else:
                log.warning("알 수 없는 피드명 무시: %s", n)
        if not feeds:
            raise SystemExit("유효한 피드명이 없다.")
        return feeds
    # 기본값: 전 부처 보도자료 통합 피드
    return {"보도자료": ALL_FEEDS["보도자료"]}


def verify_feeds(feeds: dict[str, str]) -> None:
    """각 피드를 실제로 요청해 작동 여부와 항목 수를 보고한다."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    ok, fail = 0, 0
    print(f"\n{'피드명':<22}{'상태':<8}{'항목':<6}최신 게시일")
    print("─" * 70)
    for name, url in feeds.items():
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
            n = len(parsed.entries)
            if n > 0:
                latest = getattr(parsed.entries[0], "published", "")
                print(f"{name:<22}{'✅ OK':<8}{n:<6}{latest}")
                ok += 1
            else:
                print(f"{name:<22}{'⚠️ 빈피드':<8}{n:<6}-")
                fail += 1
        except Exception as e:
            print(f"{name:<22}{'❌ FAIL':<8}{'-':<6}{e}")
            fail += 1
        time.sleep(random.uniform(*FETCH_DELAY_RANGE))
    print("─" * 70)
    print(f"정상 {ok}개 / 문제 {fail}개 / 전체 {ok + fail}개\n")


# ──────────────────────────────────────────────────────────────────────────
# 11. 모니터링 루프
# ──────────────────────────────────────────────────────────────────────────
_STOP = False


def _handle_sigint(signum, frame):
    global _STOP
    _STOP = True
    log.info("종료 신호 수신 — 현재 주기 종료 후 멈춘다.")


def run_monitor(
    collector: Collector,
    feeds: dict[str, str],
    interval: int,
    keywords: list[str] | None,
    exclude: list[str] | None,
    notify: bool,
    full: bool = False,
    download_files: bool = False,
    files_dir: str = "files",
) -> None:
    signal.signal(signal.SIGINT, _handle_sigint)
    signal.signal(signal.SIGTERM, _handle_sigint)

    log.info("초기 동기화 시작 — 기존 항목을 DB에 적재(중복 방지 기준선).")
    first = collector.collect(feeds, keywords, exclude, notify=False,
                              full=full, download_files=download_files, files_dir=files_dir)
    log.info("초기 동기화 완료: 신규 %d건 적재. 모니터링 시작(주기 %d초).", len(first), interval)

    while not _STOP:
        slept = 0
        while slept < interval and not _STOP:
            time.sleep(min(2, interval - slept))
            slept += 2
        if _STOP:
            break
        log.info("[%s] 모니터링 주기 실행", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        new_items = collector.collect(feeds, keywords, exclude, notify=notify,
                                      full=full, download_files=download_files, files_dir=files_dir)
        log.info("신규 %d건 수집", len(new_items))
    log.info("모니터링을 종료한다.")


# ──────────────────────────────────────────────────────────────────────────
# 12. CLI
# ──────────────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="대한민국 정부부처 RSS 실시간 수집기")
    sub = p.add_subparsers(dest="command", required=True)

    def add_feed_args(sp):
        sp.add_argument("--feeds", nargs="*", help="수집할 피드명(공백 구분). 예: 보도자료 보건복지부")
        sp.add_argument("--theme", help=f"주제 그룹 선택 ({', '.join(THEMES)})")
        sp.add_argument("--all", action="store_true", help="전체 피드 사용")
        sp.add_argument("--keywords", nargs="*", help="포함 키워드 필터")
        sp.add_argument("--exclude", nargs="*", help="제외 키워드 필터")
        sp.add_argument("--notify", action="store_true", help="슬랙/텔레그램 알림 전송")
        sp.add_argument("--full", action="store_true",
                        help="신규 항목의 상세페이지를 크롤링해 첨부파일 메타데이터 보강")
        sp.add_argument("--download-files", action="store_true",
                        help="첨부파일(hwpx/pdf)을 내려받아 저장(--full 필요)")
        sp.add_argument("--files-dir", default="files", help="첨부파일 저장 폴더")
        sp.add_argument("--db", default=DB_PATH, help="SQLite 경로")

    sp_verify = sub.add_parser("verify", help="피드 작동 검증")
    sp_verify.add_argument("--feeds", nargs="*")
    sp_verify.add_argument("--theme")
    sp_verify.add_argument("--all", action="store_true", default=False)

    sp_once = sub.add_parser("once", help="1회 수집")
    add_feed_args(sp_once)

    sp_run = sub.add_parser("run", help="주기 모니터링")
    add_feed_args(sp_run)
    sp_run.add_argument("--interval", type=int, default=600, help="수집 주기(초), 기본 600")

    sp_enrich = sub.add_parser("enrich", help="DB 내 미보강 보도자료의 첨부·코드 일괄 보강")
    sp_enrich.add_argument("--limit", type=int, default=200, help="1회 보강 건수 상한")
    sp_enrich.add_argument("--download-files", action="store_true", help="첨부파일 다운로드")
    sp_enrich.add_argument("--files-dir", default="files", help="첨부파일 저장 폴더")
    sp_enrich.add_argument("--db", default=DB_PATH)

    sp_export = sub.add_parser("export", help="DB → CSV 내보내기")
    sp_export.add_argument("--out", default="gov_news.csv")
    sp_export.add_argument("--full", action="store_true", help="본문 전문(content_full) 포함")
    sp_export.add_argument("--attachments", action="store_true",
                           help="첨부파일 목록을 별도 CSV(out 접미사 _attachments)로 내보내기")
    sp_export.add_argument("--db", default=DB_PATH)

    sub.add_parser("list", help="사용 가능한 피드/주제 목록 출력")
    return p


def cmd_list() -> None:
    def dump(title, d):
        print(f"\n[{title}] ({len(d)}개)")
        names = list(d.keys())
        for i in range(0, len(names), 3):
            print("  " + "  ".join(f"{n:<20}" for n in names[i:i + 3]))
    dump("정책포털 콘텐츠", FEEDS_CONTENT)
    dump("부처", FEEDS_DEPT)
    dump("청", FEEDS_AGENCY)
    dump("위원회", FEEDS_COMMITTEE)
    print(f"\n[주제 그룹] ({len(THEMES)}개)")
    for t, members in THEMES.items():
        print(f"  {t}: {', '.join(members)}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "list":
        cmd_list()
        return 0

    if args.command == "verify":
        use_all = args.all or (not args.feeds and not args.theme)
        feeds = resolve_feeds(args.feeds, args.theme, use_all)
        if use_all:
            feeds = dict(ALL_FEEDS)
        verify_feeds(feeds)
        return 0

    if args.command == "export":
        store = Store(args.db)
        n = store.export_csv(args.out, include_full=getattr(args, "full", False))
        log.info("뉴스 %d건을 %s 로 내보냈다.", n, args.out)
        if getattr(args, "attachments", False):
            att_out = args.out.rsplit(".", 1)
            att_path = f"{att_out[0]}_attachments.csv" if len(att_out) == 2 else f"{args.out}_attachments.csv"
            m = store.export_attachments_csv(att_path)
            log.info("첨부 %d건을 %s 로 내보냈다.", m, att_path)
        store.close()
        return 0

    if args.command == "enrich":
        store = Store(args.db)
        enricher = Enricher(store)
        total = enricher.backfill(args.limit, args.download_files, args.files_dir)
        store.close()
        log.info("보강 완료: 첨부 %d건 적재.", total)
        return 0

    # once / run
    feeds = resolve_feeds(args.feeds, args.theme, args.all)
    log.info("대상 피드 %d개: %s", len(feeds), ", ".join(feeds))
    store = Store(args.db)
    enricher = Enricher(store) if getattr(args, "full", False) else None
    collector = Collector(store, enricher=enricher)
    try:
        if args.command == "once":
            items = collector.collect(
                feeds, args.keywords, args.exclude, notify=args.notify,
                full=args.full, download_files=args.download_files, files_dir=args.files_dir)
            log.info("총 신규 %d건 수집·저장 완료.", len(items))
        elif args.command == "run":
            run_monitor(collector, feeds, args.interval,
                        args.keywords, args.exclude, args.notify,
                        full=args.full, download_files=args.download_files,
                        files_dir=args.files_dir)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
