import streamlit as st

if st.session_state.get("_show_toast"):
    st.toast("Cache refreshed successfully!", icon="✅")
    st.session_state._show_toast = False

st.write("Hello")
if st.button("Refresh Cache"):
    st.session_state._show_toast = True
    st.rerun()
