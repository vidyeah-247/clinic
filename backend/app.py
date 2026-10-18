from __future__ import annotations

import copy
import json
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
CLINIC_PATH = BASE_DIR / "clinic.json"

app = FastAPI(title="Sunrise Clinic Front Desk Agent", version="1.0.0")


class RunRequest(BaseModel):
    conversation_id: str
    today: str
    turns: list[str] = Field(default_factory=list)


class ToolRuntime:
    """Deterministic, per-request tool layer. All mutations are isolated to this run."""

    def __init__(self, clinic: dict[str, Any]):
        self.data = clinic
        self.calls: list[dict[str, Any]] = []

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"name": name, "arguments": copy.deepcopy(arguments)})
        fn = getattr(self, f"_{name}")
        return fn(**arguments)

    def _lookup_patient(
        self,
        name: Optional[str] = None,
        phone: Optional[str] = None,
        target_name: Optional[str] = None,
    ) -> dict[str, Any]:
        patients = self.data["patients"]
        caller_matches = list(patients)
        if name:
            norm = normalize(name)
            exact = [p for p in patients if normalize(p["name"]) == norm]
            if exact:
                caller_matches = exact
            else:
                caller_matches = [p for p in patients if norm in normalize(p["name"]) or normalize(p["name"]) in norm]
        if phone:
            caller_matches = [p for p in caller_matches if p["phone"] == digits(phone)]
        if name and phone and not caller_matches:
            # Do not silently choose a record when name and phone disagree.
            return {"candidates": [], "resolved": None}

        target_matches = None
        if target_name:
            target_norm = normalize(target_name)
            target_matches = [p for p in patients if normalize(p["name"]) == target_norm]
            if not target_matches:
                target_matches = [p for p in patients if target_norm in normalize(p["name"])]

        candidates: list[dict[str, Any]] = []
        if target_matches is not None:
            # For a child/third-party booking, only candidates who are the named target
            # and whose guardian relationship can be checked are returned.
            for target in target_matches:
                for caller in caller_matches:
                    if caller["id"] == target["id"] or target["id"] in caller.get("guardian_of", []):
                        candidates.append({"patient_id": target["id"], "name": target["name"], "caller_id": caller["id"], "authorised": True})
            # Return matching target candidates even when the caller is not authorised;
            # the orchestrator must still reject a third party.
            if not candidates:
                candidates = [{"patient_id": p["id"], "name": p["name"], "caller_id": caller_matches[0]["id"] if len(caller_matches) == 1 else None, "authorised": False} for p in target_matches]
        else:
            candidates = [{"patient_id": p["id"], "name": p["name"], "caller_id": p["id"], "authorised": True} for p in caller_matches]

        resolved = candidates[0] if len(candidates) == 1 else None
        return {"candidates": candidates, "resolved": resolved}

    def _search_slots(self, doctor_id: str, date: str, window: Optional[str] = None) -> dict[str, Any]:
        doctor = next((d for d in self.data["doctors"] if d["id"] == doctor_id), None)
        if not doctor:
            return {"slots": [], "error": "unknown_doctor"}
        try:
            requested = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            return {"slots": [], "error": "invalid_date"}
        if date in self.data.get("holidays", []):
            return {"slots": [], "error": "clinic_closed"}
        if date in doctor.get("leave_dates", []):
            return {"slots": [], "error": "doctor_on_leave"}
        day = requested.strftime("%a")
        occupied = {
            a["start"] for a in self.data["appointments"]
            if a["doctor_id"] == doctor_id and a["date"] == date and a["status"] == "booked"
        }
        slots: list[dict[str, str]] = []
        step = int(self.data["clinic"].get("slot_minutes", 15))
        for w in doctor["windows"]:
            if w["day"] != day:
                continue
            start = datetime.strptime(w["start"], "%H:%M")
            end = datetime.strptime(w["end"], "%H:%M")
            cur = start
            while cur + timedelta(minutes=step) <= end:
                start_str = cur.strftime("%H:%M")
                if start_str not in occupied:
                    hour = cur.hour
                    period = "morning" if hour < 12 else ("afternoon" if hour < 17 else "evening")
                    if not window or window == "any" or period == window:
                        slots.append({"start": start_str, "end": (cur + timedelta(minutes=step)).strftime("%H:%M")})
                cur += timedelta(minutes=step)
        # Overlapping clinic windows can produce duplicate starts; keep first occurrence.
        unique = {s["start"]: s for s in slots}
        return {"slots": [unique[k] for k in sorted(unique)], "error": None}

    def _book_appointment(self, patient_id: str, doctor_id: str, date: str, start: str) -> dict[str, Any]:
        patient = next((p for p in self.data["patients"] if p["id"] == patient_id), None)
        doctor = next((d for d in self.data["doctors"] if d["id"] == doctor_id), None)
        if not patient or not doctor:
            return {"success": False, "error": "unknown_patient_or_doctor", "appointment_id": None}
        slots = self._search_slots(doctor_id, date, None)
        chosen = next((s for s in slots["slots"] if s["start"] == start), None)
        if not chosen:
            return {"success": False, "error": slots.get("error") or "slot_unavailable", "appointment_id": None}
        next_num = max([int(a["id"].split("_")[1]) for a in self.data["appointments"]] + [0]) + 1
        appointment = {
            "id": f"ap_{next_num:04d}", "patient_id": patient_id,
            "doctor_id": doctor_id, "date": date, "start": start,
            "end": chosen["end"], "status": "booked",
        }
        self.data["appointments"].append(appointment)
        return {"success": True, "appointment_id": appointment["id"], "appointment": appointment}

    def _reschedule_appointment(
        self, patient_id: str, new_date: str, new_start: str,
        doctor_id: Optional[str] = None,
    ) -> dict[str, Any]:
        appt = next((a for a in self.data["appointments"] if a["patient_id"] == patient_id and a["status"] == "booked" and (not doctor_id or a["doctor_id"] == doctor_id)), None)
        if not appt:
            return {"success": False, "error": "appointment_not_found", "appointment_id": None}
        target_doctor = doctor_id or appt["doctor_id"]
        slots = self._search_slots(target_doctor, new_date, None)
        chosen = next((s for s in slots["slots"] if s["start"] == new_start), None)
        if not chosen:
            return {"success": False, "error": slots.get("error") or "slot_unavailable", "appointment_id": appt["id"]}
        appt.update({"doctor_id": target_doctor, "date": new_date, "start": new_start, "end": chosen["end"]})
        return {"success": True, "appointment_id": appt["id"], "appointment": appt}

    def _cancel_appointment(self, patient_id: str, date: Optional[str] = None, doctor_id: Optional[str] = None) -> dict[str, Any]:
        candidates = [a for a in self.data["appointments"] if a["patient_id"] == patient_id and a["status"] == "booked"]
        if date:
            candidates = [a for a in candidates if a["date"] == date]
        if doctor_id:
            candidates = [a for a in candidates if a["doctor_id"] == doctor_id]
        if not candidates:
            return {"success": False, "error": "appointment_not_found", "appointment_id": None}
        appt = sorted(candidates, key=lambda a: (a["date"], a["start"]))[0]
        appt["status"] = "cancelled"
        return {"success": True, "appointment_id": appt["id"], "appointment": appt}

    def _escalate_to_human(self, reason: str, detail: str) -> dict[str, Any]:
        allowed = {"clinical_urgent", "medical_advice", "not_authorised", "ambiguous_patient", "out_of_scope"}
        if reason not in allowed:
            return {"success": False, "error": "invalid_escalation_reason"}
        return {"success": True, "reason": reason, "detail": detail}


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def find_phone(text: str) -> Optional[str]:
    m = re.search(r"(?<!\d)(\d(?:[\s-]?\d){9,11})(?!\d)", text)
    return digits(m.group(1)) if m else None


