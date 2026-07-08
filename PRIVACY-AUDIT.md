# Privacy Audit — release/ tree

This directory is intended to become the full public repository content.

## Automated Scan

The release tree was scanned for:

- local home-directory paths
- personal account handles and email-like identifiers
- legacy private bundle identifiers
- internal project names and old product codenames
- private machine names

Result: no accidental private identifiers found.

The only intentional non-English app name is the localized Simplified Chinese display name: `老管家`.

## What Was Kept

- native Swift menu-bar app source
- stdlib-only Python data engine
- public assets
- README, LICENSE, installation script

## What Was Removed

- private planning documents
- legacy implementation folders
- local strategy notes
- private repository history
- real project bucket names

## Release Notes

- Bundle identifier uses the public namespace `com.agentbutler`.
- Example project buckets are generic.
- The app is local-only: no telemetry, no hosted backend, no account system.
