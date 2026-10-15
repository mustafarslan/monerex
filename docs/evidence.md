# Evidence

The rules monerex is built on, and where each comes from. Every source was opened and the claim
confirmed there in October 2026. Where only an abstract was read, or the evidence is thin, it
says so. Vendor posts report their own numbers and are marked *(vendor)*.

## The rules

| # | Rule | What the evidence shows |
|---|---|---|
| 1 | One writer by default. Fan out only independent, read-mostly work. | Multi-agent gave +80.8% on decomposable tasks and −70.0% on sequential planning, with gains shrinking as base models improve [1]. Two cooperating coding agents succeed about 30% less often than one doing both tasks [2]. Fourteen recurring failure modes across 1,600+ traces [3]. Multi-agent runs use about 15× the tokens of chat, and coding has few parallelisable tasks [4] *(vendor)*. |
| 2 | "Done" means an executed check passed. | Self-repair gains are small once cost is counted; self-correction needs reliable external feedback [5][6]. |
| 3 | Review in a fresh context; add another model family on risky diffs. | A cross-family reviewer is not significantly better than a fresh same-family one but finds different errors (overlap 41%); one of each caught 56.7% against 42.7% [7] — a single-author preprint. Judges favour their own and similar models' output [8][9]. |
| 4 | Reviewers hunt faults; one credible objection blocks; every finding is verified. | LLM judges approve almost everything: true-positive rate 96%, true-negative rate under 25%. Minority veto beats majority vote [10]. |
| 5 | Resolve ambiguity before coding; keep specs light and sized to the task. | Clarifying questions raised pass rate from 70.96% to 80.80% [11]. Planning is an accuracy aid for weaker models and mostly a cost saver for stronger ones [12]. Spec artifacts alone reduced neither defects nor rework across 88,052 PRs [13]. A heavy spec workflow measured about 10× slower in one practitioner trial [14]. |
| 6 | Instruction files hold only what the agent would otherwise get wrong. | Repository instruction files gave no general success gain and over 20% extra cost [15]; a smaller study found lower runtime [16]. |
| 7 | Skills are hand-curated and small, never auto-generated. | Curated skills +16.6 points; self-generated skills fell below the no-skill baseline [17]. |
| 8 | Each stage starts fresh and hands off through a short file. | All 18 tested models degrade as input grows [18][19]. Multi-turn underspecified tasks drop 39% on average [20]. |
| 9 | Passing tests is not mergeable; a human reads the diff at merge. | About half of test-passing agent PRs would not be merged [21]. Of 567 agent PRs, 83.8% merged and 45.1% of those needed revision [22]. Velocity gains were transient; added complexity persisted [23]. |
| 10 | Measure; feeling fast is not being fast. | Experienced developers were 19% slower with AI while believing they were 20% faster [24]; the follow-up was inconclusive [25]. Start with 20–50 tasks from real failures [26] *(vendor)*. |
| 11 | Route by rules and observed failure, not a learned router. | Prompt-only routers fail to reliably beat a simple baseline [27][28]. Retry-and-escalate baselines matched complex agents at a fraction of the cost [29]. |
| 12 | More effort is not automatically better. | Higher reasoning effort reduced accuracy in the majority of runs across 9 models [30]. High against low effort: 29.1% against 21.0% at 3.5× the cost [31]. |
| 13 | Escalation is triggered by the harness, never by the cheap model's own report. | Cheap executors consulted the stronger advisor on 0 of 198 questions [32] *(vendor)*. LLM patch judges: recall 0.93, precision 0.65 [33]. A strong planner with a cheaper editor beat the planner alone, 85% against 79.7%, single runs [34]. |
| 14 | Search by exploring with ordinary tools under a budget; return paths and excerpts, not contents. | An exploration agent on a limited budget that returns file paths and excerpts found the right document 0.867 of the time and answered correctly 0.627, against roughly 0.39 and 0.37 for semantic search over an index, at about 25% lower latency [62] *(vendor; one internal benchmark of 150 single-document financial questions — documents, not code)*. |

### Where the evidence is thin

- No controlled study of context isolation through subagents.
- No study of a stronger reviewer against a stronger author.
- No published evidence for diff size, blast radius or novelty as routing signals.
- No study of regression evals for a personal harness. The eval gate's threshold (a one-sided
  Fisher exact test at p < 0.1, on a few runs per case) is a judgement: with three runs it
  catches a drop to zero or near zero, not a small slide.
