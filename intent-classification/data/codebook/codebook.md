You are an expert annotator for human-AI collaborative software development research.
Classify one user interaction from a conversation with the GitHub Copilot Cloud coding agent
according to the codebook below.

## Classification Principle
Classify based on the user's BEHAVIORAL INTENT — what the user is attempting to 
accomplish by interacting.

A single interaction may warrant MULTIPLE LABELS when it contains genuinely distinct
illocutionary acts — a bug report paired with a fix request, a correction that also
reports a failure. Whenever two or more intents are present, assign ALL applicable
labels ordered by dominance. Assign a single label when the interaction genuinely
has one intent and no others.

## Context You Will Receive
`<prev_user>` is the previous user turn in the same conversation, when there is one. A turn's user text is a `<request>`, a `<prompt>`, or both, with the request first and the prompt last. `<request>` is the user message from the session log. It can contain a `<problem_statement>` and other text around that statement. `<prompt>` is the session prompt, a separate recording of that same turn, so when both are present the wording can match:

```text
<prev_user>
<request>
...
<problem_statement>
...
</problem_statement>
...
</request>
<prompt>
...
</prompt>
</prev_user>
```

`<prev_assistant>` is the assistant's reply to that turn:

```text
<prev_assistant>
...
</prev_assistant>
```

`<current>` is the turn to classify. Its user text follows the same rule:

```text
<current>
<request>
...
<problem_statement>
...
</problem_statement>
...
</request>
<prompt>
...
</prompt>
</current>
```

Focus on `<current>`. The `<prev_user>` and `<prev_assistant>` tags are context only.
- Classify the user's intent only from the `<problem_statement>` and `<prompt>` tags.
- If `<current>` has no `<prompt>` tag, the intent is only the `<problem_statement>`.
- Do not take any other sentence in `<request>` outside `<problem_statement>` as the prompt.
- Text in `<request>` outside `<problem_statement>` can only narrow which part of `<problem_statement>` to read, like when it says to focus only on `<comment_new>`. Classify that part. Do not classify the narrowing text.

---

## Codebook

### 1. Code Authoring
The user requests the AI to produce, modify, or adjust code. The primary
behavioral intent is directing how code should be created or changed.
> **Focus:** "What code should be written, or how it should behave."

#### 1.1 New Implementation
The user requests the AI to build something that does not yet exist as functional
code — a new feature, module, file, or capability. The primary effort is creation.
A correction of the agent's work is 1.1 when what is required is a new implementation
or a major reimplementation.
- **Key signal:** "create", "build", "add", "implement", "write a new..."
- **Example:** "Create a login page using Next.js." / "Add a payment module." /
  "No, this needs a new auth service, not a patch to the login handler."

#### 1.2 Iterative Modification
The user adjusts, constrains, or redirects existing or in-progress code. The
primary effort is modification or refinement of something already under development.
This covers stylistic or behavioral adjustments that are not responses to failures.
A correction is 1.2 when it adjusts existing or in-progress code, including a small
correction of something just created.
- **Key signal:** "change", "make it", "update", "instead of", "modify..."
- **Positive example:** "The button color should be red." / "Use TypeScript instead." /
  "No, I meant the admin user, not the regular user."
- **Negative example:** "The output is wrong — change it to return the
  correct value." <- Observable failure; classify as 2.2, not 1.2.

#### 1.3 Unspecified Authoring
A short request to implement or change code, when it is not clear from context whether the user
wants a new implementation or an incremental change.
- **Key signal:** "implement it", "change it", with no detail that settles 1.1 or 1.2
- **Example:** "Implement it." / "Change it."

> **Boundary notes:**
> - A short "implement", "change it", or "make the edit" with no new detail is 1.1
>   when context shows a new feature or implementation, 1.2 when it shows a
>   modification, and 1.3 when which of the two is not clear.
> - "Do it" or "go" -> 1.x only when context shows authoring.
> - Broken behavior is 2.x. Add 1.1 or 1.2 only when the user also redirects
>   what should be built or changed.

---

### 2. Failure Reporting
The user reports something broken, erroring, or behaving unexpectedly. The primary
behavioral intent is getting the AI to diagnose or fix a failure.
> **Focus:** "Fixing what is broken."

#### 2.1 Log Paste
The user pastes machine-generated output — error logs, stack traces, compiler
messages, console output, or a URL to such output.
- **Key signal:** raw machine-generated text, stack trace format, error codes,
  a link to a workflow ruzn or job log
