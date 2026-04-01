"""
LinkedIn tools using Playwright.

Session strategy:
- First run: opens a visible browser so the user can log in, then saves cookies.
- Subsequent runs: loads saved cookies — no login required.
- Adds human-like delays to reduce detection risk.
"""
import json
import os
import pathlib
import random
import time

SESSION_FILE = pathlib.Path(__file__).parent.parent / "linkedin_session.json"
BROWSER_CONTEXT = None  # module-level singleton


def _delay(min_s=1.5, max_s=3.5):
    time.sleep(random.uniform(min_s, max_s))


def get_browser_context():
    """Return (or create) a persistent Playwright browser context with LinkedIn session."""
    global BROWSER_CONTEXT
    if BROWSER_CONTEXT is not None:
        return BROWSER_CONTEXT

    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=False,  # visible so user can handle login / captchas
        args=["--start-maximized"],
    )

    context_options = {
        "viewport": {"width": 1280, "height": 900},
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }

    # Load saved session if it exists
    if SESSION_FILE.exists():
        with open(SESSION_FILE) as f:
            context_options["storage_state"] = json.load(f)

    context = browser.new_context(**context_options)
    page = context.new_page()

    # Check if we are logged in
    page.goto("https://www.linkedin.com/feed/", timeout=30000)
    _delay(2, 4)

    if "login" in page.url or "authwall" in page.url:
        print("\n[LinkedIn] Not logged in. Please log in to LinkedIn in the browser window.")
        print("[LinkedIn] The session will be saved automatically once you are logged in.")
        # Wait for the user to log in (up to 3 minutes)
        page.wait_for_url("**/feed/**", timeout=180000)
        print("[LinkedIn] Logged in. Saving session...")
        context.storage_state(path=str(SESSION_FILE))

    BROWSER_CONTEXT = (context, page)
    return BROWSER_CONTEXT


def search_linkedin_profile(name: str, company: str = "", role: str = "") -> dict:
    """
    Search LinkedIn for a person by name + optional company/role.
    Returns: { found, url, name, headline, location, confidence_note }
    """
    try:
        context, page = get_browser_context()
        query = name
        if company:
            query += f" {company}"
        if role:
            query += f" {role}"

        search_url = f"https://www.linkedin.com/search/results/people/?keywords={query.replace(' ', '%20')}"
        page.goto(search_url, timeout=30000)
        _delay(2, 4)

        # Get first result
        results = page.query_selector_all(".reusable-search__result-container")
        if not results:
            return {"found": False, "url": None, "note": "No results found"}

        first = results[0]
        link_el = first.query_selector("a.app-aware-link")
        headline_el = first.query_selector(".entity-result__primary-subtitle")
        location_el = first.query_selector(".entity-result__secondary-subtitle")
        name_el = first.query_selector(".entity-result__title-text")

        url = link_el.get_attribute("href").split("?")[0] if link_el else None
        headline = headline_el.inner_text().strip() if headline_el else ""
        location = location_el.inner_text().strip() if location_el else ""
        found_name = name_el.inner_text().strip() if name_el else ""

        # Simple confidence check — name should loosely match
        name_parts = name.lower().split()
        found_lower = found_name.lower()
        matched_parts = sum(1 for p in name_parts if p in found_lower)
        confidence = "high" if matched_parts >= 2 else "low" if matched_parts == 0 else "medium"

        return {
            "found": True,
            "url": url,
            "name": found_name,
            "headline": headline,
            "location": location,
            "confidence": confidence,
            "note": f"Name match confidence: {confidence}",
        }

    except Exception as e:
        return {"found": False, "url": None, "note": f"Error: {e}"}


