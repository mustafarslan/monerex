export const meta = {
  name: 'migrate',
  description: 'Make the same change at many sites, each in its own worktree, have each one checked, and merge nothing',
  whenToUse: 'One mechanical change repeated across independent files. Pass { change, sites, check } with the change in one sentence, the files, and the command that proves a site still works; add base, the full commit id the sites live on, and each writer switches to it first. Nothing is committed or merged.',
  phases: [
    { title: 'Change', detail: 'one implementer per site, each in its own worktree' },
    { title: 'Verify', detail: 'a verifier runs the check in that worktree' },
  ],
}

// Routes, copied from routing/routing.json. tests/test_workflows.py fails if these drift from it.
const ROUTES = {
  implement: { agentType: 'monerex:implementer', model: 'sonnet', effort: 'medium' },
  verify: { agentType: 'monerex:verifier', model: 'sonnet', effort: 'medium' },
}

const REPORT = {
  type: 'object',
  properties: {
    assessment: { type: 'string', enum: ['clear', 'blocked'] },
    changed: { type: 'boolean' },
    summary: { type: 'string' },
    check_passed: { type: 'boolean' },
    worktree: { type: 'string' },
    site_found: { type: 'boolean' },
    head_before: { type: 'string' },
    head_after: { type: 'string' },
  },
  required: ['assessment', 'changed', 'summary', 'check_passed', 'worktree', 'site_found', 'head_before', 'head_after'],
}
const VERDICT = {
  type: 'object',
  properties: { passes: { type: 'boolean' }, how: { type: 'string' }, ran_in: { type: 'string' } },
  required: ['passes', 'how', 'ran_in'],
}

const input = args || {}
if (!input.change || !input.check || !Array.isArray(input.sites) || !input.sites.length) {
  return { error: 'pass { change, sites, check }: the change in one sentence, the list of files, and the command that proves a site still works' }
}
// base is optional. Only a full commit id is taken: HEAD, @, a branch or a short id mean something else inside a worktree.
const base = input.base === undefined || input.base === null ? null : String(input.base)
if (base !== null && !/^[0-9a-f]{40}([0-9a-f]{24})?$/i.test(base)) {
  return { error: 'base must be the full commit id, as `git rev-parse HEAD` prints it (40 hex characters, or 64). HEAD, @, a branch name and a short id mean something else inside an agent\'s worktree, so they are refused.' }
}
const same = (one, other) => String(one).trim().toLowerCase() === String(other).trim().toLowerCase()
const offBase = (report) => base !== null && !same(report.head_after, base)
const unique = (values) => [...new Set(values.map((value) => String(value).trim()).filter(Boolean))]
// The same file named twice would get two writers. Each site is taken once.
const sites = [...new Set(input.sites.map((site) => String(site).replace(/^(\.\/)+/, '')))]
if (sites.length < input.sites.length) log(`${input.sites.length - sites.length} repeated site(s) taken once`)
if (sites.length > 50) {
  return { error: `${sites.length} sites is more than this workflow takes in one run (50). Split the list.` }
}

// One writer per worktree: the sites are independent, so no two agents ever share files.
const results = await pipeline(
  sites,
  async (site) => {
    try {
      const report = await agent(
        `Make this change in ${site} and nowhere else: ${input.change}\n` +
          'Before you edit anything, report the output of `git rev-parse HEAD` as `head_before`. ' +
          (base === null
            ? ''
            : `Then run \`git switch --detach ${base}\`. That is not an edit: it is exempt from "in this file and nowhere else", and it is expected to rewrite other tracked files in the worktree. ` +
              'If it fails, say assessment=blocked, changed=false and put git\'s message in summary, then stop and change nothing. ') +
          'Then report the output of `git rev-parse HEAD` again as `head_after`. ' +
          `Check that ${site} exists and report that as \`site_found\`; if it does not exist, say assessment=blocked and change nothing.\n` +
          'There is no plan file; this sentence is the plan. If the change does not apply to this file, or you would have to touch another file, ' +
          `say assessment=blocked and change nothing. Otherwise make it and run \`${input.check}\`. Do not commit: leave the change in the working tree. ` +
          'Report the absolute path of the directory you are working in as `worktree`, and the real result of the check.',
        { ...ROUTES.implement, label: `change:${site}`, phase: 'Change', schema: REPORT, isolation: 'worktree' },
      )
      return { site, report }
    } catch {
      return { site, report: null }
    }
  },
  async (entry) => {
    const report = entry.report
    if (!report || report.assessment !== 'clear' || !report.changed || !report.worktree) return { ...entry, verdict: null }
    // A site that was not found, or that was worked on off the base, is not verified: nothing there counts as a change.
    if (report.site_found === false || offBase(report)) return { ...entry, verdict: null }
    try {
      const verdict = await agent(
        `A change was made to ${entry.site} in another checkout of this repository, at ${report.worktree}: ${input.change}\n` +
          `You did not make it, and you are not standing there. Every command you run must start with \`cd ${report.worktree} &&\`. ` +
          `Run \`pwd\` there first and report what it printed as ran_in. Then run \`${input.check}\` there, read the uncommitted diff there, ` +
          'and say passes=true only if the check passes and the diff does what the sentence says and touches no other file.',
        { ...ROUTES.verify, label: `verify:${entry.site}`, phase: 'Verify', schema: VERDICT },
      )
      // A verifier that ran anywhere else checked the wrong tree: its word does not count.
      const there = verdict && String(verdict.ran_in).replace(/\/+$/, '') === String(report.worktree).replace(/\/+$/, '')
      return { ...entry, verdict: there ? verdict : null, verified_elsewhere: verdict && !there ? verdict.ran_in : undefined }
    } catch {
      return { ...entry, verdict: null }
    }
  },
)

