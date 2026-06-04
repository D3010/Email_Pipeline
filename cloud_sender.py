import json, time, smtplib, os, uuid, urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text      import MIMEText
from email.mime.base      import MIMEBase
from email                import encoders
from email.utils          import formataddr

GMAIL_ACCOUNTS = [
    {"email": os.environ.get("GMAIL_0_EMAIL",""), "app_pass": os.environ.get("GMAIL_0_PASS",""), "daily_limit": int(os.environ.get("GMAIL_0_LIMIT","9999"))},
    {"email": os.environ.get("GMAIL_1_EMAIL",""), "app_pass": os.environ.get("GMAIL_1_PASS",""), "daily_limit": int(os.environ.get("GMAIL_1_LIMIT","9999"))},
]
GMAIL_ACCOUNTS = [a for a in GMAIL_ACCOUNTS if a["email"] and a["app_pass"]]

FROM_NAME          = "Parthiv Shah"
PRIMARY_REPLY_NAME = "Parthiv Shah"
PRIMARY_REPLY_TO   = "parthiv@rxbuysell.com"
RENDER_API_KEY     = os.environ.get("RENDER_API_KEY", "")
RENDER_SERVICE_ID  = os.environ.get("RENDER_SERVICE_ID", "")
ATTACH_PDF         = os.environ.get("ATTACH_PDF","1") == "1"
ATTACHMENT_NAME    = "CT_Portfolio.pdf"   # shipped in repo
SENT_LOG_PATH      = "sent_log.json"

def _load_sent():
    if os.path.exists(SENT_LOG_PATH):
        try:
            with open(SENT_LOG_PATH) as f: return set(json.load(f))
        except Exception: return set()
    return set()

def _mark_sent(email, s):
    s.add(email)
    try:
        with open(SENT_LOG_PATH,"w") as f: json.dump(list(s), f)
    except Exception as e: print(f"  warn sent_log: {e}")

def suspend_self():
    if not RENDER_API_KEY or not RENDER_SERVICE_ID:
        print("  RENDER_API_KEY/SERVICE_ID missing — suspend manually."); return
    try:
        url=f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/suspend"
        req=urllib.request.Request(url, data=b"{}", headers={"Authorization":f"Bearer {RENDER_API_KEY}","Content-Type":"application/json"}, method="POST")
        urllib.request.urlopen(req); print("  worker self-suspended")
    except Exception as e: print(f"  self-suspend failed: {e}")

def build_msg(item, from_email):
    domain=from_email.split("@")[1]
    msg=MIMEMultipart("mixed")
    msg["From"]=formataddr((FROM_NAME, from_email))
    msg["To"]=formataddr((item["to_name"], item["to_email"]))
    msg["Subject"]=item["subject"]
    msg["Reply-To"]=formataddr((PRIMARY_REPLY_NAME, PRIMARY_REPLY_TO))
    msg["Message-ID"]=f"<{uuid.uuid4().hex}.{int(time.time())}@{domain}>"
    msg["Date"]=time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime())
    msg["List-Unsubscribe"]=f"<mailto:{PRIMARY_REPLY_TO}?subject=unsubscribe>"
    msg["List-Unsubscribe-Post"]="List-Unsubscribe=One-Click"
    alt=MIMEMultipart("alternative")
    alt.attach(MIMEText(item["plain"],"plain","utf-8"))
    alt.attach(MIMEText(item["html"],"html","utf-8"))
    msg.attach(alt)
    if ATTACH_PDF and os.path.exists(ATTACHMENT_NAME):
        with open(ATTACHMENT_NAME,"rb") as f:
            part=MIMEBase("application","octet-stream"); part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{ATTACHMENT_NAME}"')
        msg.attach(part)
    return msg

def send_one(item, counts):
    n=len(GMAIL_ACCOUNTS); order=[(item["acct_idx"]+i)%n for i in range(n)]
    for idx in order:
        acct=GMAIL_ACCOUNTS[idx]; limit=acct.get("daily_limit",9999)
        if counts.get(acct["email"],0)>=limit:
            print(f"  cap {acct['email']}"); continue
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com",465,timeout=30) as conn:
                conn.ehlo("rxbuysell.com"); conn.login(acct["email"],acct["app_pass"]); conn.send_message(build_msg(item,acct["email"]))
            counts[acct["email"]]=counts.get(acct["email"],0)+1
            print(f"  OK [{time.strftime('%H:%M:%S')}] T{item.get('template_id','?')} {item['cname']} -> {item['to_email']} via {acct['email']}")
            return True
        except smtplib.SMTPRecipientsRefused:
            print(f"  BOUNCE {item['to_email']}"); return False
        except Exception as e:
            print(f"  {acct['email']} failed ({e})"); continue
    print(f"  ALL FAILED {item['to_email']}"); return False

def main():
    with open("send_queue.json") as f: queue=json.load(f)
    sent=_load_sent()
    queue=[i for i in queue if i["to_email"] not in sent]
    start=time.time(); ok=bad=0; counts={}
    print(f"Render sender — {len(queue)} to send")
    for i,item in enumerate(queue):
        wait=start+item["send_offset_sec"]-time.time()
        if wait>0: time.sleep(wait)
        if send_one(item, counts): ok+=1; _mark_sent(item["to_email"], sent)
        else: bad+=1
    print(f"Complete — {ok} sent {bad} failed"); suspend_self()

if __name__=="__main__": main()