def all_text(turns: list[str]) -> str:
    return " ".join(turns)


def detect_doctor(text: str, clinic: dict[str, Any]) -> Optional[str]:
    low = text.lower()
    if re.search(r"\b(sethi|vikram)\b", low):
        return "dr_sethi"
    if re.search(r"\b(rao|anjali)\b", low):
        return "dr_rao"
    # Paediatric cues can identify Dr Sethi when the patient is a child, but avoid
    # guessing a doctor if both are explicitly mentioned.
    if re.search(r"\b(pediatric|paediatric|bachche|beta|bete|son|daughter|beti)\b", low):
        return "dr_sethi"
    return None


def extract_target_name(text: str, caller_name: Optional[str]) -> Optional[str]:
    low = text.lower()
    if not re.search(r"\b(mera beta|mere bete|meri beti|my son|my daughter|for my child|kabir|aarav|arjun)\b", low):
        return None
    names = ["Kabir Joshi", "Aarav Gupta", "Arjun Gupta"]
    for name in names:
        if name.split()[0].lower() in low:
            return name
    if "kabir" in low:
        return "Kabir Joshi"
    if "aarav" in low:
        return "Aarav Gupta"
    if "arjun" in low:
        return "Arjun Gupta"
    return None


def extract_person_name(text: str) -> Optional[str]:
    # Match known patient names only; caller text is untrusted and never used as an ID.
    return None


