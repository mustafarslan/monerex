export const meta = {
  name: 'plan-from-angles',
  description: 'Draft several independent designs for one task, judge them, and recommend one',
  whenToUse: 'A feature where the first design that comes to mind should not win by default. Pass { task } or { task, intent } with the path of an accepted intent file.',
  phases: [
    { title: 'Design', detail: 'one design per angle, none seeing the others' },
    { title: 'Judge', detail: 'one judge compares them and recommends' },
  ],
}

// Routes, copied from routing/routing.json. tests/test_workflows.py fails if these drift from it.
const ROUTES = {
  plan: { agentType: 'monerex:architect', model: 'opus', effort: 'medium' },
  review: { agentType: 'monerex:reviewer', model: 'opus', effort: 'high' },
}

const ANGLES = [
  { key: 'smallest', brief: 'the smallest change that delivers the outcome, leaving out everything that can wait' },
  { key: 'safest', brief: 'the least risk to behaviour that already works, even if it takes more steps' },
  { key: 'durable', brief: 'the shape that the next two likely changes would fit into without rework' },
]

const DESIGN = {
  type: 'object',
  properties: {
    approach: { type: 'string' },
    files: { type: 'array', items: { type: 'string' } },
    risks: { type: 'array', items: { type: 'string' } },
    checks: { type: 'array', items: { type: 'string' } },
    open_questions: { type: 'array', items: { type: 'string' } },
  },
  required: ['approach', 'files', 'risks', 'checks', 'open_questions'],
}
const RULING = {
  type: 'object',
  properties: {
    recommended: { type: 'string' },
    why: { type: 'string' },
    taken_from_others: { type: 'array', items: { type: 'string' } },
    against_each: { type: 'array', items: { type: 'object', properties: { angle: { type: 'string' }, weakness: { type: 'string' } }, required: ['angle', 'weakness'] } },
    decisions_for_the_owner: { type: 'array', items: { type: 'string' } },
  },
  required: ['recommended', 'why', 'taken_from_others', 'against_each', 'decisions_for_the_owner'],
}

const input = typeof args === 'string' ? { task: args } : args || {}
if (!input.task) {
  return { error: 'pass { task }, and { intent } with the path of an accepted intent file if there is one' }
}
const brief = input.intent ? `${input.task}\nThe accepted intent is at ${input.intent}; the design may not go beyond it.` : input.task

phase('Design')
// A barrier on purpose: the judge needs every design side by side.
const designs = await parallel(
  ANGLES.map((angle) => () =>
    agent(`Design this, reading the code it touches first:\n${brief}\nAim for ${angle.brief}. Name every file that would change and the commands that would prove it works.`, {
      ...ROUTES.plan,
      label: `design:${angle.key}`,
      phase: 'Design',
      schema: DESIGN,
    }),
  ),
)
const drafted = ANGLES.map((angle, index) => ({ angle: angle.key, design: designs[index] })).filter((entry) => entry.design)
const notRun = ANGLES.filter((_, index) => !designs[index]).map((angle) => `design for ${angle.key}`)
if (drafted.length < 2) {
  return { error: 'fewer than two designs came back, so there is nothing to compare', designs: drafted, not_run: notRun }
}

phase('Judge')
let ruling = null
try {
  ruling = await agent(
    `Compare these designs for the task below and recommend one. Look for what is wrong with each before what is right.\nTask: ${brief}\n` +
      `Designs: ${JSON.stringify(drafted)}\nName the angle you recommend, what to take from the others, the weakness of each, and the choices only the owner can make.`,
    // The judge names one of the designs that came back, in the script's own words for it.
    {
      ...ROUTES.review,
      label: 'judge',
      phase: 'Judge',
      schema: { ...RULING, properties: { ...RULING.properties, recommended: { type: 'string', enum: drafted.map((entry) => entry.angle) } } },
    },
  )
} catch {
  ruling = null // the designs are still worth returning
}
// The judge may only recommend a design that was drafted.
const exists = Boolean(ruling) && drafted.some((entry) => entry.angle === ruling.recommended)

return {
  designs: drafted,
  ruling: exists ? ruling : null,
  ruling_problem: ruling && !exists ? `the judge recommended "${ruling.recommended}", which is not one of the designs that came back` : null,
  not_run: ruling ? notRun : [...notRun, 'the judge'],
}
