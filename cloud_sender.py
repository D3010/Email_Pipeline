import json, time, smtplib, os, uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text      import MIMEText
from email.utils          import formataddr

GMAIL_ACCOUNTS = [
    {"email": os.environ.get("GMAIL_0_EMAIL",""), "app_pass": os.environ.get("GMAIL_0_PASS","")},
    {"email": os.environ.get("GMAIL_1_EMAIL",""), "app_pass": os.environ.get("GMAIL_1_PASS","")},
    {"email": os.environ.get("GMAIL_2_EMAIL",""), "app_pass": os.environ.get("GMAIL_2_PASS","")},
    {"email": os.environ.get("GMAIL_3_EMAIL",""), "app_pass": os.environ.get("GMAIL_3_PASS","")},
]
GMAIL_ACCOUNTS = [a for a in GMAIL_ACCOUNTS if a["email"] and a["app_pass"]]

PRIMARY_REPLY_TO   = "deep@deepshah.tech"
PRIMARY_REPLY_NAME = "Deep Shah"
FROM_NAME          = "Deep Shah"

# ── Idempotency: track every email address we have already sent to ────────────
SENT_LOG_PATH = "sent_log.json"

def _load_sent_log() -> set:
    """Load the set of already-sent email addresses from disk."""
    if os.path.exists(SENT_LOG_PATH):
        try:
            with open(SENT_LOG_PATH) as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def _mark_sent(email: str, sent_set: set) -> None:
    """Append email to the in-memory set AND persist to disk immediately."""
    sent_set.add(email)
    try:
        with open(SENT_LOG_PATH, "w") as f:
            json.dump(list(sent_set), f, indent=2)
    except Exception as e:
        print(f"  ⚠️  Could not write sent_log: {e}")
# ─────────────────────────────────────────────────────────────────────────────

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

def send_one(item):
    n     = len(GMAIL_ACCOUNTS)
    order = [(item["acct_idx"] + i) % n for i in range(n)]
    for idx in order:
        acct = GMAIL_ACCOUNTS[idx]
        msg  = build_msg(item, acct["email"])
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as conn:
                conn.ehlo("deepshah.tech")
                conn.login(acct["email"], acct["app_pass"])
                conn.send_message(msg)
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
    print(f"  ❌ ALL FAILED: {item['to_email']}")
    return False

def main():
    with open("send_queue.json") as f:
        queue = json.load(f)

    # ── Load sent log ONCE at startup ─────────────────────────────────────────
    already_sent = _load_sent_log()
    skipped      = [item for item in queue if item["to_email"] in already_sent]
    queue        = [item for item in queue if item["to_email"] not in already_sent]
    # ─────────────────────────────────────────────────────────────────────────

    n     = len(queue)
    start = time.time()
    sent  = failed = 0

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
        ok = send_one(item)
        if ok:
            sent += 1
            # ── Persist immediately so redeploys can't re-send ────────────────
            _mark_sent(item["to_email"], already_sent)
            # ─────────────────────────────────────────────────────────────────
        else:
            failed += 1

    print(f"\n{'─'*60}")
    print(f"✅ Complete — {sent} sent  {failed} failed  {len(skipped)} skipped (already sent)")
    print(f"⏰ Finished: {time.strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()
