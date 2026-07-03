---
name: stride-threat-model
description: Performs a systematic STRIDE threat modeling assessment on the current project's codebase and architecture. Use this when starting a new implementation phase or reviewing existing components.
---

# STRIDE Threat Modeling Skill

## Goal
Guide the agent to analyze the workspace directory structure, configuration files, and code files to produce a structured threat_model.md assessment.

## Instructions
1. **Analyze System Boundaries**: Map entry points (tools, workflows, data flows, parameters) and data storage layers.
2. **STRIDE Evaluation**: Evaluate against the six STRIDE pillars:
   - Spoofing: Are caller identities verified?
   - Tampering: Can users manipulate parameters or state?
   - Repudiation: Are critical transactions logged?
   - Information Disclosure: Are PII, tokens, or stack traces at risk?
   - Denial of Service: Are rate limits on expensive queries?
   - Elevation of Privilege: Can unauthenticated users reach privileged actions?
3. **Output**: Generate a highly structured threat_model.md saved directly into the workspace root.
