---
name: skill-creator
description: Automatically creates, scaffolds, and formats new custom Antigravity agent skills inside the current project (.agent/skills/) or global directory (~/.gemini/antigravity/skills/). Use this whenever the user asks to create a new skill, generate a skill, or turn instructions into a skill.
---

# Antigravity Skill Creator Instructions

When the user asks to build or generate a new skill, follow these rules:

## 1. Skill Location
Determine if the user wants a workspace-level skill or a global skill:
- **Project Scope (Default):** `.agent/skills/<skill-name>/`
- **Global Scope:** `%USERPROFILE%\.gemini\antigravity\skills\<skill-name>\` (Windows) or `~/.gemini/antigravity/skills/<skill-name>/` (POSIX)

## 2. Directory & File Structure
Create the skill folder containing at minimum a `SKILL.md` file: