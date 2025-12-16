from phone_agent.actions.handler import parse_action

cases = [
    'do(action="Launch", app="哈啰")</answer>',
    '<answer>\n{think}当前处于主屏幕\n</answer>\n do(action="Launch", app="哈啰")',
    'finish(message="已完成")</answer>',
    "{action=Swipe, start=[499, 499], end=[499, 0]}",
    "<answer>{action=Swipe, start=[499, 499], end=[499, 0]}</answer>",
]

for i, s in enumerate(cases, 1):
    try:
        result = parse_action(s)
        print(f"Test {i}: {result}")
    except Exception as e:
        print(f"Test {i} ERR: {e}")
