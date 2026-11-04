"""job-radar MCP 서버: 기업 리스트의 채용 페이지에서 공고를 가져온다."""

import asyncio
import html
import json
import re
from pathlib import Path

import logging

import httpx
import yaml
from mcp.server.mcpserver import MCPServer

COMPANIES_FILE = Path(__file__).parent / "companies.yaml"
HEADERS = {"User-Agent": "Mozilla/5.0 (job-radar)"}

mcp = MCPServer("job-radar")
logging.getLogger("httpx").setLevel(logging.WARNING)


def load_companies() -> list[dict]:
    return yaml.safe_load(COMPANIES_FILE.read_text(encoding="utf-8"))["companies"]


def title_career(title):
    """제목에 적힌 경력으로 (표기, 최소 연차)를 추정. 못 찾으면 ("", None)."""
    m = re.search(r"(\d+)\s*년\s*(이상|↑|\+)", title)
    if m:
        return f"{m.group(1)}년 이상", int(m.group(1))
    if "신입" in title or "인턴" in title or "무관" in title:
        return "신입 가능", 0
    if "경력" in title:
        return "경력", None
    return "", None


def job(company, title, url, *, career="", career_min=None, due=None, location="", detail=""):
    """모든 출처의 공고를 같은 모양으로 맞춘다. career_min: 최소 경력 연차(모르면 None)."""
    if not career:
        career, career_min = title_career(title)
    return {
        "company": company, "title": title, "url": url, "career": career,
        "career_min": career_min, "due": due, "location": location, "detail": detail,
    }


# ---------- 출처별 수집 ----------

async def fetch_greenhouse(client, c):
    r = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{c['id']}/jobs")
    r.raise_for_status()
    return [
        job(c["name"], j["title"], j["absolute_url"], location=(j.get("location") or {}).get("name", ""))
        for j in r.json()["jobs"]
    ]


def _walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


async def fetch_greeting(client, c):
    r = await client.get(f"https://{c['id']}/")
    r.raise_for_status()
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
    if not m:
        raise ValueError("그리팅 페이지 데이터 없음")
    seen, out = set(), []
    for o in _walk(json.loads(m.group(1))):
        oid = o.get("openingId")
        if not oid or not isinstance(o.get("title"), str) or oid in seen:
            continue
        seen.add(oid)
        positions = (o.get("openingJobPosition") or {}).get("openingJobPositions") or []
        careers = [p.get("jobPositionCareer") or {} for p in positions]
        types = {cr.get("careerType") for cr in careers}
        froms = [cr.get("careerFrom") or 0 for cr in careers if cr.get("careerType") == "EXPERIENCED"]
        tos = [cr.get("careerTo") for cr in careers if cr.get("careerTo") is not None]
        if "EXPERIENCED" in types and len(types) == 1:
            lo = min(froms) if froms else None
            career = f"경력 {lo}년~" + (f"{max(tos)}년" if tos else "") if lo is not None else "경력"
            career_min = lo
        elif types - {None}:
            names = {"NEW": "신입", "NOT_MATTER": "경력무관", "EXPERIENCED": "경력"}
            career, career_min = "/".join(sorted(names.get(t, t) for t in types if t)), 0
        else:
            career, career_min = "", None
        place = next((p.get("workspacePlace") or {} for p in positions if p.get("workspacePlace")), {})
        out.append(job(
            c["name"], o["title"], f"https://{c['id']}/ko/o/{oid}",
            career=career, career_min=career_min,
            due=(o.get("dueDate") or "")[:10] or None, location=place.get("place", ""),
        ))
    return out


async def fetch_naver(client, c):
    out = []
    for page in range(50):
        r = await client.get(
            "https://recruit.navercorp.com/rcrt/loadJobList.do",
            params={"annoId": "", "sw": "", "subJobCdArr": "", "sysCompanyCdArr": "",
                    "empTypeCdArr": "", "entTypeCdArr": "", "workAreaCdArr": "", "firstIndex": page * 10},
        )
        r.raise_for_status()
        items = r.json().get("list") or []
        if not items:
            break
        for j in items:
            ent = j.get("entTypeCdNm", "")
            end = j.get("endYmd") or ""
            out.append(job(
                f"{c['name']} ({j.get('sysCompanyCdNm', '')})", j["annoSubject"], j["jobDetailLink"],
                career=ent, career_min=0 if ent in ("신입", "무관", "신입/경력") else None,
                due=f"{end[:4]}-{end[4:6]}-{end[6:8]}" if len(end) == 8 else None,
            ))
    return out