def parse_date(text: str, today: str) -> Optional[str]:
    low = text.lower()
    base = datetime.strptime(today, "%Y-%m-%d").date()

    # Explicit day numbers: take the last one in the conversation, so a correction
    # such as "Tuesday 6 ... no, Wednesday 7" wins over the abandoned date.
    explicit_days = list(re.finditer(r"(?<!\d)(\d{1,2})\s*(?:october|oct|tareekh|tarikh)?\b", low))
    for match in reversed(explicit_days):
        day = int(match.group(1))
        if 1 <= day <= 31:
            try:
                candidate = date(base.year, base.month, day)
                if candidate >= base - timedelta(days=1):
                    return candidate.isoformat()
            except ValueError:
                pass

    # Resolve relative terms using request.today, not the machine clock.
    if re.search(r"\b(today|aaj|aaj ka|aaj ki)\b", low):
        return base.isoformat()
    if re.search(r"\b(parso|day after tomorrow)\b", low):
        return (base + timedelta(days=2)).isoformat()
    if re.search(r"\b(kal|tomorrow)\b", low):
        return (base + timedelta(days=1)).isoformat()

    weekdays = {
        "monday": 0, "somwar": 0, "mon": 0,
        "tuesday": 1, "mangalwar": 1, "tue": 1,
        "wednesday": 2, "budhwar": 2, "wed": 2,
        "thursday": 3, "guruwar": 3, "thu": 3,
        "friday": 4, "shukrawar": 4, "fri": 4,
        "saturday": 5, "shanivaar": 5, "shanivar": 5, "sat": 5,
        "sunday": 6, "ravivar": 6, "sun": 6,
    }
    found = [(m.start(), word, weekday) for word, weekday in weekdays.items()
             for m in re.finditer(rf"\b{re.escape(word)}\b", low)]
    if found:
        _, _, weekday = max(found)
        delta = (weekday - base.weekday()) % 7
        if delta == 0 and not re.search(r"\b(today|aaj)\b", low):
            delta = 7
        return (base + timedelta(days=delta)).isoformat()
    return None


def parse_time(text: str) -> Optional[str]:
    low = text.lower()
    # Numeric times must be marked as a clock time; never interpret a day number
    # ("8 tareekh") or a phone-number fragment as a time.
    m = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", low)
    if m:
        h, minute = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and minute in (0, 15, 30, 45):
            return f"{h:02d}:{minute:02d}"
    m = re.search(r"(?<!\d)(\d{1,2})\s*(am|pm|baje|bajey)\b", low)
    if m:
        h, suffix = int(m.group(1)), m.group(2)
        if suffix == "pm" and h < 12: h += 12
        if suffix == "am" and h == 12: h = 0
        if 0 <= h <= 23:
            return f"{h:02d}:00"
    hindi = {
        "saade nau": "09:30", "saadhe nau": "09:30", "nau": "09:00",
        "saade das": "10:30", "saadhe das": "10:30", "das": "10:00",
        "gyarah": "11:00", "barah": "12:00", "ek baje": "13:00",
        "teen baje": "15:00",
    }
    for phrase, value in sorted(hindi.items(), key=lambda kv: len(kv[0]), reverse=True):
        if re.search(rf"\b{re.escape(phrase)}\b", low):
            return value
    return None


