# job-radar

대기업·중견·강소·상장·공기업·외국계 채용 페이지에서 원하는 직무·경력의 공고를 모아 노션 DB에 넣는 Claude Code용 MCP 서버 + 스킬.

- MCP 서버(`server.py`): `companies.yaml`의 회사 채용 페이지에서 공고를 가져온다. 지원 출처: Greenhouse, 그리팅, 마이다스(recruiter.co.kr), 잡알리오(공공기관), 삼성·CJ·네이버·카카오·토스 채용 사이트. 마이다스·삼성·그리팅·Greenhouse는 공고 본문(자격 요건)도 API로 읽는다(`get_job_detail`).
- 스킬(`skills/job-radar/SKILL.md`): 직무·경력 조건으로 거르고, 노션에 넣고, 중복·마감 공고를 정리한다.
- 기업 리스트: 2026년 공정위 공시대상기업집단 102개 기준 + 중견·강소·공기업 (약 115곳).

## 설치

필요한 것: [Claude Code](https://claude.com/claude-code), [uv](https://docs.astral.sh/uv/), 노션 계정.

**1. 플러그인 설치** (Claude Code 안에서)

```
/plugin install job-radar --marketplace KIMDONGWOOK12/job-radar
```

예전 버전 Claude Code라면 두 줄로:

```
/plugin marketplace add KIMDONGWOOK12/job-radar
/plugin install job-radar@job-radar
```

스킬과 MCP 서버가 같이 설치된다. 설치 후 Claude Code를 다시 연다.

**2. 노션 연결** (둘 중 하나)
- claude.ai 설정 → 커넥터에서 Notion 연결 (Claude Code에 같은 계정으로 로그인돼 있으면 그대로 쓰임)
- 또는 터미널에서 `claude mcp add --transport http notion https://mcp.notion.com/mcp` 후 Claude Code에서 `/mcp`로 로그인

<details>
<summary>플러그인 없이 직접 설치</summary>

```bash
git clone https://github.com/KIMDONGWOOK12/job-radar.git && cd job-radar
uv sync
claude mcp add job-radar -s user -- uv run --directory "$(pwd)" server.py
ln -s "$(pwd)/skills/job-radar" ~/.claude/skills/job-radar
```
</details>

## 사용

Claude Code에서 `/job-radar` (플러그인으로 설치했으면 `/job-radar:job-radar`, 또는 "채용 공고 업데이트해줘").

처음 실행하면 다음을 묻고 `~/.job-radar/profile.yaml`에 저장한 뒤 바로 수집한다.
1. 원하는 직무 (자유롭게)
2. 연차 (신입이면 0)
3. 기업 분류 (대기업, 대기업 계열사, 중견기업, 강소·유망, 공기업, 외국계)
4. 빼고 싶은 공고
5. 공고를 넣을 노션 DB (없으면 새로 만듦)

검색 키워드는 직무 답을 보고 Claude가 만들어 확인받는다. 나중에 바꾸려면 "job-radar 설정 바꿔줘".

## 기업 추가

`companies.yaml`에 한 줄 추가.
- 그리팅: `https://<회사>.career.greetinghr.com`이 열리면 `source: greeting, id: <회사>.career.greetinghr.com`
- Greenhouse: `https://boards-api.greenhouse.io/v1/boards/<회사>/jobs`가 열리면 `source: greenhouse, id: <회사>`
- 마이다스: `https://<회사>.recruiter.co.kr/career/home`이 열리면 `source: recruiter, id: <회사>.recruiter.co.kr`
- 그 외: `source: custom, url: <채용 페이지>` (Claude가 직접 읽음)

코드로 못 가져오는 곳: SK(skcareers.com), LG(careers.lg.com, 봇 차단), 현대자동차그룹(talent.hyundai.com, 대기열). 직접 확인.

## 라이선스

MIT
