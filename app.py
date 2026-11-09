import os
import sys
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components

# Set page config
st.set_page_config(
    page_title="Tuấn Blogger • AI Video & Whiteboard Studio",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Hide all Streamlit default UI chrome and set 100% immersive dark theme
st.markdown("""
<style>
    /* Ẩn hoàn toàn header, footer, thanh công cụ, sidebar và thông báo của Streamlit */
    #MainMenu, header, footer, [data-testid="stSidebar"], [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"] {
        display: none !important;
        visibility: hidden !important;
        height: 0px !important;
    }
    html, body {
        margin: 0 !important;
        padding: 0 !important;
        overflow: hidden !important;
        background-color: #0b0f19 !important;
        width: 100vw !important;
        height: 100vh !important;
    }
    .main, .block-container {
        padding: 0 !important;
        margin: 0 !important;
        max-width: 100vw !important;
        width: 100vw !important;
        height: 100vh !important;
        overflow: hidden !important;
        background-color: #0b0f19 !important;
    }
    iframe {
        position: fixed !important;
        top: 0 !important;
        left: 0 !important;
        width: 100vw !important;
        height: 100vh !important;
        border: none !important;
        margin: 0 !important;
        padding: 0 !important;
        z-index: 999999 !important;
        background-color: #0b0f19 !important;
    }
</style>
""", unsafe_allow_html=True)

# Load the exact 3D Cyberpunk Executive Office App
office_file = Path(__file__).resolve().parent / "modern-3d-office" / "standalone_office.html"
if office_file.exists():
    html_code = office_file.read_text(encoding="utf-8")
    components.html(html_code, height=980, scrolling=False)
else:
    st.error("Không tìm thấy file giao diện 3D Office.")