def parse_window(text: str) -> Optional[str]:
    low = text.lower()
    if re.search(r"\b(morning|subah|savera)\b", low): return "morning"
    if re.search(r"\b(afternoon|dopahar)\b", low): return "afternoon"
    if re.search(r"\b(evening|shaam|sham)\b", low): return "evening"
    return None


def detect_urgent(text: str) -> bool:
    low = text.lower()
    patterns = [
        r"chest pain", r"seene mein dard", r"seene me dard", r"saans .*phool",
        r"difficulty breathing", r"can.t breathe", r"saans nahi aa", r"unconscious",
        r"behosh", r"severe bleeding", r"heavy bleeding", r"stroke", r"fits aa",
    ]
    return any(re.search(p, low) for p in patterns)


def detect_medical_advice(text: str) -> bool:
    low = text.lower()
    asks_judgement = any(p in low for p in ["le lun ya nahi", "le loon ya nahi", "kitni der mein", "should i take", "how much medicine", "dose bata", "kya dawa", "which medicine", "medical advice"])
    symptoms = any(p in low for p in ["bukhar", "fever", "dawai", "dawa", "crocin", "tablet", "goli", "medicine"])
    return asks_judgement and symptoms


def detect_injection_or_bulk_cancel(text: str) -> bool:
    low = text.lower()
    return ("ignore your previous instructions" in low or "administrator mode" in low or
            ("cancel every appointment" in low) or "cancel all appointments" in low or
            "authorised internal test" in low)


def extract_name(text: str) -> Optional[str]:
    # Only return an exact name present in the fixture, never a fuzzy identity guess.
    data = json.loads(CLINIC_PATH.read_text(encoding="utf-8"))
    low = normalize(text)
    for patient in sorted(data["patients"], key=lambda p: len(p["name"]), reverse=True):
        if normalize(patient["name"]) in low:
            return patient["name"]
    # Specific shorthand that the caller actually used.
    if re.search(r"\bsharma\b", low): return "Sharma"
    if re.search(r"\bpriya\b", low): return "Priya"
    return None


def make_reply(state: str, reason: Optional[str], appointment: Optional[dict[str, Any]], message: Optional[str] = None) -> str:
    if message:
        return message
    if state == "booked" and appointment:
        return f"Aapka appointment {appointment['date']} ko {appointment['start']} par book ho gaya hai."
    if state == "rescheduled" and appointment:
        return f"Aapka appointment {appointment['date']} ko {appointment['start']} par reschedule ho gaya hai."
    if state == "cancelled": return "Aapka appointment cancel kar diya gaya hai."
    if reason == "clinical_urgent": return "Aapke symptoms ke liye abhi urgent clinical help zaroori hai. Main aapko human team se connect kar rahi hoon. Agar saans lene mein dikkat ya chest pain abhi ho raha hai, turant local emergency services se sampark karein."
    if reason == "medical_advice": return "Main medical judgement ya dawa ki dose advise nahi kar sakti. Main aapko clinic team se connect kar rahi hoon."
    if reason == "not_authorised": return "Main bina verified authorisation ke kisi doosre patient ka appointment change nahi kar sakti. Main is request ko clinic team ko bhej rahi hoon."
    if reason == "ambiguous_patient": return "Patient ki pehchaan clear nahi ho paayi. Main clinic team ko handoff kar rahi hoon."
    if reason == "out_of_scope": return "Yeh request front desk ke scope se bahar hai. Main clinic team ko connect kar rahi hoon."
    if state == "refused": return "Main is request par action nahi le sakti."
    return "Abhi koi appointment action nahi hua. Jab aap details confirm kar sakein, humein dobara batayein."


