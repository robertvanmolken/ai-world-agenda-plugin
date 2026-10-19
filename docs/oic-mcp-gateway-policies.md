# Oracle Integration MCP gateway: example policies for the AI World Agenda Assistant

This document proposes example policies for putting the Agenda Assistant behind the Oracle Integration (OIC Gen 3) MCP gateway. The rules are written in plain language. Nothing here is configured yet.

Source: Oracle documentation, "Secure and Manage MCP Servers with MCP Gateway", and the pages "Business and Security Policies for MCP Gateway", "Create Business Policies for MCP Servers" and "Create Security Policies for MCP Servers".

## What the gateway can do

| Policy type | What it controls | Scope | Enforced |
|---|---|---|---|
| Business policy | Allow or deny a call, based on a rule over the tool's input | One tool on one MCP server | Before the request is sent to the MCP server |
| Tool filter | Which tools of a server agents can discover | One MCP server (several filters possible) | Not applicable |
| PII detection | Block, redact, mask, replace or remove sensitive data (uses OCI Language) | Gateway, server or tool | Request, response or both |

A business policy sees the request only. It cannot judge a response.

## The tools on this server

All tools are read-only. They change nothing and store nothing.

| Tool | Input | Purpose |
|---|---|---|
| `search_sessions` | query, date, from_time, to_time, content_area, area_of_interest, session_type, industry, speaker, company, room, level, limit | Search the agenda |
| `get_session_by_code` | code | One session |
| `find_session_conflicts` | codes, minimum_transition_minutes | Overlaps among chosen sessions |
| `check_transition` | code_a, code_b | Can you walk from one session to the next |
| `check_walk` | from_place, to_place, gap_minutes | Walking check for custom stops |
| `plan_strict_day` | date, topics, lateness, lunch and networking settings, day_start, day_end, fixed_commitments | Full day plan |
| `optimize_agenda` | date, interests, minimum_transition_minutes, fixed_commitments | Simpler conflict-free agenda |
| `get_catalog_metadata` | none | Describes the catalog snapshot |
| `search`, `fetch` | query, id | ChatGPT-compatible search and fetch |

## Tool filters

Three filters, so each gateway exposes only what its audience needs.

### Filter 1: Attendee (general audience)
Expose: `search_sessions`, `get_session_by_code`, `find_session_conflicts`, `check_transition`, `check_walk`, `plan_strict_day`, `optimize_agenda`, `get_catalog_metadata`.

Why: everything an attendee needs. It leaves out the two generic tools, which duplicate search and exist for ChatGPT.

### Filter 2: ChatGPT compatibility
Expose: everything in Filter 1, plus `search` and `fetch`.

Why: ChatGPT's deep research and company knowledge features need `search` and `fetch`. Use this filter only for a gateway that ChatGPT connects to, and check it against your ChatGPT setup.

### Filter 3: Lookup only (restricted audience)
Expose: `search_sessions`, `get_session_by_code`, `get_catalog_metadata`.

Why: for a partner, kiosk or demo where people may browse sessions but not run the planning tools. The planning tools take more input and more compute, so this is the lowest-risk profile.

## Business policies

Each rule applies to one tool. The wording is plain language, ready to turn into policy logic.

### Search
1. **Cap the result count.** Deny `search_sessions` if `limit` is above 50. The default is 25.
2. **Require some input.** Deny `search_sessions` if the query and every filter are empty. This blocks a request that pulls the whole catalog.
3. **Check the date.** Deny any call where `date` is not YYYY-MM-DD, or is outside the event week.
4. **Check times.** Deny any call where `from_time`, `to_time`, `day_start`, `day_end` or the lunch and networking times are not HH:MM.

### Session lookups
5. **Check session codes.** Deny `get_session_by_code`, `check_transition` and `fetch` if a code doesn't look like a session code (letters followed by digits, such as LRN1128).
6. **Limit the list size.** Deny `find_session_conflicts` if `codes` has more than 15 entries.