async def _kakao_page(client, part, page):
    r = await client.get("https://careers.kakao.com/public/api/job-list",
                         params={"part": part, "keyword": "", "page": page})
    r.raise_for_status()
    return r.json()


async def fetch_kakao(client, c):
    first = await _kakao_page(client, "TECHNOLOGY", 1)
    parts = [t["jobType"] for t in first.get("jobTypeCountDtoList") or []] or ["TECHNOLOGY"]
    out = []
    for part in parts:
        page, total = 1, 1
        while page <= total and page <= 30:
            d = first if (part, page) == ("TECHNOLOGY", 1) else await _kakao_page(client, part, page)
            total = d.get("totalPage") or 1
            for j in d.get("jobList") or []:
                out.append(job(
                    j.get("companyName") or c["name"], j["jobOfferTitle"],
                    f"https://careers.kakao.com/jobs/{j['realId']}",
                    due=(j.get("endDate") or "")[:10] or None, location=j.get("locationName", ""),
                ))
            page += 1
    return out


async def fetch_toss(client, c):
    r = await client.get("https://api-public.toss.im/api/v3/ipd-eggnog/career/jobs")
    r.raise_for_status()
    out = []
    for j in r.json()["success"]:
        sub = next((m["value"] for m in j.get("metadata") or []
                    if "자회사" in m.get("name", "") and isinstance(m.get("value"), str)), "")
        out.append(job(sub or c["name"], j["title"], j["absolute_url"],
                       location=(j.get("location") or {}).get("name", "")))
    return out


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


async def fetch_recruiter(client, c):
    """마이다스 인재경영 (<회사>.recruiter.co.kr)."""
    r = await client.post(
        "https://api-recruiter.recruiter.co.kr/position/v1/jobflex",
        headers={"prefix": c["id"]},
        json={"pageableRq": {"page": 1, "size": 200, "sort": []}, "filter": {"openStatusList": ["OPEN"]}},
    )
    r.raise_for_status()
    names = {"NEW": "신입", "CAREER": "경력", "NEW_CAREER": "신입/경력",
             "FIELD_DIFFERENCE": "신입/경력(분야별)", "IRRELEVANT": "경력무관"}
    out = []
    for j in r.json().get("list") or []:
        if j.get("submissionStatus") == "POST_SUBMISSION":  # 접수 마감
            continue
        ct = j.get("careerType") or ""
        career, career_min = (names.get(ct, ct), None if ct == "CAREER" else 0) if ct else ("", None)
        out.append(job(
            c["name"], j["title"], f"https://{c['id']}/career/jobs/{j['positionSn']}",
            career=career, career_min=career_min, due=(j.get("endDateTime") or "")[:10] or None,
            detail=", ".join(t["tagName"] for t in j.get("tagList") or []),
        ))
    return out


async def fetch_samsung(client, c):
    r = await client.post(
        "https://www.samsungcareers.com/hr/list.data",
        data={"currentPageNo": 1, "intNo": 0, "strVal": "", "strTxt": "", "strKey": "",
              "strCompany": "", "strType": "", "strOrderBy": "", "strEntity": ""},
    )
    r.raise_for_status()
    out = []
    for li in re.findall(r"<li>(.*?)</li>", r.text, re.S):
        no = re.search(r'<a href="/#none"\s+data-value="([\d,]+)"', li)
        if not no:
            continue
        get = lambda cls: _text((re.search(rf'class="{cls}">(.*?)</', li, re.S) or [None, ""])[1])
        period = get("period")
        end = re.findall(r"\d{4}\.\d{2}\.\d{2}", period)
        tags = [_text(t) for t in re.findall(r'class="flag grey">(.*?)</span>', li, re.S)]
        out.append(job(
            f"{c['name']} ({get('company')})", get("title"),
            f"https://www.samsungcareers.com/hr/?no={no.group(1).replace(',', '')}",
            due=end[-1].replace(".", "-") if end else None, detail=", ".join(tags),
        ))
    return out


async def fetch_cj(client, c):
    r = await client.post(
        "https://recruit.cj.net/recruit/ko/recruit/recruit/searchNewGonggoList.fo",
        json={"pageVal": "1", "pageIndex": "500", "orderDesc": "1", "sch_title": "", "arrGubun": "",
              "arrRecBu": "", "arrRecJob": "", "arrRecArea": "", "schArea": "N"},
    )
    r.raise_for_status()
    out = []
    for j in r.json().get("ds_newRecruitList") or []:
        no = j["zz_jo_num"]
        url = ("https://recruit.cj.net/recruit/ko/recruit/recruit/detail.fo?zz_jo_num=" if j.get("gubun") == "1"
               else "https://recruit.cj.net/recruit/ko/recruit/recruit/bestDetail.fo?direct=N&zz_jo_num=") + no
        out.append(job(
            j.get("compnm") or c["name"], _text(j.get("zz_title") or ""), url,
            due=(j.get("zz_end_dt_str") or "").replace(".", "-") or None, location=j.get("location_cd_nm") or "",
        ))
    return out


