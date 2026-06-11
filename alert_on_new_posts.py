import csv
import os
import sys
import time
from datetime import datetime, timezone
from xml.etree.ElementTree import ParseError

import defusedxml.ElementTree as ET
import requests  # type: ignore
import resend

# --- Configuration & Validation ---


def check_environment_vars():
    """Check required environment variables and abort if any are missing."""
    required_vars = [
        "URL",
        "LAST_POSTS_FILE",
        "SENDER_EMAIL",
        "RECIPIENT_EMAIL",
        "TITLE",
        "RESEND_API_KEY",
    ]
    missing_vars = [v for v in required_vars if not os.environ.get(v)]

    if missing_vars:
        print("--- ❌ CRITICAL ERROR ---")
        print(
            "The following required environment variables are missing: "
            f"{', '.join(missing_vars)}"
        )
        print("Script aborted.")
        sys.exit(1)


check_environment_vars()

URL = os.environ.get("URL")
LAST_POSTS_FILE = os.environ.get("LAST_POSTS_FILE")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL")
TITLE = os.environ.get("TITLE")
# Optional: comma- or whitespace-separated terms. All must appear in a deal's
# title (case-insensitive) for it to be kept. Empty -> no title filter.
TITLE_FILTER = os.environ.get("TITLE_FILTER", "")

RSS_NS = {"ozb": "https://www.ozbargain.com.au"}

resend.api_key = os.environ.get("RESEND_API_KEY")


# --- Scraping Logic ---


class ScrapeError(Exception):
    """Raised when the scraper cannot fetch or parse the OzBargain feed."""


def fetch_feed(url):
    """Fetch and parse an OzBargain RSS feed."""
    print(f"Fetching feed: {url}")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-AU,en;q=0.9",
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except requests.RequestException as e:
        raise ScrapeError(f"Error fetching feed {url}: {e}") from e
    try:
        return ET.fromstring(response.content)
    except ParseError as e:
        raise ScrapeError(f"Error parsing feed XML from {url}: {e}") from e


def parse_filter_terms(raw):
    """Split TITLE_FILTER into lowercase terms. All must match (AND)."""
    terms = []
    for chunk in raw.split(","):
        for term in chunk.split():
            if term:
                terms.append(term.lower())
    return terms


def title_matches(title, terms):
    lower = title.lower()
    return all(term in lower for term in terms)


def is_expired(expiry_str, now):
    """OzBargain expiry is e.g. '2026-07-06T00:00:00+10:00'."""
    if not expiry_str:
        return False
    try:
        expiry = datetime.fromisoformat(expiry_str)
    except ValueError:
        return False
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return expiry < now


def scrape_feed(url):
    """Fetch the feed and return matching, non-expired posts."""
    root = fetch_feed(url)
    items = root.findall("./channel/item")
    terms = parse_filter_terms(TITLE_FILTER)
    now = datetime.now(timezone.utc)
    posts = []
    for it in items:
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        if not title or not link:
            continue
        if terms and not title_matches(title, terms):
            continue
        meta = it.find("ozb:meta", RSS_NS)
        expiry = meta.get("expiry") if meta is not None else None
        if is_expired(expiry, now):
            continue
        date_text = (it.findtext("pubDate") or "").strip()
        posts.append({"title": title, "link": link, "date": date_text})
    print(f"Feed returned {len(items)} items; {len(posts)} match filter.")
    return posts


# --- Persistence ---


SEEN_FIELDS = ["title", "link", "date"]


def load_seen_rows():
    """Load previously-seen post rows from CSV."""
    if not os.path.exists(LAST_POSTS_FILE):
        return []
    rows = []
    try:
        with open(LAST_POSTS_FILE, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (row.get("link") or "").strip():
                    rows.append({k: row.get(k, "") for k in SEEN_FIELDS})
    except Exception as e:
        print(f"Warning: failed to read {LAST_POSTS_FILE}: {e}")
    return rows


def save_seen_rows(rows):
    """Persist the (merged) seen-set CSV."""
    os.makedirs(os.path.dirname(LAST_POSTS_FILE), exist_ok=True)
    try:
        with open(LAST_POSTS_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=SEEN_FIELDS)
            writer.writeheader()
            for r in rows:
                writer.writerow({k: r.get(k, "") for k in SEEN_FIELDS})
    except Exception as e:
        print(f"Warning: failed to write {LAST_POSTS_FILE}: {e}")


def send_alert_email(new_posts):
    """Sends an email with the details of new posts using Resend."""

    if not resend.api_key:
        print("Error: RESEND_API_KEY not set. Cannot send email.")
        return False

    html_body = f"<h1>New Deals Found: {TITLE}</h1>"
    for post in new_posts:
        html_body += f"""
        <p>
            title: {post['title']}
            date: {post['date']}
            link: {post['link']}
        </p>
        <hr>
        """

    params = {
        "from": SENDER_EMAIL,
        "to": [RECIPIENT_EMAIL],
        "subject": f"🚨 {TITLE} Alert: {len(new_posts)} New Posts Found",
        "html": html_body,
    }

    try:
        email_response = resend.Emails.send(params)
        print(f"Email sent. ID: {email_response.get('id')}")
        return True
    except Exception as e:
        print(f"Error sending email with Resend: {e}")
        return False


# --- Main Execution ---

if __name__ == "__main__":
    print(
        f"--- Running Scraper: {TITLE} at {time.strftime('%Y-%m-%d %H:%M:%S')} ---"
    )

    try:
        current_posts = scrape_feed(URL)
    except ScrapeError as e:
        print(e)
        sys.exit(1)

    seen_rows = load_seen_rows()
    seen_links = {r["link"] for r in seen_rows}
    new_posts = [p for p in current_posts if p["link"] not in seen_links]

    if new_posts:
        print(f"🎉 Found {len(new_posts)} new posts! Sending email alert...")
        if not send_alert_email(new_posts):
            # Exit before persisting so we retry on the next run.
            sys.exit(1)
        seen_rows.extend(new_posts)
        save_seen_rows(seen_rows)
    else:
        print("No new posts since last check.")