### Walking checks
7. **Limit the gap.** Deny `check_walk` if `gap_minutes` is negative or above 240.
8. **Limit place text.** Deny `check_walk` if either place is longer than 100 characters.
9. **Block self-comparison.** Deny `check_transition` when both codes are the same.

### Planning
10. **Limit lateness.** Deny `plan_strict_day` if `late_tolerance_minutes` is above 10. Someone who accepts being 30 minutes late doesn't want a "strict" plan.
11. **Limit topics.** Deny `plan_strict_day` and `optimize_agenda` if there are more than 10 topics or interests, or any is longer than 100 characters.
12. **Limit lunch and networking.** Deny `plan_strict_day` if lunch is longer than 90 minutes, or networking blocks total more than 120 minutes.
13. **Limit fixed commitments.** Deny `plan_strict_day` and `optimize_agenda` if there are more than 10.
14. **Check the lateness basis.** Deny `plan_strict_day` unless `lateness_basis` is `worst` or `best`.

### Fair use
15. **Block likely scraping.** Deny any search whose query is a single wildcard-like value, such as `*`, `%` or `.`.
16. **Keep to read-only use.** Nothing here writes data, so no rule is needed. If a write tool is ever added, deny it by default and give it its own policy.

Notes:
- The gateway only sees the request. Rules about what comes back, such as hiding unconfirmed rooms, belong in the server.
- I didn't find per-user rate limits or role rules in the policy pages I read. Check the identity page ("Propagate User Identity for MCP Tool Invocations") before promising them.
- This server already validates some of these inputs. The gateway rules are a second layer, most useful for rules you want to change without redeploying.

## PII detection

### Where personal data could appear
- **Request:** free text in `query`, `speaker`, `company`, `topics`, `interests`, `from_place`, `to_place` and the titles inside `fixed_commitments`. A user may type an email address, a phone number or a private appointment.
- **Response:** speaker names and companies in session data. This is public catalog information.

### Policy 1: Protect free-text input (recommended)
- **Scope:** MCP gateway (all tools)
- **Enforcement:** request only
- **Detectors:** email address, phone number, social security number and any national ID detector offered. Add a custom pattern for payment-card numbers if the built-in list has none.
- **Action:** Redact, using Replace with a value such as `[removed]`
- **Why:** the tool has no use for these values and keeps no record. Redacting lets the search still run.

### Policy 2: Private commitments
- **Scope:** MCP tools `plan_strict_day` and `optimize_agenda`
- **Enforcement:** request only
- **Fields to scan:** only the `fixed_commitments` titles, using the inclusion list if your setup offers it
- **Action:** Block
- **Why:** these titles are the most likely place for private information, such as a medical or personal appointment. Blocking makes the user rephrase, which is clearer than silently changing a calendar entry.

### Not recommended: redacting responses
Don't apply PII detection to responses from the session tools. Speaker names, companies and email-like text in session descriptions are public, and redacting them would damage the answers. If you want to try it, limit it to one tool and test with real sessions first.

### Open points
- PII detection depends on the OCI Language service, which needs a compartment where the service is available. It may add a small delay and a cost per call.
- Detection is never perfect. It reduces risk and is not a guarantee.
- Whether a person's name is a detectable type depends on the detector list in your tenancy. I didn't confirm this.

## Before you build this

1. **Authentication:** the server has no authentication today. If the gateway should be the only way in, the server needs a way to reject direct calls, such as a shared secret that only the gateway sends. Check the gateway's authentication options in the OIC documentation.
2. **Test every rule:** the policy editor can generate rule code from a plain-language description. Review and test each generated rule before relying on it.
3. **Keep tool names in sync:** filters and policies point at tool names. If a tool is renamed in this repo, update the policy.
4. **Start small:** a first release could be Filter 1, rules 1, 5, 7, 10 and 11, and PII policy 1.
