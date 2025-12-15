from phone_agent.actions.handler import parse_action

cases = [
    'do(action="Launch", app="哈啰")</answer>',
    '<answer>\n{think}当前处于主屏幕\n</answer>\n do(action="Launch", app="哈啰")',
    'finish(message="已完成")</answer>'
]

for s in cases:
    try:
        print(parse_action(s))
    except Exception as e:
        print("ERR:", e)
