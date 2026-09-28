# SetuCode

> A minimal terminal AI coding agent.

SetuCode can read your project, understand code, make changes, run tools, and ask before doing sensitive actions.

### Features

* 🧠 Context management + compaction
* ⚡ Prompt prefix / KV caching
* 🧩 Skills with `SKILL.md`
* 📝 Plans + TODO tracking
* 🔐 Sandbox + permission system
* 🤖 Subagents
* 🔧 Tool-based code editing
* 🔌 Anthropic, OpenAI & Gemini

### Setup

Requires **Python 3.12+** and **uv**.

```bash
git clone https://github.com/druva-kiran/setucode.git
cd setucode
uv sync
```

Add your API key to `.env`:

```env
ANTHROPIC_API_KEY=...
# OPENAI_API_KEY=...
# GEMINI_API_KEY=...
```

### Run

```bash
uv run setucode
```

### Test

```bash
uv run pytest
```

### Structure

```text
setucode/
├── agent/
├── skills/
├── tools/
├── sandbox/
├── subagents/
└── dashboard/
```

Built to stay **small, modular, and under your control**.
