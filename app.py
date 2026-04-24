import os
import streamlit as st
from models import Pet, Owner, Task, get_default_tasks
from rag import generate_schedule_with_llm, answer_question

st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="centered")

# ---------------------------------------------------------------------------
# KB readiness check — warn once if the index hasn't been built yet
# ---------------------------------------------------------------------------
CHROMA_PATH = os.path.join(os.path.dirname(__file__), ".chroma")
_kb_ready = os.path.isdir(CHROMA_PATH)

st.title("🐾 PawPal+")

if not _kb_ready:
    st.warning(
        "Knowledge base not found. Run `python scripts/build_kb.py` once to enable "
        "AI-grounded schedule explanations and the Ask PawPal+ chat."
    )

# ---------------------------------------------------------------------------
# Pet & owner inputs
# ---------------------------------------------------------------------------
st.subheader("Your Pet")
col_pet, col_species, col_hours = st.columns(3)
with col_pet:
    pet_name = st.text_input("Pet name", value="Mochi")
with col_species:
    species = st.selectbox("Species", ["dog", "cat"])
with col_hours:
    available_hours = st.number_input("Hours available today", min_value=2, max_value=16, value=8)

# ---------------------------------------------------------------------------
# Task inputs
# ---------------------------------------------------------------------------
st.markdown("### Tasks")
st.caption("Add custom tasks, or use the defaults for your pet's species.")

if "tasks" not in st.session_state:
    st.session_state.tasks = []

col1, col2, col3 = st.columns(3)
with col1:
    task_title = st.text_input("Task title", value="Morning walk")
with col2:
    duration = st.number_input("Duration (minutes)", min_value=1, max_value=240, value=20)
with col3:
    priority = st.selectbox("Priority", ["low", "medium", "high"], index=2)

btn_col1, btn_col2 = st.columns(2)
with btn_col1:
    if st.button("Add task"):
        st.session_state.tasks.append(
            {"title": task_title, "duration_minutes": int(duration), "priority": priority, "frequency": 1}
        )
with btn_col2:
    if st.button("Load defaults for species"):
        pet_temp = Pet(name=pet_name, species=species, age=0)
        defaults = get_default_tasks(pet_temp)
        st.session_state.tasks = [
            {
                "title": t.title,
                "duration_minutes": t.duration_minutes,
                "priority": t.priority,
                "frequency": t.frequency,
            }
            for t in defaults
        ]

if st.session_state.tasks:
    st.write("Current tasks:")
    st.table(st.session_state.tasks)
    if st.button("Clear tasks"):
        st.session_state.tasks = []
        st.rerun()
else:
    st.info("No tasks yet. Add one above or load the species defaults.")

st.divider()

# ---------------------------------------------------------------------------
# Schedule generation
# ---------------------------------------------------------------------------
st.subheader("Build Schedule")

if st.button("Generate schedule", type="primary"):
    if not st.session_state.tasks:
        st.warning("Add at least one task before generating a schedule.")
    else:
        pet = Pet(name=pet_name, species=species, age=0)
        owner = Owner(name="", available_hours=available_hours)
        tasks = [
            Task(
                title=t["title"],
                duration_minutes=t["duration_minutes"],
                priority=t["priority"],
                frequency=t.get("frequency", 1),
                pet=pet,
            )
            for t in st.session_state.tasks
        ]
        with st.spinner("Building AI-grounded schedule..."):
            schedule = generate_schedule_with_llm(tasks, pet, owner)

        st.session_state.schedule = schedule
        st.session_state.pet = pet

if "schedule" in st.session_state:
    schedule = st.session_state.schedule
    if not schedule.blocks:
        st.warning("No tasks fit the time budget. Try adding shorter or higher-priority tasks.")
    else:
        st.subheader("Today's Schedule")
        st.table([
            {
                "Start": b.start_time.strftime("%I:%M %p").lstrip("0"),
                "Task": b.task.title,
                "Pet": b.task.pet.name,
                "Why": b.reason,
            }
            for b in schedule.blocks
        ])

    if schedule.skipped:
        st.subheader("Skipped Tasks")
        st.table([
            {"Task": t.title, "Duration (min)": t.duration_minutes, "Priority": t.priority}
            for t in schedule.skipped
        ])

# ---------------------------------------------------------------------------
# Ask PawPal+ — sidebar chat
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Ask PawPal+")
    st.caption("Ask anything about your pet's care. Answers are grounded in veterinary guidelines.")

    if not _kb_ready:
        st.info("Build the knowledge base first (`python scripts/build_kb.py`) to enable chat.")
    else:
        if "chat_history" not in st.session_state:
            st.session_state.chat_history = []

        # Display conversation history
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

        # Input box
        user_q = st.chat_input("e.g. How often should I brush my cat?")
        if user_q:
            # Determine pet context — fall back to a generic pet if no schedule run yet
            pet_ctx = st.session_state.get(
                "pet", Pet(name="your pet", species=species, age=0)
            )

            st.session_state.chat_history.append({"role": "user", "content": user_q})
            with st.chat_message("user"):
                st.write(user_q)

            with st.chat_message("assistant"):
                with st.spinner("Looking up guidelines..."):
                    answer = answer_question(user_q, pet_ctx)
                st.write(answer)

            st.session_state.chat_history.append({"role": "assistant", "content": answer})
