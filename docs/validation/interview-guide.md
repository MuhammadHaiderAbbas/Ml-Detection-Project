# User interview guide

**Purpose:** find out whether the problems Adaptive IDS addresses are real, frequent and costly for the
people who would use or pay for it, before more features are built.

**Rules for the interviewer**

- Ask about the **past and present** ("tell me about the last time…"), not the future ("would you use…?").
  People are generous about hypothetical products and accurate about their own week.
- Don't demo, pitch or defend the product until the last 10 minutes, and only if the person asks.
- Never ask for, accept or record real network data, credentials, IP addresses or incident details that
  identify an organisation. Notes are paraphrased and anonymised (participant ID, segment, organisation
  size band).
- Ask permission before taking notes or recording, and explain how notes are stored and when they will be
  deleted (suggested: 12 months).

## 1. Screener (5 questions, before booking)

1. Which best describes your role? (SOC analyst / SOC lead / IT or network admin / MSSP / researcher or
   educator / other)
2. Roughly how many employees does your organisation have? (<50 / 50–250 / 250–1,000 / >1,000)
3. Do you currently review network security alerts as part of your work? (daily / weekly / rarely / never)
4. Which tools produce those alerts today? (free text)
5. Are you involved in choosing or paying for security tools? (decide / recommend / no)

Prioritise people who answered *daily or weekly* to question 3. Aim for a mix of organisation sizes, and
of people who decide on tools and people who don't.

## 2. Hypotheses to test

| # | Hypothesis | Supported if people describe… | Refuted if… |
|---|---|---|---|
| H1 | Analysts can't tell **why** an ML or anomaly alert fired, and that slows triage or erodes trust | Spending time reconstructing the reason; ignoring a tool's alerts because they're opaque | They trust the scores, or never use ML-based tools |
| H2 | Detection quality **silently degrades** as traffic changes, and nobody notices until something is missed | A past incident or a noisy period traced to changed traffic or an untuned model | Their tools are rule-based and tuned weekly with no such problem |
| H3 | Changing a detection model or ruleset is risky, and there is **no evidence-based way to approve** a change | Rollbacks, change freezes, "we only update when the vendor does" | Changes are routine and safe |
| H4 | Small and medium organisations want this **on-premises**, not as a hosted service | Data that can't leave the site; regulatory or contractual limits | They already send flows to cloud SIEMs without concern |
| H5 | Someone would **pay** to solve H1–H3 | An existing budget line, a tool they replaced, a price they consider normal | No budget owner, or "only if it's free" |

## 3. Interview script (45 minutes)

**Opening (3 min).** Who you are, the purpose ("learning how teams handle network alerts; not selling"),
consent, and that they can skip any question.

**Context (7 min)**
- Walk me through a normal day or week, as far as alerts are concerned.
- What tools produce alerts for you? Which do you trust most and least, and why?

**Last real alert (10 min)** (H1)
- Tell me about the last alert you investigated that took longer than it should have. What happened?
- What did you need to know to decide? Where did you get it? How long did that take?
- When a tool gives a score or "anomaly", how do you decide whether to believe it?

**Change over time (8 min)** (H2)
- Has a tool ever become noisier or quieter without anyone changing it? How did you notice?
- What happened when your network changed (new service, migration, more remote staff)?

**Changing detections (7 min)** (H3)
- How are detection rules or models updated where you work? Who approves it? What evidence do they look at?
- Tell me about a change that went wrong, or that you were nervous about.

**Deployment and data (5 min)** (H4)
- Where is your security data allowed to go? Who decides that?
- What would an on-premises tool have to run on to be acceptable?

**Money (5 min)** (H5)
- What do you spend today on detection and monitoring tools, roughly? Who signs that off?
- What was the last tool you bought or dropped, and why?

**Close.** "Is there anything I should have asked?" Then, only if they want it, a 5-minute demo, using
synthetic data only. Ask who else you should talk to.

## 4. After each interview (within 24 hours)

Fill in one row of the synthesis table. Quote what people *did*, not their opinions about the product.

| ID | Segment | Org size | H1 | H2 | H3 | H4 | H5 | Strongest quote (paraphrased) | Follow-up / referral |
|---|---|---|---|---|---|---|---|---|---|
| P01 | | | ✓ / ✗ / ? | | | | | | |

**Mark a hypothesis ✓** only with a concrete past example. "That sounds useful" is **?**.

## 5. Synthesis (after 12–15 interviews)

- For each hypothesis: count ✓, ✗ and ?, and pick the two best examples.
- Rank the problems people raised unprompted. Did any of H1–H5 make their top two?
- Note what people asked for that this product doesn't do (for example live capture, a SIEM integration,
  SSO).
- Apply the decision gate in `phase-9-commercial-validation.md` §4 and write down the decision, with the
  date.