async def fetch_alio(client, c):
    """잡알리오 (공공기관 채용). c['keywords']로 본문까지 검색, 진행 중 공고만."""
    out, seen = [], set()
    for kw in c.get("keywords") or ["AI"]:
        for page in range(1, 6):
            r = await client.get("https://job.alio.go.kr/recruit.do",
                                 params={"keyword": kw, "pageNo": page, "pageSet": 30, "ing": 2})
            r.raise_for_status()
            rows = re.findall(r"<tr>(.*?)</tr>", r.text, re.S)
            got = 0
            for row in rows:
                m = re.search(r'recruitview\.do\?idx=(\d+)"[^>]*/?>([^<]+)</a>', row)
                if not m:
                    continue
                got += 1
                if m.group(1) in seen:
                    continue
                seen.add(m.group(1))
                tds = [_text(t) for t in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
                due = re.search(r"(\d{2})\.(\d{2})\.(\d{2})", tds[7] if len(tds) > 7 else "")
                out.append(job(
                    tds[3] if len(tds) > 3 else c["name"], m.group(2).strip(),
                    f"https://job.alio.go.kr/recruitview.do?idx={m.group(1)}",
                    due=f"20{due.group(1)}-{due.group(2)}-{due.group(3)}" if due else None,
                    location=tds[4] if len(tds) > 4 else "", detail=tds[5] if len(tds) > 5 else "",
                ))
            if got < 30:
                break
    return out


FETCHERS = {
    "greenhouse": fetch_greenhouse, "greeting": fetch_greeting, "recruiter": fetch_recruiter,
    "naver": fetch_naver, "kakao": fetch_kakao, "toss": fetch_toss,
    "samsung": fetch_samsung, "cj": fetch_cj, "alio": fetch_alio,
}


async def collect(companies):
    """여러 회사를 동시에 수집 (동시 10곳). 실패한 회사는 errors에 담는다."""
    sem = asyncio.Semaphore(10)

    async def run(client, c):
        async with sem:
            return await FETCHERS[c["source"]](client, c)

    async with httpx.AsyncClient(headers=HEADERS, timeout=25, follow_redirects=True) as client:
        targets = [c for c in companies if c["source"] in FETCHERS]
        results = await asyncio.gather(*(run(client, c) for c in targets), return_exceptions=True)
    jobs, errors = [], []
    for c, res in zip(targets, results):
        if isinstance(res, Exception):
            errors.append(f"{c['name']}: {type(res).__name__} {res}"[:200])
        else:
            for j in res:
                j["category"] = c["category"]
            jobs.extend(res)
    manual = [{"company": c["name"], "category": c["category"], "url": c["url"]}
              for c in companies if c["source"] == "custom"]
    return jobs, errors, manual


# ---------- 공고 본문 ----------

async def _detail_text(client, url):
    """공고 url에서 본문 텍스트를 API로 가져온다. 지원하지 않는 출처면 None."""
    u = httpx.URL(url)
    host = u.host
    if host.endswith(".recruiter.co.kr"):
        sn = u.path.rstrip("/").split("/")[-1]
        r = await client.get(f"https://api-recruiter.recruiter.co.kr/position/v2/jobflex/{sn}",
                             headers={"prefix": host})
        r.raise_for_status()
        return _text(r.json().get("jobDescription") or "") or "(본문이 이미지라 글자로 읽을 수 없음)"
    if host.endswith("samsungcareers.com"):
        r = await client.get("https://www.samsungcareers.com/recruit/detail.data",
                             params={"seqno": u.params["no"], "strCode": ""})
        r.raise_for_status()
        d = r.json()["data"]
        parts = [f"[공통 지원자격]\n{d['result'].get('qlfctKr') or ''}"]
        for it in d.get("items") or []:
            parts.append(f"[직무: {it.get('titleKr')}]\n담당업무: {it.get('taskKr') or ''}\n"
                         f"지원자격: {it.get('qlfctKr') or ''}\n우대사항: {it.get('favorKr') or ''}\n"
                         f"근무지: {it.get('workPlaceKr') or ''}")
        return "\n\n".join(parts)
    if re.search(r"/o/\d+$", u.path):  # 그리팅
        r = await client.get(url)
        r.raise_for_status()
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
        details = [o["detail"] for o in _walk(json.loads(m.group(1)))
                   if isinstance(o.get("detail"), str)] if m else []
        return _text(max(details, key=len)) if details else None
    gh = re.search(r"gh_jid=(\d+)", url) or re.search(r"greenhouse\.io/([^/]+)/jobs/(\d+)", url)
    if gh:
        if host == "toss.im":
            r = await client.get(f"https://api-public.toss.im/api/v3/ipd-eggnog/career/jobs/{gh.group(1)}")
            r.raise_for_status()
            content = r.json()["success"]["content"]
        else:
            jid = gh.group(gh.lastindex)
            boards = [gh.group(1)] if gh.lastindex == 2 else \
                [c["id"] for c in load_companies() if c["source"] == "greenhouse"]
            content = None
            for b in boards:
                r = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{b}/jobs/{jid}")
                if r.status_code == 200:
                    content = r.json()["content"]
                    break
            if content is None:
                return None
        return _text(html.unescape(content))
    return None


def _matcher(words):
    """영어 키워드는 단어 단위(AI가 training에 걸리지 않게), 한글은 부분 일치."""
    parts = [rf"(?<![a-z]){re.escape(w)}(?![a-z])" if w.isascii() else re.escape(w) for w in words]
    return re.compile("|".join(parts), re.I)


# ---------- MCP 도구 ----------

@mcp.tool()
def list_companies(category: str | None = None) -> list[dict]:
    """수집 대상 기업 리스트. category로 거를 수 있다 (대기업, 대기업 계열사, 중견기업, 강소·유망, 공기업, 외국계)."""
    cs = load_companies()
    return [c for c in cs if not category or c["category"] == category]


@mcp.tool()
async def fetch_jobs(company: str) -> dict:
    """회사 하나의 열린 공고 전체를 가져온다. company는 list_companies의 name."""
    cs = [c for c in load_companies() if c["name"] == company]
    if not cs:
        return {"error": f"리스트에 없는 회사: {company}"}
    jobs, errors, manual = await collect(cs)
    return {"jobs": jobs, "errors": errors, "manual_check": manual}


@mcp.tool()
async def search_jobs(
    keywords: list[str],
    max_career: int | None = None,
    categories: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
) -> dict:
    """리스트의 모든 회사에서 공고를 모아 1차로 거른다.

    - keywords: 제목 또는 직무 태그에 하나라도 들어 있어야 함 (대소문자 무시). 예: ["AI", "ML", "LLM", "에이전트", "데이터"]
    - max_career: 최소 요구 경력이 이보다 크면 뺀다. 경력을 모르는 공고는 남긴다 (career_min=None).
    - categories: 기업 분류로 제한.
    - exclude_keywords: 제목에 들어 있으면 뺀다. 예: ["강사", "Staff", "Principal"]
    반환: jobs(공고), errors(수집 실패 회사), manual_check(코드 수집이 안 돼 직접 읽어야 하는 채용 페이지).
    """
    cs = [c for c in load_companies() if not categories or c["category"] in categories]
    jobs, errors, manual = await collect(cs)
    kw, ex = _matcher(keywords), _matcher(exclude_keywords or [])

    def keep(j):
        t = j["title"]
        td = f"{t} {j['detail']}"  # 삼성처럼 제목이 뭉뚱그려진 곳은 직무 태그(detail)까지 본다
        if not kw.search(td) or (ex.pattern and ex.search(t)):
            return False
        return max_career is None or j["career_min"] is None or j["career_min"] <= max_career

    return {"jobs": [j for j in jobs if keep(j)], "errors": errors, "manual_check": manual}


@mcp.tool()
async def get_job_detail(url: str) -> dict:
    """공고 본문(자격 요건·연차 등)을 API로 가져온다. url은 search_jobs 결과의 url.

    지원: 마이다스(recruiter.co.kr), 삼성, 그리팅, Greenhouse(토스 포함).
    supported=False면 지원하지 않는 출처이니 WebFetch로 읽는다.
    """
    async with httpx.AsyncClient(headers=HEADERS, timeout=25, follow_redirects=True) as client:
        try:
            text = await _detail_text(client, url)
        except Exception as e:
            return {"supported": True, "error": f"{type(e).__name__} {e}"[:200]}
    if text is None:
        return {"supported": False}
    return {"supported": True, "text": html.unescape(text)[:8000]}


if __name__ == "__main__":
    mcp.run()
