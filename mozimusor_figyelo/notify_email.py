#!/usr/bin/env python3
"""E-mail küldő a mozi műsorfigyelőnek.

A jelentést a szabványos bemeneten kapja. Az első sorból lesz a tárgy (a
`=== … ===` keretet levágjuk), a teljes szöveg a levél törzse.

A levél kétrészes: sima szöveg és HTML. Azért kell a HTML is, mert a sima
szöveges levélben a leveleződ maga próbálja felismerni a linkeket, és a
sorvégi URL-ekbe belerántja a következő sort — így kattinthatatlan,
elrontott címek keletkeznek. A HTML részben a linkek explicit `<a>` elemek,
ott ez nem fordulhat elő.

Miért nem a GitHub értesítése? Mert az a beállításoktól függ, és a "watching"
típusú értesítéseket nem minden fióknál kézbesíti e-mailben. Ez itt közvetlen
SMTP: pontosan egy levél megy, a mi tárgysorunkkal.

Kötelező környezeti változók:
  GMAIL_USER          a küldő Gmail-cím
  GMAIL_APP_PASSWORD  16 karakteres Google app-jelszó (NEM a fiók jelszava)

Opcionális:
  EMAIL_TO   címzett, alapból ugyanaz, mint a küldő
  SMTP_HOST  alapból smtp.gmail.com
  SMTP_PORT  alapból 465 (SSL)
"""

import html
import os
import re
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

URL = re.compile(r"https?://[^\s<>\"']+")


def sor_html(sor):
    """Egy sor HTML-re: a szöveg escape-elve, az URL-ek kattinthatóan."""
    darabok, poz = [], 0
    for talalat in URL.finditer(sor):
        darabok.append(html.escape(sor[poz:talalat.start()]))
        cim = talalat.group(0)
        darabok.append(f'<a href="{html.escape(cim, quote=True)}" '
                       f'style="color:#1a73e8">{html.escape(cim)}</a>')
        poz = talalat.end()
    darabok.append(html.escape(sor[poz:]))
    return "".join(darabok)


def torzs_html(szoveg):
    sorok = []
    for sor in szoveg.split("\n"):
        # a "jegy: <url>" sorból rövid, kattintható gomb-szerű link lesz
        jegy = re.match(r"^(\s*)jegy:\s*(\S+)\s*$", sor)
        if jegy:
            cim = html.escape(jegy.group(2), quote=True)
            sorok.append(f'{"&nbsp;" * len(jegy.group(1))}'
                         f'<a href="{cim}" style="color:#1a73e8">jegyvásárlás →</a>')
            continue
        sorok.append(sor_html(sor).replace("  ", "&nbsp;&nbsp;"))
    return (
        '<div style="font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,'
        'monospace;font-size:13px;line-height:1.55;color:#202124">'
        + "<br>".join(sorok) +
        '</div>'
    )


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
    uzenet.add_alternative(torzs_html(torzs), subtype="html")

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
