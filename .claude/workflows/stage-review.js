export const meta = {
  name: 'stage-review',
  description: '팀장 산출물을 파트너·고객·전문가 4인이 독립 채점(10점 만점), 6명 전원 9.5 이상이면 통과',
  whenToUse: '상권분석 과제의 각 단계 산출물 게이트 리뷰. args: {stage, title, round, goal, artifacts:[paths], leader_note, prev_round_summary}',
  phases: [{ title: 'Review', detail: '6인 독립 채점' }],
}

const PROJ = 'C:/Users/zzang/하네스 엔지니어링 실습/상권분석 과제'
const A = args || {}
const PASS = 9.5

const BRIEF = `
[프로젝트] ${PROJ}
[과제] 클라이언트: 사모펀드(PE)가 보유한 커피·베이커리 전문점. 요청: 서울열린데이터로 "3년 뒤 성장할 상권"과 출점 입지 도출 → 인테리어 컨셉 → 메뉴 구성 → 손익 시뮬레이션. 최종 산출물: 한 페이지 HTML(GitHub 업로드) + 내레이션 2분 영상(HTML에 포함).
[과제 평가 기준, 각 10점]
 01 지표 설계의 논리성: 성장 상권 판단 지표·가중치가 MECE하고 지표 간 정합성 확보
 02 근거의 구체성: 주장마다 출처·기간·단위 명시, 사실로 확인됨
 03 인사이트: 클라이언트가 예상 못한 발견("와우")
 04 컨셉의 일관성: 상권분석→타깃·공간·메뉴·차별화·손익이 하나의 논리
 05 전달력: 2분 영상이 결론부터(Answer First), 웹페이지가 30초 안에 핵심 전달
[팀 규칙] ${PROJ}/TEAM_PROCESS.md 참조. 전체 단계: 1 데이터 정비 → 2 지표·백테스트 → 3 입지 선정 → 4 타깃·컨셉·메뉴 → 5 손익 → 6 스토리 → 7 제작·배포
`

const REVIEWERS = [
  { key: 'partner', name: '파트너 (컨설팅 파트너)', lens: '가장 날카로운 리뷰어. 논리 구조, MECE, So-what, Answer First, 과제 평가기준 01~05 관점에서 이 산출물이 최종 점수를 끌어올리는지/깎는지. 듣기 좋은 말 금지, 약점부터.' },
  { key: 'client', name: '고객 (PE 신규 출점 담당자)', lens: '투자 의사결정에 쓸 수 있는가: ROI·투자회수기간·다운사이드 리스크·다점포 확장성·실행 가능성. 컨설턴트 용어보다 "그래서 어디에, 얼마 벌고, 무엇이 위험한가".' },
  { key: 'expert_trdar', name: '전문가1 (상권 분석)', lens: '상권분석서비스 데이터의 구조·한계를 잘 안다. 지표 설계와 데이터 해석의 타당성(추정매출은 카드 기반 추정치, 유동인구≠구매, 상권 경계·코드 변경, 계절성, 생존 편향 등) 함정을 짚는다.' },
  { key: 'expert_fnb', name: '전문가2 (커피/제과)', lens: '커피·베이커리 매장 운영 실무. 객단가·원가율·생산 동선·인력·메뉴 믹스·시간대별 수요의 현실성. 이 단계 산출물이 이후 메뉴·손익 설계에 필요한 재료를 주는지도 본다.' },
  { key: 'expert_trend', name: '전문가3 (창업·자영업 트렌드)', lens: '2025~2026 자영업 시장(저가커피 확산, 디저트·베이커리 카페 경쟁, 폐업률, 임대료, 배달·테이크아웃 비중 등)과 정합한가. 과거 추세 외삽의 함정, 트렌드 반영 여부.' },
  { key: 'expert_ux', name: '전문가4 (UI/UX)', lens: '최종 웹페이지·영상으로 전달될 때 30초 안에 이해되는가. 이 단계 산출물이 시각화 가능한 형태로 정리됐는지, 핵심 메시지·숫자가 명확한지, 청중이 따라올 수 있는 구조인지.' },
]

