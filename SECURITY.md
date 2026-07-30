# Security Policy

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Instead, use GitHub's private vulnerability reporting:
1. Go to the [Security tab](https://github.com/BrendanWorks/happypdf/security) of this repository.
2. Click "Report a vulnerability."

This opens a private advisory visible only to the maintainer until a fix is ready, so the issue isn't disclosed before it can be addressed.

If you're reporting an issue with a third-party dependency (Modal, olmOCR, Anthropic/OpenAI/Google APIs) rather than happypdf's own code, please report it to that project directly as well.

## Scope

This covers the happypdf codebase (`api/`, `src/`, `modal/`, `frontend/`) and its deployment configuration. It does not cover the security of your own self-hosted deployment's infrastructure (Modal account, secrets manager, ingress): see the [Self-hosting checklist](README.md#self-hosting-checklist) in the README for hardening guidance there.

## What to Include

- A description of the vulnerability and its potential impact.
- Steps to reproduce, if possible.
- Which part of the system is affected (frontend, API, pipeline, a specific deployment mode).

## Response

This is a small, actively-maintained project; response time is best-effort, not guaranteed. Confirmed vulnerabilities will be fixed and disclosed via a GitHub Security Advisory once a patch is available.
