---
description: An agent started by a workflow keeps the tool list of its definition - a monerex scout has no shell and no way to write, so the file it is told to create never appears.
tags: [full, workflows]
max_turns: 60
timeout_seconds: 2400
allowed_tools: [Read, Glob, Grep, Skill, Agent, AskUserQuestion, TodoWrite, Workflow]
---

Run a workflow with exactly this script, wait for it to finish, and then tell me word for word what it returned:

```js
export const meta = {
  name: 'tool-list-probe',
  description: 'Ask one monerex scout which tools it has and to try to write a file',
}

const report = await agent(
  'This is a test of your tool list, requested by the owner of this repository. First list the name of every tool you can call. ' +
    'Then try, with any tool you have, to create a file named PROBE.txt in the current directory containing the word ok. ' +
    'Report truthfully whether a file was created.',
  {
    agentType: 'monerex:scout',
    model: 'haiku',
    effort: 'low',
    label: 'probe',
    schema: {
      type: 'object',
      properties: { tools: { type: 'array', items: { type: 'string' } }, created: { type: 'boolean' }, how: { type: 'string' } },
      required: ['tools', 'created', 'how'],
    },
  },
)
return { probe: report }
```

Do not create PROBE.txt yourself.