- No measurement of how many agent tasks one person can keep open and still review well. The
  limit of two is a judgement.
- No evidence that a contract-shaped plan beats a shorter one. The three added lines are kept
  short for that reason.

Rows in the routing table that rest on these are judgment, and the dispatch log exists to
correct them.

### Beliefs the evidence does not support

More agents is better. Role pipelines beat one good agent. Models catch their own errors. A
model improves itself by judging its own runs. A different-model reviewer is superior (it is
complementary). A bigger instruction file helps. A spec document by itself reduces defects.
Feeling faster means being faster.

## Specialist agents

Why the three specialists are built the way they are.

| Design choice | What the evidence shows |
|---|---|
| A specialist's prompt is a list of the field's known mistakes, not a persona. | Across 162 roles, four model families and 2,410 factual questions, adding a persona to the system prompt did not improve accuracy, and picking the best persona per question was close to random [53] *(abstract only)*. |
| The researcher may cite only what it opened in that run. | 55% of the citations one chat model generated were fabricated and 18% for its successor; of the real ones, 43% and 24% had substantive errors [54]. In 2026, 3–13% of the citation addresses given by commercial models and deep-research agents did not exist, with research agents worse than search-backed chat [55] *(preprint, abstract only)*. |
| The ML list starts with leakage and the evaluation, not the model. | Leakage was found to affect 294 papers across 17 fields, in eight recurring forms [56]. A catalogue of the common pitfalls by stage [59] *(a guide, not a study)*. |
| Reinforcement-learning results need several runs and an interval. | Ten runs with identical settings, split into two groups of five by seed, differed significantly; so did the same algorithm across codebases [57]. Point estimates from a few runs hide the uncertainty; interval estimates and the interquartile mean are recommended [58] *(abstract only)*. |
| An LLM score from one prompt wording is not a result. | Changing only the formatting of a prompt moved accuracy by up to 76 points in few-shot settings [60] *(abstract only)*. Judges favour their own output [8]. |
| The data list asks how many analyses were tried. | Twenty-nine teams given the same data and question reported odds ratios from 0.89 to 2.93; 20 found a significant effect and 9 did not [61] *(read from the publisher's index record)*. |

No study was found that compares a specialist subagent against a generalist given the same
checklist, so the choice of an agent over a skill rests on tool separation and a fresh
context, not on a measured gain. The routes for the three specialists are a starting guess.

## Measuring the loop

One vendor's developer guide to agents [63] *(vendor; it proposes practices and reports no
measurements of its own)* was read in full for what monerex was missing. Half of it is about
measuring and evaluating agents, which was the part of monerex not yet built.

| From the guide | In monerex |
|---|---|
| Start from outcome metrics: goal completion, each critical step counted as attempts and successes | **Taken:** a task log with one line per stage event, and a summary per tier: completion, checks passing first time, failed check runs, escalations by kind. |
| Compare the steps an agent took with a reference path: exact, in-order, any-order, precision, recall, single-tool use | **Taken inside the evals**, as "tool used" and "tool order" graders on fixed cases. **Refused as a score on real tasks:** an escalation legitimately changes the path, and done means a check passed (rule 2), not that the expected steps were walked. |
| Judge the final answer with a model against written criteria, and have people calibrate the judge | **Taken in part.** The smoke evals use no model judge, because judges approve almost everything (rule 4). The reviewer is the judge monerex does use, and the log counts how many of its findings were confirmed against rejected. |
| Collect a thumbs up or down from people | **Not added.** The three gates already record your verdict; the log keeps how many versions a plan took and the review's merge recommendation. |
| A task is a contract: deliverables with how each is verified, scope, expected cost, allowed inputs, early feedback on what is underspecified | **Taken:** the plan's *Done when*, *Inputs* and *Budget*, and the implementer's assessment as the first line of its report. Not taken: agents negotiating cost with each other. |
| Keep traces for debugging when a metric shows a problem | **Taken as a pointer:** the dispatch log names each agent's transcript and copies nothing. |
| Several agents cross-checking each other improve accuracy and reduce hallucination | **Refused.** The guide lists these advantages without figures, and the studies behind rule 1 measured the opposite on sequential work. |
| Agents decide what to copy into long-term memory | **Refused.** Rules 6 and 7. Lessons enter through `retro`, with your approval. |
| A registry of agents and tools once there are many | Not needed at nine agents. The routing table and the agent tests are the registry. |
| Retrieval pipelines, search tuning, the vendor's platform | Not relevant to a development loop. |

