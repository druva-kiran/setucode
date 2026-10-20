# SetuCode

A fast, lightweight AI coding agent that runs right in your terminal. Built to help you write, test, and fix code without getting in your way.

---

## Table of Contents
- [What is SetuCode?](#what-is-setucode)
- [Key Features](#key-features)
- [Setup & Installation](#setup--installation)
- [How to Run](#how-to-run)
- [Running Tests](#running-tests)
- [Project Structure](#project-structure)

---

## What is SetuCode?

SetuCode is an autonomous software engineering agent inspired by tools like Hermes and Claude Code. It reads your files, uses tools to execute commands, catches its own test/compiler errors, and self-corrects until your task is done.

## Key Features

- **Self-Healing Loop**: When tests or builds fail, exit codes and stack traces feed back into the agent so it can fix the code immediately.
- **Smart Patching**: If a unified diff patch fails due to whitespace or line mismatch, it gets the exact file snippet back so it never gets stuck.
- **Rigorous Safeguards**: Programmatically blocked from finishing modifying tasks with chat text alone — it has to actually write or edit code files.
- **Provider Agnostic**: Works out-of-the-box with Anthropic Claude, OpenAI, and Google Gemini.
- **Zero Bloat**: Clean, understandable Python codebase with no unnecessary frameworks.

## Setup & Installation

Make sure you have **Python 3.12+** and **uv** installed.

```bash
git clone https://github.com/druva-kiran/setucode.git
cd setucode
uv sync
```

## How to Run

Launch SetuCode or configure your API provider:

```bash
# Run interactive agent session
uv run setucode

# Run setup wizard to configure API keys & models
uv run setucode --setup
```

## Running Tests

To run the full test suite with pytest:

```bash
python -m pytest
```

## Project Structure

```text
setucode/
├── app/
│   ├── agent/       # ReAct loop, state, and execution guardrails
│   ├── tools/       # File read, write, edit, search, and run_command
│   ├── skills/      # Dynamic skill loader and execution hints
│   ├── memory/      # Persistent memory management
│   ├── subagents/   # Subagent delegation manager
│   └── permissions/ # Sandbox and security checks
├── dashboard/       # TUI / Dashboard and entry point
└── tests/           # Comprehensive pytest suite
```