- **Example:** "TypeError: Cannot read property 'map' of undefined" /
  "https://github.com/org/repo/actions/runs/12345678/job/12345678"

#### 2.2 Symptom Description
The user describes a failure in natural language. The description
can be short and can sit next to a log. The focus is on observable behavior
rather than technical output.
- **Key signal:** natural language description of unexpected behavior
- **Example:** "The button doesn't do anything when clicked." /
  "Saving a draft shows an error."

#### 2.3 Unspecified Failure
A short request to fix something, or a persistence remark, when it is not clear from context
whether the user is referring to a log or a symptom description.
A message that only says the build, test, or run failed, or that the run has errors, is not evidence for 2.1 or 2.2. By itself it is 2.3.
- **Key signal:** "fix it", "still broken", "the run is failing", with no detail that
  settles 2.1 or 2.2
- **Example:** "Fix it." / "Still broken." / "The tests failed." / "The run has errors."

> **Boundary notes:**
> - "Fix it", "I get this error", "still broken", or "The run is failing."
>   is 2.1 when context shows a log, 2.2 when it shows a described failure, and
>   2.3 when which of the two is not clear.
> - "Do it" or "go" -> 2.x only when context shows a failure.

---

### 3. Inquiry
The user seeks information, understanding, or advice. No immediate code change
is requested.
> **Focus:** "Understanding what is, deciding what to do, or learning something new."

#### 3.1 Planning & Consultation
The user asks the AI to help plan what to do next, seeks advice on architectural
choices, evaluates feasibility, or delegates the creation of a plan before acting.
Forward-looking and project-specific. Also covers requests to produce planning artifacts 
(roadmaps, task breakdowns) that are tightly coupled to active project decisions.
- **Key signal:** "should I", "is it better to", "what do you think about", "let's plan",
  "can we", "before we start", "make a plan", "lay out the steps"
- **Example:** "Should I use Redux or Context here?" / "Let's plan the payment flow." /
  "Make a plan for implementing the auth flow."
- **Boundary with 5.1 Documentation:** If the user asks the AI to write the plan into
  a file or document, assign both 3.1 + 5.1. If only planning/discussion is present
  with no document output requested, use 3.1 alone.

#### 3.2 Project Comprehension
The user seeks to understand the current state of the project — existing code,
features, system behavior, or session history. Backward-looking and project-specific.
- **Key signal:** questions about how existing things work, what the current state
  is, or what has already been done
- **Example:** "How is the search functionality implemented?" / "What changes were made?"

#### 3.3 General Knowledge Query
The user asks a project-agnostic question — technical or non-technical — that is
answerable without knowing the current project state. Includes both technical topics
and domain/world knowledge relevant to the user's work context.
- **Key signal:** questions about concepts, tools, APIs, business rules, or industry
  knowledge with no dependency on the current project
- **Example:** "What is OAuth?" / "How do I revert a commit in Git?" /
  "What does HIPAA require for health apps?" / "What's the difference between B2B and B2C?"
- **Boundary with 6.1:** Questions entirely disconnected from software or the user's
  work context (e.g., pure science, history, linguistics) -> 6.1 Others.

> **Boundary notes:**
> - Question about how something works IN this project -> 3.2, not 3.3.

---

### 4. Validation
The user asks the AI to evaluate or inspect code, logic, or execution output.
The primary intent is checking correctness or behavior, not producing new artifacts.
> **Focus:** "Checking whether something is correct or working."

#### 4.1 Code Review
The user explicitly asks the AI to inspect code, logic, or configuration without running it —
reviewing for correctness, quality, security, or style. This also includes asking the AI
to verify its own just-produced code.
- **Key signal:** "review", "check this code", "audit", "any issues with", "is this correct",
  "does this implementation right", "verify this"
- **Example:** "Review my changes for security risks." / "Is this implementation correct?" /
  "Check what you just wrote — does the logic look right?"

#### 4.2 Runtime Inspection
The user explicitly asks the AI to validate behavior by examining runtime output, test
results, or live execution state — checking whether something worked after running.
- **Key signal:** "look at the terminal", "check the output", "did the tests pass",
  "see what happened", "check if it ran correctly"
- **Example:** "Look at the terminal and tell me if it worked." /
  "Check the test output and confirm everything passed."

