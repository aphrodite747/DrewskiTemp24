import asyncio
import urllib.parse
import random
from pathlib import Path
from datetime import datetime, UTC
from playwright.async_api import async_playwright

M3U8_FILE = "TheTVApp.m3u8"
BASE_URL = "https://thetvapp.to"
CHANNEL_LIST_URL = f"{BASE_URL}/tv"

SECTIONS_TO_APPEND = {
    "/nba": "NBA",
    "/mlb": "MLB",
    "/wnba": "WNBA",
    "/nfl": "NFL",
    "/ncaaf": "NCAAF",
    "/ncaab": "NCAAB",
    "/soccer": "Soccer",
    "/ppv": "PPV",
    "/events": "Events",
    "/nhl": "NHL",
}

HEADER_TEXT_MAP = {
    "NCAAF": "College Football Streams",
    "NCAAB": "College Basketball Streams",
    "NBA": "NBA Streams",
    "NFL": "NFL Streams",
    "NHL": "NHL Streams",
    "MLB": "MLB Streams",
    "PPV": "PPV Events",
    "WNBA": "WNBA Streams",
    "Soccer": "Soccer Streams",
    "Events": "Events",
}

SPORTS_METADATA = {
    "MLB": {"tvg-id": "MLB.Baseball.Dummy.us", "logo": "http://drewlive24.duckdns.org:9000/Logos/Baseball-2.png"},
    "PPV": {"tvg-id": "PPV.EVENTS.Dummy.us", "logo": "http://drewlive24.duckdns.org:9000/Logos/PPV.png"},
    "NFL": {"tvg-id": "NFL.Dummy.us", "logo": "http://drewlive24.duckdns.org:9000/Logos/NFL.png"},
    "NCAAF": {"tvg-id": "NCAA.Football.Dummy.us", "logo": "http://drewlive24.duckdns.org:9000/Logos/CFB.png"},
    "NBA": {"tvg-id": "NBA.Basketball.Dummy.us", "logo": "http://drewlive24.duckdns.org:9000/Logos/NBA.png"},
    "NHL": {"tvg-id": "NHL.Hockey.Dummy.us", "logo": "http://drewlive24.duckdns.org:9000/Logos/Hockey.png"},
}


def extract_real_m3u8(url: str):
    if "ping.gif" in url and "mu=" in url:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        mu = qs.get("mu", [None])[0]
        if mu:
            return urllib.parse.unquote(mu)
    if ".m3u8" in url:
        return url
    return None


async def scrape_single_tv(context, href, title_raw):
    full_url = BASE_URL + href
    title = " - ".join(line.strip() for line in title_raw.splitlines() if line.strip()).replace(",", "")

    stream_url = None
    page = await context.new_page()

    def handle_response(response):
        nonlocal stream_url
        real = extract_real_m3u8(response.url)
        if real and stream_url is None:
            stream_url = real
            print(f"✅ [TV] {title} → {real}")
            try: page.remove_listener("response", handle_response)
            except: pass

    page.on("response", handle_response)

    try:
        await page.goto(full_url, wait_until="domcontentloaded", timeout=15000)
    except:
        pass

    for _ in range(150):
        if stream_url:
            break
        await page.wait_for_timeout(25)

    try:
        page.remove_listener("response", handle_response)
    except:
        pass

    await page.close()
    return stream_url


async def scrape_tv_urls():
    urls = []
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        print("🔄 Loading /tv channel list...")
        await page.goto(CHANNEL_LIST_URL, wait_until="domcontentloaded", timeout=15000)

        links = await page.locator("ol.list-group a").all()
        hrefs_titles = [
            (await l.get_attribute("href"), await l.text_content())
            for l in links if await l.get_attribute("href")
        ]
        await page.close()

        for idx, (href, title_raw) in enumerate(hrefs_titles, 1):
            stream = await scrape_single_tv(context, href, title_raw)
            if stream:
                urls.append(stream)

            if idx % 12 == 0:
                await asyncio.sleep(random.uniform(1.2, 1.8))

        await browser.close()
    return urls


def clean_m3u_header(lines):
    lines = [l for l in lines if not l.strip().startswith("#EXTM3U")]
    ts = int(datetime.now(UTC).timestamp())
    lines.insert(
        0,
        f'#EXTM3U url-tvg="https://raw.githubusercontent.com/DrewLiveTemp/DrewskiTemp24/main/DrewLive.xml.gz" # Updated: {ts}'
    )
    return lines