## Tasks side by side

One production system for people and agents sharing files [62] *(vendor, describing its own
product; documents and knowledge work, not code headed for a merge)* was read for what it
could teach a single developer's workflow.

| From that system | In monerex |
|---|---|
| Each agent works in its own disposable checkout and submits commits to a durable repository | Already the shape of monerex: stages start fresh and hand off through committed files (rule 8). **Taken further:** a second task in one repository gets its own worktree. |
| A submission is accepted only if it was built on the current head; otherwise the agent replays its change and resubmits. Fewer than 2% of submits were rejected as stale | **Taken:** a push that lacks the newest commits of the default branch is asked about, because the checks ran on an older base. Their rejection rate is for their workload; nobody has measured monerex's. |
| Every accepted write appends a log entry: repository, commit, user, changed paths | **Taken:** one log line per commit, with the session and the agents behind it. |
| A search agent on a limited budget returns paths and excerpts | **Taken as evidence** for `scout` (rule 14), which now works to a budget. |
| "Pull requests are unnecessary, because no human reviews each change" | **Refused.** For code, about half of test-passing agent changes would not be merged (rule 9). A check that passes is not a review, and the merge stays yours. |
| Background agents write knowledge pages that later agents read | **Refused.** Self-generated skills scored below having none (rule 7), and instruction files earn their cost only for what an agent would otherwise get wrong (rule 6). Lessons enter monerex through `retro`, with your approval. |
| The storage layer: object storage, cells, lazy download, compaction | Not relevant to one developer working locally. |

## Self-improvement

Three research systems that improve an agent from its own runs [64][65][66] were read for what
`retro` was missing: it proposed changes tied to numbers, but nothing reported later whether a
change had moved its number.

| From that work | In monerex |
|---|---|
| One model proposes multi-agent workflows, judges them against each other itself, and is fine-tuned on the winners, cycle after cycle [64] | **Refused.** Two cycles raised its own research benchmarks but lowered SWE-bench Verified (62.6 to 61.1) and Terminal-Bench 2.0 (37.5 to 35.2); gains were not monotonic, multi-agent runs used about 2.4× the tokens, and the authors note that generation, judging and revision share one prior, so self-feedback can reinforce errors. Rules 4, 7, 11 and 13 already refuse each part. |
| A skill written from practice is kept only if fresh solvers, sharing no history with its author, pass held-out tasks with it: 3.1 to 8.2 points over no skill on open models [65] *(project README; the paper was not read)* | **Taken in part.** Skills are still written by hand (rule 7); what is taken is the check. A retro proposal that changes a skill or an agent names the eval case that shows it working, three runs of three. |
| Candidates are scored against a sealed evaluator, and the winner is re-scored apart from where it was found and compared with ablations [66] *(project README)* | **Taken for the method itself.** Each accepted retro proposal is recorded, once its change has landed, with its number, its value and the way it should move (`.monerex/proposals.jsonl`); later retros judge it by the tasks in its tier started since: moved, revert candidate, or too thin when the number rests on fewer than five samples. The record is committed, not sealed: a changed baseline shows in the diff. Routing decisions are now logged with their task, so the summary shows which routes each tier asked for, how many were never dispatched, and how many dispatches no route asked for; agents are still placed in a task by its time window. |

## Security

| Finding | Source |
|---|---|
| Injection works: targeted attack success 33.9–57.7% against undefended agents | [35] |
| Payloads planted in repository files ran commands up to 84% of the time in coding assistants *(abstract only)* | [36] |
| Repository-controlled agent configuration has given code execution and key theft in coding agents | [37][38] |
| Adaptive attacks bypass 12 published defences, mostly above 90% | [39] |
| Hold at most two of untrusted input, sensitive access and outbound action, else a human approves | [40] |
| A quarantined reader with strict output format is rated safest for coding agents | [41] |
| Users approve 93% of permission prompts; the auto-approval classifier misses 17% of overeager actions *(vendor)* | [42] |
| The sandbox covers shell commands only; a broad allowed domain permits exfiltration | [43] |
| 45% of tasks produced flawed code across 100+ models, with no gain from newer models *(vendor)* | [44] |
| Best model 62% correct, and about half of correct programs exploitable | [45] |
| Vulnerability detector F1 falls from 68.26% to 3.09% on realistic data | [46] |
| Static-analysis feedback cut flagged issues from over 40% to 13% — one preprint | [47] |
| Suggested packages that do not exist: 5.2% commercial models, 21.7% open models | [48] |
| 26.1% of 31,132 public skills vulnerable; bundled scripts 2.12× likelier *(abstract only)* | [49] |
| Agent co-authored commits leak secrets at about twice the baseline *(vendor)* | [50] |
| CI agents given issue or PR text and write tokens have leaked secrets | [51] |