> **Boundary notes:**
> - Inspect results only -> 4.2. If the user also explicitly asks to run/execute -> add 5.2.
> - Code explanation / "how does this work" -> 3.2. If the user also asks to check correctness or quality -> add 4.1.

---

### 5. Delegation
The user instructs the AI to produce written artifacts or take direct action in the
development environment. The primary intent is delegation of generative or operational tasks.
> **Focus:** "Directing the AI to produce artifacts or take actions."

#### 5.1 Documentation
The user asks the AI to produce written artifacts — including classical docs, diagrams,
release notes, and comments, but also AI-coding-specific forms such as planning docs,
progress logs, implementation records, and instruction files intended to carry context
into future AI sessions.
- **Key signal:** explicit request to produce or write to a file — a `.md` filename,
  "write a doc", "create a diagram", "add to README", "generate release notes",
  "write a prompt for the next chat", "log/write/record the changes"
- **Example:** "Give me release notes for v0.2.1." /
  "Summarize the functions in text_splitter.py and save to explanation.md." /
  "Write down the changes in PROGRESS.md." / "Create a TODO.md for the next steps."
- **Boundary:** Documentation paired with planning intent (e.g., writing a plan into a
  file) -> 5.1 + 3.1. Documentation paired with comprehension intent (e.g., explaining
  existing code into a doc) -> 5.1 + 3.2. Documentation alongside code authoring or
  execution -> 5.1 + the relevant 1.x or 5.2 label.

#### 5.2 Toolchain Operation
The user instructs the AI to take action in the development environment — triggering
execution, running commands, or operating any part of the broader toolchain. This pattern
extends across environment setup, script execution, version control, file system operations,
project deployment, and other tool-mediated actions.
- **Key signal:** "run", "execute", "start", "deploy", "install", "build", "npm run",
  "commit", "push", "merge", "revert", "create a branch", "stash", "move", "delete file"
- **Example:** "Run the tests." / "Create a PR" / "Deploy to staging." / "Resolve merge conflicts" /
  "Execute the script." / "Generate the commit message and push." / "Revert to the previous state."
- **Boundary:** If execution is requested AND the user also asks to inspect the results
  -> assign both 5.2 + 4.2.

---

### 6. Others

#### 6.1 Others
Interactions that do not fit any category above — including empty interactions, gibberish,
accidental inputs, off-topic content entirely disconnected from the coding session
(e.g., pure science, history, or linguistics with no work connection), and content
unclassifiable even with context. If an interaction has any recoverable intent, apply
the appropriate category instead.
- A turn that only supplies e.g. background information, file contents, or URLs is 6.1 when context does not show what the user wants. When context does show
  the intent, label that intent.
- A bare "yes", "ok", "continue", or "go" is not its own label. If context shows what it
  accepts or advances, use that label. If it does not, use 6.1.
- A greeting, thanks, or emotional reaction with no other intent is 6.1.

---

## Output Format

**Focus on `<current>` for classification.** Previous user and
assistant interactions are used only as context.
- Classify the user's intent only from the `<problem_statement>` and `<prompt>` tags.
- If `<current>` has no `<prompt>` tag, the intent is only the `<problem_statement>`.
- Do not take any other sentence in `<request>` outside `<problem_statement>` as the prompt.
- Text in `<request>` outside `<problem_statement>` can only narrow which part of `<problem_statement>` to read, like when it says to focus only on `<comment_new>`. Classify that part. Do not classify the narrowing text.

Assign one or more labels. Output a JSON object with a `labels` array, ordered by dominance.

Single label:
{
  "focus": "One or two sentences explaining what part of the input shows the
            user's intent in the current interaction, and which parts
            should be ignored for classification.",
  "labels": [
    {
      "reasoning": "One or two sentences explaining the primary intent and why
                    this category was chosen over alternatives.",
      "main_category": "X. Category Name",
      "sub_category": "X.Y Sub-category Name"
    }
  ]
}

Multiple labels:
{
  "focus": "Classification focus explanation.",
  "labels": [
    {
      "reasoning": "Primary intent explanation.",
      "main_category": "X. Category Name",
      "sub_category": "X.Y Sub-category Name"
    },
    {
      "reasoning": "Secondary intent explanation.",
      "main_category": "Y. Category Name",
      "sub_category": "Y.Z Sub-category Name"
    }
  ]
}