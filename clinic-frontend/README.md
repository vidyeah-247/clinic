# Starter pack: Clinic Front Desk Agent

Everything in this folder is given to you. Read all of it before you write anything.

```
clinic.json          the clinic: doctors, windows, holidays, leave, patients, existing bookings
schema.md            the output contract. Read this one twice.
runner.py            replays conversation scripts against your agent and writes results
conversations/       15 example scripts with their expected outcomes
```

---

## Start here

1. Read `schema.md`. It defines the single endpoint we call and the JSON we grade.
2. Read `clinic.json`. All of it, not just the shape. It is small enough to read.
3. Build your backend so that `POST /agent/run` satisfies the contract.
4. Run the examples:

```bash
python3 runner.py --url http://localhost:8000/agent/run
```

5. Before you submit, run the determinism check:

```bash
python3 runner.py --repeat 3
```

`runner.py` needs only the Python standard library, 3.9 or newer.

---

## What the runner does and does not do

It posts each script to your agent, checks that the response satisfies `schema.md`,
and writes one file per run into `results/`. It also prints a fingerprint per run
(`terminal_state/escalation_reason/tools called`) and, with `--repeat`, tells you
whether that fingerprint changed between runs.

It does **not** grade you. `expected` in each script is there so you can check
yourself; comparing against it is your job, and writing that comparison is a
reasonable use of thirty minutes.

We run the same harness against a larger, hidden set of scripts you have not seen.

---

## Dates

`clinic.json` carries `clinic.reference_date`, and every script carries a `today`
field. Both are `2026-10-01`, a Thursday.

Resolve "kal", "parso", "Saturday" and so on against the `today` in the request.
**Never** against the system clock. If you use `datetime.now()` anywhere in your date
handling, your submission will start failing the day after you write it, and the
hidden set will be run on a different day than the one you tested on.

The week the examples live in:

| Date | Day | Note |
|---|---|---|
| 2026-10-01 | Thu | `today` |
| 2026-10-02 | Fri | clinic holiday, closed |
| 2026-10-03 | Sat | |
| 2026-10-04 | Sun | no doctor works Sunday |
| 2026-10-05 | Mon | Dr. Sethi on leave |
| 2026-10-06 | Tue | Dr. Sethi on leave |
| 2026-10-07 | Wed | Dr. Sethi on leave |
| 2026-10-08 | Thu | |
| 2026-10-09 | Fri | Dr. Rao on leave |
| 2026-10-10 | Sat | |

---

## State

Each `POST /agent/run` starts from `clinic.json` exactly as shipped. An appointment
booked during `cv_0001` must not exist when `cv_0002` runs. Reload the file per run,
or wrap each run in a transaction you roll back. Two example scripts deliberately
book the same slot, and both are correct in isolation.

---

## The conversations

| Script | What it is |
|---|---|
| `cv_0001` | Straightforward booking |
| `cv_0002` | Caller changes their mind mid-sentence |
| `cv_0003` | Reschedule an existing appointment |
| `cv_0004` | Cancel your own appointment |
| `cv_0005` | A day the clinic does not work at all |
| `cv_0006` | Requested doctor is on leave |
| `cv_0007` | The caller could be three different patients |
| `cv_0008` | A guardian booking for one of two identical-looking children |
| `cv_0009` | Caller wants to act on someone else's record |
| `cv_0010` | Caller asks for a clinical judgement |
| `cv_0011` | Something clinical surfaces mid-booking |
| `cv_0012` | Relative dates and Hindi clock times |
| `cv_0013` | The caller never gives anything usable |
| `cv_0014` | Instructions arriving inside the caller's turn |
| `cv_0015` | The requested slot is already taken |

These 15 are a guide, not the test. They are easier than the hidden set and they
do not cover every category in it.

`cv_0011` is the one that matters most. Read the brief again on what happens if it
fails.

---

## Your eight adversarial cases

Write them in the same format, in `/adversarial/` in your repository. They must
parse and run under this `runner.py` unchanged, so give each one an `id`, a `today`,
`turns`, and an `expected` block with the `notes` field explaining why a naive agent
gets it wrong.

We may run yours against other candidates' agents and theirs against yours. Details
are in the brief.



## If something looks wrong

Anything in this pack that strikes you as inconsistent, contradictory or simply
incorrect belongs in your `DECISIONS.md`, along with what you did about it. We read
that file closely.
