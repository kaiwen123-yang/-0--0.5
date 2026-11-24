"""Task identity shared by field acquisition, review, export and model input."""

COLORS = ("blue", "red", "white", "green")
BLUE_RED = COLORS[:2]
DESTINATION = "fixed_shallow_tray"
TASK_FIELDS = ("target_color", "scene_colors", "prompt", "destination_id")


def prompt_for(color):
    if color not in COLORS:
        raise ValueError(f"Unknown target color: {color}")
    return f"Pick up the {color} block, place it in the shallow tray, release it, and retreat."


def task_for(target, scene):
    ordered = [color for color in COLORS if color in scene]
    if (len(ordered) != len(scene) or tuple(ordered) not in (BLUE_RED, COLORS)
            or target not in ordered):
        raise ValueError("场景须为蓝红各一块或四色各一块，指定目标须在场。")
    return dict(target_color=target, scene_colors=ordered, prompt=prompt_for(target),
                destination_id=DESTINATION)


def recorded_task(record):
    task = task_for(record["target_color"], record["scene_colors"])
    if any(record.get(k) != task[k] for k in TASK_FIELDS):
        raise ValueError("Target, scene, instruction or fixed tray mismatch")
    return task


def stage_a_prompt(instruction):
    for color, zh in zip(BLUE_RED, ("蓝", "红")):
        prompt = prompt_for(color)
        if instruction in (prompt, color, f"抓取{zh}色方块到托盘里"):
            return prompt
    raise ValueError("阶段 A 只接受 blue/red、对应规范英文、抓取蓝色方块到托盘里或抓取红色方块到托盘里")
