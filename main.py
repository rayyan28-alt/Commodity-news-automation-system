import os
import json
import requests
import feedparser
import finnhub
import google.generativeai as genai

# Configure API Keys
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

# Initialize Finnhub Client
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY")
finnhub_client = finnhub.Client(api_key=FINNHUB_KEY) if FINNHUB_KEY else None

SYSTEM_INSTRUCTION = """
You are a Senior Commodity Strategist. Analyze news items for market sentiment (BULLISH/BEARISH/NEUTRAL) 
and impact power (1-5) on Gold, Silver, Crude Oil, and Natural Gas. Return strict JSON.
"""

model = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    system_instruction=SYSTEM_INSTRUCTION,
    generation_config={"response_mime_type": "application/json"}
)

RSS_FEEDS = [
    "https://www.investing.com/rss/news_11.rss",       # Commodities
    "https://www.investing.com/rss/news_14.rss"        # Forex/Macro
]

CALENDAR_RSS = "https://www.investing.com/rss/forex_EconomicCalendar.rss"

def fetch_finnhub_news():
    """Fetches real-time general & forex market news from Finnhub API."""
    if not finnhub_client:
        print("Finnhub API key missing. Skipping Finnhub feed.")
        return []
    
    articles = []
    try:
        # Fetch latest general/forex market news wire
        news_data = finnhub_client.general_news('general', min_id=0)
        for item in news_data[:5]:  # Process top 5 breaking items
            articles.append({
                "title": item.get('headline', ''),
                "summary": item.get('summary', ''),
                "source": f"Finnhub ({item.get('source', 'Wire')})"
            })
    except Exception as e:
        print(f"Error fetching Finnhub news: {e}")
    return articles

def check_economic_calendar():
    """Scans Economic Calendar RSS for upcoming volatility triggers."""
    try:
        feed = feedparser.parse(CALENDAR_RSS)
        keywords = ["EIA", "Crude Oil Stocks", "Natural Gas Storage", "CPI", "Fed Interest Rate", "Nonfarm Payrolls", "FOMC"]
        for entry in feed.entries[:5]:
            title = entry.title
            if any(kw.lower() in title.lower() for kw.lower() in keywords):
                send_calendar_alert(title, getattr(entry, 'published', 'Today'))
    except Exception as e:
        print(f"Error checking Economic Calendar: {e}")

def run_pipeline():
    # 1. First, check upcoming scheduled events
    check_economic_calendar()

    # 2. Gather news from BOTH Finnhub (Live API) and RSS Feeds
    all_news = fetch_finnhub_news()

    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:3]:
                all_news.append({
                    "title": entry.title,
                    "summary": getattr(entry, 'summary', ''),
                    "source": "Investing.com RSS"
                })
        except Exception as e:
            print(f"Error reading RSS feed {feed_url}: {e}")

    # 3. Analyze all collected news through Gemini AI
    for item in all_news:
        title = item["title"]
        summary = item["summary"]
        source = item["source"]

        prompt = f"Source: {source}\nTitle: {title}\nSummary: {summary}"
        
        try:
            response = model.generate_content(prompt)
            ai_eval = json.loads(response.text)
            
            # Send Telegram Alert for every item processed
            send_news_alert(title, source, ai_eval)
        except Exception as e:
            print(f"Error processing news '{title}': {e}")

def send_calendar_alert(event_title, time_str):
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    
    message = (
        f"⏰ *HIGH VOLATILITY CALENDAR WARNING*\n\n"
        f"*Event:* {event_title}\n"
        f"*Time:* {time_str}\n\n"
        f"⚠️ *Risk Note:* High market volatility expected on MCX/COMEX."
    )
    requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    )

def send_news_alert(title, source, data):
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    
    sentiment = data.get("sentiment", "NEUTRAL")
    emoji = "🟢 BULLISH" if sentiment == "BULLISH" else "🔴 BEARISH" if sentiment == "BEARISH" else "⚪ NEUTRAL"
    
    message = (
        f"📰 *COMMODITY NEWS UPDATE*\n"
        f"📡 *Source:* {source}\n\n"
        f"*Headline:* {title}\n"
        f"*Commodities:* {', '.join(data.get('affected_commodities', ['General']))}\n"
        f"*Sentiment:* {emoji}\n"
        f"*Impact Score:* ⭐ {data.get('impact_power_score', 1)}/5\n\n"
        f"*Summary:* {data.get('short_summary', 'N/A')}\n\n"
        f"*Transmission:* {data.get('transmission_channel', 'N/A')}\n\n"
        f"💡 *Takeaway:* {data.get('actionable_takeaway', 'N/A')}"
    )
    
    requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    )

if __name__ == "__main__":
    run_pipeline()
