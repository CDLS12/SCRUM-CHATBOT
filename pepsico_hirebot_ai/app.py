from __future__ import annotations

from pathlib import Path

import streamlit as st

from hirebot.engine import BotState, HireBotEngine, FIELD_LABELS, REQUIRED_FIELDS


# ============================================================
# PepsiCo HireBot AI - Interfaz web con Streamlit
# ============================================================
# Ejecutar:
#   pip install -r requirements.txt
#   streamlit run app.py

BASE_DIR = Path(__file__).resolve().parent
engine = HireBotEngine(BASE_DIR / "data" / "solicitudes.json")

st.set_page_config(
    page_title="PepsiCo HireBot AI",
    page_icon="🤖",
    layout="wide",
)

# CSS simple para que se vea más como prototipo profesional.
st.markdown(
    """
    <style>
    .main-title {
        font-size: 2.1rem;
        font-weight: 800;
        margin-bottom: 0.2rem;
    }
    .subtitle {
        color: #FFFFFF;
        font-size: 1rem;
        font-weight: 500;
        line-height: 1.5;
        margin-bottom: 1.2rem;
    }
    .metric-card {
        border: 1px solid #e6e6e6;
        border-radius: 14px;
        padding: 14px;
        background: #fafafa;
    }
    .field-ok { color: #147a2e; font-weight: 600; }
    .field-missing { color: #a15c00; font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)


def init_session() -> None:
    if "bot_state" not in st.session_state:
        st.session_state.bot_state = BotState().to_dict()
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": (
                    "Hola, soy **PepsiCo HireBot AI**. Puedo ayudarte a levantar una solicitud de contratación de manera guiada.\n\n"
                    "Puedo capturar la información del puesto, pedir los datos faltantes, validar la información clave y dejar la solicitud lista para revisión.\n\n"
                    "Escribe algo como: `Quiero contratar a un Analista de Datos para Data Analytics en Monterrey` "
                    "o usa el botón **Cargar ejemplo** para una demostracion de como quedaria una contratacion."
                ),
            }
        ]


def get_state() -> BotState:
    return BotState.from_dict(st.session_state.bot_state)


def set_state(state: BotState) -> None:
    st.session_state.bot_state = state.to_dict()


def send_message(message: str) -> None:
    state = get_state()
    st.session_state.messages.append({"role": "user", "content": message})
    response, new_state = engine.reply(message, state)
    set_state(new_state)
    st.session_state.messages.append({"role": "assistant", "content": response})


def reset_chat() -> None:
    st.session_state.bot_state = BotState().to_dict()
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": "Solicitud reiniciada. Escribe una nueva contratación o carga un ejemplo.",
        }
    ]


init_session()
state = get_state()

left, right = st.columns([0.68, 0.32], gap="large")

with left:
    st.markdown('<div class="main-title">🤖 PepsiCo HireBot AI</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Asistente conversacional inteligente para crear solicitudes de contratación, capturar información faltante de forma guiada, validar los datos clave del puesto y generar una solicitud lista para revisión por Recursos Humanos, Finanzas e IT.</div>',
        unsafe_allow_html=True,
    )

    top_buttons = st.columns(4)
    with top_buttons[0]:
        if st.button("➕ Nueva solicitud", use_container_width=True):
            reset_chat()
            st.rerun()
    with top_buttons[1]:
        if st.button("⚡ Cargar ejemplo", use_container_width=True):
            send_message("ejemplo")
            st.rerun()
    with top_buttons[2]:
        if st.button("📋 Resumen", use_container_width=True):
            send_message("resumen")
            st.rerun()
    with top_buttons[3]:
        if st.button("✅ Confirmar", use_container_width=True):
            send_message("confirmar")
            st.rerun()

    st.divider()

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    prompt = st.chat_input("Escribe tu mensaje al HireBot...")
    if prompt:
        send_message(prompt)
        st.rerun()

with right:
    st.subheader("Estado de la solicitud")
    draft = state.draft or {}
    completed = sum(1 for f in REQUIRED_FIELDS if draft.get(f) not in [None, "", []])
    total = len(REQUIRED_FIELDS)
    progress = completed / total if total else 0

    st.progress(progress, text=f"{completed}/{total} campos completos")

    if state.ready_to_submit:
        st.success("Lista para confirmar")
    elif state.active:
        st.info("En captura")
    else:
        st.warning("Sin solicitud activa")

    if state.awaiting_field:
        st.markdown(f"**Siguiente dato:** {FIELD_LABELS.get(state.awaiting_field, state.awaiting_field)}")

    st.divider()
    st.subheader("Campos capturados")

    for field in REQUIRED_FIELDS:
        value = draft.get(field)
        if isinstance(value, list):
            value = ", ".join(value)
        elif isinstance(value, bool):
            value = "Sí" if value else "No"
        elif value in [None, "", []]:
            value = "Pendiente"

        ok = value != "Pendiente"
        icon = "✅" if ok else "🟡"
        st.markdown(f"{icon} **{FIELD_LABELS[field]}:** {value}")

    st.divider()
    st.subheader("Solicitudes guardadas")
    records = engine.list_requests()
    if not records:
        st.caption("Aún no hay solicitudes guardadas en esta demo.")
    else:
        for record in reversed(records[-5:]):
            st.markdown(f"**{record['folio']}**")
            st.caption(f"{record.get('created_at')} · {record.get('status')}")
