import json, time, smtplib, os, uuid, urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text      import MIMEText
from email.utils          import formataddr

# daily_limit read from Render env vars — set GMAIL_0_LIMIT=40 etc. in dashboard
GMAIL_ACCOUNTS = [
    {"email": os.environ.get("GMAIL_0_EMAIL",""), "app_pass": os.environ.get("GMAIL_0_PASS",""), "daily_limit": int(os.environ.get("GMAIL_0_LIMIT","9999"))},
    {"email": os.environ.get("GMAIL_1_EMAIL",""), "app_pass": os.environ.get("GMAIL_1_PASS",""), "daily_limit": int(os.environ.get("GMAIL_1_LIMIT","9999"))},
    {"email": os.environ.get("GMAIL_2_EMAIL",""), "app_pass": os.environ.get("GMAIL_2_PASS",""), "daily_limit": int(os.environ.get("GMAIL_2_LIMIT","9999"))},
    {"email": os.environ.get("GMAIL_3_EMAIL",""), "app_pass": os.environ.get("GMAIL_3_PASS",""), "daily_limit": int(os.environ.get("GMAIL_3_LIMIT","9999"))},
    {"email": os.environ.get("GMAIL_4_EMAIL",""), "app_pass": os.environ.get("GMAIL_4_PASS",""), "daily_limit": int(os.environ.get("GMAIL_4_LIMIT","9999"))},
]
GMAIL_ACCOUNTS = [a for a in GMAIL_ACCOUNTS if a["email"] and a["app_pass"]]

PRIMARY_REPLY_TO   = "deep@deepshah.tech"
PRIMARY_REPLY_NAME = "Deep Shah"
FROM_NAME          = "Deep Shah"
RENDER_API_KEY     = os.environ.get("RENDER_API_KEY", "")
RENDER_SERVICE_ID  = os.environ.get("RENDER_SERVICE_ID", "")

SENT_LOG_PATH = "sent_log.json"

def _load_sent_log() -> set:
    if os.path.exists(SENT_LOG_PATH):
        try:
            with open(SENT_LOG_PATH) as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def _mark_sent(email: str, sent_set: set) -> None:
    sent_set.add(email)
    try:
        with open(SENT_LOG_PATH, "w") as f:
            json.dump(list(sent_set), f, indent=2)
    except Exception as e:
        print(f"  ⚠️  Could not write sent_log: {e}")

def suspend_self():
    if not RENDER_API_KEY or not RENDER_SERVICE_ID:
        print("  ⚠️  RENDER_API_KEY or RENDER_SERVICE_ID missing — suspend manually!")
        return
    try:
        url     = f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/suspend"
        headers = {
            "Authorization": f"Bearer {RENDER_API_KEY}",
            "Content-Type":  "application/json",
        }
        req = urllib.request.Request(url, data=b"{}", headers=headers, method="POST")
        urllib.request.urlopen(req)
        print(f"  ✅ Worker self-suspended via Render API — safe to leave ✅")
    except Exception as e:
        print(f"  ⚠️  Self-suspend failed: {e} — suspend manually on dashboard!")

def build_msg(item, from_email):
    domain = from_email.split("@")[1]
    msg = MIMEMultipart("mixed")
    msg["From"]       = formataddr((FROM_NAME, from_email))
    msg["To"]         = formataddr((item["to_name"], item["to_email"]))
    msg["Subject"]    = item["subject"]
    msg["Reply-To"]   = formataddr((PRIMARY_REPLY_NAME, PRIMARY_REPLY_TO))
    msg["Message-ID"] = f"<{uuid.uuid4().hex}.{int(time.time())}@{domain}>"
    msg["Date"]       = time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime())
    msg["List-Unsubscribe"]      = f"<mailto:{PRIMARY_REPLY_TO}?subject=unsubscribe>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(item["plain"], "plain", "utf-8"))
    alt.attach(MIMEText(item["html"],  "html",  "utf-8"))
    msg.attach(alt)
    return msg

def send_one(item, sent_counts: dict):
    n     = len(GMAIL_ACCOUNTS)
    order = [(item["acct_idx"] + i) % n for i in range(n)]
    for idx in order:
        acct  = GMAIL_ACCOUNTS[idx]
        limit = acct.get("daily_limit", 9999)
        if sent_counts.get(acct["email"], 0) >= limit:
            print(f"  ⏭️  {acct['email']} at daily cap ({limit}) — skipping")
            continue
        msg = build_msg(item, acct["email"])
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as conn:
                conn.ehlo("deepshah.tech")
                conn.login(acct["email"], acct["app_pass"])
                conn.send_message(msg)
            sent_counts[acct["email"]] = sent_counts.get(acct["email"], 0) + 1
            ts = time.strftime("%H:%M:%S")
            print(f"  ✅ [{ts}] T{item.get('template_id','?')} "
                  f"{item['cname']:<24} -> {item['to_email']} via {acct['email']}")
            return True
        except smtplib.SMTPRecipientsRefused:
            print(f"  ❌ BOUNCE: {item['to_email']}")
            return False
        except Exception as e:
            print(f"  ⚠️  {acct['email']} failed ({e}) — trying next")
            continue
    print(f"  ❌ ALL FAILED OR AT CAP: {item['to_email']}")
    return False

def main():
    with open("send_queue.json") as f:
        queue = json.load(f)

    already_sent = _load_sent_log()
    skipped      = [item for item in queue if item["to_email"] in already_sent]
    queue        = [item for item in queue if item["to_email"] not in already_sent]

    n           = len(queue)
    start       = time.time()
    sent        = failed = 0
    sent_counts = {}   # per-account counter — enforces daily_limit at Render runtime

    print(f"🚀 Render sender — {n} emails to send  ({len(skipped)} already sent, skipping)")
    if skipped:
        for s in skipped:
            print(f"  ⏭️  Already sent — skipping {s['to_email']} ({s['cname']})")
    print(f"⏰ Started: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'─'*60}")

    for i, item in enumerate(queue):
        send_at = start + item["send_offset_sec"]
        wait    = send_at - time.time()
        if wait > 0:
            eta = time.strftime("%H:%M", time.localtime(start + queue[-1]["send_offset_sec"]))
            print(f"  ⏳ [{i+1}/{n}] waiting {wait:.0f}s  finish ~{eta}", end="\r", flush=True)
            time.sleep(wait)
        ok = send_one(item, sent_counts)
        if ok:
            sent += 1
            _mark_sent(item["to_email"], already_sent)
        else:
            failed += 1

    print(f"\n{'─'*60}")
    print(f"✅ Complete — {sent} sent  {failed} failed  {len(skipped)} skipped (already sent)")
    print(f"⏰ Finished: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    suspend_self()

if __name__ == "__main__":
    main()