def replace_urls_only(lines, new_urls):
    out = []
    i = 0
    for line in lines:
        if line.strip().startswith("http") and i < len(new_urls):
            out.append(new_urls[i])
            i += 1
        else:
            out.append(line)
    return out


def remove_sd_entries(lines):
    cleaned = []
    skip = False
    for line in lines:
        if skip:
            skip = False
            continue
        if line.strip().startswith("#EXTINF") and "SD" in line.upper():
            skip = True
            continue
        cleaned.append(line)
    return cleaned


async def scrape_all_sports_sections():
    all_urls = []
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context()

        for path, group in SECTIONS_TO_APPEND.items():
            try:
                section_url = BASE_URL + path
                header_text = HEADER_TEXT_MAP.get(group, group)

                print(f"\n📁 Loading {section_url} (looking for H3: '{header_text}')")

                page = await context.new_page()
                await page.goto(section_url, wait_until="load", timeout=15000)
                
                locator_xpath = f"//h3[text()='{header_text}']/following-sibling::div//ol[contains(@class, 'list-group')]/a"
                
                links = []
                try:
                    await page.wait_for_selector(locator_xpath, state="attached", timeout=5000)
                    links = await page.locator(locator_xpath).all()
                except Exception:
                    pass
                
                print(f"    Found {len(links)} links for '{group}'.")

                if not links:
                    await page.close()
                    continue 

                hrefs_and_titles = []
                for link in links:
                    try:
                        href = await link.get_attribute("href")
                        title_raw = await link.text_content()
                        hrefs_and_titles.append((href, title_raw))
                    except Exception as e:
                        print(f"   ⚠️ Error reading a link (it may have disappeared): {e}")

                await page.close()

                for href, title_raw in hrefs_and_titles:
                    if not href or not title_raw:
                        continue

                    title = " - ".join(line.strip() for line in title_raw.splitlines() if line.strip()).replace(",", "")
                    full_url = BASE_URL + href
                    stream_url = None

                    sub = await context.new_page()

                    def handle_response(response):
                        nonlocal stream_url
                        real = extract_real_m3u8(response.url)
                        if real and stream_url is None:
                            stream_url = real
                            print(f"✅ [{group}] {title} → {real}")
                            try: sub.remove_listener("response", handle_response)
                            except: pass

                    sub.on("response", handle_response)

                    try:
                        await sub.goto(full_url, wait_until="domcontentloaded", timeout=15000)
                    except:
                        pass

                    for _ in range(160):
                        if stream_url:
                            break
                        await sub.wait_for_timeout(25)

                    try:
                        sub.remove_listener("response", handle_response)
                    except:
                        pass

                    await sub.close()

                    if stream_url:
                        all_urls.append((stream_url, group, title))

                await asyncio.sleep(random.uniform(1.2, 1.8))

            except Exception as e:
                print(f"⚠️ Skipped {group}: {e}")
                continue

        await browser.close()

    return all_urls


def replace_sports_section(lines, sports_urls):
    cleaned = []
    skip_next = False

    target_groups = {f'TheTVApp - {s}' for s in SECTIONS_TO_APPEND.values()}

    for line in lines:
        if skip_next:
            skip_next = False
            continue

        if line.startswith("#EXTINF") and any(g in line for g in target_groups):
            skip_next = True
            continue

        cleaned.append(line)

    for url, group, title in sports_urls:
        final_title = f"{title} HD"
        meta = SPORTS_METADATA.get(group, {})

        cleaned.append(
            f'#EXTINF:-1 tvg-id="{meta.get("tvg-id","")}" '
            f'tvg-name="{final_title}" tvg-logo="{meta.get("logo","")}" '
            f'group-title="TheTVApp - {group}",{final_title}'
        )
        cleaned.append(url)

    return cleaned


async def main():
    if not Path(M3U8_FILE).exists():
        print(f"❌ Missing file: {M3U8_FILE}")
        return

    lines = Path(M3U8_FILE).read_text(encoding="utf-8").splitlines()
    lines = clean_m3u_header(lines)

    print("🔧 Updating TV URLs...")
    tv_urls = await scrape_tv_urls()
    if tv_urls:
        lines = replace_urls_only(lines, tv_urls)

    print("🧹 Removing SD entries...")
    lines = remove_sd_entries(lines)

    print("⚽ Updating sports sections...")
    sports = await scrape_all_sports_sections()
    if sports:
        lines = replace_sports_section(lines, sports)

    Path(M3U8_FILE).write_text("\n".join(lines), encoding="utf-8")
    print("✅ Done — playlist updated successfully (TV & Sports).")


if __name__ == "__main__":
    asyncio.run(main())
