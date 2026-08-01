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


BETU = ("-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,"
        "Helvetica,Arial,sans-serif")
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"


def gomb_html(felirat, cim):
    """Kattintható gomb. Táblázattal, mert a levelezőkliensek egy része a
    CSS-t megnyirbálja, de a táblázatos cellakitöltést mind ismeri."""
    return (
        '<table role="presentation" cellspacing="0" cellpadding="0" '
        'style="margin:4px 0 20px"><tr><td '
        'style="background:#1a73e8;border-radius:6px">'
        f'<a href="{html.escape(cim, quote=True)}" '
        f'style="display:inline-block;padding:11px 22px;color:#ffffff;'
        f'font-family:{BETU};font-size:15px;font-weight:600;'
        f'text-decoration:none">{html.escape(felirat)} &rarr;</a>'
        '</td></tr></table>'
    )


def torzs_html(szoveg):
    darabok, sorok = [], []

    def sorok_urites():
        if sorok:
            darabok.append(
                f'<div style="font-family:{MONO};font-size:13px;'
                f'line-height:1.6;color:#202124">' + "<br>".join(sorok) +
                '</div>')
            sorok.clear()

    for sor in szoveg.split("\n"):
        # "=== Cím ===" -> fejléc
        fejlec = re.match(r"^===\s*(.*?)\s*===$", sor)
        if fejlec:
            sorok_urites()
            darabok.append(
                f'<div style="font-family:{BETU};font-size:17px;'
                f'font-weight:600;color:#202124;margin:0 0 14px">'
                f'{html.escape(fejlec.group(1))}</div>')
            continue
        # ">> Felirat: https://…" -> gomb
        gomb = re.match(r"^>>\s*(.+?):\s*(https?://\S+)\s*$", sor)
        if gomb:
            sorok_urites()
            darabok.append(gomb_html(gomb.group(1), gomb.group(2)))
            continue
        sorok.append(sor_html(sor).replace("  ", "&nbsp;&nbsp;"))
    sorok_urites()
    return "".join(darabok)


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