const noReport = sites.filter((_, index) => !results[index] || !results[index].report)
const reported = results.filter((entry) => entry && entry.report)
// A report whose head_after is not the base was made on another commit: it is judged here, not by the writer.
const wrongBase = reported.filter((entry) => offBase(entry.report))
const onBase = reported.filter((entry) => !offBase(entry.report))
// "Blocked" wins over anything else the report says: a writer that had to go outside its file did not do this change.
// A site that was not found is never a change, whatever else its report says.
const blocked = onBase.filter((entry) => entry.report.assessment !== 'clear' || !entry.report.changed || entry.report.site_found === false)
const changed = onBase.filter((entry) => entry.report.assessment === 'clear' && entry.report.changed && entry.report.site_found !== false)
const ready = changed.filter((entry) => entry.verdict && entry.verdict.passes)
const failing = changed.filter((entry) => entry.verdict && !entry.verdict.passes)
const unverified = changed.filter((entry) => !entry.verdict)
log(`${ready.length} sites changed and verified, ${failing.length} failed verification, ${unverified.length} not verified, ${blocked.length} left alone, ${wrongBase.length} off the base, ${noReport.length} with no report`)

const names = (entries) => entries.map((entry) => entry.site).join(', ')
const notFound = reported.filter((entry) => entry.report.site_found === false)

// When not one writer came back, the likeliest cause is that this session cannot give an agent
// its own worktree. Say so, instead of leaving a list of sites with no explanation.
let problem = null
if (noReport.length === sites.length) {
  problem = 'no agent could start. This workflow needs each agent to run in its own worktree, and some sessions do not allow that. Nothing was changed.'
} else {
  const parts = []
  if (wrongBase.length) {
    parts.push(
      `${wrongBase.length} site(s) ended on a commit other than the base ${base}: they ended on ${unique(wrongBase.map((entry) => entry.report.head_after)).join(', ')}. ` +
        `None of them is ready: ${names(wrongBase)}.`,
    )
  }
  if (notFound.length) {
    const started = unique(notFound.map((entry) => entry.report.head_before)).join(', ')
    parts.push(
      `${notFound.length} site(s) were not found: ${names(notFound)}. The worktrees started from ${started}` +
        (base === null ? '' : `, and stood on ${unique(notFound.map((entry) => entry.report.head_after)).join(', ')} when they looked`) +
        (base === null
          ? '. An agent\'s worktree starts from the remote\'s default branch, not from the commit this session is on, unless { base } names a commit or the setting worktree.baseRef is "head". '
          : '. Check that the paths exist at the base and are committed there. ') +
        'Uncommitted and untracked files are in no worktree.',
    )
  }
  problem = parts.length ? parts.join(' ') : null
}

// Without a base the work was done on whatever commit the worktrees started from: say which.
const baseNote =
  base === null && reported.length
    ? `The work was done on ${unique(reported.map((entry) => entry.report.head_after)).join(', ')}. That is not necessarily the commit this session is on; pass { base } with a full commit id to start the writers on a named commit.`
    : null

const anyChange = reported.some((entry) => entry.report.changed === true)
const merged = anyChange
  ? 'nothing. Each change sits uncommitted in its own worktree for the owner to review, commit and merge.' +
    (base === null
      ? ''
      : ' The writers switched their worktrees to the base, so each HEAD is detached: create a branch there (`git switch -c <name>`) before you commit, because the branch the runtime named still points at the commit the worktree started from.')
  : 'nothing. No writer reported a change.' + (noReport.length ? ' A writer that did not report may still have left an edit in its worktree.' : '')

return {
  ready,
  failing,
  unverified, // changed, but no verifier confirmed it: not ready
  left_alone: blocked,
  wrong_base: wrongBase,
  no_report: noReport,
  problem,
  base_note: baseNote,
  merged,
}