const SCHEMA = {
  type: 'object',
  properties: {
    score: { type: 'number', minimum: 0, maximum: 10, description: '소수점 1자리' },
    verdict: { type: 'string', description: '한두 문장 총평' },
    strengths: { type: 'array', items: { type: 'string' } },
    must_fix: { type: 'array', description: '9.5에 도달하려면 반드시 고칠 것. 구체적으로(무엇을, 어떻게).',
      items: { type: 'object', properties: { issue: { type: 'string' }, why: { type: 'string' }, how: { type: 'string' } }, required: ['issue', 'why', 'how'] } },
    nice_to_have: { type: 'array', items: { type: 'string' } },
    checked: { type: 'array', items: { type: 'string' }, description: '직접 열어보거나 돌려서 확인한 것' },
  },
  required: ['score', 'verdict', 'strengths', 'must_fix', 'nice_to_have', 'checked'],
}

phase('Review')
const reviews = (await parallel(REVIEWERS.map(r => () => agent(`${BRIEF}
당신은 이 컨설팅 팀의 ${r.name} 이다.
관점: ${r.lens}

[리뷰 대상] ${A.stage}단계 "${A.title}" — 라운드 ${A.round || 1}
[이 단계의 목표] ${A.goal}
[산출물 파일] ${(A.artifacts || []).map(p => `${PROJ}/${p}`).join('\n')}
[팀장 메모] ${A.leader_note || '-'}
${A.prev_round_summary ? `[이전 라운드 지적과 팀장 반영 내역]\n${A.prev_round_summary}\n이전 지적이 실제로 해결됐는지 파일에서 확인하라.` : ''}

지시:
- 산출물 파일을 직접 열고, 주장 중 확인 가능한 것은 데이터(파일)로 직접 확인하라. Python은 \`py -I -X utf8\` 로 실행(pandas 있음). 파일은 수정하지 말 것. API 키(.env)는 출력하지 말 것.
- 이 단계의 목표 대비, 그리고 최종 과제 점수에 미치는 영향 기준으로 채점.
- 채점 기준선: 9.5~10 = PE 투자위원회에 그대로 올릴 수준·남은 지적 사소 / 9.0~9.4 = 반드시 고칠 결함 1~2개 / 8.0~8.9 = 주요 결함 / 7.9 이하 = 구조적 재작업. 점수 인플레 금지. 확인 못 한 주장은 감점.
- 9.5 미만이면 must_fix에 그 점수를 9.5 이상으로 올리는 데 필요한 것을 빠짐없이 적어라. 당신 관점과 무관한 단계라도, 이후 단계에서 당신 관점의 문제가 될 씨앗이 있으면 지적하라.`,
  { label: `review:${r.key}`, phase: 'Review', schema: SCHEMA })
  .then(res => res && ({ reviewer: r.key, name: r.name, ...res }))))).filter(Boolean)

if (reviews.length < REVIEWERS.length) log(`리뷰 누락: ${REVIEWERS.length - reviews.length}명`)
const avg = Math.round(reviews.reduce((s, r) => s + r.score, 0) / Math.max(1, reviews.length) * 100) / 100
// 통과 조건: 6명 전원 9.5 이상 (사용자 지정)
const below = reviews.filter(r => r.score < PASS).map(r => r.reviewer)
const pass = reviews.length === REVIEWERS.length && below.length === 0
log(`라운드 ${A.round || 1}: 평균 ${avg}, 최저 ${Math.min(...reviews.map(r => r.score))} (${reviews.map(r => `${r.reviewer} ${r.score}`).join(', ')}) → ${pass ? '통과' : `미달: ${below.join(', ')}`}`)
return { stage: A.stage, round: A.round || 1, avg, min: Math.min(...reviews.map(r => r.score)), below, pass, threshold: PASS, rule: 'all >= 9.5', reviews }
