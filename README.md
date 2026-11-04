# job-radar

취업 준비하면서 채용 사이트를 매일 하나씩 돌아보는 게 힘들어서 만들었습니다. 대기업, 중견, 강소, 공기업, 외국계 채용 페이지에서 내 직무와 연차에 맞는 공고만 모아 노션 DB에 넣어 주는 Claude Code 플러그인입니다.

구성은 두 가지예요. MCP 서버(`server.py`)가 `companies.yaml`에 적힌 회사들의 채용 페이지에서 공고를 가져오고, 스킬(`skills/job-radar/SKILL.md`)이 그걸 직무·경력 조건으로 걸러서 노션에 넣어요. 이미 넣은 공고나 마감된 공고도 스킬이 정리해 줍니다.

회사 목록은 2026년 공정위 공시대상기업집단 102개를 기준으로 중견·강소·공기업을 더해서 지금 115곳 정도예요. 공고는 Greenhouse, 그리팅, 마이다스(recruiter.co.kr), 잡알리오(공공기관), 그리고 삼성·CJ·네이버·카카오·토스 채용 사이트에서 가져와요. 마이다스, 삼성, 그리팅, Greenhouse는 공고 본문(자격 요건)까지 API로 읽어서(`get_job_detail`) 연차를 확인합니다.

## 구조

```
job-radar/
├── .claude-plugin/
│   ├── plugin.json         플러그인 정보 (이름, 버전, 설명)
│   └── marketplace.json    /plugin install로 설치할 수 있게 해 주는 목록
├── .mcp.json               설치하면 MCP 서버를 자동으로 등록
├── server.py               MCP 서버
│   ├── search_jobs         회사들에서 공고를 모으고 키워드·연차로 1차 거르기
│   ├── get_job_detail      공고 본문(자격 요건) 읽기
│   ├── fetch_jobs          회사 하나의 공고 전체
│   └── list_companies      수집 대상 회사 목록
├── companies.yaml          수집할 회사 115곳 (이름, 분류, 채용 사이트)
└── skills/
    └── job-radar/
        └── SKILL.md        설정 묻기 → 마감 공고 정리 → 수집 → 거르기 → 노션에 넣기

~/.job-radar/profile.yaml   내 직무·연차·기업 분류 (처음 실행할 때 만들어짐, 저장소에는 안 올라감)
```

한 번 실행하면 이 순서로 돌아가요.

1. 스킬이 `profile.yaml`에서 내 직무, 연차, 기업 분류를 읽어요. 파일이 없으면 먼저 물어보고 만들어요.
2. 노션 DB에서 마감일이 지난 공고를 지워요.
3. `search_jobs`가 `companies.yaml`의 회사들에서 공고를 한꺼번에 모은 뒤, 제목 키워드와 연차로 1차로 걸러요.
4. 연차가 안 적힌 공고는 `get_job_detail`로 본문을 읽고 자격 요건을 확인해요. 직무가 맞는지는 Claude가 판단해요.
5. 노션에 이미 있는 공고는 건너뛰고 새 공고만 넣은 다음, 몇 건 넣었는지 알려 줘요.

## 설치

[Claude Code](https://claude.com/claude-code), [uv](https://docs.astral.sh/uv/), 노션 계정이 있어야 해요.

Claude Code 안에서 플러그인을 설치합니다.

```
/plugin install job-radar --marketplace KIMDONGWOOK12/job-radar
```

Claude Code 버전이 예전 거라 위 명령이 안 되면 두 줄로 나눠서 하면 돼요.

```
/plugin marketplace add KIMDONGWOOK12/job-radar
/plugin install job-radar@job-radar
```

스킬이랑 MCP 서버가 같이 깔려요. 설치하고 나서 Claude Code를 한 번 껐다 켜 주세요.

그다음 노션을 연결합니다. claude.ai 설정의 커넥터에서 Notion을 켜 두면 같은 계정으로 로그인한 Claude Code에서도 그대로 쓸 수 있어요. 아니면 터미널에서 `claude mcp add --transport http notion https://mcp.notion.com/mcp`를 실행하고 Claude Code에서 `/mcp`로 로그인해도 됩니다.

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

Claude Code에서 `/job-radar`를 실행하거나 "채용 공고 업데이트해줘"라고 말하면 돼요. 플러그인으로 설치했다면 명령 이름은 `/job-radar:job-radar`예요.

처음 실행할 때 몇 가지를 물어봐요. 원하는 직무(자유롭게 적으면 돼요), 연차(신입이면 0), 기업 분류(대기업, 대기업 계열사, 중견기업, 강소·유망, 공기업, 외국계 중 고르기), 빼고 싶은 공고, 그리고 공고를 넣을 노션 DB예요. 노션 DB가 없으면 새로 만들어 줘요. 답한 내용은 `~/.job-radar/profile.yaml`에 저장되고 바로 첫 수집을 시작합니다.

검색 키워드는 직접 안 적어도 돼요. 직무 답을 보고 Claude가 만든 다음 맞는지 한 번 물어봐요. 나중에 조건을 바꾸고 싶으면 "job-radar 설정 바꿔줘"라고 하면 됩니다.

## 회사 추가

`companies.yaml`에 한 줄 넣으면 돼요. 회사 채용 페이지가 어디 서비스를 쓰는지에 따라 적는 방법이 달라요.

- 그리팅: `https://<회사>.career.greetinghr.com`이 열리면 `source: greeting, id: <회사>.career.greetinghr.com`
- Greenhouse: `https://boards-api.greenhouse.io/v1/boards/<회사>/jobs`가 열리면 `source: greenhouse, id: <회사>`
- 마이다스: `https://<회사>.recruiter.co.kr/career/home`이 열리면 `source: recruiter, id: <회사>.recruiter.co.kr`
- 그 외: `source: custom, url: <채용 페이지>` (실행할 때 Claude가 페이지를 직접 읽어요)

SK(skcareers.com), LG(careers.lg.com), 현대자동차그룹(talent.hyundai.com)은 코드로 못 가져와요. LG는 봇 차단이 있고 현대차는 접속 대기열이 걸려 있어서, 이 세 곳은 직접 들어가서 확인해야 해요.

## 만든 사람

- [@KIMDONGWOOK12](https://github.com/KIMDONGWOOK12)
- [@SWHee](https://github.com/SWHee)

## 라이선스

MIT
