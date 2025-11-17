import asyncio
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

BASE_URL = "https://v2.streameast.ga/"
M3U8_PATTERN = re.compile(r"https?://[^\s\"']+\.m3u8[^\s\"']*", re.I)
PLAYLIST_FILE = "StreamEast.m3u8"

# --- Headers required for working playback ---
ORIGIN = "https://streamcenter.pro"
REFERER = "https://streamcenter.pro/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"

DEFAULT_LOGO = "https://v2.streameast.ga/icons/favicon-48x48.png"


# --- Category detection mapping ---
def detect_category(url: str):
    """Detect sport type from URL path and assign correct TVG-ID + group-title."""
    url_lower = url.lower()

    mapping = {
        "nfl": ("NFL", "NFL.Dummy.us"),
        "ncaaf": ("NCAA Football", "NCAA.Football.Dummy.us"),
        "ncaab": ("NCAA Basketball", "NCAA.Mens.Basketball.Dummy.us"),
        "nba": ("NBA", "NBA.Basketball.Dummy.us"),
        "wnba": ("WNBA", "WNBA.Dummy.us"),
        "nhl": ("NHL", "NHL.Hockey.Dummy.us"),
        "mlb": ("MLB", "MLB.Baseball.Dummy.us"),
        "soccer": ("Soccer", "World.Soccer.Dummy.us"),
        "epl": ("Premier League", "Premier.League.Dummy.us"),
        "uefa": ("UEFA", "UEFA.Champions.League.Dummy.us"),
        "mls": ("MLS", "MLS.Soccer.Dummy.us"),
        "ufc": ("UFC / MMA", "UFC.Fight.Pass.Dummy.us"),
        "mma": ("UFC / MMA", "UFC.Fight.Pass.Dummy.us"),
        "boxing": ("Boxing / PPV", "PPV.EVENTS.Dummy.us"),
        "ppv": ("Boxing / PPV", "PPV.EVENTS.Dummy.us"),
        "golf": ("Golf", "Golf.Dummy.us"),
        "tennis": ("Tennis", "Tennis.Dummy.us"),
        "racing": ("Racing", "Racing.Dummy.us"),
        "nascar": ("Racing", "Racing.Dummy.us"),
        "f1": ("Racing", "Racing.Dummy.us"),
        "rugby": ("Rugby", "Rugby.Dummy.us"),
        "cricket": ("Cricket", "Cricket.Dummy.us"),
        "darts": ("Darts", "Darts.Dummy.us"),
        "billiard": ("Billiards", "BilliardTV.Dummy.us"),
    }

    for key, (group, tvg) in mapping.items():
        if f"/{key}/" in url_lower:
            return f"StreamEast - {group}", tvg

    return "StreamEast - All Sports", "Sports.Dummy.us"


async def extract_links(page_html):
    """Extract live match links, team names, and one logo per card."""
    soup = BeautifulSoup(page_html, "html.parser")
    links = []

    for a in soup.select("a.uefa-card.live"):
        href = a.get("href")
        if not href:
            continue
        full_url = urljoin(BASE_URL, href)

        # Title
        teams = [t.text.strip() for t in a.select("span.uefa-name") if t.text.strip()]
        title = " vs ".join(teams) if teams else "Unknown Match"

        # One logo only
        logo_url = None
        for img in a.select("img"):
            src = (img.get("src") or "").strip()
            if not src or src.startswith("data:"):
                continue
            logo_url = urljoin(BASE_URL, src)
            break
        if not logo_url:
            logo_url = DEFAULT_LOGO

        links.append({
            "title": title,
            "url": full_url,
            "logo": logo_url
        })
    return links


async def find_m3u8(page, url):
    """Visit match page, trigger player, intercept .m3u8 in real-time."""
    m3u8_found = []

    async def on_request(request):
        if ".m3u8" in request.url:
            m3u8_found.append(request.url)

    page.on("request", on_request)

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        await page.mouse.click(400, 300)
        await page.keyboard.press("Space")

        try:
            req = await page.wait_for_event(
                "request",
                timeout=12000,
                predicate=lambda r: ".m3u8" in r.url
            )
            return req.url
        except:
            pass

        await page.wait_for_timeout(4000)
    except Exception as e:
        print(f"    [ERROR] Navigation failed: {e}")

    if m3u8_found:
        return m3u8_found[0]

    html = await page.content()
    match = M3U8_PATTERN.search(html)
    if match:
        return match.group(0)
    return None


async def main():
    print("------------------------------------------------------------")
    print("M3U8 Link Finder (StreamEast - Grouped Output)")
    print("------------------------------------------------------------")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(
            user_agent=USER_AGENT,
            ignore_https_errors=True
        )
        page = await context.new_page()

        print(f"STEP 1: Loading homepage {BASE_URL}")
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=20000)
        html = await page.content()
        matches = await extract_links(html)
        print(f"Found {len(matches)} live match pages. Starting interception...\n")

        results = []
        for i, match in enumerate(matches, start=1):
            print(f"[Processing {i}/{len(matches)}] {match['title']}")
            m3u8_url = await find_m3u8(page, match["url"])
            sport_group, tvg_id = detect_category(match["url"])
            if m3u8_url:
                print(f"    ✅ Found M3U8: {m3u8_url}")
            else:
                print(f"    ❌ No M3U8 found.")
            results.append({
                "title": match["title"],
                "url": match["url"],
                "m3u8": m3u8_url,
                "logo": match["logo"],
                "group": sport_group,
                "tvg": tvg_id
            })

        # Write playlist
        with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
            f.write('#EXTM3U url-tvg="https://epgshare01.online/epgshare01/epg_ripper_DUMMY_CHANNELS.xml.gz"\n')
            for r in results:
                if r["m3u8"]:
                    f.write(
                        f'#EXTINF:-1 tvg-id="{r["tvg"]}" tvg-logo="{r["logo"]}" '
                        f'group-title="{r["group"]}",{r["title"]}\n'
                        f'#EXTVLCOPT:http-origin={ORIGIN}\n'
                        f'#EXTVLCOPT:http-referrer={REFERER}\n'
                        f'#EXTVLCOPT:http-user-agent={USER_AGENT}\n'
                        f'{r["m3u8"]}\n'
                    )

        print("\n============================================================")
        print("BATCH RESULTS: DIRECT M3U8 LINKS")
        print("============================================================")
        found = sum(1 for r in results if r["m3u8"])
        for r in results:
            status = "✅ Found" if r["m3u8"] else "❌ Failed"
            print(f"\n{status}: {r['title']}")
            print(f"  > Group: {r['group']}  |  TVG-ID: {r['tvg']}")
            print(f"  > Logo: {r['logo']}")
            print(f"  > Stream: {r['m3u8'] or 'NOT FOUND'}")

        print("\n============================================================")
        print(f"SUMMARY: {found} of {len(results)} M3U8 links successfully extracted.")
        print("============================================================")
        print(f"Playlist saved to: {PLAYLIST_FILE}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
