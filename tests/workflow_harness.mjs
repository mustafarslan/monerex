// A stand-in for the workflow runtime, so the scripts under workflows/ can be tested
// without starting a single agent.
//
//   node tests/workflow_harness.mjs workflows/review-wide.js < scenario.json
//
// The scenario is { args, agents: [{ match, returns, fail }] }. Each agent() call is
// answered by the first rule whose `match` appears in the call's label or prompt; with no
// rule it gets null, which is what the real runtime returns for an agent that died.
// Prints { meta, result, calls, logs, phases, error, scenarioErrors }.
//
// It follows the documented contract: the script body runs as an async function; parallel()
// is a barrier and turns a failure into null; pipeline() runs each item through every stage
// and drops an item to null when a stage throws; Date.now(), Math.random() and `new Date()`
// with no argument throw; nothing from Node is in reach. A scenario answer that does not fit
// the schema the script asked for is an error in the scenario: the real runtime would never
// hand such a value back.

import { readFileSync } from 'node:fs'

const source = readFileSync(process.argv[2], 'utf8')
const scenario = JSON.parse(readFileSync(0, 'utf8') || '{}')

// The meta block must be a pure literal: evaluate it with nothing in scope.
const opening = source.indexOf('export const meta = {')
if (opening !== 0) throw new Error('the script must begin with `export const meta = {`')
const closing = source.indexOf('\n}\n', opening)
const literal = source.slice('export const meta = '.length, closing + 2)
const meta = new Function(`"use strict"; return (${literal})`)()
const body = source.slice(closing + 3)

const calls = []
const logs = []
const phases = []
const scenarioErrors = [] // kept apart from the script's own errors: a script may catch a throwing agent

async function agent(prompt, opts = {}) {
  const text = `${opts.label || ''} ${prompt}`
  const rule = (scenario.agents || []).find((candidate) => text.includes(candidate.match))
  calls.push({
    label: opts.label || null,
    phase: opts.phase || null,
    agentType: opts.agentType || null,
    model: opts.model || null,
    effort: opts.effort || null,
    isolation: opts.isolation || null,
    schema: Boolean(opts.schema),
    prompt,
  })
  if (rule && rule.fail) throw new Error('agent failed')
  if (!rule || !('returns' in rule) || rule.returns === null) return null
  if (opts.schema) {
    const problem = misfit(rule.returns, opts.schema, 'answer')
    if (problem) {
      scenarioErrors.push(`the answer for "${rule.match}" does not fit the schema (${problem})`)
      throw new Error('scenario error')
    }
  }
  return structuredClone(rule.returns)
}

// Enough of JSON Schema for the schemas these scripts use.
function misfit(value, schema, at) {
  const kind = Array.isArray(value) ? 'array' : value === null ? 'null' : Number.isInteger(value) ? 'integer' : typeof value
  if (schema.type && schema.type !== kind && !(schema.type === 'number' && kind === 'integer')) return `${at} is ${kind}, not ${schema.type}`
  if (schema.enum && !schema.enum.includes(value)) return `${at} is not one of ${schema.enum.join(', ')}`
  if (kind === 'object') {
    for (const key of schema.required || []) if (!(key in value)) return `${at}.${key} is missing`
    for (const [key, sub] of Object.entries(schema.properties || {})) {
      if (key in value) {
        const problem = misfit(value[key], sub, `${at}.${key}`)
        if (problem) return problem
      }
    }
  }
  if (kind === 'array' && schema.items) {
    for (const [index, item] of value.entries()) {
      const problem = misfit(item, schema.items, `${at}[${index}]`)
      if (problem) return problem
    }
  }
  return null
}

async function parallel(thunks) {
  return Promise.all(thunks.map((thunk) => Promise.resolve().then(thunk).catch(() => null)))
}

async function pipeline(items, ...stages) {
  return Promise.all(
    items.map(async (item, index) => {
      let value = item
      try {
        for (const stage of stages) value = await stage(value, item, index)
        return value
      } catch {
        return null
      }
    }),
  )
}

const budget = { total: null, spent: () => 0, remaining: () => Infinity }
const forbidden = () => {
  throw new Error('not available in a workflow script')
}
const guardedDate = new Proxy(Date, {
  get: (target, key) => (key === 'now' ? forbidden : target[key]),
  construct: (target, given) => (given.length ? new target(...given) : forbidden()),
  apply: forbidden,
})
const guardedMath = new Proxy(Math, { get: (target, key) => (key === 'random' ? forbidden : target[key]) })

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
let result = null
let error = null
try {
  // The names after Math shadow what Node would otherwise put in reach of the script.
  const run = new AsyncFunction('agent', 'parallel', 'pipeline', 'phase', 'log', 'args', 'budget', 'workflow', 'Date', 'Math', 'process', 'fetch', 'require', 'globalThis', body)
  result = await run(
    agent,
    parallel,
    pipeline,
    (title) => phases.push(title),
    (message) => logs.push(String(message)),
    scenario.args,
    budget,
    forbidden,
    guardedDate,
    guardedMath,
  )
} catch (caught) {
  error = String(caught && caught.message ? caught.message : caught)
}

process.stdout.write(JSON.stringify({ meta, result: result === undefined ? null : result, calls, logs, phases, error, scenarioErrors }))