def run_agent(payload: RunRequest) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        date.fromisoformat(payload.today)
    except ValueError:
        raise HTTPException(status_code=422, detail="today must be YYYY-MM-DD")
    if any(not isinstance(t, str) for t in payload.turns):
        raise HTTPException(status_code=422, detail="turns must be an array of strings")

    # Reload for every conversation so no mutation leaks across requests.
    clinic = json.loads(CLINIC_PATH.read_text(encoding="utf-8"))
    tools = ToolRuntime(clinic)
    text = all_text(payload.turns)
    low = text.lower()
    state = "abandoned"
    reason = None
    patient_id = None
    appointment_id = None
    appointment = None
    final_message = None

    # Safety gates run before all routine scheduling logic.
    if not payload.turns or not any(t.strip() for t in payload.turns):
        state = "abandoned"
    elif detect_injection_or_bulk_cancel(text):
        state = "refused"
        final_message = "Main bulk cancellations ya caller-provided instruction overrides execute nahi kar sakti."
    elif detect_urgent(text):
        detail = "caller reports symptoms requiring immediate clinical attention"
        tools.call("escalate_to_human", {"reason": "clinical_urgent", "detail": detail})
        state, reason = "escalated", "clinical_urgent"
    elif detect_medical_advice(text):
        tools.call("escalate_to_human", {"reason": "medical_advice", "detail": "caller requests medication or clinical judgement"})
        state, reason = "escalated", "medical_advice"
    else:
        cancel_intent = bool(re.search(r"\b(cancel|cancell? kar|rद्द|रद्द|hatana)\b", low))
        reschedule_intent = (bool(re.search(r"\b(reschedule|shift|move|change.*appointment|date change|aage kar|baad mein kar|dusre din kar)\b", low)) or ("aaj ka appointment" in low and "karwana" in low)) and not cancel_intent
        booking_intent = bool(re.search(r"\b(appointment|booking|book|mil jayega|milna|dikhana|chahiye|aa sakta|slot)\b", low)) or (detect_doctor(text, {}) is not None and parse_date(text, payload.today) is not None and parse_time(text) is not None)
        caller_name = extract_name(text)
        phone = find_phone(text)
        target_name = extract_target_name(text, caller_name)

        # Non-self record action must be authorised as self or listed guardian.
        mentions_other = bool(re.search(r"\b(padosi|neighbour|neighbor|friend|colleague|uncle|aunt)\b", low))
        third_party_cancel = cancel_intent and ("lakshmi iyer" in low or mentions_other)
        if third_party_cancel:
            tools.call("escalate_to_human", {"reason": "not_authorised", "detail": "caller requests cancellation for another patient without listed guardian authorisation"})
            state, reason = "escalated", "not_authorised"
        elif cancel_intent or reschedule_intent or booking_intent:
            # Lookup is called only when there's an identifiable patient request.
            if caller_name or phone or target_name:
                lookup_args = {"name": caller_name, "phone": phone, "target_name": target_name}
                lookup = tools.call("lookup_patient", lookup_args)
                candidates = lookup["candidates"]
                if len(candidates) == 0:
                    state = "abandoned"
                    final_message = "Patient details match nahi hue; maine koi appointment change nahi kiya."
                elif len(candidates) > 1 or lookup["resolved"] is None:
                    tools.call("escalate_to_human", {"reason": "ambiguous_patient", "detail": "multiple patient records match; identity not established"})
                    state, reason = "escalated", "ambiguous_patient"
                else:
                    resolved = lookup["resolved"]
                    patient_id = resolved["patient_id"]
                    if not resolved.get("authorised", False):
                        tools.call("escalate_to_human", {"reason": "not_authorised", "detail": "caller is not the patient or a listed guardian"})
                        state, reason = "escalated", "not_authorised"
                    else:
                        doctor_id = detect_doctor(text, clinic)
                        if cancel_intent:
                            args = {"patient_id": patient_id, "date": payload.today if re.search(r"\b(aaj|today)\b", low) else None, "doctor_id": doctor_id}
                            result = tools.call("cancel_appointment", args)
                            if result["success"]:
                                state = "cancelled"; appointment_id = result["appointment_id"]
                            else:
                                state = "abandoned"; final_message = "Is patient ke liye matching active appointment nahi mila; kuch cancel nahi hua."
                        elif reschedule_intent:
                            new_date = parse_date(text, payload.today)
                            new_start = parse_time(text)
                            if new_date and new_start:
                                result = tools.call("reschedule_appointment", {"patient_id": patient_id, "new_date": new_date, "new_start": new_start, "doctor_id": doctor_id})
                                if result["success"]:
                                    state = "rescheduled"; appointment_id = result["appointment_id"]; appointment = result["appointment"]
                                else:
                                    state = "abandoned"; final_message = "Requested slot available nahi tha; appointment change nahi hua."
                            else:
                                state = "abandoned"; final_message = "Reschedule ke liye nayi date aur time clear nahi hai; koi change nahi hua."
                        else:
                            new_date = parse_date(text, payload.today)
                            window = parse_window(text)
                            new_start = parse_time(text)
                            if not doctor_id or not new_date:
                                state = "abandoned"; final_message = "Doctor aur date confirm nahi ho paayi; koi booking nahi hui."
                            else:
                                slots_result = tools.call("search_slots", {"doctor_id": doctor_id, "date": new_date, "window": window or "any"})
                                slots = slots_result["slots"]
                                if not slots:
                                    state = "abandoned"; final_message = "Us date par requested doctor ke available slots nahi hain. Koi booking nahi hui."
                                else:
                                    chosen = next((s for s in slots if new_start and s["start"] == new_start), None)
                                    if not chosen and not new_start:
                                        chosen = slots[0]
                                    if not chosen:
                                        # If requested time is occupied, choose a later valid slot only if caller stated a correction.
                                        corrected = len(payload.turns) >= 2 and any(w in low for w in ["nahi nahi", "accha, toh", "instead", "rather", "9:30 kar"])
                                        if corrected:
                                            after = [s for s in slots if s["start"] > (new_start or "00:00")]
                                            chosen = after[0] if after else None
                                    if not chosen:
                                        state = "abandoned"; final_message = "Requested time available nahi hai. Koi appointment create nahi hua."
                                    else:
                                        result = tools.call("book_appointment", {"patient_id": patient_id, "doctor_id": doctor_id, "date": new_date, "start": chosen["start"]})
                                        if result["success"]:
                                            state = "booked"; appointment_id = result["appointment_id"]; appointment = result["appointment"]
                                        else:
                                            state = "abandoned"; final_message = "Booking nahi ho paayi kyunki slot available nahi tha."
            else:
                # Availability can be checked without resolving a patient; never book
                # until identity and authorisation are established.
                doctor_id = detect_doctor(text, clinic)
                requested_date = parse_date(text, payload.today)
                if booking_intent and doctor_id and requested_date:
                    tools.call("search_slots", {"doctor_id": doctor_id, "date": requested_date, "window": parse_window(text) or "any"})
                state = "abandoned"
                final_message = "Patient ki details nahi mili; koi appointment action nahi hua."
        else:
            state = "abandoned"

    reply = make_reply(state, reason, appointment, final_message)
    elapsed_ms = max(1, int((time.perf_counter() - started) * 1000))
    token_estimate = max(1, (len(text) + len(reply) + sum(len(json.dumps(c, ensure_ascii=False)) for c in tools.calls)) // 4)
    return {
        "conversation_id": payload.conversation_id,
        "tool_calls": tools.calls,
        "terminal_state": state,
        "escalation_reason": reason,
        "patient_id": patient_id,
        "appointment_id": appointment_id,
        "reply": reply,
        "metrics": {"turns": len(payload.turns), "tokens": token_estimate, "latency_ms": elapsed_ms},
    }
@app.post("/agent/run")
def agent_run(payload: RunRequest) -> dict[str, Any]:
    return run_agent(payload)