import html
import time

import httpx
import streamlit as st

API_URL = "http://api:8000"
SESSION_TIMEOUT_MINUTES = 30


def _esc(text: str) -> str:
    """HTML-escape user-controlled text to prevent XSS."""
    return html.escape(str(text))


# --- Custom CSS (Tailwind-inspired) ---

def inject_styles():
    st.markdown(
        """
        <style>
        /* Base reset */
        .stApp { background-color: #0f172a; color: #e2e8f0; }

        /* Login card */
        .login-card {
            max-width: 400px;
            margin: 80px auto;
            padding: 2rem;
            background: #1e293b;
            border-radius: 0.75rem;
            border: 1px solid #334155;
        }
        .login-card h2 {
            color: #f8fafc;
            font-size: 1.5rem;
            font-weight: 700;
            margin-bottom: 1.5rem;
            text-align: center;
        }

        /* Chat messages */
        .user-msg {
            background: #1e40af;
            color: #f8fafc;
            padding: 0.75rem 1rem;
            border-radius: 0.75rem 0.75rem 0.25rem 0.75rem;
            margin: 0.5rem 0;
            max-width: 80%;
            margin-left: auto;
            word-wrap: break-word;
        }
        .assistant-msg {
            background: #1e293b;
            color: #e2e8f0;
            padding: 0.75rem 1rem;
            border-radius: 0.75rem 0.75rem 0.75rem 0.25rem;
            margin: 0.5rem 0;
            max-width: 80%;
            border: 1px solid #334155;
            word-wrap: break-word;
            white-space: pre-wrap;
        }

        /* Sources expander */
        .source-item {
            background: #0f172a;
            padding: 0.5rem 0.75rem;
            border-radius: 0.5rem;
            margin: 0.25rem 0;
            font-size: 0.85rem;
            border-left: 3px solid #3b82f6;
        }

        /* Sidebar */
        [data-testid="stSidebar"] {
            background-color: #1e293b;
            border-right: 1px solid #334155;
        }
        [data-testid="stSidebar"] .stMarkdown { color: #cbd5e1; }

        /* Document list items */
        .doc-item {
            background: #0f172a;
            padding: 0.5rem 0.75rem;
            border-radius: 0.5rem;
            margin: 0.25rem 0;
            font-size: 0.85rem;
            border: 1px solid #334155;
        }
        .doc-item strong { color: #93c5fd; }

        /* Session timer */
        .session-timer {
            font-size: 0.75rem;
            color: #64748b;
            text-align: center;
            padding: 0.25rem;
        }

        /* Streamlit overrides */
        .stTextInput input {
            background-color: #0f172a !important;
            color: #e2e8f0 !important;
            border-color: #334155 !important;
        }
        .stButton > button {
            background-color: #2563eb !important;
            color: white !important;
            border: none !important;
            border-radius: 0.5rem !important;
            padding: 0.5rem 1.5rem !important;
            font-weight: 600 !important;
            width: 100%;
        }
        .stButton > button:hover {
            background-color: #1d4ed8 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# --- Session state init ---

def init_session():
    defaults = {
        "token": None,
        "username": None,
        "access_group": None,
        "role": None,
        "messages": [],
        "login_time": None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def is_authenticated() -> bool:
    if st.session_state.token is None:
        return False
    if st.session_state.login_time is None:
        return False
    elapsed = time.time() - st.session_state.login_time
    if elapsed > SESSION_TIMEOUT_MINUTES * 60:
        logout()
        return False
    return True


def logout():
    st.session_state.token = None
    st.session_state.username = None
    st.session_state.access_group = None
    st.session_state.role = None
    st.session_state.messages = []
    st.session_state.login_time = None


def auth_headers() -> dict:
    return {"Authorization": f"Bearer {st.session_state.token}"}


# --- API calls ---

def api_login(username: str, password: str) -> dict | None:
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{API_URL}/auth/login",
                json={"username": username, "password": password},
            )
            if resp.status_code == 200:
                return resp.json()
            return None
    except httpx.RequestError:
        return None


def api_chat_stream(question: str, top_k: int = 10):
    """Yield tokens from the SSE chat endpoint."""
    with httpx.Client(timeout=360.0) as client:
        with client.stream(
            "POST",
            f"{API_URL}/chat",
            json={"question": question, "top_k": top_k},
            headers=auth_headers(),
        ) as response:
            if response.status_code == 401:
                logout()
                return
            response.raise_for_status()
            for line in response.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                payload = line[6:]  # strip "data: "
                if payload == "[DONE]":
                    return
                yield payload


def api_get_documents() -> list[dict]:
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(
                f"{API_URL}/documents",
                headers=auth_headers(),
            )
            if resp.status_code == 200:
                return resp.json()
            return []
    except httpx.RequestError:
        return []


# --- UI: Login ---

def render_login():
    st.markdown(
        '<div class="login-card"><h2>GroundHog RAG</h2></div>',
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign In")

            if submitted:
                if not username or not password:
                    st.error("Please enter both username and password.")
                    return

                result = api_login(username, password)
                if result and "access_token" in result:
                    st.session_state.token = result["access_token"]
                    st.session_state.username = username
                    st.session_state.login_time = time.time()

                    import json
                    import base64

                    payload_b64 = result["access_token"].split(".")[1]
                    payload_b64 += "=" * (4 - len(payload_b64) % 4)
                    claims = json.loads(base64.urlsafe_b64decode(payload_b64))
                    st.session_state.access_group = claims.get("access_group")
                    st.session_state.role = claims.get("role")

                    st.rerun()
                else:
                    st.error("Invalid username or password.")


# --- UI: Sidebar ---

def render_sidebar():
    with st.sidebar:
        st.markdown(f"### {_esc(st.session_state.username)}")
        st.markdown(
            f"**Role:** {_esc(st.session_state.role)}  \n"
            f"**Group:** {_esc(st.session_state.access_group)}"
        )

        # Session timer
        if st.session_state.login_time:
            elapsed = time.time() - st.session_state.login_time
            remaining = max(0, SESSION_TIMEOUT_MINUTES * 60 - elapsed)
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            st.markdown(
                f'<div class="session-timer">Session expires in {mins}m {secs}s</div>',
                unsafe_allow_html=True,
            )

        st.divider()

        # Documents list
        st.markdown("### Documents")
        docs = api_get_documents()
        if docs:
            for doc in docs:
                ingested = doc.get("ingested_at", "")[:10] if doc.get("ingested_at") else "N/A"
                st.markdown(
                    f'<div class="doc-item">'
                    f'<strong>{_esc(doc["filename"])}</strong><br>'
                    f'{_esc(str(doc.get("page_count", "?")))} pages &middot; {_esc(ingested)} &middot; '
                    f'{_esc(doc.get("access_group", ""))}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.caption("No documents ingested yet.")

        st.divider()

        if st.button("Logout"):
            logout()
            st.rerun()


# --- UI: Chat ---

def render_chat():
    st.title("GroundHog RAG")

    # Render message history
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            st.markdown(
                f'<div class="user-msg">{_esc(msg["content"])}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="assistant-msg">{_esc(msg["content"])}</div>',
                unsafe_allow_html=True,
            )
            if msg.get("sources"):
                with st.expander("View Sources"):
                    for src in msg["sources"]:
                        st.markdown(
                            f'<div class="source-item">'
                            f'{_esc(src["file"])}, Page {_esc(str(src["page"]))} '
                            f'(similarity: {_esc(str(src["similarity"]))})'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

    # Chat input
    question = st.chat_input("Ask a question about your documents...")

    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        st.markdown(
            f'<div class="user-msg">{_esc(question)}</div>',
            unsafe_allow_html=True,
        )

        # Stream response
        response_placeholder = st.empty()
        full_response = ""
        sources_text = ""
        in_sources = False

        try:
            for token in api_chat_stream(question):
                if "\n\n---\nSources:" in (full_response + token):
                    in_sources = True

                if in_sources:
                    sources_text += token
                else:
                    full_response += token
                    response_placeholder.markdown(
                        f'<div class="assistant-msg">{_esc(full_response)}</div>',
                        unsafe_allow_html=True,
                    )

        except httpx.RequestError:
            full_response = "Error: Could not connect to the API."
            response_placeholder.markdown(
                f'<div class="assistant-msg">{_esc(full_response)}</div>',
                unsafe_allow_html=True,
            )

        # Parse sources
        parsed_sources = []
        if sources_text:
            parts = (full_response + sources_text).split("\n\n---\nSources:\n")
            if len(parts) == 2:
                full_response = parts[0]
                response_placeholder.markdown(
                    f'<div class="assistant-msg">{_esc(full_response)}</div>',
                    unsafe_allow_html=True,
                )
                for line in parts[1].strip().split("\n"):
                    line = line.strip().lstrip("- ")
                    if not line:
                        continue
                    try:
                        file_part, rest = line.split(", Page ")
                        page_part, sim_part = rest.split(" (similarity: ")
                        parsed_sources.append({
                            "file": file_part,
                            "page": int(page_part),
                            "similarity": sim_part.rstrip(")"),
                        })
                    except (ValueError, IndexError):
                        parsed_sources.append({
                            "file": line,
                            "page": 0,
                            "similarity": "N/A",
                        })

        if parsed_sources:
            with st.expander("View Sources"):
                for src in parsed_sources:
                    st.markdown(
                        f'<div class="source-item">'
                        f'{_esc(src["file"])}, Page {_esc(str(src["page"]))} '
                        f'(similarity: {_esc(str(src["similarity"]))})'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

        st.session_state.messages.append({
            "role": "assistant",
            "content": full_response,
            "sources": parsed_sources,
        })


# --- Main ---

def main():
    st.set_page_config(
        page_title="GroundHog RAG",
        page_icon="",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    inject_styles()
    init_session()

    if not is_authenticated():
        render_login()
    else:
        render_sidebar()
        render_chat()


if __name__ == "__main__":
    main()
