export const meta = {
  name: 'review-wide',
  description: 'Review a diff from several angles, try to refute every finding, and rank what survives',
  whenToUse: 'A large or risky change, when one reviewer is not enough. Pass { diff, plan } with the paths of a saved diff and of the plan it should satisfy. For a very large diff add segments, the output of scripts/segment_diff.py. The performance angle runs only when named in angles.',
  phases: [
    { title: 'Review', detail: 'one reviewer per angle, on the whole diff or on each of its segments' },
    { title: 'Synthesise', detail: 'with segments only: one reviewer on the whole diff, for what crosses them' },
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
  { key: 'security', brief: 'missing authorisation; injection into a query, a shell or a path; server-side request forgery; unsafe deserialisation; cross-site scripting or request forgery; secrets; unsafe handling of input from outside' },
  { key: 'tests', brief: 'tests that do not test the change, tests that were weakened, behaviour that changed with no test' },
  // Only when asked: most diffs add no query, remote call or loop over outside data.
  { key: 'performance', brief: 'cost that grows with the input: a query or remote call inside a loop (N+1), an unbounded query or loop, quadratic work on data that can be large, a resource never released; name the input size that makes it slow', optional: true },
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
const angles = input.angles === undefined ? ANGLES.filter((angle) => !angle.optional) : ANGLES.filter((angle) => [].concat(input.angles).includes(angle.key))
const against = input.plan ? ` against the plan at ${input.plan}` : ''

// Segments split a very large diff so each reviewer reads less (context degrades as it grows);
// the whole diff stays in reach, and one more reviewer looks only at what crosses them.
const MAX_SEGMENTS = 3
// An empty list is what segment_diff.py prints when splitting would not help: review the whole diff.
const segments = Array.isArray(input.segments) && input.segments.length === 0 ? undefined : input.segments
if (segments !== undefined) {
  const usable = Array.isArray(segments) && segments.length >= 2 && segments.length <= MAX_SEGMENTS &&
    segments.every((part) => part && typeof part.name === 'string' && typeof part.diff === 'string' &&
      Array.isArray(part.paths) && part.paths.length > 0) &&
    new Set(segments.map((part) => part.name)).size === segments.length
  if (!usable) {
    return { error: `segments must be 2 to ${MAX_SEGMENTS} entries of { name, diff, paths }, named apart and each with its paths, as scripts/segment_diff.py prints them` }
  }
}
const assignments = segments
  ? angles.flatMap((angle) => segments.map((part) => ({ angle, part })))
  : angles.map((angle) => ({ angle, part: null }))
const MAX_REVIEWERS = 12
if (assignments.length > MAX_REVIEWERS) {
  return { error: `at most ${MAX_REVIEWERS} reviewers by angle, besides the one across segments: ${angles.length} angles on ${segments.length} segments is ${assignments.length}. Drop an angle or a segment` }
}

phase('Review')
// A barrier on purpose: findings are merged across every reviewer before anything is verified.
const reviews = await parallel(
  assignments.map(({ angle, part }) => () =>
    agent(
      (part
        ? `Review one part of a change: the diff at ${part.diff}, which holds ${part.paths.join(', ')}. ` +
          `The whole change is at ${input.diff}${against}; read it for context, and report findings in your part only. `
        : `Review the diff at ${input.diff}${against}. `) +
        `Your angle is ${angle.key}: ${angle.brief}. ` +
        'Report only findings on that angle, each with the input or state that triggers it. Read the code the diff depends on.',
      { ...ROUTES.review, label: part ? `review:${angle.key}:${part.name}` : `review:${angle.key}`, phase: 'Review', schema: FINDINGS },
    ),
  ),
)

const reviewer = ({ angle, part }) => `reviewer for ${angle.key}${part ? ` on ${part.name}` : ''}`
const notRun = assignments.filter((_, index) => !reviews[index]).map(reviewer)
const order = { critical: 0, improvement: 1, nit: 2 }
const merged = new Map()
const add = (finding, angleName, partName) => {
  const key = `${finding.path}:${finding.line || 0}:${finding.claim.toLowerCase().replace(/\s+/g, ' ').slice(0, 80)}`
  const first = merged.get(key)
  if (!first) {
    merged.set(key, { ...finding, angles: [angleName], triggers: [finding.trigger], ...(segments ? { segments: partName ? [partName] : [] } : {}) })
    return
  }
  // Two reviewers, one finding: it keeps the graver of the two severities and every trigger named.
  if (!first.angles.includes(angleName)) first.angles.push(angleName)
  if (partName && first.segments && !first.segments.includes(partName)) first.segments.push(partName)
  if (!first.triggers.includes(finding.trigger)) first.triggers.push(finding.trigger)
  if (order[finding.severity] < order[first.severity]) {
    first.severity = finding.severity
    first.trigger = finding.trigger
  }
}
reviews.forEach((review, index) => {
  for (const finding of (review && review.findings) || []) add(finding, assignments[index].angle.key, assignments[index].part && assignments[index].part.name)
})

if (segments) {
  phase('Synthesise')
  const found = [...merged.values()].map((finding) => `- ${finding.path}: ${finding.claim}`).join('\n') || '(none)'
  let across = null
  try {
    across = await agent(
      `Synthesise: the change at ${input.diff}${against} was reviewed in parts (${segments.map((part) => part.name).join(', ')}). ` +
        `The parts' reviewers found:\n${found}\n` +
        'Report only faults that cross parts: an interface, a rename, a contract or data passed between them that one side changed ' +
        'and the other did not follow. Do not repeat the findings above.',
      { ...ROUTES.review, label: 'review:across', phase: 'Synthesise', schema: FINDINGS },
    )
  } catch (failure) {
    across = null // the parts' findings stand; the look across them is reported as not run
  }
  if (!across) notRun.push('reviewer across segments')
  for (const finding of (across && across.findings) || []) add(finding, 'across segments', null)
}
const candidates = [...merged.values()]
const reviewers = assignments.length + (segments ? 1 : 0)
log(`${candidates.length} candidate findings from ${reviewers - notRun.length} of ${reviewers} reviewers`)

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
