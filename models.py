# models.py — pure Python, importable without Streamlit
import datetime
from dataclasses import dataclass, field

# Numeric sort keys — prevents alphabetical priority comparison bug
# Phase 2 scheduler uses: sorted(tasks, key=lambda t: PRIORITY_ORDER[t.priority])
PRIORITY_ORDER: dict[str, int] = {"high": 0, "medium": 1, "low": 2}


@dataclass
class Pet:
    name: str
    species: str        # "dog" | "cat"
    age: int
    preferences: dict = field(default_factory=dict)


@dataclass
class Owner:
    name: str
    available_hours: int
    pets: list = field(default_factory=list)


@dataclass
class Task:
    title: str
    duration_minutes: int
    priority: str       # "high" | "medium" | "low"
    frequency: int = 1  # times per day
    pet: "Pet | None" = None


def get_default_tasks(pet: Pet) -> list:
    """Return pre-constructed Task objects for the given pet's species.

    Args:
        pet: A Pet object whose species determines the returned task list.

    Returns:
        List of Task objects pre-assigned to the given pet.

    Raises:
        ValueError: If pet.species is not "dog" or "cat".
    """
    if pet.species == "dog":
        return [
            Task("Morning walk",  30, "high",   1, pet),
            Task("Feeding",       10, "high",   2, pet),
            Task("Water refresh",  5, "medium", 2, pet),
            Task("Evening walk",  30, "high",   1, pet),
            Task("Playtime",      20, "medium", 1, pet),
            Task("Grooming",      15, "low",    1, pet),
        ]
    elif pet.species == "cat":
        return [
            Task("Feeding",       10, "high",   2, pet),
            Task("Water refresh",  5, "medium", 2, pet),
            Task("Litter box",    10, "high",   1, pet),
            Task("Playtime",      15, "medium", 1, pet),
            Task("Brushing",      10, "low",    1, pet),
            Task("Nail trim",      5, "low",    1, pet),
        ]
    else:
        raise ValueError(f"No default tasks for species: {pet.species!r}")


@dataclass
class TimeBlock:
    task: "Task"
    start_time: datetime.time
    end_time: datetime.time
    reason: str


@dataclass
class Schedule:
    blocks: list = field(default_factory=list)   # list[TimeBlock]
    skipped: list = field(default_factory=list)  # list[Task]

    def explain(self) -> str:
        if not self.blocks:
            return "No tasks scheduled."
        lines = []
        for block in self.blocks:
            start = block.start_time.strftime("%H:%M")
            end   = block.end_time.strftime("%H:%M")
            lines.append(
                f"{start} - {end}: {block.task.title} "
                f"({block.task.pet.name}) — {block.reason}"
            )
        return "\n".join(lines)


@dataclass
class Scheduler:
    owner: "Owner"
    tasks: list  # list[Task]

    def generate_schedule(self) -> "Schedule":
        # Split available time into two halves.
        # First occurrences of all tasks fill the morning half.
        # Repeat occurrences (frequency > 1) are pushed to the afternoon half,
        # so e.g. feeding x2 lands at 8am and ~noon rather than 8:30 and 8:40.
        total_minutes = self.owner.available_hours * 60
        half_minutes = total_minutes // 2
        day_start = datetime.datetime.combine(datetime.date.today(), datetime.time(8, 0))

        first_occ = sorted(self.tasks, key=lambda t: PRIORITY_ORDER[t.priority])
        repeat_occ = sorted(
            [t for t in self.tasks if t.frequency > 1],
            key=lambda t: PRIORITY_ORDER[t.priority],
        )

        schedule = Schedule()

        def _fill_slot(tasks, slot_start, slot_budget):
            current = slot_start
            remaining = slot_budget
            for task in tasks:
                if task.duration_minutes <= remaining:
                    start = current.time()
                    current += datetime.timedelta(minutes=task.duration_minutes)
                    schedule.blocks.append(
                        TimeBlock(task, start, current.time(), f"Scheduled: priority={task.priority}")
                    )
                    remaining -= task.duration_minutes
                else:
                    if task not in schedule.skipped:
                        schedule.skipped.append(task)

        _fill_slot(first_occ, day_start, half_minutes)
        afternoon_start = day_start + datetime.timedelta(minutes=half_minutes)
        _fill_slot(repeat_occ, afternoon_start, half_minutes)

        return schedule
