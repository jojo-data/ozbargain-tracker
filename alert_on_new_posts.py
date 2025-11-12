import csv
import os
import sys
import time

import requests  # type: ignore
import resend
from bs4 import BeautifulSoup

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
    missing_vars = []

    for var in required_vars:
        if not os.environ.get(var):
            missing_vars.append(var)

    if missing_vars:
        print("--- ❌ CRITICAL ERROR ---")
        print(
            "The following required environment variables are missing: "
            f"{', '.join(missing_vars)}"
        )
        print("Script aborted.")
        sys.exit(1)  # Exit immediately with an error code


# Run the check first
check_environment_vars()

# Assign environment variables after validation
URL = os.environ.get("URL")
LAST_POSTS_FILE = os.environ.get("LAST_POSTS_FILE")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL")
TITLE = os.environ.get("TITLE")
BASE_URL = "https://www.ozbargain.com.au"

# Resend API Key is pulled securely and assigned
resend.api_key = os.environ.get("RESEND_API_KEY")


# --- Scraping Logic: UPDATED FUNCTION ---


def scrape_page(url, all_posts):
    """
    Fetches a single page, extracts posts, and finds the next page link.
    Recursively calls itself until no 'Next' link is found.
    """
    print(f"Scraping page: {url}")

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/91.0.4472.124 Safari/537.36"
            )
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # --- 1. Extract posts from the search results page ---
        # Structure: anchors live inside <dt class="title"> elements
        # within the dl.search-results block.
        search_result_links = soup.select("dl.search-results dt.title a")
        if not search_result_links:
            search_result_links = soup.select("dt.title a")

        for a in search_result_links:
            # Join nested text nodes with spaces to preserve readable title
            title = a.get_text(" ", strip=True)
            href = a.get("href") or ""
            if not href or not title:
                continue

            # Fetch the date from the immediate following dd (if present)
            date_text = ""
            dt = a.find_parent("dt")
            if dt:
                dd = dt.find_next_sibling("dd")
                if dd:
                    meta_span = dd.select_one("span.meta")
                    if meta_span:
                        date_text = meta_span.get_text(strip=True)

            link_full = BASE_URL + href if href.startswith("/") else href
            if not any(p.get("link") == link_full for p in all_posts):
                all_posts.append({"title": title, "link": link_full, "date": date_text})

        # --- 2. Find Next Page Link ---
        # The "Go to next page" link is the pager control to follow.

        # Find the "Go to next page" anchor inside the pager.
        next_link_tag = soup.select_one('li a[title="Go to next page"]')

        if next_link_tag:
            next_relative_url = next_link_tag.get("href")
            next_full_url = BASE_URL + next_relative_url

            # Pause briefly to be polite to the server
            time.sleep(1)

            # Recursive call to scrape the next page
            scrape_page(next_full_url, all_posts)

        return all_posts

    except requests.RequestException as e:
        print(f"Error fetching URL {url}: {e}")
        return all_posts  # Return posts scraped so far


# Initial call function for the main script
def scrape_all_pages(start_url):
    all_posts = []
    return scrape_page(start_url, all_posts)


# --- Supporting Functions (Remain the same) ---


def load_last_posts():
    """Load previously seen post links from CSV file."""
    if not os.path.exists(LAST_POSTS_FILE):
        return set()
    seen_links = set()
    try:
        with open(LAST_POSTS_FILE, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                link_value = (row.get("link") or "").strip()
                if link_value:
                    seen_links.add(link_value)
    except Exception as e:
        print(f"Warning: failed to read {LAST_POSTS_FILE}: {e}")
    return seen_links


def save_current_posts(posts):
    """Save posts (title, link, date) to CSV for the next run."""
    os.makedirs(os.path.dirname(LAST_POSTS_FILE), exist_ok=True)
    fieldnames = ["title", "link", "date"]
    try:
        with open(LAST_POSTS_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for post in posts:
                writer.writerow(
                    {
                        "title": post.get("title", ""),
                        "link": post.get("link", ""),
                        "date": post.get("date", ""),
                    }
                )
    except Exception as e:
        print(f"Warning: failed to write {LAST_POSTS_FILE}: {e}")


def check_for_new_posts(current_posts, last_post_links):
    """Return posts whose link was not seen previously."""
    return [post for post in current_posts if post.get("link") not in last_post_links]


def send_alert_email(new_posts):
    """Sends an email with the details of new posts using Resend."""

    if not resend.api_key:
        print("Error: RESEND_API_KEY not set. Cannot send email.")
        return

    # 1. Build the HTML content for the email
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

    # 2. Define the email parameters
    params = {
        "from": SENDER_EMAIL,
        "to": [RECIPIENT_EMAIL],
        "subject": f"🚨 {TITLE} Alert: {len(new_posts)} New Posts Found",
        "html": html_body,
    }

    # 3. Send the email
    try:
        email_response = resend.Emails.send(params)
        print(f"Email sent. ID: {email_response.get('id')}")
    except Exception as e:
        print(f"Error sending email with Resend: {e}")


# --- Main Execution ---

if __name__ == "__main__":
    print(
        f"--- Running Scraper: {TITLE} at " f"{time.strftime('%Y-%m-%d %H:%M:%S')} ---"
    )

    # Use the new function that scrapes all pages
    current_posts = scrape_all_pages(URL)

    if not current_posts:
        print("No posts found or scraping failed. Exiting.")
    else:
        last_post_links = load_last_posts()
        new_posts = check_for_new_posts(current_posts, last_post_links)

        save_current_posts(current_posts)

        if new_posts:
            print(f"🎉 Found {len(new_posts)} new posts! " "Sending email alert...")
            send_alert_email(new_posts)
        else:
            print("No new posts since last check.")
