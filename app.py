"""
SocialSpark - Social Media Content Planner
Workflow: enter campaign objective -> generate post ideas -> content calendar -> edit before publishing
Run:  streamlit run app.py
"""
import os

import pandas as pd
import streamlit as st
from google import genai
from google.genai import types
from pydantic import BaseModel

# ---------- Data models (Pydantic validates the Gemini output) ----------


class Post(BaseModel):
    day: int
    format: str        # Reel, Carousel, Story or Static post
    hook: str          # first line or first 3 seconds
    caption: str
    hashtags: list[str]
    best_time: str
    cta: str


class ContentPlan(BaseModel):
    posts: list[Post]


COLUMNS = ["Day", "Format", "Hook", "Caption", "Hashtags", "Best time", "CTA"]

# ---------- Gemini helpers ----------


def get_client(api_key: str):
    return genai.Client(api_key=api_key)


def brief_text(b: dict) -> str:
    return (
        f"Brand/page: {b['brand']}\n"
        f"Niche: {b['niche']}\n"
        f"Campaign objective: {b['objective']}\n"
        f"Target audience: {b['audience']}\n"
        f"Platform: {b['platform']}\n"
        f"Tone: {b['tone']}"
    )


def call_gemini(client, model: str, prompt: str, schema):
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.9,
        ),
    )
    return schema.model_validate_json(resp.text)


def generate_plan(client, model: str, b: dict, days: int) -> list[Post]:
    prompt = (
        "You are a social media strategist. Create a content calendar.\n\n"
        f"{brief_text(b)}\n\n"
        f"Create exactly {days} posts, one per day, numbered 1 to {days}. "
        "Mix formats (Reel, Carousel, Story, Static post), with Reels as the priority. "
        "For each post give: a scroll-stopping hook (the first line or first 3 seconds), "
        "a ready-to-post caption, 5 relevant hashtags, a best posting time (e.g. 7:30 PM IST), "
        "and one clear call to action. Keep every post different from the others."
    )
    plan = call_gemini(client, model, prompt, ContentPlan)
    return sorted(plan.posts, key=lambda p: p.day)


def regenerate_post(client, model: str, b: dict, day: int, existing_hooks: list[str]) -> Post:
    prompt = (
        "You are a social media strategist. Write ONE replacement post.\n\n"
        f"{brief_text(b)}\n\n"
        f"It is for day {day}. Do not reuse ideas from these existing hooks:\n"
        + "\n".join(f"- {h}" for h in existing_hooks)
        + "\n\nGive a hook, caption, 5 hashtags, best posting time and a call to action."
    )
    post = call_gemini(client, model, prompt, Post)
    post.day = day
    return post


def posts_to_df(posts: list[Post]) -> pd.DataFrame:
    rows = []
    for p in posts:
        tags = " ".join(t if t.startswith("#") else f"#{t}" for t in p.hashtags)
        rows.append([p.day, p.format, p.hook, p.caption, tags, p.best_time, p.cta])
    return pd.DataFrame(rows, columns=COLUMNS)


# ---------- UI ----------

st.set_page_config(page_title="SocialSpark", page_icon="✨", layout="wide")
st.title("✨ SocialSpark")
st.caption("Plan a Reels-first content calendar, then edit it before you publish.")

with st.sidebar:
    st.header("Settings")
    api_key = st.text_input(
        "Gemini API key",
        value=os.getenv("GEMINI_API_KEY", ""),
        type="password",
        help="Get a free key at aistudio.google.com",
    )
    model = st.text_input("Model", value="gemini-2.5-flash")
    st.markdown("Your key is only used for this session.")

with st.form("brief"):
    c1, c2 = st.columns(2)
    brand = c1.text_input("Brand / page name", placeholder="e.g. Framewrk")
    niche = c2.text_input("Niche", placeholder="e.g. tech and creator tips")
    objective = st.text_area(
        "Campaign objective",
        placeholder="e.g. Grow followers by 500 and launch my new editing template pack",
    )
    audience = st.text_input("Target audience", placeholder="e.g. college students who want to start creating")
    c3, c4, c5 = st.columns(3)
    platform = c3.selectbox("Platform", ["Instagram", "YouTube Shorts", "LinkedIn", "X (Twitter)"])
    tone = c4.selectbox("Tone", ["Friendly", "Professional", "Funny", "Bold", "Inspirational", "Educational"])
    days = c5.selectbox("Calendar length", [7, 14, 30], index=0)
    submitted = st.form_submit_button("Generate calendar", type="primary")

if submitted:
    if not api_key:
        st.error("Add your Gemini API key in the sidebar.")
    elif not (brand.strip() and objective.strip() and audience.strip()):
        st.error("Please fill in the brand, objective and audience.")
    else:
        brief = {
            "brand": brand.strip(),
            "niche": niche.strip() or "general",
            "objective": objective.strip(),
            "audience": audience.strip(),
            "platform": platform,
            "tone": tone,
        }
        try:
            with st.spinner("Planning your content..."):
                posts = generate_plan(get_client(api_key), model, brief, days)
            st.session_state.brief = brief
            st.session_state.plan = posts_to_df(posts)
        except Exception as e:
            st.error(f"Could not generate the calendar: {e}")

if "plan" in st.session_state:
    st.subheader("Your content calendar")
    st.caption("Click any cell to edit it. Nothing is published automatically.")

    st.session_state.plan = st.data_editor(
        st.session_state.plan,
        use_container_width=True,
        hide_index=True,
        disabled=["Day"],
        column_config={
            "Caption": st.column_config.TextColumn(width="large"),
            "Hook": st.column_config.TextColumn(width="medium"),
        },
        key="editor",
    )

    st.markdown("**Don't like a day? Regenerate it.**")
    r1, r2 = st.columns([1, 3])
    day_pick = r1.selectbox("Day", st.session_state.plan["Day"].tolist(), label_visibility="collapsed")
    if r2.button("Regenerate this day"):
        if not api_key:
            st.error("Add your Gemini API key in the sidebar.")
        else:
            df = st.session_state.plan
            hooks = df.loc[df["Day"] != day_pick, "Hook"].tolist()
            try:
                with st.spinner(f"Rewriting day {day_pick}..."):
                    new = regenerate_post(get_client(api_key), model, st.session_state.brief, int(day_pick), hooks)
                new_row = posts_to_df([new]).iloc[0]
                df.loc[df["Day"] == day_pick, COLUMNS] = new_row.values
                st.session_state.plan = df
                st.rerun()
            except Exception as e:
                st.error(f"Could not regenerate: {e}")

    st.download_button(
        "Download as CSV",
        st.session_state.plan.to_csv(index=False).encode("utf-8"),
        file_name="socialspark_calendar.csv",
        mime="text/csv",
    )
