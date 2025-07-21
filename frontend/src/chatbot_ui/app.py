# Fichier: app.py

import streamlit as st
import requests
import uuid

st.set_page_config(page_title="Chat avec Seline", layout="wide")
st.title("💬 Chat avec Seline")

if "messages" not in st.session_state:
    st.session_state.messages = []

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

with st.sidebar:
    st.header("Options")
    if st.button("Nouvelle Conversation"):
        st.session_state.messages = []
        st.session_state.session_id = str(uuid.uuid4())
        st.success("Nouvelle conversation démarrée !")
        st.rerun()

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Écrivez votre message à Seline..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # L'URL doit correspondre au préfixe défini dans main.py
    backend_url = "http://backend:8001/api/v1/chat"
    payload = {
        "session_id": st.session_state.session_id,
        "message": prompt
    }

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        try:
            response = requests.post(backend_url, json=payload, timeout=60) # Ajout d'un timeout
            
            if response.status_code != 200:
                error_detail = response.json().get('detail', 'Erreur inconnue.')
                st.error(f"Erreur du backend (Code: {response.status_code}): {error_detail}")
                assistant_response = None
            else:
                assistant_response = response.json().get("response")

        except requests.exceptions.RequestException as e:
            st.error(f"Impossible de contacter le backend. Est-il bien démarré ? Détails: {e}")
            assistant_response = None

    if assistant_response:
        message_placeholder.markdown(assistant_response)
        st.session_state.messages.append({"role": "assistant", "content": assistant_response})

