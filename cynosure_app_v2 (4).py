import json, re
from datetime import datetime, timedelta
from pathlib import Path
import streamlit as st
import pandas as pd
import streamlit.components.v1 as components

APP_TITLE = "Cynosure 2025 — Secure Event Portal (v3)"

# ---------- Helpers ----------
def live_autorefresh(enabled: bool, interval_ms: int = 5000, key: str = 'auto_refresh'):
    """Reloads the page every interval_ms while enabled. No external deps."""
    if enabled:
        components.html(
            f"""<script>setTimeout(function(){{window.parent.location.reload();}}, {interval_ms});</script>""",
            height=0,
        )

def get_query_params():
    try:
        # Newer Streamlit (dict-like)
        return dict(st.query_params)
    except Exception:
        try:
            return st.experimental_get_query_params()
        except Exception:
            return {}

def norm(s: str) -> str:
    if not s: return ""
    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s

def ekey(name: str) -> str: return norm(name)
def nkey(name: str) -> str: return norm(name)

# ---------- Data ----------
DATA_PATH = Path(__file__).with_name("cynosure_events.json")
if not DATA_PATH.exists():
    st.error("Missing cynosure_events.json next to the app file."); st.stop()
EVENTS = json.loads(DATA_PATH.read_text(encoding="utf-8")).get("events", [])
EVENTS_BY_KEY = {ekey(ev.get("name","")): ev for ev in EVENTS}

STORE_PATH = Path(__file__).with_name("participants_store.json")
DEFAULT_STORE = {
    "participants": [], "messages": [], "completions": [], "sessions": [], "updated_at": "",
    "categories": {}, "drafts": {}  # drafts[event_key][category] = last form values
}

def load_store():
    if not STORE_PATH.exists():
        STORE_PATH.write_text(json.dumps(DEFAULT_STORE, ensure_ascii=False), encoding="utf-8")
    try:
        store = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        store = dict(DEFAULT_STORE)
    changed = False
    store.setdefault("categories", {})
    store.setdefault("drafts", {})
    for p in store.get("participants", []):
        p.setdefault("name",""); p.setdefault("phone",""); p.setdefault("email","")
        p.setdefault("grade",""); p.setdefault("division",""); p.setdefault("subcat","")
        if "name_key" not in p: p["name_key"] = nkey(p.get("name","")); changed = True
        if "event_key" not in p: p["event_key"] = ekey(p.get("event","")); changed = True
    for m in store.get("messages", []):
        m.setdefault("to_key", nkey(m.get("to",""))); m.setdefault("from_key", nkey(m.get("from",""))); m.setdefault("event_key", ekey(m.get("event","")))
        m.setdefault("kind","chat"); m.setdefault("meta",{})
    if changed: save_store(store)
    return store

def save_store(store):
    store["updated_at"] = datetime.now().isoformat()
    STORE_PATH.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")

def upsert_session(name: str, role: str, phone: str = ""):
    s = load_store()
    now = datetime.now().isoformat()
    nk = nkey(name)
    for row in s.get("sessions", []):
        if row.get("name_key")==nk:
            row["name"] = name; row["role"] = role; row["last_seen"] = now; row["phone"] = phone.strip()
            save_store(s); return
    s.setdefault("sessions", []).append({"name": name, "name_key": nk, "role": role, "last_seen": now, "phone": phone.strip()})
    save_store(s)

# Optional seed
def maybe_seed():
    s = load_store()
    if not s["participants"] and EVENTS:
        demo = {"event": EVENTS[0].get("name","(Unnamed)"), "event_key": ekey(EVENTS[0].get("name","")), "name": "Demo User",
                "name_key": nkey("Demo User"), "phone":"", "email":"", "grade":"", "division":"", "subcat":""}
        s["participants"].append(demo); save_store(s)
maybe_seed()

