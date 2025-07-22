# Fichier: frontend/src/chatbot_ui/app.py

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

    st.header("Pilotage de la Personnalité")
    
    sales_tactic = st.slider(
        "Tactique de Vente", 1, 5, 2,
        help="Niveau 1 : Jamais de vente. Niveau 5 : Très direct et fréquent."
    )
    
    dominance = st.slider("Soumise (1) vs. Dominatrice (5)", 1, 5, 3)
    audacity = st.slider("Niveau d'Audace", 1, 5, 3)
    tone = st.slider("Tonalité : Joueuse (1) vs. Sérieuse (5)", 1, 5, 2)
    emotion = st.slider("Niveau d'Émotion Exprimée", 1, 5, 3)
    initiative = st.slider("Niveau d'Initiative", 1, 5, 3)
    vocabulary = st.slider("Variété Lexicale", 1, 5, 3)
    emojis = st.slider("Fréquence des Emojis", 1, 5, 3)
    imperfection = st.slider("Touche d'Imperfection", 1, 5, 1)

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Écrivez votre message à Seline..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    backend_url = "http://backend:8001/api/v1/chat/configured"
    
    persona_payload = {
        "sales_tactic": sales_tactic,
        "dominance": dominance,
        "audacity": audacity,
        "tone": tone,
        "emotion": emotion,
        "initiative": initiative,
        "vocabulary": vocabulary,
        "emojis": emojis,
        "imperfection": imperfection
    }

    payload = {
        "message": prompt,
        "history": [msg for msg in st.session_state.messages if msg['role'] != 'user'][-10:],
        "persona": persona_payload
    }

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        try:
            response = requests.post(backend_url, json=payload, timeout=60)
            
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