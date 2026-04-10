with open("client/tests/integration/test_sop_loop.py", "r") as f:
    content = f.read()

content = content.replace("with patch('client.agent.update_task_session'):", "with patch('client.agent.firestore_update_document'):")

with open("client/tests/integration/test_sop_loop.py", "w") as f:
    f.write(content)
