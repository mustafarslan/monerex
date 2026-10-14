export const meta = {
  name: 'review-wide',
  description: 'Review a diff from several angles, try to refute every finding, and rank what survives',
  whenToUse: 'A large or risky change, when one reviewer is not enough. Pass { diff, plan } with the paths of a saved diff and of the plan it should satisfy.',
  phases: [
    { title: 'Review', detail: 'one reviewer per angle, each on the same diff' },
    { title: 'Verify', detail: 'every finding put to a verifier told to refute it' },
  ],
}

// Routes, copied from routing/routing.json: a workflow script cannot ask the table, and
// nothing may be inherited. tests/test_workflows.py fails if these drift from it.
const ROUTES = {
  review: { agentType: 'monerex:reviewer', model: 'opus', effort: 'high' },
  verify: { agentType: 'monerex:verifier', model: 'sonnet', effort: 'medium' },
}

const ANGLES = [
  { key: 'correctness', brief: 'behaviour that is wrong: logic errors, unhandled cases, broken callers, error paths that fail open' },
  { key: 'fit', brief: 'gaps between the diff and what the plan asked for, and places where it works against the existing structure' },
  { key: 'security', brief: 'missing authorisation, injection, secrets, unsafe handling of input from outside' },
  { key: 'tests', brief: 'tests that do not test the change, tests that were weakened, behaviour that changed with no test' },
]

const FINDINGS = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          path: { type: 'string' },
          line: { type: 'integer' },
          claim: { type: 'string' },
          trigger: { type: 'string' },
          severity: { type: 'string', enum: ['critical', 'improvement', 'nit'] },
        },
        required: ['path', 'claim', 'trigger', 'severity'],
      },
    },
  },
  required: ['findings'],
}

const VERDICT = {
  type: 'object',
  properties: {
    outcome: { type: 'string', enum: ['reproduced', 'consistent', 'refuted'] },
    how: { type: 'string' },
  },
  required: ['outcome', 'how'],
}

const input = typeof args === 'string' ? { diff: args } : args || {}
if (!input.diff) {
  return { error: 'pass { diff, plan }: the path of a saved diff, and of the plan if there is one' }
}
const known = ANGLES.map((angle) => angle.key)
if (input.angles !== undefined) {
  const asked = Array.isArray(input.angles) ? input.angles : [input.angles]
  const unknown = asked.filter((key) => !known.includes(key))
  // A mistyped angle must not quietly become a review that never ran.
  if (!asked.length || unknown.length) {
    return { error: `angles must be some of: ${known.join(', ')}. Not known: ${unknown.join(', ') || '(none given)'}` }
  }
}
const angles = input.angles === undefined ? ANGLES : ANGLES.filter((angle) => [].concat(input.angles).includes(angle.key))
const against = input.plan ? ` against the plan at ${input.plan}` : ''

phase('Review')
// A barrier on purpose: findings are merged across every reviewer before anything is verified.
const reviews = await parallel(
  angles.map((angle) => () =>
    agent(
      `Review the diff at ${input.diff}${against}. Your angle is ${angle.key}: ${angle.brief}. ` +
        'Report only findings on that angle, each with the input or state that triggers it. Read the code the diff depends on.',
      { ...ROUTES.review, label: `review:${angle.key}`, phase: 'Review', schema: FINDINGS },
    ),
  ),
)

const notRun = angles.filter((_, index) => !reviews[index]).map((angle) => `reviewer for ${angle.key}`)
const order = { critical: 0, improvement: 1, nit: 2 }
const merged = new Map()
reviews.forEach((review, index) => {
  for (const finding of (review && review.findings) || []) {
    const key = `${finding.path}:${finding.line || 0}:${finding.claim.toLowerCase().replace(/\s+/g, ' ').slice(0, 80)}`
    const first = merged.get(key)
    if (!first) {
      merged.set(key, { ...finding, angles: [angles[index].key], triggers: [finding.trigger] })
      continue
    }
    // Two reviewers, one finding: it keeps the graver of the two severities and every trigger named.
    first.angles.push(angles[index].key)
    if (!first.triggers.includes(finding.trigger)) first.triggers.push(finding.trigger)
    if (order[finding.severity] < order[first.severity]) {
      first.severity = finding.severity
      first.trigger = finding.trigger
    }
  }
})
const candidates = [...merged.values()]
log(`${candidates.length} candidate findings from ${angles.length - notRun.length} of ${angles.length} reviewers`)

phase('Verify')
const judged = await parallel(
  candidates.map((finding) => () =>
    agent(
      `A reviewer claims this about the diff at ${input.diff}. Treat it as a claim, not a fact, and try to refute it.\n` +
        `Where: ${finding.path}${finding.line ? `:${finding.line}` : ''}\nClaim: ${finding.claim}\nStated trigger: ${finding.triggers.join(' / ')}\n` +
        'Read the code and, where a test can settle it, run one. Answer "reproduced" if you made it happen, ' +
        '"consistent" if the code agrees with the claim but you did not reproduce it, "refuted" only if you can show it is wrong.',
      { ...ROUTES.verify, label: `verify:${finding.path}`, phase: 'Verify', schema: VERDICT },
    ).then((verdict) => ({ ...finding, verdict })),
  ),
)

// A verifier that died leaves its finding unchecked. That is reported, never dropped and never counted as cleared.
const unchecked = candidates.filter((_, index) => !judged[index] || !judged[index].verdict)
const checked = judged.filter((finding) => finding && finding.verdict)
const ranked = (findings) => [...findings].sort((a, b) => order[a.severity] - order[b.severity])
const withOutcome = (outcome) => ranked(checked.filter((finding) => finding.verdict.outcome === outcome))

return {
  confirmed: withOutcome('reproduced'),
  plausible: withOutcome('consistent'),
  rejected: withOutcome('refuted'),
  unchecked: ranked(unchecked),
  not_run: notRun,
}