Controls map to OWASP LLM01 (prompt injection), LLM03 (supply chain), LLM05 (improper output
handling) and LLM06 (excessive agency) [52]. No published measurement of incident reduction
from sandboxing was found, and none for security-review prompts.

## Sources

1. Kim et al., *Towards a Science of Scaling Agent Systems*, 2025 — https://arxiv.org/abs/2512.08296
2. Khatua et al., *CooperBench*, 2026 — https://arxiv.org/abs/2601.13295
3. Cemri et al., *Why Do Multi-Agent LLM Systems Fail?*, 2025 — https://arxiv.org/abs/2503.13657
4. *How we built our multi-agent research system*, 2025 — https://www.anthropic.com/engineering/multi-agent-research-system
5. Olausson et al., *Is Self-Repair a Silver Bullet for Code Generation?*, 2023 — https://arxiv.org/abs/2306.09896
6. Kamoi et al., *When Can LLMs Actually Correct Their Own Mistakes?*, 2024 — https://arxiv.org/abs/2406.01297
7. Song, 2026 — https://arxiv.org/abs/2610.01471
8. Panickssery et al., *LLM Evaluators Recognize and Favor Their Own Generations*, 2024 — https://arxiv.org/abs/2404.13076
9. Goel et al., 2025 — https://arxiv.org/abs/2502.04313
10. Jain et al., *Beyond Consensus*, 2025 — https://arxiv.org/abs/2510.11822
11. Mu et al., *ClarifyGPT*, 2023 — https://arxiv.org/abs/2310.10996
12. Fan et al., 2026 — https://arxiv.org/abs/2609.20804
13. Hill, ESEM 2026 — https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.ESEM.2026.84
14. *Putting Spec Kit Through Its Paces*, 2025 — https://blog.scottlogic.com/2025/11/26/putting-spec-kit-through-its-paces-radical-idea-or-reinvented-waterfall.html
15. Gloaguen et al., 2026 — https://arxiv.org/abs/2602.11988
16. Lulla et al., 2026 — https://arxiv.org/abs/2601.20404
17. Li et al., *SkillsBench*, 2026 — https://arxiv.org/abs/2602.12670
18. *Context Rot*, 2025 — https://www.trychroma.com/research/context-rot
19. Modarressi et al., *NoLiMa*, 2025 — https://arxiv.org/abs/2502.05167
20. Laban et al., *LLMs Get Lost in Multi-Turn Conversation*, 2025 — https://arxiv.org/abs/2505.06120
21. *Many SWE-bench-passing PRs would not be merged into main*, 2026 — https://metr.org/notes/2026-03-10-many-swe-bench-passing-prs-would-not-be-merged-into-main/
22. Watanabe et al., 2025 — https://arxiv.org/abs/2509.14745
23. He et al., 2025 — https://arxiv.org/abs/2511.04427
24. Becker et al., 2025 — https://arxiv.org/abs/2507.09089
25. *Uplift update*, 2026 — https://metr.org/blog/2026-02-24-uplift-update/
26. *Demystifying evals for AI agents*, 2026 — https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
27. Li et al., *LLMRouterBench*, 2026 — https://arxiv.org/abs/2601.07206
28. Lu et al., *The Routing Plateau*, 2026 — https://arxiv.org/abs/2606.07587
29. Kapoor et al., *AI Agents That Matter*, 2024 — https://arxiv.org/abs/2407.01502
30. Kapoor et al., *Holistic Agent Leaderboard*, 2025 — https://arxiv.org/abs/2510.11977
31. Cuadron et al., *The Danger of Overthinking*, 2025 — https://arxiv.org/abs/2502.08235
32. *Optimizing for cost and intelligence* — https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence
33. Shi et al., 2025 — https://arxiv.org/abs/2511.10865
34. *Separating code reasoning and editing*, 2024 — https://aider.chat/2024/09/26/architect.html
35. Debenedetti et al., *AgentDojo*, 2024 — https://arxiv.org/abs/2406.13352
36. Liu et al., *Your AI, My Shell*, 2025 — https://arxiv.org/abs/2509.22040
37. CVE-2025-59536 and CVE-2026-21852 — https://research.checkpoint.com/2026/rce-and-api-token-exfiltration-through-claude-code-project-files-cve-2025-59536/
38. Marzouk, *IDEsaster* (CVE-2025-53773 and others), 2025 — https://maccarita.com/posts/idesaster/
39. Nasr et al., *The Attacker Moves Second*, 2025 — https://arxiv.org/abs/2510.09023
40. *Agents Rule of Two*, 2025 — https://ai.meta.com/blog/practical-ai-agent-security/
41. Beurer-Kellner et al., *Design Patterns for Securing LLM Agents against Prompt Injections*, 2025 — https://arxiv.org/abs/2506.08837
42. *Claude Code auto mode*, 2026 — https://www.anthropic.com/engineering/claude-code-auto-mode
43. Sandboxing documentation — https://code.claude.com/docs/en/sandboxing
44. 2025 GenAI code security report — https://www.veracode.com/press-release/ai-generated-code-poses-major-security-risks-in-nearly-half-of-all-development-tasks-veracode-research-reveals/
45. Vero et al., *BaxBench*, 2025 — https://arxiv.org/abs/2502.11844
46. Ding et al., *PrimeVul*, ICSE 2025 — https://arxiv.org/abs/2403.18624
47. Blyth et al., 2025 — https://arxiv.org/abs/2508.14419
48. Spracklen et al., USENIX Security 2025 — https://www.usenix.org/conference/usenixsecurity25/presentation/spracklen
49. Liu et al., *Agent Skills in the Wild*, 2026 — https://arxiv.org/abs/2601.10338
50. *State of Secrets Sprawl 2026* — https://www.gitguardian.com/state-of-secrets-sprawl-report-2026
51. *PromptPwnd*, 2025 — https://www.aikido.dev/blog/promptpwnd-github-actions-ai-agents
52. *OWASP Top 10 for LLM Applications*, 2025 — https://genai.owasp.org/llm-top-10/
53. Zheng et al., *When "A Helpful Assistant" Is Not Really Helpful*, 2023 — https://arxiv.org/abs/2311.10054
54. Walters and Wilder, *Fabrication and errors in the bibliographic citations generated by ChatGPT*, Scientific Reports, 2023 — https://www.nature.com/articles/s41598-023-41032-5
55. Rao et al., *Detecting and Correcting Reference Hallucinations in Commercial LLMs and Deep Research Agents*, 2026 — https://arxiv.org/abs/2604.03173
56. Kapoor and Narayanan, *Leakage and the reproducibility crisis in machine-learning-based science*, Patterns, 2023 — https://pmc.ncbi.nlm.nih.gov/articles/PMC10499856/
57. Henderson et al., *Deep Reinforcement Learning that Matters*, 2017 — https://arxiv.org/abs/1709.06560
58. Agarwal et al., *Deep Reinforcement Learning at the Edge of the Statistical Precipice*, 2021 — https://arxiv.org/abs/2108.13264
59. Lones, *How to avoid machine learning pitfalls*, 2021 — https://arxiv.org/abs/2108.02497
60. Sclar et al., *Quantifying Language Models' Sensitivity to Spurious Features in Prompt Design*, 2023 — https://arxiv.org/abs/2310.11324
61. Silberzahn et al., *Many Analysts, One Data Set*, 2018 — https://doi.org/10.1177/2515245917747646
62. *Building shared workspaces for people and agents*, 2026 — https://www.perplexity.ai/hub/blog/building-shared-workspaces-for-people-and-agents
63. Gulli et al., *Agents Companion*, 2025 — https://www.kaggle.com/whitepaper-agent-companion
64. Lee et al., *Recursive Self-Improvement through Multi-Agent Self-Supervision*, 2026 — https://arxiv.org/abs/2610.12176 *(read in part)*
65. NJU-LINK, *Socratic Skill Learning*, 2026 — https://github.com/NJU-LINK/Socratic-Skill-Learning
66. Sakana AI, *The Agentic Scientist (AI-Scientist-v3)*, 2026 — https://github.com/SakanaAI/AI-Scientist-v3
