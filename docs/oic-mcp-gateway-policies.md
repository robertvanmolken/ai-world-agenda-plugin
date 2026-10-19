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

In the gateway, a business policy applies to one tool on one MCP server, and you can't combine tools in one policy. So there is one policy per tool below. Each policy lists every check that belongs to that tool, so it can be written as a single rule. The wording is plain language, ready to turn into policy logic.

A check that appears in several tools, such as the session code format, is repeated in each tool's policy.

| # | Policy (one tool) | Tool |
|---|---|---|
| 1 | Search guard | `search_sessions` |
| 2 | Session lookup guard | `get_session_by_code` |
| 3 | Conflict check guard | `find_session_conflicts` |
| 4 | Transition guard | `check_transition` |
| 5 | Walk check guard | `check_walk` |
| 6 | Strict day plan guard | `plan_strict_day` |
| 7 | Agenda optimizer guard | `optimize_agenda` |
| 8 | ChatGPT search guard | `search` |
| 9 | ChatGPT fetch guard | `fetch` |

`get_catalog_metadata` takes no input, so it needs no policy.

### 1. Search guard (`search_sessions`)
Deny the call if any of these is true:
- `limit` is above 50. The default is 25.
- The query and every filter are empty. This blocks a request that pulls the whole catalog.
- The query is a single wildcard-like value, such as `*`, `%` or `.`.
- `date` is given but is not YYYY-MM-DD, or is outside the event week.
- `from_time` or `to_time` is given but is not HH:MM.

### 2. Session lookup guard (`get_session_by_code`)
Deny the call if `code` doesn't look like a session code: letters followed by digits, such as LRN1128.

### 3. Conflict check guard (`find_session_conflicts`)
Deny the call if any of these is true:
- `codes` has more than 15 entries, or is empty.
- Any code doesn't look like a session code.
- `minimum_transition_minutes` is negative or above 120.

### 4. Transition guard (`check_transition`)
Deny the call if any of these is true:
- `code_a` or `code_b` doesn't look like a session code.
- `code_a` and `code_b` are the same.

### 5. Walk check guard (`check_walk`)
Deny the call if any of these is true:
- `gap_minutes` is negative or above 240.
- `from_place` or `to_place` is empty or longer than 100 characters.

### 6. Strict day plan guard (`plan_strict_day`)
Deny the call if any of these is true:
- `date` is not YYYY-MM-DD, or is outside the event week.
- `topics` is empty, has more than 10 entries, or any entry is longer than 100 characters.
- `late_tolerance_minutes` is above 10. Someone who accepts being 30 minutes late doesn't want a "strict" plan.
- `lateness_basis` is not `worst` or `best`.
- `lunch_minutes` is above 90.
- `networking_blocks` times `networking_minutes` is above 120.
- `day_start`, `day_end`, `lunch_from`, `lunch_until`, `networking_from` or `networking_until` is not HH:MM.
- `fixed_commitments` has more than 10 entries.

### 7. Agenda optimizer guard (`optimize_agenda`)
Deny the call if any of these is true:
- `date` is not YYYY-MM-DD, or is outside the event week.
- `interests` is empty, has more than 10 entries, or any entry is longer than 100 characters.
- `minimum_transition_minutes` is negative or above 120.
- `fixed_commitments` has more than 10 entries, or any time in them is not HH:MM.

### 8. ChatGPT search guard (`search`)
Deny the call if the query is empty, longer than 200 characters, or a single wildcard-like value such as `*`, `%` or `.`. Only needed on a gateway that exposes this tool (tool filter 2).

### 9. ChatGPT fetch guard (`fetch`)
Deny the call if `id` doesn't look like a session code. Only needed on a gateway that exposes this tool (tool filter 2).

### Notes
- Read-only: nothing here writes data. If a write tool is ever added, give it its own policy and deny by default.
- The gateway only sees the request. Rules about what comes back, such as hiding unconfirmed rooms, belong in the server.
- I didn't find per-user rate limits or role rules in the policy pages I read. Check the identity page ("Propagate User Identity for MCP Tool Invocations") before promising them.
- This server already validates some of these inputs. The gateway rules are a second layer, most useful for rules you want to change without redeploying.
- A tool filter only decides which tools are visible. If a tool is not exposed, its policy is not needed.

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

### Policy 2: Private commitments in `plan_strict_day`
- **Scope:** MCP tool `plan_strict_day`
- **Enforcement:** request only
- **Fields to scan:** only the `fixed_commitments` titles, using the inclusion list if your setup offers it
- **Action:** Block
- **Why:** these titles are the most likely place for private information, such as a medical or personal appointment. Blocking makes the user rephrase, which is clearer than silently changing a calendar entry.

### Policy 3: Private commitments in `optimize_agenda`
Same as policy 2, with scope MCP tool `optimize_agenda`. The tool scope covers one tool, so it needs its own policy.

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
4. **Start small:** a first release could be tool filter 1, business policies 1, 4, 5 and 6, and PII policy 1.