# ---------- Time helpers ----------
def parse_datetime_fields(ev: dict):
    text_date = ev.get("date") or ev.get("date_info_duty","")
    text_time = ev.get("time","")
    up_date = (text_date or "").upper()

    start_day = end_day = None
    if "FRIDAY" in up_date or "26" in up_date: start_day = "2025-09-26"
    if "SATURDAY" in up_date or "27" in up_date:
        if start_day: end_day = "2025-09-27"
        else: start_day = "2025-09-27"
    if "BOTH" in up_date:
        start_day, end_day = "2025-09-26", "2025-09-27"

    tpat = re.compile(r'(\d{1,2}:\d{2}\s*(?:A\.M\.|P\.M\.|AM|PM|Noon|NOON)|\d{1,2}\s*(?:A\.M\.|P\.M\.|AM|PM))')
    matches = [m.group(1) for m in tpat.finditer(text_time or "")]
    def tparse(s):
        s = s.replace("A.M.","AM").replace("P.M.","PM").replace("NOON","12:00 PM").replace("Noon","12:00 PM")
        s = re.sub(r'(?<=\d)\s*(AM|PM)$', r' \1', s)
        for fmt in ("%I:%M %p", "%I %p"):
            try:
                return datetime.strptime(s.strip(), fmt).time()
            except:
                pass
        return None
    stime = tparse(matches[0]) if len(matches)>=1 else None
    etime = tparse(matches[1]) if len(matches)>=2 else None

    sdt = edt = None
    if start_day and stime:
        sdt = datetime.strptime(start_day, "%Y-%m-%d").replace(hour=stime.hour, minute=stime.minute)
    elif start_day:
        sdt = datetime.strptime(start_day, "%Y-%m-%d").replace(hour=9, minute=0)

    if end_day and etime:
        edt = datetime.strptime(end_day, "%Y-%m-%d").replace(hour=etime.hour, minute=etime.minute)
    elif sdt and etime:
        edt = sdt.replace(hour=etime.hour, minute=etime.minute)
    elif sdt and not etime:
        edt = sdt + timedelta(hours=2)

    return sdt, edt

