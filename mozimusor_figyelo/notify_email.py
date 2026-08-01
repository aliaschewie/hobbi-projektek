#!/usr/bin/env python3
"""E-mail küldő a mozi műsorfigyelőnek.

A jelentést a szabványos bemeneten kapja. Az első sorból lesz a tárgy (a
`=== … ===` keretet levágjuk), a teljes szöveg a levél törzse.

Miért nem a GitHub értesítése? Mert az a beállításoktól függ, és a "watching"
típusú értesítéseket nem minden fióknál kézbesíti e-mailben. Ez itt közvetlen
SMTP: pontosan egy levél megy, a mi tárgysorunkkal, semmi nem nyelheti el.

Kötelező környezeti változók:
  GMAIL_USER          a küldő Gmail-cím
  GMAIL_APP_PASSWORD  16 karakteres Google app-jelszó (NEM a fiók jelszava)

Opcionális:
  EMAIL_TO   címzett, alapból ugyanaz, mint a küldő
  SMTP_HOST  alapból smtp.gmail.com
  SMTP_PORT  alapból 465 (SSL)
"""

import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import formatdate, make_msgid


def main():
    torzs = sys.stdin.read().strip()
    if not torzs:
        print("[hiba] ures a jelentes, nincs mit kuldeni", file=sys.stderr)
        return 1

    user = os.environ.get("GMAIL_USER", "").strip()
    # az app-jelszót a Google 4-es csoportokban mutatja; a szóközök nem részei
    jelszo = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    if not user or not jelszo:
        print("[hiba] hianyzik a GMAIL_USER valtozo vagy a GMAIL_APP_PASSWORD "
              "secret", file=sys.stderr)
        return 1

    cimzett = os.environ.get("EMAIL_TO", "").strip() or user
    targy = torzs.split("\n", 1)[0].strip("= ").strip() or "Mozi műsorfigyelő"

    uzenet = EmailMessage()
    uzenet["Subject"] = targy
    uzenet["From"] = f"Mozi műsorfigyelő <{user}>"
    uzenet["To"] = cimzett
    uzenet["Date"] = formatdate(localtime=True)
    uzenet["Message-ID"] = make_msgid(domain="mozimusor.local")
    uzenet.set_content(torzs)

    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    try:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(),
                              timeout=30) as kapcsolat:
            kapcsolat.login(user, jelszo)
            kapcsolat.send_message(uzenet)
    except smtplib.SMTPAuthenticationError:
        print("[hiba] a Gmail elutasitotta a belepest. Ellenorizd, hogy a "
              "GMAIL_APP_PASSWORD tenyleg app-jelszo (16 karakter), es hogy a "
              "GMAIL_USER ugyanahhoz a fiokhoz tartozik.", file=sys.stderr)
        return 1

    print(f"[email] elkuldve ide: {cimzett}")
    print(f"[email] targy: {targy}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
