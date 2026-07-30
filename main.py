import json
import os
import time
import feedparser
import finnhub
from google import genai
from google.genai import types
from google.genai.errors import APIError
import requests

# ---------------------------------------------------------
# 1. INITIALIZE API KEYS & CLIENTS
# ---------------------------------------------------------
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not GEMINI_KEY:
    raise ValueError("Missing GEMINI_API_KEY in GitHub Secrets!")

# Initialize Gemini Client
client = genai.Client(api_key=GEMINI_KEY)

# Initialize Finnhub client if API key exists
finnhub_client = finnhub.Client(api_key=FINNHUB_KEY) if FINNHUB_KEY else None

SYSTEM_INSTRUCTION = """
You are a Senior Commodity Strategist. Analyze news items for market sentiment (BULLISH/BEARISH/NEUTRAL) 
and impact power (1-5) on Gold, Silver, Crude Oil, and Natural Gas. 
Return strictly JSON following this structure:
{
  "target_commodity": "Gold",
  "affected_commodities": ["Gold", "Silver"],
  "sentiment": "BULLISH",
  "impact_power_score": 3,
  "short_summary": "1-2 sentence executive summary of the catalyst",
  "transmission_channel": "How this impacts Indian MCX or international spot prices",
  "actionable_takeaway": "Note for futures traders"
}
"""

RSS_FEEDS = [
    "https://www.investing.com/rss/news_11.rss",  # Commodities News
]

CALENDAR_RSS = "https://www.investing.com/rss/forex_EconomicCalendar.rss"


# ---------------------------------------------------------
# 2. DATA INGESTION FUNCTIONS
# ---------------------------------------------------------
def fetch_finnhub_news():
    """Fetches breaking news from Finnhub API."""
    if not finnhub_client:
        print("FINNHUB_API_KEY missing or not configured. Skipping Finnhub.")
        return []

    articles = []
    try:
        news_data = finnhub_client.general_news("general", min_id=0)
        # Grab only the single newest article to conserve API quota
        for item in news_data[:1]:
            articles.append(
                {
                    "title": item.get("headline", ""),
                    "summary": item.get("summary", ""),
                    "source": f"Finnhub ({item.get('source', 'Live Wire')})",
                }
            )
    except Exception as e:
        print(f"Error fetching Finnhub news: {e}")
    return articles


def check_economic_calendar():
    """Scans Economic Calendar RSS for upcoming market volatility triggers."""
    try:
        feed = feedparser.parse(CALENDAR_RSS)
        keywords = [
            "EIA",
            "Crude Oil Stocks",
            "Natural Gas Storage",
            "CPI",
            "Fed Interest Rate",
            "Nonfarm Payrolls",
            "FOMC",
        ]
        for entry in feed.entries[:2]:
            title = entry.title
            if any(kw.lower() in title.lower() for kw in keywords):
                send_calendar_alert(
                    title, getattr(entry, "published", "Today")
                )
    except Exception as e:
        print(f"Error checking Economic Calendar: {e}")


# ---------------------------------------------------------
# 3. TELEGRAM ALERT FUNCTIONS
# ---------------------------------------------------------
def send_calendar_alert(event_title, time_str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Missing Telegram Secrets. Skipping alert.")
        return

    message = (
        f"⏰ *HIGH VOLATILITY CALENDAR WARNING*\n\n"
        f"*Event:* {event_title}\n"
        f"*Time:* {time_str}\n\n"
        f"⚠️ *Trading Risk Note:* Expected volatility on MCX/COMEX. Review position sizes or stop-losses."
    )
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",
        },
    )


def send_news_alert(title, source, data):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Missing Telegram Secrets. Skipping alert.")
        return

    sentiment = data.get("sentiment", "NEUTRAL")
    if sentiment == "BULLISH":
        emoji = "🟢 BULLISH"
    elif sentiment == "BEARISH":
        emoji = "🔴 BEARISH"
    else:
        emoji = "⚪ NEUTRAL"

    score = data.get("impact_power_score", 1)
    commodities = ", ".join(data.get("affected_commodities", ["General"]))

    message = (
        f"📰 *COMMODITY NEWS UPDATE*\n"
        f"📡 *Source:* {source}\n\n"
        f"*Headline:* {title}\n"
        f"*Commodities:* {commodities}\n"
        f"*Sentiment:* {emoji}\n"
        f"*Impact Score:* ⭐ {score}/5\n\n"
        f"*Summary:* {data.get('short_summary', 'N/A')}\n\n"
        f"*Transmission:* {data.get('transmission_channel', 'N/A')}\n\n"
        f"💡 *Takeaway:* {data.get('actionable_takeaway', 'N/A')}"
    )

    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",
        },
    )


# ---------------------------------------------------------
# 4. MAIN PIPELINE EXECUTION WITH AUTO-RETRY
# ---------------------------------------------------------
def generate_with_retry(prompt, retries=3):
    """Calls Gemini API with exponential backoff on 429 quota limits."""
    # List of fallback models to try if quota is exceeded
    models_to_try = ["gemini-2.5-flash-lite", "gemini-1.5-flash", "gemini-2.5-flash"]
    
    for model_id in models_to_try:
        for attempt in range(retries):
            try:
                response = client.models.generate_content(
                    model=model_id,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        response_mime_type="application/json",
                    ),
                )
                return response
            except APIError as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    wait_time = (attempt + 1) * 15
                    print(f"⚠️ Quota hit on {model_id}. Retrying in {wait_time}s... (Attempt {attempt + 1}/{retries})")
                    time.sleep(wait_time)
                else:
                    print(f"API error on {model_id}: {e}")
                    break
            except Exception as e:
                print(f"Unexpected error: {e}")
                break
    return None


def run_pipeline():
    # Step A: Check upcoming economic calendar events
    check_economic_calendar()

    # Step B: Gather breaking news (1 from Finnhub, 1 from RSS)
    all_news = fetch_finnhub_news()

    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:1]:
                all_news.append(
                    {
                        "title": entry.title,
                        "summary": getattr(entry, "summary", ""),
                        "source": "Investing.com RSS",
                    }
                )
        except Exception as e:
            print(f"Error reading RSS feed {feed_url}: {e}")

    # Step C: Evaluate items via Gemini AI (Max 2 items per run)
    for item in all_news[:2]:
        title = item["title"]
        summary = item["summary"]
        source = item["source"]

        prompt = f"Source: {source}\nTitle: {title}\nSummary: {summary}"

        response = generate_with_retry(prompt)
        if response and response.text:
            try:
                ai_eval = json.loads(response.text)
                send_news_alert(title, source, ai_eval)
                print(f"✅ Successfully processed & sent: {title}")
            except Exception as e:
                print(f"❌ JSON parsing error for '{title}': {e}")
        else:
            print(f"⏩ Skipped '{title}' due to API quota exhaustion.")

        time.sleep(10)


if __name__ == "__main__":
    run_pipeline()
