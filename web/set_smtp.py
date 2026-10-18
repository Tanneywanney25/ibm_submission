"""Turn on real email (sign-in links, alerts, welcome mail) on the LinuxONE instance.

Run it yourself in an interactive SSH session; it prompts for the password with
no echo, so the secret never lands in a chat log, a shell history or the repo:

    ssh -t -i datathon.pem linux1@148.100.77.112 \
        "python3 ~/heatahead/site/web/set_smtp.py"

It logs in to the SMTP server first and only saves settings that work, mails a
test message to the sending address, writes SMTP_* into
~/.config/heatahead/accounts.env (mode 600, the file the heatahead-web systemd
drop-in loads) and restarts heatahead-web. Defaults suit a Gmail app password
(myaccount.google.com/apppasswords; the account needs 2-Step Verification).
"""

import getpass
import os
import smtplib
import subprocess
from email.message import EmailMessage
from pathlib import Path

ENV = Path.home() / ".config" / "heatahead" / "accounts.env"
KEYS = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "SMTP_FROM")


def ask(prompt, default=""):
    got = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return got or default


def main():
    host = ask("SMTP server", "smtp.gmail.com")
    port = int(ask("Port (STARTTLS)", "587"))
    user = ask("Sending address (the Gmail account)")
    # Google shows app passwords in groups of four; the spaces are not part of it
    password = getpass.getpass("App password (hidden): ").replace(" ", "").strip()
    sender = f"HeatAhead <{user}>"
    if not user or not password:
        raise SystemExit("Nothing saved: address and password are both required.")

    print("Logging in and sending a test message ...")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = "HeatAhead email is on", sender, user
    msg.set_content("The HeatAhead server can send email now: sign-in links, "
                    "building alerts and welcome messages will be delivered.")
    try:
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.starttls()
            s.login(user, password)
            s.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        raise SystemExit(f"Nothing saved: {type(e).__name__}: {e}")

    keep = []
    if ENV.exists():
        keep = [ln for ln in ENV.read_text().splitlines()
                if ln.split("=", 1)[0] not in KEYS]
    values = dict(SMTP_HOST=host, SMTP_PORT=str(port), SMTP_USER=user,
                  SMTP_PASS=password, SMTP_FROM=sender)
    ENV.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(ENV, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        # systemd EnvironmentFile: quote the From value because it has spaces
        f.write("\n".join(keep + [f'{k}="{v}"' if " " in v else f"{k}={v}"
                                  for k, v in values.items()]) + "\n")
    os.chmod(ENV, 0o600)
    print(f"Saved to {ENV}. Restarting heatahead-web ...")
    subprocess.run(["sudo", "systemctl", "restart", "heatahead-web"], check=True)
    print(f"Done. Check {user} for the test message; email sign-in appears on the "
          "site within two minutes.")


if __name__ == "__main__":
    main()