def status_badge(sdt, edt):
    now = datetime.now()
    if not sdt: 
        return "⏱️ Time TBD"
    if now < sdt:
        delta = sdt - now
        days = delta.days
        hours = int(delta.seconds // 3600)
        mins = int((delta.seconds % 3600) // 60)
        if days > 0:
            return f"🕒 Starts in {days}d {hours}h {mins}m"
        return f"🕒 Starts in {hours}h {mins}m"
    if edt and now > edt:
        return "✅ Completed"
    return "🔴 On-going"

# ---------- Messaging & store helpers ----------
def send_message(to_name, from_name, ev_name, text, to_role, kind="chat", meta=None):
    if not text.strip() and kind=="chat": return
    s = load_store()
    s["messages"].append({
        "to": to_name, "to_key": nkey(to_name),
        "from": from_name, "from_key": nkey(from_name),
        "event": ev_name, "event_key": ekey(ev_name),
        "to_role": to_role,
        "text": text.strip(),
        "timestamp": datetime.now().isoformat(),
        "kind": kind,
        "meta": meta or {}
    })
    save_store(s)

def event_participants(ev_name, subcat=None):
    s = load_store()
    evk = ekey(ev_name)
    rows = [p for p in s["participants"] if p.get("event_key")==evk]
    if subcat and subcat!="All":
        rows = [p for p in rows if (p.get("subcat") or "")==subcat]
    rows.sort(key=lambda p: (p.get("subcat") or "", p.get("name","").lower()))
    return rows

def upsert_participant(ev_name, name, phone, email, grade, division, subcat):
    s = load_store()
    evk, nk = ekey(ev_name), nkey(name)
    sc = subcat or ""
    for p in s["participants"]:
        if p["event_key"]==evk and p["name_key"]==nk and (p.get("subcat") or "")==sc:
            p.update({"name":name.strip(),"phone":phone.strip(),"email":email.strip(),"grade":grade.strip(),"division":division.strip(),"subcat":sc})
            save_store(s); return
    s["participants"].append({"event": ev_name, "event_key": evk, "name": name.strip(), "name_key": nk,
                              "phone": phone.strip(), "email": email.strip(), "grade": grade.strip(),
                              "division": division.strip(), "subcat": sc})
    save_store(s)

def remove_participant(ev_name, name, subcat_display):
    s = load_store()
    evk, nk = ekey(ev_name), nkey(name)
    sc = subcat_display or ""
    s["participants"] = [p for p in s["participants"] if not (p["event_key"]==evk and p["name_key"]==nk and (p.get("subcat") or "")==sc)]
    save_store(s)

def get_thread(ev_key, participant_nkey):
    msgs = load_store()["messages"]
    th = [m for m in msgs if m.get("event_key")==ev_key and (m.get("to_key")==participant_nkey or m.get("from_key")==participant_nkey)]
    th.sort(key=lambda x: x["timestamp"])
    return th

# ---------- Category extraction from brochure ----------
def extract_age_categories(text: str):
    if not text: return []
    cats = []
    m = re.search(r'Age\s*Category\s*:\s*(.+)', text, flags=re.IGNORECASE)
    if m:
        seg = m.group(1)
        for part in re.split(r'(?=(?:I{1,3}|IV|V)\s*[.:])', seg):
            part = part.strip(" .:\n\t")
            if not part: continue
            m2 = re.match(r'((?:I{1,3}|IV|V))\s*[.:]\s*(.+)', part)
            if m2:
                rn, rng = m2.group(1), m2.group(2).strip()
                cats.append(f"Category {rn} : {rng}")
    for line in text.splitlines():
        m3 = re.match(r'\s*Category\s*((?:I{1,3}|IV|V))\s*[:\-]\s*(.+)', line, flags=re.IGNORECASE)
        if m3:
            rn = m3.group(1).upper()
            rng = m3.group(2).strip()
            val = f"Category {rn} : {rng}"
            if val not in cats:
                cats.append(val)
    out = []
    for c in cats:
        if c not in out: out.append(c)
    return out

def extract_gender_categories(text: str):
    if not text: return []
    t = text.lower()
    if ("girls team" in t and "boys team" in t) or ("one girls team" in t and "one boys team" in t):
        return ["Girls", "Boys"]
    if re.search(r'\bgirls?\s+team\b', t) and re.search(r'\bboys?\s+team\b', t):
        return ["Girls", "Boys"]
    return []

def brochure_subcategories(ev: dict):
    block = ev.get("brochure_block","")
    age_cats = extract_age_categories(block)
    gender_cats = extract_gender_categories(block)
    if gender_cats:
        return gender_cats
    if age_cats:
        return age_cats
    single2 = re.search(r"\b([0-9]{1,2}(?:th|st|nd|rd)\s*to\s*[0-9]{1,2}(?:th|st|nd|rd))\b", block, flags=re.I)
    if single2:
        return [f"Category : {single2.group(1)}"]
    return []

def admin_defined_subcategories(ev_key: str):
    s = load_store()
    return s.get("categories", {}).get(ev_key, [])

def set_admin_subcategories(ev_key: str, items: list):
    s = load_store()
    s.setdefault("categories", {})
    s["categories"][ev_key] = [i for i in items if str(i).strip()]
    save_store(s)

def load_draft(ev_key: str, subcat: str):
    s = load_store()
    evmap = s["drafts"].get(ev_key, {})
    return evmap.get(subcat or "", {"name":"","phone":"","email":"","grade":"","division":""})

def save_draft(ev_key: str, subcat: str, name, phone, email, grade, division):
    s = load_store()
    s.setdefault("drafts", {})
    s["drafts"].setdefault(ev_key, {})
    s["drafts"][ev_key][subcat or ""] = {"name":name,"phone":phone,"email":email,"grade":grade,"division":division}
    save_store(s)

# ---------- UI ----------
st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(APP_TITLE)
st.info(f"🕒 Now: {datetime.now().strftime('%a %d %b %Y, %I:%M %p')}")
st.caption("Participants must already be added by Admin. Case-insensitive login. Admins need password + name.")

# Login gate
mode = st.radio("Login as", ["Participant", "Admin"], horizontal=True, key="login_mode")
authorized = False
is_admin = False
current_user = None
admin_name = None
admin_phone = ""

if mode == "Admin":
    pwd = st.text_input("Admin password", type="password", key="admin_pwd")
    if pwd == "vxxxk":
        admin_name = st.text_input("Admin full name", key="admin_name").strip()
        admin_phone = st.text_input("Admin contact phone (for tel: link)", key="admin_phone").strip()
        if admin_name:
            is_admin = True; authorized = True
            upsert_session(admin_name, "admin", admin_phone)
            st.success(f"Hello {admin_name}! Admin mode enabled.")
    elif pwd:
        st.error("Incorrect password.")
else:
    cand = st.text_input("Participant full name (must already be saved)", key="participant_name").strip()
    phone = st.text_input("Your contact phone (optional, for call link)", key="participant_phone").strip()
    if cand:
        nk = nkey(cand)
        exists = any(p for p in load_store()["participants"] if p.get("name_key")==nk)
        if exists:
            authorized = True; current_user = cand
            upsert_session(cand, "participant", phone)
            my_ev_keys = [p["event_key"] for p in load_store()["participants"] if p["name_key"]==nk]
            soon = None
            for ek in my_ev_keys:
                ev = EVENTS_BY_KEY.get(ek); 
                if not ev: continue
                sd, ed = parse_datetime_fields(ev)
                if sd and (soon is None or sd < soon[0]): soon = (sd, ed, ev)
            if soon:
                sd, ed, ev = soon
                now = datetime.now()
                if ed and now > ed:
                    st.success(f"Hello {cand}, your event **{ev.get('name','(Unnamed)')}** is completed.")
                elif sd and now < sd:
                    d = sd - now
                    st.success(f"Hello {cand}, your event **{ev.get('name','(Unnamed)')}** starts in {d.days}d {int(d.seconds//3600)}h {int((d.seconds%3600)//60)}m.")
                else:
                    st.success(f"Hello {cand}, your event **{ev.get('name','(Unnamed)')}** is on-going.")
        else:
            st.error("Name not found. Ask Admin to add you to an event first.")

if not authorized:
    st.stop()

# --- Live refresh control ---
with st.sidebar:
    st.header("🔁 Live")
    live = st.toggle("Live auto-refresh (Messages)", value=False, help="Refresh every 5s while this is on.")
    if live:
        live_autorefresh(True, 5000, 'live_autorefresh_sidebar')
        st.write("Auto-refresh is active.")
    st.experimental_set_query_params(**get_query_params())

if "live_ticks" not in st.session_state: st.session_state["live_ticks"] = 0
gp = get_query_params()
if gp.get("live") in (["1"], "1") or st.sidebar.checkbox("Tick (dev)", value=False, key="devtick"):
    st.session_state["live_ticks"] += 1

# ---------- Card renderer ----------
def render_event_card(ev: dict, scope: str, is_admin=False, participant_name: str=None, admin_name: str=None, admin_phone: str=""):
    K = lambda suffix: f"{scope}_{ekey(ev.get('name',''))}_{suffix}"

    sdt, edt = parse_datetime_fields(ev)
    st.markdown(f"### {ev.get('name','(Unnamed)')}")
    c1, c2, c3 = st.columns([1,1,1])
    with c1:
        st.write(f"**Category:** {ev.get('category','')}")
        st.write(f"**Age:** {ev.get('age_category','')}")
    with c2:
        if ev.get("date") or ev.get("date_info_duty"):
            st.write(f"**Date:** {ev.get('date') or ev.get('date_info_duty','')}")
        if ev.get("time"):
            st.write(f"**Time:** {ev.get('time')}")
        if ev.get("venue"):
            st.write(f"**Venue:** {ev.get('venue')}")
    with c3:
        st.write(f"**Teacher:** {ev.get('teacher_in_charge','')}")
        st.write(status_badge(sdt, edt))

    with st.expander("Brochure (word-for-word)"):
        block = ev.get("brochure_block","(Not found in brochure)")
        st.code(block)
        def _ics():
            def fmt(dt): return dt.strftime("%Y%m%dT%H%M%S")
            uid = f"{ekey(ev.get('name',''))}@cynosure"
            body = "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Cynosure//EN\nBEGIN:VEVENT\nUID:"+uid+"\nSUMMARY:"+ev.get('name','(Unnamed)')+"\n"
            if sdt: body += "DTSTART:"+fmt(sdt)+"\n"
            if edt: body += "DTEND:"+fmt(edt)+"\n"
            if ev.get("venue"): body += "LOCATION:"+ev.get('venue','')+"\n"
            body += "DESCRIPTION:"+block.replace("\\n", " \\n ")[:1800]+"\nEND:VEVENT\nEND:VCALENDAR"
            return body.encode("utf-8")
        st.download_button("➕ Add to Calendar (.ics)", _ics(), file_name=f"{ev.get('name','(Unnamed)')}.ics", mime="text/calendar", key=K("ics"))

    st.divider()

    # --- Categories: merge brochure-derived + admin-defined ---
    brochure_cats = brochure_subcategories(ev)
    admin_cats = admin_defined_subcategories(ekey(ev.get("name","")))
    merged = []
    for c in brochure_cats + admin_cats:
        if c not in merged: merged.append(c)

    st.subheader("Participants")
    if not merged:
        st.info("No age/gender categories detected. Admins may add custom categories below.")

    # Admin category editor
    if is_admin:
        with st.expander("🛠️ Category Manager (Admin)", expanded=False):
            st.caption("These are **extra** categories that admins can add or remove per event. Brochure categories stay intact.")
            current = admin_defined_subcategories(ekey(ev.get("name",""))) or []
            edit_df = pd.DataFrame({"Category": current if current else [""]})
            data = st.data_editor(edit_df, num_rows="dynamic", key=K("cat_editor"))
            if st.button("Save Categories", key=K("cat_save")):
                vals = [str(x).strip() for x in data["Category"].tolist() if str(x).strip()]
                set_admin_subcategories(ekey(ev.get("name","")), vals)
                st.success("Saved admin categories.")

    colf, colm = st.columns([1,1])
    with colf:
        sub_filter = st.selectbox("Filter by category", (["All"] + merged) if merged else ["All"], key=K("flt_cat"))
    with colm:
        st.caption("Categories = Brochure ⊕ Admin-defined.")

    plist = event_participants(ev.get("name",""), sub_filter if merged else None)

    # Admin participant editor (with persistent per-category drafts)
    if is_admin:
        st.markdown("**Add/Update a participant**")
        current_cat = sub_filter if (sub_filter and sub_filter!="All") else (merged[0] if merged else "")
        draft = load_draft(ekey(ev.get("name","")), current_cat)

        with st.form(K("form_one")):
            pname = st.text_input("Full name", value=draft.get("name",""), key=K(f"one_name_{current_cat}"))
            phone = st.text_input("Phone", value=draft.get("phone",""), key=K(f"one_phone_{current_cat}"))
            email = st.text_input("Email ID", value=draft.get("email",""), key=K(f"one_email_{current_cat}"))
            grade = st.text_input("STD (e.g., 11, 8, etc.)", value=draft.get("grade",""), key=K(f"one_grade_{current_cat}"))
            division = st.text_input("DIV (e.g., A, D, etc.)", value=draft.get("division",""), key=K(f"one_div_{current_cat}"))
            sc = ""
            if merged:
                sc = st.selectbox("Category", merged, index=(merged.index(current_cat) if current_cat in merged else 0), key=K(f"one_cat_{current_cat}"))
            saved = st.form_submit_button("Save")
        # Saving a participant also updates the draft so fields persist when you come back later
        if saved:
            if pname and pname.strip():
                upsert_participant(ev.get("name",""), pname, phone, email, grade, division, sc)
                save_draft(ekey(ev.get("name","")), sc, pname, phone, email, grade, division)
                st.success("Saved.")
            else:
                # Save draft even if name is empty, so when switching you still remember inputs
                save_draft(ekey(ev.get("name","")), sc, pname, phone, email, grade, division)
                st.info("Draft saved. Enter a name to save as participant.")

        if plist:
            st.write("**Inline edit participants**")
            df = pd.DataFrame(plist)
            view_cols = ["name","phone","email","grade","division","subcat"]
            df = df[view_cols]
            edited = st.data_editor(df, num_rows="dynamic", key=K("edit_participants"))
            if st.button("Apply edits", key=K("apply_edits")):
                for _, row in edited.iterrows():
                    upsert_participant(ev.get("name",""), row["name"], str(row.get("phone","")), str(row.get("email","")),
                                       str(row.get("grade","")), str(row.get("division","")), str(row.get("subcat","")))
                st.success("Applied edits.")
            st.download_button("⬇️ Export participants (CSV)", edited.to_csv(index=False).encode("utf-8"), file_name=f"{ekey(ev.get('name',''))}_participants.csv", mime="text/csv")

        if plist:
            rm = st.selectbox("Remove participant (current category view)", ["--"]+[p["name"] for p in plist], key=K("rm"))
            if rm != "--":
                remove_participant(ev.get("name",""), rm, sub_filter if (merged and sub_filter!="All") else "")
                st.warning(f"Removed {rm}")

    else:
        st.info("Only admins can edit participants.")

    # Roster & messaging per participant
    for idx, p in enumerate(plist, start=1):
        c1, c2, c3, c4 = st.columns([2,2,1,3])
        with c1:
            st.write(f"{idx}. **{p['name']}** — _{p.get('subcat') or '(no category)'}_")
            st.caption(f"STD: {p.get('grade','')}  •  DIV: {p.get('division','')}")
        with c2:
            st.write(p.get("phone","")); st.caption(p.get("email",""))
        with c3:
            if is_admin:
                if st.button("Message", key=K(f"msgbtn_{idx}")):
                    st.session_state[K(f"open_thread_{idx}")] = True
            if is_admin and p.get("phone"):
                st.markdown(f"[📞 Call participant]({'tel:' + p['phone']})")
        with c4:
            thread = get_thread(ekey(ev.get("name","")), p["name_key"])
            if thread:
                last = thread[-1]
                kind = last.get("kind","chat")
                msg_icon = "📞" if kind=="call_request" else "💬"
                st.caption(f"Last {msg_icon} {last['from']}: {last['text'][:60]}{'...' if len(last['text'])>60 else ''}")

        open_key = st.session_state.get(K(f"open_thread_{idx}"), False)
        is_self = participant_name and nkey(participant_name)==p["name_key"]
        if open_key or is_self:
            with st.expander(f"Thread with {p['name']} — {ev.get('name','(Unnamed)')}", expanded=True if is_self else False):
                thread = get_thread(ekey(ev.get("name","")), p["name_key"])
                if not thread:
                    st.caption("No messages yet.")
                else:
                    for m in thread:
                        dir_txt = (f"{m['from']} → You" if m["to_key"]==p["name_key"] else f"{m['from']} → Admins")
                        icon = "📞" if m.get("kind")=="call_request" else "💬"
                        st.markdown(f"{icon} **{m['timestamp']}** — {dir_txt}")
                        if m.get("kind")=="call_request":
                            want = m.get("meta",{}).get("direction","both")
                            st.write(f"Call request: {want}")
                        st.write(m["text"])

                if is_self:
                    msg = st.text_area("Your message to Admins", key=K(f"pmsg_{idx}"))
                    colA, colB = st.columns(2)
                    with colA:
                        if st.button("Send", key=K(f"psend_{idx}")) and msg.strip():
                            send_message("Admins", participant_name, ev.get("name",""), msg.strip(), to_role="admin")
                            st.success("Sent.")
                    with colB:
                        want = st.selectbox("Request a call (direction)", ["Admin → Me","Me → Admin","Both"], key=K(f"call_dir_{idx}"))
                        if st.button("Request Call", key=K(f"pcall_{idx}")):
                            send_message("Admins", participant_name, ev.get("name",""), f"Call requested ({want}).", to_role="admin", kind="call_request", meta={"direction": want})
                            st.success("Call request sent.")

                if is_admin and admin_name:
                    reply = st.text_area("Admin message", key=K(f"amsg_{idx}"))
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("Send to participant", key=K(f"asend_{idx}")) and reply.strip():
                            send_message(p["name"], admin_name, ev.get("name",""), reply.strip(), to_role="participant")
                            st.success("Sent.")
                            st.session_state[K(f"open_thread_{idx}")] = False
                    with col2:
                        if st.button("Mark call fulfilled", key=K(f"acall_{idx}")):
                            send_message(p["name"], admin_name, ev.get("name",""), "Admin completed the call request.", to_role="participant", kind="system")

    # Participant controls
    if participant_name:
        my_rows = [p for p in event_participants(ev.get("name","")) if p["name_key"]==nkey(participant_name)]
        if my_rows:
            st.subheader("Your Event Control")
            now = datetime.now()
            if sdt and now >= sdt and (not edt or now <= edt + timedelta(hours=1)):
                atv = st.checkbox("I am at the venue", key=K("venue"))
                if st.button("Mark event completed", key=K("done")):
                    s = load_store()
                    s["completions"].append({
                        "event": ev.get("name",""), "event_key": ekey(ev.get("name","")),
                        "name": participant_name, "name_key": nkey(participant_name),
                        "timestamp": datetime.now().isoformat(), "at_venue": bool(atv)
                    })
                    save_store(s); st.success("Marked completed.")
            else:
                if sdt:
                    mins = int((sdt - now).total_seconds() // 60)
                    if 0 < mins <= 30: st.warning("⏰ Your event starts in 30 minutes or less.")
                    if 0 < mins <= 10: st.error("⏰ Your event starts in 10 minutes — are you at the venue?")
            if admin_phone:
                st.markdown(f"[📞 Call Admin]({'tel:' + admin_phone})")

# ----- Tabs -----
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["🔎 Search", "🗓️ Timeline", "🧑‍🎓 Your Events", "✉️ Messages", "🟢 Online", "🗂️ Admin Data"])

with tab1:
    kind = st.radio("Search for", ["Events","Participants"], horizontal=True, key="search_kind")
    if kind == "Events":
        q = st.text_input("Search events/teachers/keywords", key="search_events_q")
        cats = ["All"] + sorted({ev.get("category","") for ev in EVENTS})
        c1, c2 = st.columns([1,1])
        with c1: pick_cat = st.selectbox("Filter by category", cats, key="flt_cat_global")
        with c2: pick_day = st.selectbox("Filter by day", ["All","Day 1 (Fri 26 Sep)","Day 2 (Sat 27 Sep)"], key="flt_day_global")
        nq = norm(q or "")
        res = []
        for ev in EVENTS:
            hay = " ".join([ev.get("name",""), ev.get("category",""), ev.get("age_category",""),
                            ev.get("teacher_in_charge",""), ev.get("brochure_block","")]).lower()
            ok = True if not nq else all(tok in hay for tok in nq.split())
            if pick_cat!="All": ok &= (ev.get("category","")==pick_cat)
            if pick_day!="All":
                ds = (ev.get("date") or ev.get("date_info_duty","")).upper()
                if pick_day.endswith("26 Sep"): ok &= ("FRIDAY" in ds or "26" in ds)
                else: ok &= ("SATURDAY" in ds or "27" in ds)
            if ok: res.append(ev)
        st.write(f"Found {len(res)} event(s).")
        for ev in res:
            with st.container():
                render_event_card(ev, scope="search", is_admin=is_admin, participant_name=current_user, admin_name=admin_name, admin_phone=admin_phone)
    else:
        pq = st.text_input("Search participant name", key="search_participant_global").strip()
        s = load_store()
        hits = [p for p in s["participants"] if norm(pq) in p["name_key"]] if pq else []
        ev_keys = {p["event_key"] for p in hits}
        res = [EVENTS_BY_KEY[k] for k in ev_keys if k in EVENTS_BY_KEY]
        st.write(f"Found {len(hits)} participant(s) in {len(res)} event(s).")
        for ev in res:
            with st.container():
                render_event_card(ev, scope="psearch", is_admin=is_admin, participant_name=current_user, admin_name=admin_name, admin_phone=admin_phone)

with tab2:
    st.subheader("🗓️ Timeline — What’s on & when")
    rows = []
    for ev in EVENTS:
        sdt, edt = parse_datetime_fields(ev)
        rows.append({
            "Event": ev.get("name",""),
            "Start": sdt.isoformat() if sdt else "",
            "End": edt.isoformat() if edt else "",
            "Venue": ev.get("venue",""),
            "Teacher": ev.get("teacher_in_charge",""),
            "Status": status_badge(sdt, edt)
        })
    df = pd.DataFrame(rows).sort_values(by=["Start","Event"])
    st.dataframe(df, use_container_width=True)

with tab3:
    st.subheader("Your registered events")
    if mode == "Participant" and current_user:
        nk = nkey(current_user)
        s = load_store()
        my = [p for p in s["participants"] if p["name_key"]==nk]
        if not my:
            st.info("You have not been added to any event by Admin yet.")
        else:
            for row in my:
                ev = EVENTS_BY_KEY.get(row["event_key"])
                if not ev: continue
                with st.container():
                    render_event_card(ev, scope="mine", is_admin=False, participant_name=current_user, admin_name=admin_name, admin_phone=admin_phone)
    else:
        st.info("Only participants see their events here.")

with tab4:
    st.subheader("✉️ Messages (All)")
    s = load_store()
    msgs = sorted(s.get("messages",[]), key=lambda m: m["timestamp"])
    if st.toggle("Live mode (5s auto-refresh)", key="live_msg"):
        live_autorefresh(True, 5000, 'messages_live')
    for m in msgs[-250:]:
        icon = "📞" if m.get("kind")=="call_request" else "💬"
        st.markdown(f"{icon} **{m['timestamp']}** — _{m['event']}_ — **{m['from']}** → **{m['to']}**: {m['text']}")

with tab5:
    st.subheader("🟢 Online (last seen)")
    s = load_store()
    ses = sorted(s.get("sessions",[]), key=lambda r: r.get("last_seen",""), reverse=True)
    df = pd.DataFrame([{"name":r["name"], "role": r.get("role",""), "phone": r.get("phone",""), "last_seen": r.get("last_seen","")} for r in ses])
    st.dataframe(df, use_container_width=True)

def export_master_csv():
    """Builds the consolidated CSV with exact headers and spacing from the provided format."""
    # Headers exactly as per sample
    headers = [
        "NAME OF THE EVENT",
        "TEACHER IN CHARGE",
        "NAME OF PARTICIPANTS",
        "EMAIL ID OF PARTICIPANTS",
        "PHONE NUMBER",
        "STD",
        "DIV",
        "DATES",
        "CATEGORY"
    ]
    s = load_store()
    rows = []
    for p in s.get("participants", []):
        ev = EVENTS_BY_KEY.get(p.get("event_key",""))
        if not ev: 
            evname = p.get("event","")
            teacher = ""
            dates = ""
        else:
            evname = ev.get("name","")
            teacher = ev.get("teacher_in_charge","")
            dates = (ev.get("date") or ev.get("date_info_duty","") or "").strip()
        name = p.get("name","")
        email = p.get("email","")
        phone = p.get("phone","")
        std = p.get("grade","")
        div = p.get("division","")
        cat = p.get("subcat","")
        rows.append([evname, teacher, name, email, phone, std, div, dates, cat])

    df = pd.DataFrame(rows, columns=headers)
    out_path = Path(__file__).with_name("ADMIN_MASTER_PARTICIPANTS.csv")
    df.to_csv(out_path, index=False, encoding="utf-8")
    return df, out_path

with tab6:
    st.subheader("Admin Data")
    if is_admin:
        s = load_store()
        st.write("Store path:", str(STORE_PATH))
        st.json({"updated_at": s.get("updated_at",""), "participants_count": len(s.get("participants",[])), "messages_count": len(s.get("messages",[]))})

        # Master CSV export in the exact format
        st.markdown("### 📦 Master CSV Export (Exact Format)")
        df, out_path = export_master_csv()
        st.download_button("⬇️ Download ADMIN_MASTER_PARTICIPANTS.csv", df.to_csv(index=False).encode("utf-8"),
                           file_name="ADMIN_MASTER_PARTICIPANTS.csv", mime="text/csv")
        st.caption(f"Also saved server-side at: {out_path.name}")

        st.download_button("⬇️ Download data JSON", json.dumps(s, ensure_ascii=False, indent=2).encode("utf-8"),
                           file_name="participants_store_export.json", mime="application/json")
    else:
        st.info("Admins only.")
