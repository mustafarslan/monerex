export const meta = {
  name: 'audit',
  description: 'Ask one question of many paths, check each answer, and say what was not covered',
  whenToUse: 'A read-only sweep too wide for one context. Pass { question, paths } with the question and the files or folders to ask it of.',
  phases: [
    { title: 'Read', detail: 'one reader per path' },
    { title: 'Check', detail: 'each answer that found something is checked against the code' },
    { title: 'Gaps', detail: 'what the sweep did not cover' },
  ],
}

// Routes, copied from routing/routing.json. tests/test_workflows.py fails if these drift from it.
const ROUTES = {
  search: { agentType: 'monerex:scout', model: 'haiku', effort: 'low' },
  verify: { agentType: 'monerex:verifier', model: 'sonnet', effort: 'medium' },
  plan: { agentType: 'monerex:architect', model: 'opus', effort: 'medium' },
}

const ANSWER = {
  type: 'object',
  properties: {
    found: { type: 'boolean' },
    answer: { type: 'string' },
    evidence: { type: 'array', items: { type: 'object', properties: { path: { type: 'string' }, line: { type: 'integer' }, note: { type: 'string' } }, required: ['path', 'note'] } },
  },
  required: ['found', 'answer', 'evidence'],
}
const CHECK = { type: 'object', properties: { holds: { type: 'boolean' }, how: { type: 'string' } }, required: ['holds', 'how'] }
const GAPS = { type: 'object', properties: { gaps: { type: 'array', items: { type: 'string' } } }, required: ['gaps'] }

const input = args || {}
if (!input.question || !Array.isArray(input.paths) || !input.paths.length) {
  return { error: 'pass { question, paths }: the question, and the list of files or folders to ask it of' }
}

// Each path goes through both stages by itself; nothing waits for the slowest reader.
const results = await pipeline(
  input.paths,
  (path) =>
    agent(`Question: ${input.question}\nAnswer it for ${path} only. Report what the code does, with path and line; if it does not apply there, say found=false.`, {
      ...ROUTES.search,
      label: `read:${path}`,
      phase: 'Read',
      schema: ANSWER,
    }),
  async (answer, path) => {
    if (!answer || !answer.found) return { path, answer, check: null }
    try {
      const check = await agent(
        `Someone answered a question about ${path}. Treat the answer as a claim and check it against the code.\nQuestion: ${input.question}\nAnswer: ${answer.answer}\n` +
          `Evidence given: ${JSON.stringify(answer.evidence)}\nSay holds=true only if the code supports it.`,
        { ...ROUTES.verify, label: `check:${path}`, phase: 'Check', schema: CHECK },
      )
      return { path, answer, check }
    } catch {
      return { path, answer, check: null } // the path was read; only its check is missing
    }
  },
)

const unread = input.paths.filter((_, index) => !results[index] || !results[index].answer)
const read = results.filter((result) => result && result.answer)
const supported = read.filter((result) => result.check && result.check.holds)
const unsupported = read.filter((result) => result.answer.found && result.check && !result.check.holds)
const unchecked = read.filter((result) => result.answer.found && !result.check)
log(`${read.length} of ${input.paths.length} paths read; ${supported.length} findings held, ${unsupported.length} did not, ${unchecked.length} unchecked`)

phase('Gaps')
let critic = null
try {
  critic = await agent(
    `A sweep asked "${input.question}" of these paths: ${input.paths.join(', ')}. Paths that could not be read: ${unread.join(', ') || 'none'}. ` +
      'Looking at the repository, name what the sweep should also have covered to answer the question, at most ten items. Do not answer the question itself.',
    { ...ROUTES.plan, label: 'gaps', phase: 'Gaps', schema: GAPS },
  )
} catch {
  critic = null // the last call is the likeliest to fail; what was already found must still be returned
}

return {
  question: input.question,
  supported,
  unsupported,
  unchecked,
  nothing_found: read.filter((result) => !result.answer.found).map((result) => result.path),
  not_read: unread,
  gaps: critic ? critic.gaps : null,
  not_run: critic ? [] : ['the gap check'],
}
