# Security Policy

## Supported versions

Security fixes are considered for the current repository head. No released-version support window
is promised while the project remains a prototype.

## Reporting a vulnerability

Do not open a public issue for suspected vulnerabilities or privacy leaks. Use the repository's
private **Security → Report a vulnerability** form (GitHub private vulnerability reporting).
If that form is unavailable, contact the repository maintainer through the repository owner's
verified GitHub contact channel. Include a minimal reproduction, affected revision, impact, and
safe reproduction steps. Do not include real audio, transcripts, credentials, or endpoint
identifiers.

The maintainer will acknowledge a report when contact is possible, assess reproducibility and
impact, coordinate a fix where appropriate, and credit reporters only with their permission.

## Scope notes

Audio routing, local transcript handling, bundled dependencies, model downloads, and diagnostics
are in scope. Third-party call applications, operating-system drivers, and virtual audio drivers
are separately maintained, but report an unsafe interaction so it can be documented or mitigated.
