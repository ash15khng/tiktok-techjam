"""
Interactive UI for the TechJam Shopping Agent.

Place this file in the ROOT of your project
(tiktok-techjam-sweekang-structural-retrieval/), then run:

    pip install streamlit
    streamlit run streamlit_app.py

It imports `Agent` from `submission.agent`, exactly like the official
evaluator does, and lets you chat with it turn by turn from a browser.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import streamlit as st

from submission.agent import Agent

st.set_page_config(page_title="Shopping Agent Console", page_icon="🛍️", layout="wide")

DEFAULT_CATALOG_PATH = "data/catalog.jsonl"
DEFAULT_PROFILE = {
    "average_prior_rating": 5.0,
    "preference_tags": ["fit", "comfort", "durability"],
    "purchase_frequency": "3-4 prior purchases",
    "rating_style": "usually positive",
    "summary": "Prior purchases emphasize fit, comfort, durability; ratings are usually positive.",
}


# ---------------------------------------------------------------------------
# Session state setup
# ---------------------------------------------------------------------------

def new_session_id() -> str:
    return uuid.uuid4().hex[:8]


if "session_id" not in st.session_state:
    st.session_state.session_id = new_session_id()
if "turn" not in st.session_state:
    st.session_state.turn = 0
if "messages" not in st.session_state:
    st.session_state.messages = []  # list of {"role": "user"/"agent", "content": ..., "extra": {...}}
if "agent" not in st.session_state:
    st.session_state.agent = None
if "agent_error" not in st.session_state:
    st.session_state.agent_error = None
if "catalog_path" not in st.session_state:
    st.session_state.catalog_path = DEFAULT_CATALOG_PATH
if "profile_text" not in st.session_state:
    st.session_state.profile_text = json.dumps(DEFAULT_PROFILE, indent=2)


def load_agent(catalog_path: str):
    try:
        agent = Agent(catalog_path=catalog_path)
        st.session_state.agent = agent
        st.session_state.agent_error = None
    except Exception as exc:  # noqa: BLE001
        st.session_state.agent = None
        st.session_state.agent_error = str(exc)


def start_new_session(profile: dict):
    st.session_state.session_id = new_session_id()
    st.session_state.turn = 0
    st.session_state.messages = []
    if st.session_state.agent is not None:
        st.session_state.agent.reset(st.session_state.session_id, profile)


# ---------------------------------------------------------------------------
# Sidebar: configuration
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Setup")

    catalog_path = st.text_input("Catalog path", value=st.session_state.catalog_path)
    st.session_state.catalog_path = catalog_path

    if not Path(catalog_path).exists():
        st.warning(
            f"'{catalog_path}' not found. Download catalog.jsonl.gz from the "
            "GitHub release, gunzip it, and place it at this path (see README)."
        )

    if st.button("Load / reload agent", use_container_width=True):
        load_agent(catalog_path)

    if st.session_state.agent_error:
        st.error(f"Failed to load agent: {st.session_state.agent_error}")
    elif st.session_state.agent is not None:
        st.success("Agent loaded")

    st.divider()
    st.subheader("Session")

    top_k = st.slider("top_k (recommendations)", min_value=1, max_value=10, value=10)

    profile_text = st.text_area("user_profile (JSON)", value=st.session_state.profile_text, height=200)
    st.session_state.profile_text = profile_text

    if st.button("Start new session", use_container_width=True, type="primary"):
        try:
            profile = json.loads(profile_text)
        except json.JSONDecodeError as exc:
            st.error(f"Invalid JSON: {exc}")
        else:
            if st.session_state.agent is None:
                load_agent(catalog_path)
            if st.session_state.agent is not None:
                start_new_session(profile)
                st.rerun()

    st.caption(f"session_id: `{st.session_state.session_id}`")
    st.caption(f"turn: {st.session_state.turn}")


# ---------------------------------------------------------------------------
# Main: chat interface
# ---------------------------------------------------------------------------

st.title("🛍️ Shopping Agent Console")
st.caption("Chat with `submission.agent.Agent` turn by turn, exactly as the evaluator would.")

if st.session_state.agent is None and not st.session_state.agent_error:
    load_agent(catalog_path)

def describe_product(parent_asin: str) -> dict:
    """Look up human-readable details for a parent_asin from the loaded catalog."""

    agent = st.session_state.agent
    product = None
    if agent is not None:
        try:
            product = agent._agent.catalog.products.get(parent_asin)
        except Exception:  # noqa: BLE001
            product = None

    if product is None:
        return {"title": parent_asin, "subtitle": "", "asin": parent_asin}

    bits = []
    if product.average_rating:
        bits.append(f"⭐ {product.average_rating:.1f} ({product.rating_number} ratings)")
    if product.price:
        bits.append(f"${product.price:.2f}")
    if product.store:
        bits.append(f"by {product.store}")

    return {
        "title": product.title or parent_asin,
        "subtitle": " · ".join(bits),
        "asin": parent_asin,
    }


for msg in st.session_state.messages:
    with st.chat_message("user" if msg["role"] == "user" else "assistant"):
        st.write(msg["content"])
        extra = msg.get("extra")
        if extra:
            if extra.get("ask_attribute"):
                st.caption(f"Looking for: **{extra['ask_attribute']}**")
            if extra.get("recommendations"):
                st.write("**Here's what I found:**")
                for rec in extra["recommendations"]:
                    info = describe_product(rec.get("parent_asin", rec))
                    with st.container(border=True):
                        st.markdown(f"**{info['title']}**")
                        if info["subtitle"]:
                            st.caption(info["subtitle"])
                        st.caption(f"Product ID: `{info['asin']}`")
            if extra.get("usage"):
                st.caption(f"usage: {extra['usage']}")

user_input = st.chat_input("Type a customer message...")

if user_input:
    if st.session_state.agent is None:
        st.error("Agent isn't loaded. Fix the catalog path and click 'Load / reload agent'.")
    else:
        st.session_state.turn += 1
        st.session_state.messages.append({"role": "user", "content": user_input})

        try:
            response = st.session_state.agent.respond(
                session_id=st.session_state.session_id,
                user_message=user_input,
                turn=st.session_state.turn,
                top_k=top_k,
            )
            st.session_state.messages.append(
                {
                    "role": "agent",
                    "content": response.get("message", ""),
                    "extra": {
                        "ask_attribute": response.get("ask_attribute"),
                        "recommendations": response.get("recommendations", []),
                        "usage": response.get("usage"),
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001
            st.session_state.messages.append(
                {"role": "agent", "content": f"⚠️ Agent raised an error: {exc}"}
            )

        st.rerun()
