# 001 – FORPSI „kontrola prohlížeče“ → Google Ads zamítá reklamy (nefunkční cíl)

**Nahlášeno:** 2026-10-19, Zuzana Krejčí (PPC, marketingppc.cz) → kubik@middex.cz
**Stav:** potvrzeno měřením 2026-10-19 (middex.cz → HTTP 429 / 403 z FORPSI proxy) – čeká na FORPSI podporu

## Symptom (z e-mailu)

- Google Ads zamítl reklamy: *nefunkční cíl*.
- URL se načtou, ale při **první návštěvě** se zobrazí hláška FORPSI, že *probíhá kontrola prohlížeče* (Firefox).
- Stránka se načítá pomalu.
- Dotaz: „Dávali jste na web nějakou ochranu?“

## Hypotéza

Na hostingu FORPSI je aktivní ochrana proti botům / anti-DDoS, která návštěvníkovi bez cookie
vrátí mezistránku s JavaScriptovou kontrolou a teprve po nastavení cookie a reloadu pustí na web.
Kontrola cílové URL v Google Ads (AdsBot-Google) mezistránku nepřejde nebo na ni čeká příliš dlouho
→ cíl je vyhodnocen jako nefunkční. Druhá a další návštěva už je rychlá (cookie), proto to
„u nás funguje“.

## Co ověřit (měřením)

1. Přidat doménu a všechny finální URL z Google Ads do [`sites.yml`](../sites.yml).
2. Spustit *Actions → Measure → Run workflow*.
3. V reportu zkontrolovat:
   - `HTTP[adsbot-google]` / `adsbot-google-mobile`: dostává mezistránku (`Challenge = YES`), jiný status než 200, nebo přesměrování?
   - `Browser[firefox] cold`: je vidět challenge, za kolik sekund se objeví skutečný obsah, screenshot hlášky.
   - `warm` návštěva: zmizí kontrola s cookie? (potvrzuje cookie-based ochranu)
   - hlavičky `Server`, `Set-Cookie` – název cookie často prozradí, o jaký filtr jde.
4. Opakovat měření několikrát denně – zjistit, jestli je ochrana trvalá, nebo se zapíná jen při zátěži
   (FORPSI uvádí, že roboty standardně neblokuje, ale při přetížení může přístupy dočasně omezit).

## Zjištění ze znalostní báze FORPSI

- [Ochrana před DoS – chyba 429](https://support.forpsi.com/kb/a4605/ochrana-pred-dos-chyba-429.aspx?translation-detect=false)
  ([EN](https://support.forpsi.com/kb/a4632/dos-protection-error-429.aspx)): ochrana je na Linux webhostingu
  **trvale zapnutá**, blokuje IP adresu s příliš mnoha požadavky, blokace po čase vyprší a při opakování se obnoví.
  Jako častou příčinu uvádí vadné WordPress pluginy/šablony.
- Žádný článek nepopisuje vypnutí ochrany v administraci ani stránku „ověření prohlížeče“ → řešit ticketem.

## Možná řešení

1. **Administrace FORPSI** → nastavení webhostingu / domény: hledat volbu typu ochrana proti botům,
   anti-DDoS, kontrola prohlížeče a vypnout ji, příp. nastavit výjimku.
2. Pokud volba v administraci není: **ticket na podporu FORPSI** – poslat doménu, screenshot hlášky
   z reportu, čas výskytu, a požádat o vypnutí kontroly nebo whitelist pro Google
   (User-Agent `AdsBot-Google*`, `Googlebot`, IP rozsahy Googlu: https://developers.google.com/static/search/apis/ipranges/special-crawlers.json).
3. Ověřit, že ochranu nepřidává samotný web (WordPress plugin typu Wordfence/anti-spam, `.htaccess`).
4. Po změně: spustit měření → AdsBot i Firefox cold musí být `OK` → požádat v Google Ads o **opětovné posouzení** zamítnutých reklam.
5. Dlouhodobě: pokud FORPSI výjimku neumožní, zvážit CDN (např. Cloudflare) s povoleným „verified bots“ nebo jiný hosting.

## Návrh odpovědi klientce

> Dobrý den, paní Krejčí,
>
> děkuji za upozornění. Hlášku „probíhá kontrola prohlížeče“ zobrazuje ochrana proti botům na straně
> hostingu FORPSI, nikoliv úprava webu z naší strany. Prověřujeme ji a řešíme s FORPSI vypnutí,
> resp. výjimku pro Google. Web zároveň průběžně automaticky měříme, abychom ověřili,
> že se roboti Google Ads dostanou rovnou na obsah. Jakmile bude opraveno, dám vědět a můžete
> požádat o opětovné posouzení reklam.
>
> S pozdravem
> Pavel Kubík