def get_linkedin_profile(url: str) -> dict:
    """
    Scrape a LinkedIn profile URL for detailed information.
    Returns: { name, headline, location, about, experience, education, skills }
    """
    try:
        context, page = get_browser_context()
        page.goto(url, timeout=30000)
        _delay(2, 4)

        def safe_text(selector):
            el = page.query_selector(selector)
            return el.inner_text().strip() if el else ""

        name = safe_text("h1.text-heading-xlarge")
        headline = safe_text(".text-body-medium.break-words")
        location = safe_text(".text-body-small.inline.t-black--light.break-words")
        about = safe_text("#about ~ .display-flex .visually-hidden") or safe_text(
            "section[data-section='summary'] .pv-shared-text-with-see-more"
        )

        # Experience
        experience = []
        exp_items = page.query_selector_all(
            "#experience ~ .pvs-list__outer-container .pvs-list__paged-list-item"
        )
        for item in exp_items[:5]:
            text = item.inner_text().strip().replace("\n", " | ")[:200]
            if text:
                experience.append(text)

        # Education
        education = []
        edu_items = page.query_selector_all(
            "#education ~ .pvs-list__outer-container .pvs-list__paged-list-item"
        )
        for item in edu_items[:3]:
            text = item.inner_text().strip().replace("\n", " | ")[:150]
            if text:
                education.append(text)

        # Skills
        skills = []
        skill_items = page.query_selector_all(
            "#skills ~ .pvs-list__outer-container .pvs-entity__pill-text"
        )
        for item in skill_items[:15]:
            t = item.inner_text().strip()
            if t:
                skills.append(t)

        return {
            "url": url,
            "name": name,
            "headline": headline,
            "location": location,
            "about": about[:500] if about else "",
            "experience": experience,
            "education": education,
            "skills": skills,
        }

    except Exception as e:
        return {"url": url, "error": str(e)}


def find_similar_profiles(url: str, max_results: int = 5) -> list[dict]:
    """
    Find profiles similar to a given LinkedIn profile.
    Uses the 'People also viewed' sidebar + a keyword search based on their headline.
    Returns list of { name, url, headline, location }
    """
    similar = []

    try:
        context, page = get_browser_context()
        page.goto(url, timeout=30000)
        _delay(2, 4)

        # Method 1: "People also viewed" sidebar
        viewed_items = page.query_selector_all(
            ".pv-browsemap-section__member, .browsemap .pv-browsemap-section__member-container"
        )
        for item in viewed_items[:max_results]:
            name_el = item.query_selector(".base-aside-card__title, .browsemap-headless__name")
            link_el = item.query_selector("a")
            sub_el = item.query_selector(".base-aside-card__subtitle")
            if link_el and name_el:
                similar.append({
                    "name": name_el.inner_text().strip(),
                    "url": link_el.get_attribute("href", "").split("?")[0],
                    "headline": sub_el.inner_text().strip() if sub_el else "",
                    "source": "people_also_viewed",
                })

        # Method 2: If sidebar didn't yield enough, search by headline keywords
        if len(similar) < max_results:
            headline_el = page.query_selector(".text-body-medium.break-words")
            if headline_el:
                headline = headline_el.inner_text().strip()
                # Take first ~5 words of headline as search keywords
                keywords = " ".join(headline.split()[:5])
                search_url = (
                    f"https://www.linkedin.com/search/results/people/"
                    f"?keywords={keywords.replace(' ', '%20')}"
                )
                page.goto(search_url, timeout=30000)
                _delay(2, 3)

                result_items = page.query_selector_all(".reusable-search__result-container")
                for item in result_items[: max_results - len(similar) + 2]:
                    link_el = item.query_selector("a.app-aware-link")
                    name_el = item.query_selector(".entity-result__title-text")
                    sub_el = item.query_selector(".entity-result__primary-subtitle")
                    loc_el = item.query_selector(".entity-result__secondary-subtitle")
                    if link_el and name_el:
                        candidate_url = link_el.get_attribute("href", "").split("?")[0]
                        # Skip if it's the same profile
                        if url in candidate_url or candidate_url in url:
                            continue
                        similar.append({
                            "name": name_el.inner_text().strip(),
                            "url": candidate_url,
                            "headline": sub_el.inner_text().strip() if sub_el else "",
                            "location": loc_el.inner_text().strip() if loc_el else "",
                            "source": "keyword_search",
                        })
                        if len(similar) >= max_results:
                            break

    except Exception as e:
        similar.append({"error": str(e)})

    return similar[:max_results]


def close_browser():
    """Close the browser context cleanly."""
    global BROWSER_CONTEXT
    if BROWSER_CONTEXT:
        context, page = BROWSER_CONTEXT
        try:
            context.storage_state(path=str(SESSION_FILE))
            context.close()
        except Exception:
            pass
        BROWSER_CONTEXT = None
