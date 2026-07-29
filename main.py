import os
import json
import requests
import feedparser
import google.generativeai as genai

# Configure Free Gemini API Key from environment variables
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

SYSTEM_INSTRUCTION = """
You are a Senior Commodity Strategist. Analyze incoming news for sentiment (BULLISH/BEARISH/NEUTRAL) 
and impact power (1-5) on Gold, Silver, Crude Oil, and Natural Gas.
Return JSON strictly in this structure:
{
  "target_commodity": "Gold",
  "affected_commodities": ["Gold"],
  "sentiment": "BULLISH",
  "impact_power_score": 4,
  "short_summary": "1-2 sentence executive summary",
  "transmission_channel": "How it impacts domestic prices",
  "actionable_takeaway": "Note for MCX/Global traders"
}
"""

model = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    system_instruction=SYSTEM_INSTRUCTION,
    generation_config={"response_mime_type": "application/json"}
)

RSS_FEEDS = [
    "https://www.investing.com/rss/news_11.rss", # Commodities News
]

def run_pipeline():
    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:3]: # Evaluate top 3 new items
            prompt = f"Source: {feed_url}\nTitle: {entry.title}\nSummary: {getattr(entry, 'summary', '')}"
            
            try:
                response = model.generate_content(prompt)
                ai_eval = json.loads(response.text)
                
                # If Impact Score is 4 or 5, send a Telegram alert
                if ai_eval.get("impact_power_score", 0) >= 4:
                    send_telegram_alert(entry.title, ai_eval)
            except Exception as e:
                print(f"Error processing item: {e}")

def send_telegram_alert(title, data):
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    
    emoji = "🟢 BULLISH" if data["sentiment"] == "BULLISH" else "🔴 BEARISH"
    message = (
        f"🚨 *HIGH IMPACT COMMODITY ALERT*\n\n"
        f"*Headline:* {title}\n"
        f"*Commodity:* {', '.join(data['affected_commodities'])}\n"
        f"*Sentiment:* {emoji}\n"
        f"*Impact Score:* 🔥 {data['impact_power_score']}/5\n\n"
        f"*Summary:* {data['short_summary']}\n\n"
        f"*Transmission:* {data['transmission_channel']}\n\n"
        f"💡 *Takeaway:* {data['actionable_takeaway']}"
    )
    
    requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    )

if __name__ == "__main__":
    run_pipeline()
